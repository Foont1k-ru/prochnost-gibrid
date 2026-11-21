"""Фоновая CAD-проекция с изоляцией, отменой и защитой от старых ответов."""
from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QLineF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.cad_assembly_projection_job import CadAssemblyProjection, CadAssemblyProjectionJob
from ..core.cad_transport import CadPreviewError
from ..export.cad_assembly_svg import SvgProjectionError, write_new_projection_svg
from ..model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint
from ..model.cad_projection_layout import (
    ProjectionLayout,
    dimension_segments,
    format_reference_length,
    projection_layout,
    reference_caption,
)


class ProjectionCanvas(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.projection: CadAssemblyProjection | None = None
        self.dimensions_enabled = True
        self.setMinimumSize(600, 280)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        projection = self.projection
        if projection is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() / 3
        for index, (plane, title, lines) in enumerate(zip(
                ('XY', 'XZ', 'YZ'), ('XY: +X →, +Y ↑', 'XZ: +X →, +Z ↑', 'YZ: +Y →, +Z ↑'),
                projection.views, strict=True)):
            left = width * index
            painter.setPen(QColor('#303840'))
            painter.drawText(QRectF(left + 4, 2, width - 8, 25), int(Qt.AlignmentFlag.AlignLeft), title)
            frame = projection_layout(projection.bounds_mm, plane, width, float(self.height()))
            painter.save()
            painter.setClipRect(QRectF(left, 27, width, self.height() - 27))
            painter.setPen(QPen(QColor('#254b70'), 1.3))
            for x1, y1, x2, y2 in lines:
                a, b = frame.screen(x1, y1), frame.screen(x2, y2)
                painter.drawLine(QLineF(left + a[0], a[1], left + b[0], b[1]))
            if self.dimensions_enabled:
                self._draw_dimensions(painter, frame, left, width)
            painter.restore()
        painter.end()


    def set_dimensions_enabled(self, enabled: bool) -> None:
        self.dimensions_enabled = enabled
        self.update()

    def _draw_dimensions(self, painter: QPainter, frame: ProjectionLayout, left: float, width: float) -> None:
        """Показывает общие габариты CAD-тел, не размеры деталей или отверстий."""
        x1, ybottom = frame.screen(frame.u_min, frame.v_min)
        _, ytop = frame.screen(frame.u_max, frame.v_max)
        dim_y, dim_x = ybottom + 13., left + x1 - 13.
        painter.setPen(QPen(QColor('#9b5016'), 1.0))
        for x_start, y_start, x_end, y_end in dimension_segments(frame):
            painter.drawLine(QLineF(left + x_start, y_start, left + x_end, y_end))
        painter.drawText(QRectF(left + 2., dim_y + 3., width - 4., 19.),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                         reference_caption(frame.plane[0], frame.width_mm))
        painter.save()
        painter.translate(dim_x - 7., (ytop + ybottom) / 2.)
        painter.rotate(-90.)
        painter.drawText(QRectF(-(self.height() - 50.) / 2., -10., self.height() - 50., 18.),
                         int(Qt.AlignmentFlag.AlignCenter), reference_caption(frame.plane[1], frame.height_mm))
        painter.restore()


class _ProjectionReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.document, self.token = document, token
        self.job = CadAssemblyProjectionJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.token, self.job.run(self.document))
        except CadPreviewError as error:
            self.failed.emit(self.token, error.code)
        except Exception:
            self.failed.emit(self.token, 'unexpected')


class CadAssemblyProjectionView(QWidget):
    def __init__(self, parent: QWidget, *, is_current: Callable[[dict[str, Any]], bool] | None = None) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._document: dict[str, Any] | None = None
        self._snapshot_fingerprint: str | None = None
        self._pending: dict[str, Any] | None = None
        self._worker: _ProjectionReader | None = None
        self._closed = False
        self.generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._start)
        layout = QVBoxLayout(self)
        note = QLabel('Видимые линии предварительных CAD-тел: две неподрезанные трубы, два корпуса и, '
                      'если добавлена, условная пластина. Кривые показаны ломаной; скрытые линии не выводятся. '
                      'Пересечения тел могут давать неполные или лишние линии. Это не производственный чертёж: '
                      'нет допусков, сварки, проверки монтажа и прочности. Масштаб видов различается.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.enable = QCheckBox('Построить предварительные CAD-проекции в фоне')
        self.enable.toggled.connect(self._schedule)
        layout.addWidget(self.enable)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setText('Выключено. Для построения требуется CAD-ядро.')
        layout.addWidget(self.status)
        self.canvas = ProjectionCanvas(self)
        layout.addWidget(self.canvas, 1)
        self.show_dimensions = QCheckBox('Размерные линии габаритов — справочно')
        self.show_dimensions.setChecked(True)
        self.show_dimensions.setToolTip('Границы всех предварительных CAD-тел, в том числе скрытых; '
                                        'не допуски и не размеры для изготовления.')
        self.show_dimensions.toggled.connect(self.canvas.set_dimensions_enabled)
        layout.addWidget(self.show_dimensions)
        self.snapshot_code = QLabel()
        self.snapshot_code.setWordWrap(True)
        self.snapshot_code.setTextFormat(Qt.TextFormat.PlainText)
        self.snapshot_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.snapshot_code.setToolTip('Код нормализованного снимка в редакторе; не хэш файла и не подпись. '
                                      'Имя и данные снимка проекта тоже входят в расчёт.')
        layout.addWidget(self.snapshot_code)
        code_controls = QHBoxLayout()
        self.copy_code = QPushButton('Скопировать код')
        self.copy_code.setEnabled(False)
        self.copy_code.setToolTip('Код будет помещён в системный буфер, доступный другим приложениям. '
                                  'После изменения сборки ранее скопированный код устаревает.')
        self.copy_code.clicked.connect(self._copy_snapshot_code)
        code_controls.addWidget(self.copy_code)
        self.comparison_input = QLineEdit()
        self.comparison_input.setPlaceholderText('Вставьте 64 символа SHA-256 снимка v1 для сравнения')
        self.comparison_input.setAccessibleName('Код снимка для сравнения')
        self.comparison_input.textChanged.connect(self._clear_comparison)
        code_controls.addWidget(self.comparison_input, 1)
        self.compare_code = QPushButton('Сравнить')
        self.compare_code.setEnabled(False)
        self.compare_code.clicked.connect(self._compare_snapshot_code)
        code_controls.addWidget(self.compare_code)
        layout.addLayout(code_controls)
        self.comparison_status = QLabel()
        self.comparison_status.setWordWrap(True)
        self.comparison_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.comparison_status)
        self.bounds = QLabel()
        self.bounds.setWordWrap(True)
        self.bounds.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.bounds)
        self.export_button = QPushButton('Сохранить предварительные виды в новый SVG…')
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_svg)
        layout.addWidget(self.export_button)
        self.export_status = QLabel()
        self.export_status.setWordWrap(True)
        self.export_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.export_status)
        self.retry = QPushButton('Повторить построение')
        self.retry.setEnabled(False)
        self.retry.clicked.connect(self._schedule)
        layout.addWidget(self.retry)

    def set_document(self, document: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            fingerprint: str | None = assembly_snapshot_fingerprint(document)
        except (TypeError, ValueError, OverflowError, RecursionError):
            fingerprint = None
        if self._document == document and self._snapshot_fingerprint == fingerprint:
            return
        self._document = deepcopy(document)
        self._snapshot_fingerprint = fingerprint
        self.copy_code.setEnabled(fingerprint is not None)
        self.compare_code.setEnabled(fingerprint is not None)
        self._clear_comparison()
        if fingerprint is None:
            self.snapshot_code.setText('Код снимка недоступен; SVG экспортировать нельзя.')
        else:
            self.snapshot_code.setText(f'SHA-256 снимка v1: {fingerprint}\n'
                                       'Не хэш файла и не подпись; сравните этот код с кодом в SVG.')
        self._schedule()

    def _clear_comparison(self, *_args: object) -> None:
        self.comparison_status.clear()

    def _current_snapshot_code(self) -> str | None:
        if (self._closed or self._document is None or self._snapshot_fingerprint is None or
                not self._candidate_is_current(self._document)):
            return None
        return self._snapshot_fingerprint

    def _copy_snapshot_code(self) -> None:
        code = self._current_snapshot_code()
        if code is None:
            self.comparison_status.setText('Код недоступен или снимок изменился. Обновите окно сборки.')
            return
        QApplication.clipboard().setText(code)
        self.comparison_status.setText('Код скопирован в системный буфер; после изменения сборки он устареет.')

    def _compare_snapshot_code(self) -> None:
        code = self._current_snapshot_code()
        if code is None:
            self.comparison_status.setText('Код недоступен или снимок изменился. Обновите окно сборки.')
            return
        entered = self.comparison_input.text().strip()
        if re.fullmatch(r'[0-9a-fA-F]{64}', entered) is None:
            self.comparison_status.setText('Введите только 64 шестнадцатеричных символа кода SHA-256 снимка v1.')
            return
        result = 'Коды совпадают' if entered.lower() == code else 'Коды различаются'
        self.comparison_status.setText(
            f'{result} на момент сравнения. Проверен только введённый текст, не содержимое SVG или файла; '
            'это не проверка геометрии, происхождения или пригодности.')

    def _candidate_is_current(self, document: dict[str, Any]) -> bool:
        if self._is_current is None:
            return True
        try:
            return self._is_current(document)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return False

    def _schedule(self, *_args: object) -> None:
        self.generation += 1
        self._timer.stop()
        self._pending = None
        self.canvas.projection = None
        self.canvas.update()
        self.bounds.clear()
        self.export_status.clear()
        self.export_button.setEnabled(False)
        self.retry.setEnabled(False)
        if self._worker is not None:
            self._worker.job.cancel()
        if self._closed:
            self.status.setText('Остановка построения…')
        elif not self.enable.isChecked():
            self.status.setText('Выключено. Для построения требуется CAD-ядро.')
        elif self._document is not None:
            self._pending = deepcopy(self._document)
            self.status.setText('Старые проекции очищены. Фоновое построение по текущему снимку…')
            self._timer.start()

    def _start(self) -> None:
        if self._closed or self._worker is not None or self._pending is None:
            return
        document, self._pending = self._pending, None
        worker = _ProjectionReader(document, self.generation, self)
        self._worker = worker
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _completed(self, token: int, result: object) -> None:
        if token != self.generation or self._closed or not self.enable.isChecked():
            return
        if self._document is None or not self._candidate_is_current(self._document):
            self._failed(token, 'changed')
            return
        if not isinstance(result, CadAssemblyProjection):
            self._failed(token, 'output')
            return
        self.canvas.projection = result
        self.canvas.update()
        bounds = result.bounds_mm
        rows = [f'{axis}: {format_reference_length(bounds[i + 3] - bounds[i])} '
                f'(от {bounds[i]:.1f} до {bounds[i + 3]:.1f})'
                for i, axis in enumerate(('X', 'Y', 'Z'))]
        self.bounds.setText('Справочные габариты CAD-тел, мм (в осях кузова; округление 0,1 мм):\n'
                            + '  •  '.join(rows) + '\nНе размеры для изготовления и не допуски.')
        self.retry.setEnabled(True)
        self.export_button.setEnabled(self._snapshot_fingerprint is not None)
        self.status.setText('Актуально для текущего снимка .kima. '
                            'Совпадение с текущим проектом проверяется отдельно ниже.')

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        reasons = {'missing_cad': 'CAD-ядро недоступно', 'timeout': 'превышено время',
                   'cancelled': 'построение отменено', 'limit': 'превышен предел сложности',
                   'no_shape': 'CAD-геометрия некорректна', 'coordinates': 'некорректные координаты',
                   'projection': 'не удалось вычислить видимые линии', 'output': 'некорректный ответ процесса',
                   'changed': 'снимок изменился во время построения',
                   'crash': 'CAD-процесс завершился аварийно', 'start': 'не удалось запустить процесс'}
        self.canvas.projection = None
        self.canvas.update()
        self.bounds.clear()
        self.export_status.clear()
        self.export_button.setEnabled(False)
        self.retry.setEnabled(self.enable.isChecked() and self._document is not None)
        self.status.setText(f'Проекции не построены: {reasons.get(code, "ошибка построения")}. '
                            'Сборка не изменена; условные виды доступны отдельно.')

    def _export_svg(self) -> None:
        projection = self.canvas.projection
        document = deepcopy(self._document)
        token, dimensions = self.generation, self.show_dimensions.isChecked()
        if (self._closed or not self.enable.isChecked() or projection is None or document is None or
                self._snapshot_fingerprint is None or
                not self._candidate_is_current(document)):
            return
        selected, _ = QFileDialog.getSaveFileName(
            self, 'Сохранить новый предварительный SVG', 'виды-сборки.svg', 'SVG (*.svg)',
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.svg':
            path = path.with_name(path.name + '.svg')
        try:
            if (self._closed or not self.enable.isChecked() or self.generation != token or
                    self.canvas.projection is not projection or self._document != document or
                    self.show_dimensions.isChecked() != dimensions or
                    not self._candidate_is_current(document)):
                raise SvgProjectionError('changed during export')
            write_new_projection_svg(path, projection, document, dimensions=dimensions)
        except (SvgProjectionError, OSError, TypeError, ValueError, OverflowError, KeyError):
            QMessageBox.warning(self, 'Экспорт SVG', 'Не удалось создать новый SVG: выберите другое имя или '
                                'повторите экспорт после перестроения. Существующие файлы не изменены.')
            return
        self.export_status.setText(f'Создан отдельный SVG: {path}. Сборка и проект автоматически не сохранены.')

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        if self._pending is not None and not self._closed:
            self._timer.start()

    def shutdown(self) -> bool:
        if not self._closed:
            self._closed = True
            self._schedule()
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))

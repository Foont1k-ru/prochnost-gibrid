"""Предварительная сборка из отдельных KIM-деталей и снимка схемы."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..model.arm_concept import make_arm_concept
from ..model.autosave_guard import same_project_file
from ..model.entities import Project
from ..model.kim_format import KimFormatError, _number, compare_lower_arm_source, write_document
from ..model.scheme_arm_assembly import rebuild_scheme_arm_assembly, validate_scheme_arm_assembly
from .arm_concept_dialog import ArmConceptCanvas
from .controller import AppController
from .kim_scheme_arm_dialog import BushingParametersDialog
from .weldment_3d import Weldment3D


class NewAssemblyParametersDialog(BushingParametersDialog):
    """Начальные параметры, которые схема сама не задаёт."""
    def __init__(self, parent: QWidget) -> None:
        super().__init__(None, parent)
        self.setWindowTitle('Параметры новой сборки')
        form = QFormLayout()
        self.radius = QLineEdit('12', self)
        self.wall = QLineEdit('2', self)
        for field in (self.radius, self.wall):
            field.setMaxLength(64)
        form.addRow('Радиус обеих труб, мм', self.radius)
        form.addRow('Толщина стенки обеих труб, мм', self.wall)
        cast(QVBoxLayout, self.layout()).insertLayout(1, form)

    def tube_values(self) -> tuple[float, float]:
        radius = _number(float(self.radius.text().strip().replace(',', '.')), positive=True)
        wall = _number(float(self.wall.text().strip().replace(',', '.')), positive=True)
        if not (0.01 <= wall <= 10000 and 0.01 <= radius <= 10000 and radius - wall >= 0.01):
            raise KimFormatError('invalid tube dimensions')
        return radius, wall

    def accept(self) -> None:
        try:
            self.tube_values()
        except (KimFormatError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Параметры труб', 'Проверьте радиус и стенку: 0,01–10000 мм, '
                                'внутренний радиус не меньше 0,01 мм.')
            return
        super().accept()


class SchemeArmAssemblyDialog(QDialog):
    def __init__(self, controller: AppController, document: dict[str, Any], path: Path | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        validate_scheme_arm_assembly(document)
        self.controller, self.path = controller, path
        self.document = deepcopy(document)
        self._saved = deepcopy(document) if path is not None else None
        self.setWindowTitle('Предварительная сборка рычага .kima')
        self.resize(800, 780)
        layout = QVBoxLayout(self)
        note = QLabel('Две трубы и два корпуса — отдельные встроенные детали .kim. '
                      'Трубы заданы в координатах кузова, корпуса — локально по оси Z и размещены в точках схемы. '
                      'Пластина, кронштейн шаровой, покупные изделия и сварка ещё не спроектированы. '
                      'Тела могут пересекаться; подрезки, монтажа и проверки прочности нет.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.tabs = QTabWidget(self)
        self.canvas = ArmConceptCanvas(self.tabs)
        self.tabs.addTab(self.canvas, 'Схема XY — условно')
        self.three_d = Weldment3D(self.tabs, is_current=lambda candidate: candidate == self.document, scheme_part=True)
        self.tabs.addTab(self.three_d, '3D — предварительная сборка')
        layout.addWidget(self.tabs, 1)
        self.source_status = QLabel()
        self.source_status.setWordWrap(True)
        layout.addWidget(self.source_status)
        self.apply_scheme = QPushButton('Перестроить по текущей схеме…')
        self.apply_scheme.clicked.connect(self._apply_current_scheme)
        layout.addWidget(self.apply_scheme)
        self.save_copy = QPushButton('Сохранить новую сборку .kima…')
        self.save_copy.clicked.connect(self._save_copy)
        layout.addWidget(self.save_copy)
        export = QFormLayout()
        self.part_choice = QComboBox(self)
        for part in self.document['parts']:
            self.part_choice.addItem(part['name'], part['id'])
        export.addRow('Встроенная отдельная деталь', self.part_choice)
        layout.addLayout(export)
        self.export_part = QPushButton('Сохранить выбранную деталь отдельно .kim…')
        self.export_part.clicked.connect(self._export_part)
        layout.addWidget(self.export_part)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.three_d.availabilityChanged.connect(self._update_save)
        self.controller.modelChanged.connect(self._update_source_status)
        self.controller.projectReplaced.connect(self._update_source_status)
        self._show_document()

    def _show_document(self) -> None:
        project = Project.from_dict(self.document['scheme'])
        geometry = self.document['parts'][0]['geometry']
        self.canvas.set_concept(make_arm_concept(project, 'tube', geometry['radius_mm'], geometry['wall_mm'], 3.))
        if self.three_d._document != self.document:
            self.three_d.set_document(deepcopy(self.document))
        path = str(self.path) if self.path else 'Новая несохранённая сборка'
        marker = ' • изменена, не сохранена' if self.document != self._saved else ''
        self.status.setText(f'{path}{marker}\nОсь корпусов: {self.document["axis"].upper()}. '
                            'Снимок схемы и все четыре детали находятся внутри сборки.')
        self._update_source_status()
        self._update_save()

    def _update_source_status(self, *_args: object) -> None:
        matches = all(compare_lower_arm_source(part, self.controller.project) for part in self.document['parts'][:2])
        state = 'совпадают' if matches else 'различаются или недоступны'
        self.source_status.setText(f'Текущий проект: тип подвески и три точки {state}. '
                                   'Это не подтверждает принадлежность сборки проекту.')

    def _update_save(self, *_args: object) -> None:
        self.save_copy.setEnabled(self.three_d.can_save())

    def _apply_current_scheme(self) -> None:
        original = deepcopy(self.document)
        try:
            updated = rebuild_scheme_arm_assembly(original, self.controller.project)
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Перестроение', 'Схема несовместима или точки некорректны. Сборка не изменена.')
            return
        if updated == original:
            self.feedback.setText('Снимок схемы уже совпадает с текущим проектом.')
            return
        answer = QMessageBox.question(self, 'Перестроение по схеме',
                                      'Проверьте, что открыт нужный проект. Заменить снимок схемы и '
                                      'перестроить трубы и размещение корпусов? Размеры деталей и ось сохранятся; '
                                      'исходный файл не изменится.',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.document != original or updated != rebuild_scheme_arm_assembly(original, self.controller.project):
                raise KimFormatError('changed during confirmation')
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Перестроение', 'Документ или схема изменились. Повторите действие.')
            return
        self.document = updated
        self.feedback.clear()
        self._show_document()

    def _safe_path(self, path: Path) -> None:
        if self.controller.is_protected_export_target(path) or (self.path and same_project_file(path, self.path)):
            raise KimFormatError('protected source')

    def _save_copy(self) -> None:
        if not self.three_d.can_save():
            return
        original, generation = deepcopy(self.document), self.three_d.generation
        selected, _ = QFileDialog.getSaveFileName(self, 'Сохранить новую сборку', 'рычаг.kima', 'Сборка KIMA (*.kima)')
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        try:
            if original != self.document or generation != self.three_d.generation or not self.three_d.can_save():
                raise KimFormatError('changed during save')
            self._safe_path(path)
            write_document(path, 'assembly', original, overwrite=False)
        except (KimFormatError, OSError, RuntimeError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Сохранение сборки', 'Не удалось сохранить новую сборку. Существующие файлы не изменены.')
            return
        self.path, self._saved = path, deepcopy(original)
        self.feedback.setText(f'Сохранена новая сборка: {path}')
        self._show_document()

    def _export_part(self) -> None:
        original = deepcopy(self.document)
        identifier = self.part_choice.currentData()
        selected, _ = QFileDialog.getSaveFileName(self, 'Сохранить деталь отдельно', f'{identifier}.kim', 'Деталь KIM (*.kim)')
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kim':
            path = path.with_name(path.name + '.kim')
        try:
            if original != self.document or identifier != self.part_choice.currentData():
                raise KimFormatError('changed during export')
            self._safe_path(path)
            part = next(part for part in original['parts'] if part['id'] == identifier)
            write_document(path, 'part', part, overwrite=False)
        except (KimFormatError, OSError, RuntimeError, TypeError, ValueError, OverflowError, StopIteration):
            QMessageBox.warning(self, 'Сохранение детали', 'Не удалось сохранить новую копию детали. Файлы не изменены.')
            return
        self.feedback.setText(f'Сохранена отдельная деталь: {path}. Внешний файл не синхронизируется со сборкой.')

    def _confirm_close(self) -> bool:
        if self.document == self._saved:
            return True
        original = deepcopy(self.document)
        answer = QMessageBox.question(self, 'Несохранённая сборка', 'Закрыть без сохранения новой сборки?',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes and self.document == original

    def reject(self) -> None:
        if self._confirm_close() and self.three_d.shutdown():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_close() and self.three_d.shutdown():
            super().reject()
            event.accept()
        else:
            event.ignore()

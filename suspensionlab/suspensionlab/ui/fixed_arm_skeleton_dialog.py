"""Пробный редактор осевых линий: только неизменяемый расчётный снимок."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..model.fixed_arm_skeleton import (
    FixedArmSnapshot,
    SkeletonError,
    SkeletonPreview,
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from ..model.fixed_arm_skeleton_io import SUFFIX, SkeletonFileError, read_skeleton, write_skeleton
from ..model.kim_format import KimFormatError
from .bend_editor import BendEditor
from .canvas.fixed_arm_projection import SkeletonProjection
from .canvas.fixed_arm_scene import LABELS, FixedArmScene, skeleton_scene
from .controller import AppController
from .weldment_3d import Weldment3D


class FixedArmSkeletonDialog(QDialog):
    """Отдельный опыт: проект не меняется, снимок сохраняется только как новый .slarm."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.snapshot: FixedArmSnapshot | None = None
        self.preview: SkeletonPreview | None = None
        self._cad_candidate: dict[str, Any] | None = None
        self._cad_snapshot: FixedArmSnapshot | None = None
        self._saved_state: tuple[object, ...] | None = None
        self._gesture_state: tuple[object, ...] | None = None
        self._gesture_project: object | None = None
        self._gesture_code: str | None = None
        self.setWindowTitle('Эксперимент: скелет по расчётному снимку')
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(1080, 760)
        root = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(split)
        scroll = QScrollArea(split)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        view_panel = QWidget(split)
        view_layout = QVBoxLayout(view_panel)
        view_layout.setContentsMargins(0, 0, 0, 0)
        split.addWidget(scroll)
        split.addWidget(view_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([420, 640])
        warning = QLabel('Передний нижний левый рычаг. Проверяется только сходимость в дискретных точках хода. '
                         'Зазоры, прочность, поворот и безопасность не проверяются. '
                         'Сохранение — только отдельный экспериментальный файл .slarm.', self)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self._from = self._spin(-250, 0, -20, 1)
        self._to = self._spin(0, 250, 20, 1)
        self._spacing = self._spin(1, 50, 10, 1)
        self._radius = self._spin(0.01, 10000, 12, 1)
        self._wall = self._spin(0.01, 10000, 2, 0.5)
        form.addRow('Отбой, мм', self._from)
        form.addRow('Сжатие, мм', self._to)
        form.addRow('Максимальный шаг отсчётов, мм', self._spacing)
        form.addRow('Радиус трубы, мм', self._radius)
        form.addRow('Толщина стенки, мм', self._wall)
        layout.addLayout(form)
        self._capture = QPushButton('Рассчитать точки и зафиксировать снимок', self)
        self._capture.clicked.connect(self._capture_snapshot)
        layout.addWidget(self._capture)
        self._status = QLabel('Снимок ещё не зафиксирован.', self)
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status)
        note = QLabel('Опоры нельзя редактировать здесь. Вершина изгиба — пересечение продолжений прямых, '
                      'а не точка на дуге; координаты абсолютные X/Y/Z, мм. Вершину можно перетаскивать '
                      'на проекциях; Esc отменяет перетаскивание.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self._bend_editor = BendEditor(self)
        self._bend_editor.set_editable(False)
        layout.addWidget(self._bend_editor)
        self._tabs = QTabWidget(self)
        self._scene = FixedArmScene(self._tabs)
        self._tabs.addTab(self._scene, '3D · осевые линии')
        self._projections = [SkeletonProjection(axes, self._tabs) for axes in ((0, 1), (0, 2), (1, 2))]
        for title, projection in zip(('XY', 'XZ', 'YZ'), self._projections, strict=True):
            self._tabs.addTab(projection, title)
            projection.pointPicked.connect(self._point_picked)
            projection.ambiguousPick.connect(self._ambiguous_pick)
            projection.dragStarted.connect(self._begin_projection_drag)
            projection.dragCancelled.connect(self._cancel_projection_drag)
            projection.dragReleased.connect(self._apply_projection_drag)
        cad_tab = QWidget(self._tabs)
        cad_layout = QVBoxLayout(cad_tab)
        cad_note = QLabel('Предварительный CAD: только две неподрезанные полые трубы. '
                          'Корпусов, шаровой, швов и проверки зазоров или прочности нет.', cad_tab)
        cad_note.setWordWrap(True)
        cad_layout.addWidget(cad_note)
        self._cad = Weldment3D(cad_tab, is_current=self._cad_is_current, fixed_skeleton=True)
        cad_layout.addWidget(self._cad, 1)
        self._tabs.addTab(cad_tab, '3D · трубы (CAD)')
        view_layout.addWidget(self._tabs, 1)
        self._reset_camera = QPushButton('Сбросить 3D-камеру', self)
        self._reset_camera.clicked.connect(self._scene.reset_camera)
        view_layout.addWidget(self._reset_camera)
        self._point_selection = QComboBox(self)
        self._point_selection.addItem('Точка не выбрана', None)
        self._point_selection.setEnabled(False)
        self._point_selection.setAccessibleName('Выбор точки скелета')
        view_layout.addWidget(self._point_selection)
        self._selection_status = QLabel('Точки выбираются щелчком по маркеру или из списка.', self)
        self._selection_status.setWordWrap(True)
        # Selection during a drag must not resize the projection and change its scale.
        self._selection_status.setFixedHeight(68)
        self._selection_status.setTextFormat(Qt.TextFormat.PlainText)
        view_layout.addWidget(self._selection_status)
        self._tabs.currentChanged.connect(self._view_tab_changed)
        self._point_selection.currentIndexChanged.connect(self._selection_changed)
        self._scene.pointPicked.connect(self._point_picked)
        self._scene.ambiguousPick.connect(self._ambiguous_pick)
        self._anchors = QLabel(self)
        self._anchors.setWordWrap(True)
        self._anchors.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._anchors)
        self._open = QPushButton('Открыть .slarm и пересчитать…', self)
        self._open.clicked.connect(self._open_file)
        layout.addWidget(self._open)
        self._save = QPushButton('Сохранить новый .slarm…', self)
        self._save.setEnabled(False)
        self._save.clicked.connect(self._save_file)
        layout.addWidget(self._save)
        self._file_status = QLabel(self)
        self._file_status.setWordWrap(True)
        self._file_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._file_status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._bend_editor.changed.connect(self._refresh)
        for spin in (self._radius, self._wall):
            spin.valueChanged.connect(self._refresh)
        for spin in (self._from, self._to, self._spacing):
            spin.valueChanged.connect(self._range_changed)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._project_replaced)
        self._saved_state = self._state()

    def _view_tab_changed(self, index: int) -> None:
        skeleton_view = index != self._tabs.count() - 1
        self._reset_camera.setVisible(skeleton_view)
        self._point_selection.setVisible(skeleton_view)
        self._selection_status.setVisible(skeleton_view)

    def _state(self) -> tuple[object, ...]:
        return (self.snapshot, self._from.value(), self._to.value(), self._spacing.value(),
                self._radius.value(), self._wall.value(), self._bend_editor.state())

    def _cad_is_current(self, candidate: dict[str, Any]) -> bool:
        if (self.snapshot is None or self.preview is None or self.snapshot != self._cad_snapshot or
                self._cad_candidate is None or candidate != self._cad_candidate or
                not self.snapshot.matches(self.controller.project)):
            return False
        try:
            fresh = fixed_arm_tube_document(self.snapshot, self.controller.project, self._radius.value(),
                                            self._wall.value(), self._bend_editor.values())
            return fresh == candidate
        except (SkeletonError, KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def confirm_close(self) -> bool:
        if self._state() == self._saved_state:
            return True
        state = self._state()
        answer = QMessageBox.question(self, 'Несохранённый скелет',
                                      'Несохранённые параметры и снимок будут потеряны. Продолжить?',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes and self._state() == state

    def shutdown(self) -> bool:
        """Остановить CAD-процесс до уничтожения Qt-виджета."""
        return self._cad.shutdown()

    def reject(self) -> None:
        if self.confirm_close() and self.shutdown():
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.confirm_close() and self.shutdown():
            super().closeEvent(event)
        else:
            event.ignore()

    def _spin(self, minimum: float, maximum: float, value: float, step: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setDecimals(2)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSingleStep(step)
        spin.setKeyboardTracking(False)
        return spin

    def _clear_preview(self) -> None:
        self.preview = None
        self._cad_candidate = None
        self._cad_snapshot = None
        self._cad.set_document(None)
        self._save.setEnabled(False)
        self._scene.set_scene(None)
        with QSignalBlocker(self._point_selection):
            self._point_selection.clear()
            self._point_selection.addItem('Точка не выбрана', None)
        self._point_selection.setEnabled(False)
        self._selection_status.setText('Точки выбираются щелчком по маркеру или из списка.')
        for canvas in self._projections:
            canvas.set_preview(None)
        self._anchors.clear()

    def _selection_changed(self, *_args: object) -> None:
        code = self._point_selection.currentData()
        if not isinstance(code, str) or self._scene.frame is None:
            self._scene.select_point(None)
            for projection in self._projections:
                projection.select_point(None)
            self._selection_status.setText('Точки выбираются щелчком по маркеру или из списка.')
            return
        point = self._scene.frame.point(code)
        if point is None:
            self._scene.select_point(None)
            for projection in self._projections:
                projection.select_point(None)
            self._selection_status.setText('Точка больше не доступна.')
            return
        self._scene.select_point(code)
        for projection in self._projections:
            projection.select_point(code)
        kind = ('Зафиксирована снимком; изменение опоры — только после нового расчёта.' if not code.startswith('bend_')
                else 'Вершина продолжений, не точка на дуге; её можно перетащить на проекциях или изменить полями.')
        self._selection_status.setText(f'{LABELS[code]}: X={point[0]:.4f}, Y={point[1]:.4f}, Z={point[2]:.4f} мм. {kind}')

    def _point_picked(self, code: str) -> None:
        index = self._point_selection.findData(code)
        if index >= 0:
            self._point_selection.setCurrentIndex(index)
            self._selection_changed()

    def _ambiguous_pick(self) -> None:
        self._selection_status.setText('Маркеры перекрываются. Выберите точку из списка; для перемещения '
                                       'используйте другую проекцию или поля координат.')

    def _cancel_projection_drag(self) -> None:
        self._gesture_state = None
        self._gesture_project = None
        self._gesture_code = None

    def _begin_projection_drag(self, code: str) -> None:
        self._cancel_projection_drag()
        if (self.snapshot is None or self.preview is None or
                not self.snapshot.matches(self.controller.project)):
            self._refresh()
            return
        self._gesture_state = self._state()
        self._gesture_project = self.controller.project
        self._gesture_code = code

    def _apply_projection_drag(self, code: str, axes: tuple[int, int], coordinates: tuple[float, float, float]) -> None:
        state, project, expected_code = self._gesture_state, self._gesture_project, self._gesture_code
        self._cancel_projection_drag()
        if (state is None or state != self._state() or project is not self.controller.project or
                self.snapshot is None or self.preview is None or code != expected_code or
                code not in ('bend_front', 'bend_rear') or axes not in ((0, 1), (0, 2), (1, 2))):
            self._refresh()
            self._selection_status.setText('Данные изменились во время перемещения. Изменение не принято.')
            return
        if not self.snapshot.matches(self.controller.project):
            self._refresh()
            self._selection_status.setText('Проект изменился. Сначала повторите расчёт и фиксацию снимка.')
            return
        leg = code.removeprefix('bend_')
        try:
            bends = self._bend_editor.values()
            # The hidden third coordinate is always taken from the editor, never the pointer.
            original = bends[leg]['vertex_mm']
            vertex = list(original)
            for axis in axes:
                vertex[axis] = coordinates[axis]
            bends[leg]['vertex_mm'] = vertex
            preview_fixed_arm(self.snapshot, self.controller.project, self._radius.value(), self._wall.value(), bends)
        except (KimFormatError, SkeletonError, KeyError, IndexError, TypeError, ValueError) as error:
            if not self.snapshot.matches(self.controller.project):
                self._refresh()
                self._selection_status.setText('Проект изменился. Сначала повторите расчёт и фиксацию снимка.')
            else:
                self._selection_status.setText(f'Перемещение не принято: {error}. Показан прежний скелет.')
            return
        if state != self._state() or not self.snapshot.matches(self.controller.project):
            self._refresh()
            self._selection_status.setText('Данные изменились во время проверки. Изменение не принято.')
            return
        fields = self._bend_editor.fields[leg]
        blockers = [QSignalBlocker(fields[axis]) for axis in axes]
        for axis in axes:
            fields[axis].setText(str(vertex[axis]))
        del blockers
        # A single change notification avoids showing transient invalid intermediate states.
        self._bend_editor.changed.emit()

    def _open_file(self) -> None:
        if not self.confirm_close():
            return
        state = self._state()
        selected, _ = QFileDialog.getOpenFileName(self, 'Открыть скелет', '', 'Скелет рычага (*.slarm)')
        if not selected:
            return
        if self._state() != state:
            QMessageBox.warning(self, 'Открытие скелета', 'Данные изменились во время выбора файла.')
            return
        try:
            loaded = read_skeleton(selected, self.controller.project)
        except SkeletonFileError as error:
            QMessageBox.warning(self, 'Открытие скелета', str(error))
            return
        # Apply only after all file, current-project, solver and geometry checks.
        spins = (self._from, self._to, self._spacing, self._radius, self._wall)
        blockers = [QSignalBlocker(spin) for spin in spins]
        self._from.setValue(loaded.snapshot.travels_mm[0])
        self._to.setValue(loaded.snapshot.travels_mm[-1])
        self._spacing.setValue(loaded.snapshot.spacing_mm)
        self._radius.setValue(loaded.radius_mm)
        self._wall.setValue(loaded.wall_mm)
        self._bend_editor.load(loaded.bends)
        del blockers
        self.snapshot = loaded.snapshot
        self._refresh()
        if self.snapshot is None or self.preview is None:
            self._file_status.setText('Схема изменилась во время открытия; снимок не принят.')
            return
        self._saved_state = self._state()
        self._file_status.setText('Открыт и пересчитан файл: ' + selected +
                                  '. Сохранённая невязка — только историческая запись, не сертификат.')

    def _save_file(self) -> None:
        if self.snapshot is None or self.preview is None:
            return
        if not self.snapshot.matches(self.controller.project):
            self._refresh()
            return
        state = self._state()
        selected, _ = QFileDialog.getSaveFileName(self, 'Сохранить новый скелет', '', 'Скелет рычага (*.slarm)')
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != SUFFIX:
            path = path.with_name(path.name + SUFFIX)
        try:
            if self._state() != state or self.snapshot is None or self.preview is None:
                raise SkeletonFileError('Данные изменились во время выбора файла')
            if self.controller.is_protected_export_target(path):
                raise SkeletonFileError('Нельзя записать поверх проекта или автосохранения')
            write_skeleton(path, self.snapshot, self.controller.project, self._radius.value(),
                           self._wall.value(), self._bend_editor.values())
        except (SkeletonFileError, KimFormatError, OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, 'Сохранение скелета', str(error))
            self._refresh()
            return
        self._saved_state = self._state()
        self._file_status.setText(f'Сохранён новый файл: {path}. Проект не изменён.')

    def _range_changed(self, *_args: object) -> None:
        self._file_status.clear()
        if self.snapshot is not None:
            self.snapshot = None
            self._bend_editor.set_editable(False)
            self._clear_preview()
            self._status.setText('Диапазон изменён. Повторно рассчитайте и зафиксируйте снимок.')

    def _project_replaced(self) -> None:
        self._file_status.clear()
        self.snapshot = None
        self._bend_editor.set_editable(False)
        self._clear_preview()
        self._status.setText('Проект заменён. Повторно рассчитайте и зафиксируйте снимок.')

    def _capture_snapshot(self) -> None:
        if self.snapshot is not None or self._bend_editor.has_bends():
            answer = QMessageBox.question(self, 'Новый снимок',
                'Рассчитать новую схему? Текущие параметры изгибов сохранятся, но будут проверены заново.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._file_status.clear()
        try:
            snapshot = capture_fixed_arm(self.controller.project, self._from.value(), self._to.value(),
                                         spacing_mm=self._spacing.value())
        except SkeletonError as error:
            self.snapshot = None
            self._bend_editor.set_editable(False)
            self._clear_preview()
            self._status.setText(str(error))
            return
        self.snapshot = snapshot
        self._bend_editor.set_editable(True)
        self._refresh()

    def _refresh(self, *_args: object) -> None:
        self._file_status.clear()
        selected_code = self._point_selection.currentData()
        self._clear_preview()
        if self.snapshot is None:
            return
        if not self.snapshot.matches(self.controller.project):
            self.snapshot = None
            self._bend_editor.set_editable(False)
            self._status.setText('Проект отличается от снимка. Скелет скрыт; повторите расчёт и фиксацию.')
            return
        self._bend_editor.set_editable(True)
        try:
            bends = self._bend_editor.values()
            preview = preview_fixed_arm(self.snapshot, self.controller.project, self._radius.value(),
                                        self._wall.value(), bends)
            document = fixed_arm_tube_document(self.snapshot, self.controller.project, self._radius.value(),
                                               self._wall.value(), bends)
            scene = skeleton_scene(preview, bends)
        except KimFormatError:
            self._status.setText('Заполните X, Y, Z и радиус для каждого включённого изгиба.')
            return
        except SkeletonError as error:
            self._status.setText(str(error))
            return
        self.preview = preview
        self._cad_candidate = document
        self._cad_snapshot = self.snapshot
        self._cad.set_document(document)
        self._save.setEnabled(True)
        self._scene.set_scene(scene)
        with QSignalBlocker(self._point_selection):
            for code, _point in scene.points:
                self._point_selection.addItem(LABELS[code], code)
            index = self._point_selection.findData(selected_code)
            self._point_selection.setCurrentIndex(max(index, 0))
        self._point_selection.setEnabled(True)
        for canvas in self._projections:
            canvas.set_preview(preview, scene.points)
        self._selection_changed()
        self._anchors.setText('Фиксированные опоры, X / Y / Z, мм:\n' + '\n'.join(
            f'{label}: {point[0]:.4f} / {point[1]:.4f} / {point[2]:.4f}' for label, point in zip(
                ('Передняя', 'Задняя', 'Шаровая'), preview.anchors, strict=True)))
        self._status.setText(f'Снимок: {len(self.snapshot.travels_mm)} дискретных положений, '
                             f'шаг продолжения не более {self.snapshot.max_step_mm:g} мм. '
                             'Между отсчётами и остальные проверки не подтверждены.')

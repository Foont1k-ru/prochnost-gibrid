"""Пробный редактор осевых линий: только неизменяемый расчётный снимок."""
from __future__ import annotations

import json
from math import dist
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..model.bent_tube import make_bend_path
from ..model.fixed_arm_housings import HousingError, make_housing_preview, validate_housings, validate_notches
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
from .fixed_arm_housings_dialog import FixedArmHousingsDialog
from .fixed_arm_overlap import FixedArmOverlap
from .weldment_3d import Weldment3D


class FixedArmSkeletonDialog(QDialog):
    """Отдельный опыт: проект не меняется, снимок сохраняется только как новый .slarm."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.snapshot: FixedArmSnapshot | None = None
        self.preview: SkeletonPreview | None = None
        self._draft: tuple[str, tuple[float, float, float]] | None = None
        self._housings: dict[str, Any] | None = None
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
        note = QLabel('Нажмите на прямую трубу, затем перетащите появившуюся вершину. '
                      'Пока доступен один изгиб на каждую трубу. Точки опор закреплены; Esc отменяет перемещение. '
                      '3D: движение в плоскости экрана; XY/XZ/YZ сохраняют третью координату.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self._housing_edit = QPushButton('Задать корпуса втулок…', self)
        self._housing_edit.setEnabled(False)
        self._housing_edit.clicked.connect(self._edit_housings)
        layout.addWidget(self._housing_edit)
        self._housing_remove = QPushButton('Убрать корпуса из просмотра', self)
        self._housing_remove.setEnabled(False)
        self._housing_remove.clicked.connect(self._remove_housings)
        layout.addWidget(self._housing_remove)
        self._housing_status = QLabel('Корпуса не заданы.', self)
        self._housing_status.setWordWrap(True)
        layout.addWidget(self._housing_status)
        self._bend_editor = BendEditor(self)
        self._bend_editor.set_editable(False)
        layout.addWidget(self._bend_editor)
        self._bend_editor.hide()  # Internal storage; edited on the canvas and on demand.
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
            projection.dragMoved.connect(self._drag_moved)
            projection.dragReleased.connect(self._apply_projection_drag)
            projection.segmentPicked.connect(self._create_draft)
        cad_tab = QWidget(self._tabs)
        cad_layout = QVBoxLayout(cad_tab)
        self._cad_note = QLabel('Предварительный CAD: две неподрезанные полые трубы; корпуса пока не заданы. '
                                'Шаровой, швов и проверки зазоров или прочности нет.', cad_tab)
        self._cad_note.setWordWrap(True)
        cad_layout.addWidget(self._cad_note)
        notch_note = QLabel('Подрезка только в CAD-просмотре, отдельно для каждой ветви по её корпусу. '
                            'Укажите радиальный зазор явно (0 — без зазора), мм. '
                            'Корпус не удлиняется. В .slarm сохраняются параметры, не CAD-результат.', cad_tab)
        notch_note.setWordWrap(True)
        cad_layout.addWidget(notch_note)
        self._notch_checks: dict[str, QCheckBox] = {}
        self._notch_clearances: dict[str, QLineEdit] = {}
        for leg, title in (('front', 'Переднюю'), ('rear', 'Заднюю')):
            row = QHBoxLayout()
            check = QCheckBox(f'Подрезать {title.lower()} трубу по своему корпусу', cad_tab)
            check.setEnabled(False)
            field = QLineEdit(cad_tab)
            field.setPlaceholderText('Радиальный зазор, мм')
            field.setAccessibleName(f'{title} труба: радиальный зазор, мм')
            field.setMaxLength(64)
            field.setEnabled(False)
            row.addWidget(check)
            row.addWidget(field)
            cad_layout.addLayout(row)
            self._notch_checks[leg] = check
            self._notch_clearances[leg] = field
            check.toggled.connect(self._refresh)
            field.textChanged.connect(self._refresh)
        self._notch_status = QLabel('', cad_tab)
        self._notch_status.setWordWrap(True)
        cad_layout.addWidget(self._notch_status)
        self._overlap = FixedArmOverlap(self._cad_is_current, cad_tab)
        cad_layout.addWidget(self._overlap)
        self._cad = Weldment3D(cad_tab, is_current=self._cad_is_current, fixed_skeleton=True)
        cad_layout.addWidget(self._cad, 1)
        self._tabs.addTab(cad_tab, '3D · детали (CAD)')
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
        self._lengths = QLabel(self)
        self._lengths.setWordWrap(True)
        self._lengths.setFixedHeight(44)
        view_layout.addWidget(self._lengths)
        actions = QHBoxLayout()
        self._edit_coordinates = QPushButton('Координаты…', self)
        self._edit_radius = QPushButton('Радиус…', self)
        self._remove_bend = QPushButton('Удалить вершину', self)
        self._edit_coordinates.setEnabled(False)
        self._edit_radius.setEnabled(False)
        self._remove_bend.setEnabled(False)
        self._edit_coordinates.clicked.connect(self._change_selected_coordinates)
        self._edit_radius.clicked.connect(self._change_selected_radius)
        self._remove_bend.clicked.connect(self._remove_selected_bend)
        actions.addWidget(self._edit_coordinates)
        actions.addWidget(self._edit_radius)
        actions.addWidget(self._remove_bend)
        view_layout.addLayout(actions)
        self._tabs.currentChanged.connect(self._view_tab_changed)
        self._point_selection.currentIndexChanged.connect(self._selection_changed)
        self._scene.pointPicked.connect(self._point_picked)
        self._scene.ambiguousPick.connect(self._ambiguous_pick)
        self._scene.segmentPicked.connect(self._create_draft)
        self._scene.dragStarted.connect(self._begin_projection_drag)
        self._scene.dragMoved.connect(self._drag_moved)
        self._scene.dragReleased.connect(self._apply_projection_drag)
        self._scene.dragCancelled.connect(self._cancel_projection_drag)
        self._anchors = QLabel(self)
        self._anchors.setWordWrap(True)
        self._anchors.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._anchors)
        self._anchors.hide()  # Coordinates of the selected point appear beside the view.
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
        layout.addStretch(1)
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
        self._lengths.setVisible(skeleton_view)
        self._edit_coordinates.setVisible(skeleton_view)
        self._edit_radius.setVisible(skeleton_view)
        self._remove_bend.setVisible(skeleton_view)

    def _state(self) -> tuple[object, ...]:
        housing_state = json.dumps(self._housings, sort_keys=True, allow_nan=False)
        notch_state = tuple((leg, self._notch_clearances[leg].text()) for leg in ('front', 'rear')
                            if self._notch_checks[leg].isChecked())
        return (self.snapshot, self._from.value(), self._to.value(), self._spacing.value(),
                self._radius.value(), self._wall.value(), self._bend_editor.state(), self._draft, housing_state,
                notch_state)

    def _reset_notches(self) -> None:
        for leg in ('front', 'rear'):
            with QSignalBlocker(self._notch_checks[leg]), QSignalBlocker(self._notch_clearances[leg]):
                self._notch_checks[leg].setChecked(False)
                self._notch_clearances[leg].clear()
            self._notch_checks[leg].setEnabled(False)
            self._notch_clearances[leg].setEnabled(False)
        self._notch_status.clear()

    def _notch_values(self) -> dict[str, float] | None:
        values: dict[str, float] = {}
        for leg in ('front', 'rear'):
            if self._notch_checks[leg].isChecked():
                try:
                    values[leg] = float(self._notch_clearances[leg].text().strip().replace(',', '.'))
                except ValueError as error:
                    raise HousingError('Укажите радиальный зазор каждой выбранной ветви (0–100 мм)') from error
        return validate_notches(values) if values else None

    def _cad_is_current(self, candidate: dict[str, Any]) -> bool:
        if (self.snapshot is None or self.preview is None or self.snapshot != self._cad_snapshot or
                self._cad_candidate is None or candidate != self._cad_candidate or
                not self.snapshot.matches(self.controller.project)):
            return False
        try:
            fresh = fixed_arm_tube_document(self.snapshot, self.controller.project, self._radius.value(),
                                            self._wall.value(), self._bend_editor.values())
            if self._housings is not None:
                fresh = make_housing_preview(fresh, self._housings, self._notch_values())
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
        """Остановить оба CAD-процесса до уничтожения Qt-виджета."""
        cad_stopped = self._cad.shutdown()
        overlap_stopped = self._overlap.shutdown()
        return cad_stopped and overlap_stopped

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
        self._draft = None
        self.preview = None
        self._cad_candidate = None
        self._cad_snapshot = None
        self._cad.set_document(None)
        self._overlap.set_document(None)
        self._save.setEnabled(False)
        self._housing_edit.setEnabled(False)
        self._housing_remove.setEnabled(False)
        self._scene.set_scene(None)
        with QSignalBlocker(self._point_selection):
            self._point_selection.clear()
            self._point_selection.addItem('Точка не выбрана', None)
        self._point_selection.setEnabled(False)
        self._selection_status.setText('Точки выбираются щелчком по маркеру или из списка.')
        self._lengths.clear()
        self._edit_coordinates.setEnabled(False)
        self._edit_radius.setEnabled(False)
        self._remove_bend.setEnabled(False)
        for canvas in self._projections:
            canvas.set_preview(None)
        self._anchors.clear()

    def _edit_housings(self) -> None:
        if self.snapshot is None or self.preview is None or self._draft is not None:
            return
        if not self.snapshot.matches(self.controller.project):
            self._refresh()
            return
        state, project = self._state(), self.controller.project
        editor = FixedArmHousingsDialog(self._housings, self)
        accepted = editor.exec() == QDialog.DialogCode.Accepted
        if (self._state() != state or self.controller.project is not project or self.snapshot is None or
                not self.snapshot.matches(self.controller.project)):
            self._refresh()
            self._housing_status.setText('Данные изменились во время ввода. Корпуса не приняты.')
            return
        if not accepted:
            return
        try:
            candidate = validate_housings(editor.result_values)
            tubes = fixed_arm_tube_document(self.snapshot, self.controller.project, self._radius.value(),
                                            self._wall.value(), self._bend_editor.values())
            make_housing_preview(tubes, candidate)
        except (HousingError, SkeletonError, KimFormatError, ValueError) as error:
            self._housing_status.setText(f'Корпуса не приняты: {error}')
            return
        self._housings = candidate
        self._reset_notches()
        self._refresh()

    def _remove_housings(self) -> None:
        if self._housings is not None and self._draft is None:
            self._housings = None
            self._reset_notches()
            self._refresh()

    def _length_summary(self, bends: dict[str, dict[str, Any]]) -> str:
        if self.preview is None:
            return ''
        result = []
        for index, (leg, name) in enumerate((('front', 'Передняя'), ('rear', 'Задняя'))):
            start, end = self.preview.anchors[index], self.preview.anchors[2]
            if leg not in bends:
                result.append(f'{name}: прямая {dist(start, end):.2f} мм')
            else:
                bend = bends[leg]
                path = make_bend_path(start, bend['vertex_mm'], end, bend['radius_mm'], self._radius.value())
                result.append(f'{name}: прямые {dist(start, path.tangent_start):.2f} + '
                              f'{dist(path.tangent_end, end):.2f} мм; дуга {path.radius * path.sweep_rad:.2f} мм')
        return ' · '.join(result)

    def _create_draft(self, leg: str, point: tuple[float, float, float]) -> None:
        if (self.snapshot is None or self.preview is None or leg not in ('front', 'rear') or
                not self.snapshot.matches(self.controller.project)):
            self._refresh()
            return
        if self._draft is not None:
            self._selection_status.setText('Сначала завершите или удалите черновую вершину.')
            return
        bends = self._bend_editor.values()
        if leg in bends:
            return
        self._draft = (leg, point)
        # The draft is not committed geometry: never display the old CAD as its result.
        self._cad_candidate = None
        self._cad_snapshot = None
        self._cad.set_document(None)
        self._overlap.set_document(None)
        self._save.setEnabled(False)
        self._housing_edit.setEnabled(False)
        self._housing_remove.setEnabled(False)
        for key in ('front', 'rear'):
            self._notch_checks[key].setEnabled(False)
            self._notch_clearances[key].setEnabled(False)
        scene = skeleton_scene(self.preview, bends)
        scene = type(scene)(scene.travel_mm, scene.segments, (*scene.points, (f'bend_{leg}', point)))
        self._scene.set_scene(scene, self.preview.centerlines)
        for canvas in self._projections:
            canvas.set_preview(self.preview, scene.points)
        with QSignalBlocker(self._point_selection):
            self._point_selection.addItem(LABELS[f'bend_{leg}'] + ' · черновик', f'bend_{leg}')
            self._point_selection.setCurrentIndex(self._point_selection.findData(f'bend_{leg}'))
        self._selection_changed()

    def _drag_moved(self, code: str, point: tuple[float, float, float]) -> None:
        if self._gesture_state is None or code != self._gesture_code or self.preview is None:
            return
        leg = code.removeprefix('bend_')
        index = 0 if leg == 'front' else 1
        self._selection_status.setText(f'Кандидат: X={point[0]:.4f}, Y={point[1]:.4f}, Z={point[2]:.4f} мм. '
                                       'Отпустите для проверки; Esc отменяет.')
        self._lengths.setText(f'До виртуальной вершины: {dist(self.preview.anchors[index], point):.2f} + '
                              f'{dist(point, self.preview.anchors[2]):.2f} мм. Не длины после скругления.')

    def _change_selected_coordinates(self) -> None:
        code = self._point_selection.currentData()
        if not isinstance(code, str) or not code.startswith('bend_') or self.snapshot is None or self.preview is None:
            return
        point = self._scene.frame.point(code) if self._scene.frame is not None else None
        if point is None:
            return
        state = self._state()
        editor = QDialog(self)
        editor.setWindowTitle('Координаты вершины')
        layout = QVBoxLayout(editor)
        form = QFormLayout()
        fields: list[QLineEdit] = []
        for axis, value in zip('XYZ', point, strict=True):
            field = QLineEdit(repr(value), editor)
            field.setObjectName('coordinate_' + axis)
            form.addRow(axis + ', мм', field)
            fields.append(field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, editor)
        buttons.accepted.connect(editor.accept)
        buttons.rejected.connect(editor.reject)
        layout.addWidget(buttons)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        if state != self._state() or self.snapshot is None or not self.snapshot.matches(self.controller.project):
            self._refresh()
            self._selection_status.setText('Данные изменились во время ввода координат. Изменение не принято.')
            return
        try:
            coordinates = tuple(float(field.text().strip().replace(',', '.')) for field in fields)
        except ValueError:
            self._selection_status.setText('Введите три конечные числовые координаты. Форма не изменена.')
            return
        self._begin_projection_drag(code)
        self._apply_projection_drag(code, (0, 1, 2), coordinates)  # type: ignore[arg-type]

    def _change_selected_radius(self) -> None:
        code = self._point_selection.currentData()
        if not isinstance(code, str) or not code.startswith('bend_') or self.snapshot is None or self.preview is None:
            return
        leg = code.removeprefix('bend_')
        if self._draft is not None and self._draft[0] == leg:
            self._selection_status.setText('Сначала перетащите черновую вершину с прямой трубы.')
            return
        state = self._state()
        try:
            bends = self._bend_editor.values()
            old = float(bends[leg]['radius_mm'])
            radius, ok = QInputDialog.getDouble(self, 'Радиус изгиба', 'Радиус осевой линии, мм:', old, 0, 1000000, 4)
            if not ok:
                return
            if state != self._state() or self.snapshot is None or not self.snapshot.matches(self.controller.project):
                self._refresh()
                return
            bends[leg]['radius_mm'] = radius
            preview_fixed_arm(self.snapshot, self.controller.project, self._radius.value(), self._wall.value(), bends)
        except (KimFormatError, SkeletonError, KeyError, ValueError, OverflowError) as error:
            self._selection_status.setText(f'Радиус не принят: {error}. Показан прежний скелет.')
            return
        self._bend_editor.fields[leg][3].setText(str(radius))

    def _remove_selected_bend(self) -> None:
        code = self._point_selection.currentData()
        if not isinstance(code, str) or not code.startswith('bend_'):
            return
        leg = code.removeprefix('bend_')
        if self._draft is not None and self._draft[0] == leg:
            self._refresh()
        elif leg in self._bend_editor.checks:
            self._bend_editor.checks[leg].setChecked(False)

    def _selection_changed(self, *_args: object) -> None:
        code = self._point_selection.currentData()
        is_bend = isinstance(code, str) and code.startswith('bend_')
        is_draft = is_bend and self._draft is not None and code == f'bend_{self._draft[0]}'
        self._edit_coordinates.setEnabled(is_bend)
        self._edit_radius.setEnabled(is_bend and not is_draft)
        self._remove_bend.setEnabled(is_bend)
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
        kind = ('Зафиксирована снимком; изменение опоры — только после нового расчёта.' if not is_bend else
                'Черновик: перетащите вершину, затем задайте радиус.' if is_draft else
                'Вершина продолжений, не точка на дуге; перетащите в 3D или на проекции.')
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
        had_gesture = self._gesture_state is not None
        self._gesture_state = None
        self._gesture_project = None
        self._gesture_code = None
        if had_gesture and self.preview is not None and self._scene.frame is not None:
            self._selection_changed()
            self._lengths.setText(self._length_summary(self._bend_editor.values()))

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
                code not in ('bend_front', 'bend_rear') or axes not in ((0, 1), (0, 2), (1, 2), (0, 1, 2))):
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
            is_draft = self._draft is not None and self._draft[0] == leg
            # Hidden projection coordinates come from the original point, never the pointer.
            original = self._draft[1] if is_draft and self._draft is not None else bends[leg]['vertex_mm']
            vertex = list(original)
            for axis in axes:
                vertex[axis] = coordinates[axis]
            if is_draft:
                radius, ok = QInputDialog.getDouble(self, 'Радиус скругления',
                                                    'Введите радиус осевой линии изгиба, мм:', 0, 0, 1000000, 4)
                if not ok:
                    self._selection_changed()
                    self._lengths.setText(self._length_summary(bends))
                    return
                if state != self._state() or self.snapshot is None or not self.snapshot.matches(self.controller.project):
                    self._refresh()
                    self._selection_status.setText('Данные изменились во время ввода радиуса. Изгиб не принят.')
                    return
                bends[leg] = {'vertex_mm': vertex, 'radius_mm': radius}
            else:
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
        if is_draft:
            self._draft = None
            self._bend_editor.load(bends)
        else:
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
        self._housings = loaded.housings
        self._reset_notches()
        for leg, clearance in (loaded.notches or {}).items():
            with QSignalBlocker(self._notch_checks[leg]), QSignalBlocker(self._notch_clearances[leg]):
                self._notch_clearances[leg].setText(repr(clearance))
                self._notch_checks[leg].setChecked(True)
        self._refresh()
        if self.snapshot is None or self.preview is None:
            self._file_status.setText('Схема изменилась во время открытия; снимок не принят.')
            return
        self._saved_state = self._state()
        self._file_status.setText('Открыт и пересчитан файл: ' + selected +
                                  '. Сохранённая невязка — только историческая запись, не сертификат.')

    def _save_file(self) -> None:
        if self.snapshot is None or self.preview is None or self._draft is not None:
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
                           self._wall.value(), self._bend_editor.values(), self._housings, self._notch_values())
        except (SkeletonFileError, KimFormatError, OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, 'Сохранение скелета', str(error))
            self._refresh()
            return
        self._saved_state = self._state()
        self._file_status.setText(f'Сохранён новый файл: {path}. Проект не изменён; '
                                  'параметры подрезки не подтверждают успешное CAD-построение.')

    def _range_changed(self, *_args: object) -> None:
        self._file_status.clear()
        if self.snapshot is not None:
            self.snapshot = None
            self._housings = None
            self._reset_notches()
            self._housing_status.setText('Корпуса сброшены: требуется новое подтверждение опор и параметров.')
            self._bend_editor.set_editable(False)
            self._clear_preview()
            self._status.setText('Диапазон изменён. Повторно рассчитайте и зафиксируйте снимок.')

    def _project_replaced(self) -> None:
        self._file_status.clear()
        self.snapshot = None
        self._housings = None
        self._reset_notches()
        self._housing_status.setText('Корпуса сброшены: требуется новое подтверждение опор и параметров.')
        self._bend_editor.set_editable(False)
        self._clear_preview()
        self._status.setText('Проект заменён. Повторно рассчитайте и зафиксируйте снимок.')

    def _capture_snapshot(self) -> None:
        if self.snapshot is not None or self._bend_editor.has_bends():
            answer = QMessageBox.question(self, 'Новый снимок',
                'Рассчитать новую схему? Изгибы будут проверены заново; параметры корпусов сбросятся '
                'и потребуют нового подтверждения опор.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._file_status.clear()
        try:
            snapshot = capture_fixed_arm(self.controller.project, self._from.value(), self._to.value(),
                                         spacing_mm=self._spacing.value())
        except SkeletonError as error:
            self.snapshot = None
            self._housings = None
            self._reset_notches()
            self._housing_status.setText('Корпуса не заданы.')
            self._bend_editor.set_editable(False)
            self._clear_preview()
            self._status.setText(str(error))
            return
        self.snapshot = snapshot
        self._housings = None
        self._reset_notches()
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
            self._housings = None
            self._reset_notches()
            self._housing_status.setText('Корпуса сброшены: требуется новое подтверждение опор и параметров.')
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
            if self._housings is not None:
                document = make_housing_preview(document, self._housings)
            scene = skeleton_scene(preview, bends)
        except KimFormatError:
            self._status.setText('Заполните X, Y, Z и радиус для каждого включённого изгиба.')
            return
        except (SkeletonError, HousingError) as error:
            self._status.setText(str(error))
            return
        self.preview = preview
        self._save.setEnabled(True)
        self._housing_edit.setEnabled(True)
        self._housing_remove.setEnabled(self._housings is not None)
        for leg in ('front', 'rear'):
            self._notch_checks[leg].setEnabled(self._housings is not None)
            self._notch_clearances[leg].setEnabled(self._housings is not None and self._notch_checks[leg].isChecked())
        self._notch_status.clear()
        cad_document: dict[str, Any] | None = document
        notches = None
        if self._housings is not None:
            try:
                notches = self._notch_values()
                cad_document = make_housing_preview(document['tubes'], self._housings, notches)
            except (HousingError, ValueError) as error:
                cad_document = None
                self._save.setEnabled(False)
                self._notch_status.setText(f'CAD и сохранение скрыты: {error}. Исправьте ввод или отключите подрезку.')
        self._cad_candidate = cad_document
        self._cad_snapshot = self.snapshot if cad_document is not None else None
        self._cad.set_document(cad_document)
        self._overlap.set_document(cad_document)
        self._housing_status.setText('Оба корпуса заданы и центры опор подтверждены.' if self._housings is not None
                                     else 'Корпуса не заданы.')
        self._cad_note.setText('Предварительный CAD: выбранные ветви подрезаются только по своим корпусам; '
                               'прочие пересечения, швы, шаровая, зазоры и прочность не проверяются.'
                               if notches else
                               'Предварительный CAD: трубы не подрезаны; корпуса — отдельные тела. '
                               'Возможны пересечения; швов, шаровой и проверки зазоров или прочности нет.'
                               if self._housings is not None else
                               'Предварительный CAD: трубы не подрезаны, корпуса не заданы. '
                               'Шаровой, швов и проверки зазоров или прочности нет.')
        self._scene.set_scene(scene, preview.centerlines)
        self._lengths.setText(self._length_summary(bends))
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

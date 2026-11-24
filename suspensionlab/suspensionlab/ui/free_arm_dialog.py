"""Первый независимый черновик рычага: явные координаты, эскиз и предварительный CAD."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import dist, isfinite
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ..core.cad_mesh import CadMesh
from ..model.bend_length import vertex_for_length
from ..model.bent_tube import make_bend_path
from ..model.fixed_arm_housings import HousingError
from ..model.fixed_arm_skeleton import SkeletonPreview
from ..model.free_arm import FreeArmBend, FreeArmDraft, FreeArmError
from ..model.free_arm_housing import FreeArmBallHousing, FreeArmHousingDraft, FreeArmHousingError
from ..model.free_arm_housing_io import read_independent_arm, write_free_arm_housing
from ..model.free_arm_housing_io import to_data as housing_to_data
from ..model.free_arm_inner_housings import FreeArmInnerHousing, FreeArmInnerHousingDraft, FreeArmInnerHousings
from ..model.free_arm_inner_housings_io import to_data as inner_to_data
from ..model.free_arm_inner_housings_io import write_free_arm_inner_housings
from ..model.free_arm_io import FreeArmFileError, to_data, write_free_arm
from ..model.free_arm_miter import FreeArmMiterDraft, FreeArmMiterError
from ..model.free_arm_miter_io import to_data as miter_to_data
from ..model.free_arm_miter_io import write_free_arm_miter
from ..model.free_arm_tube_joint import FreeArmTubeJoint, FreeArmTubeJointDraft
from ..model.free_arm_tube_joint_io import to_data as joint_to_data
from ..model.free_arm_tube_joint_io import write_free_arm_tube_joint
from .canvas.fixed_arm_projection import SkeletonProjection
from .canvas.fixed_arm_scene import FixedArmScene, skeleton_scene
from .inline_tube_sketch import InlineTubeSketch
from .weldment_3d import Weldment3D


@dataclass(frozen=True, slots=True)
class _ProjectionSession:
    canvas: SkeletonProjection
    code: str
    form: tuple[object, ...]
    draft: FreeArmDraft
    housing: FreeArmBallHousing | None
    preview: SkeletonPreview
    initial_text: tuple[str, ...]
    original_points: tuple[tuple[str, tuple[float, float, float]], ...]
    new_vertex: tuple[float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class _CutPick:
    part: str
    generation: int
    form: tuple[object, ...]
    draft: FreeArmDraft
    housing: FreeArmBallHousing | None
    inner: FreeArmInnerHousings | None
    miter: bool
    joint: FreeArmTubeJoint | None
    mesh: CadMesh


@dataclass(frozen=True, slots=True)
class _TrimState:
    """Только принятые подрезки и их отображаемый ввод; не история всей модели."""
    inner: FreeArmInnerHousings | None
    miter: bool
    joint: FreeArmTubeJoint | None
    front_checked: bool
    front_text: str
    rear_checked: bool
    rear_text: str
    joint_target: object
    joint_text: str


class FreeArmDialog(QDialog):
    """Не читает и не изменяет открытый проект подвески."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Независимый рычаг по трём точкам · эксперимент')
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(1080, 760)
        self.draft: FreeArmDraft | None = None
        self.housing: FreeArmBallHousing | None = None
        self.inner_housings: FreeArmInnerHousings | None = None
        self.miter = False
        self.tube_joint: FreeArmTubeJoint | None = None
        self._accepted_form: tuple[object, ...] | None = None
        self._inline_session: tuple[str, int, tuple[object, ...], FreeArmDraft, CadMesh] | None = None
        self._inline_initial: tuple[str, ...] | None = None
        self._cad_cut_pick: _CutPick | None = None
        self._cad_cut_prompting = False
        self._projection_session: _ProjectionSession | None = None
        self._projection_gesture: _ProjectionSession | None = None
        self._projection_radius_pending = False
        self._loading = False
        self._trim_history: list[_TrimState] = []
        self._trim_history_index = 0
        self._trim_history_context: tuple[object, ...] | None = None
        self._closing_confirmed = False
        root = QVBoxLayout(self)
        warning = QLabel('Независимые координаты XYZ, мм. Это не расчётная подвеска и не снимок хода. '
                         'Кинематика, зазоры, монтаж, сварка и прочность не проверяются. '
                         'Без выбранных подрезок трубы неподрезаны; центральный корпус опционален. '
                         'Стыки труб несовместимы между собой и с центральным корпусом; CAD не является расчётом. '
                         'В CAD щёлкните ПКМ по трубе для эскиза; это не длины детали. '
                         'Выключенные изгибы и корпус в файл не записываются.', self)
        warning.setWordWrap(True)
        root.addWidget(warning)
        workspace_row = QHBoxLayout()
        self._settings_toggle = QPushButton('Параметры и файлы', self)
        self._settings_toggle.setObjectName('free_arm_settings_toggle')
        self._settings_toggle.setCheckable(True)
        self._settings_toggle.setChecked(True)
        self._settings_toggle.setToolTip('Показать или скрыть панель ввода и сохранения, не изменяя документ')
        workspace_row.addWidget(self._settings_toggle)
        self._advanced_toggle = QPushButton('Дополнительные CAD-инструменты', self)
        self._advanced_toggle.setObjectName('free_arm_advanced_toggle')
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setChecked(True)
        self._advanced_toggle.setToolTip('Показать или скрыть качество, дерево деталей и сброс вида')
        workspace_row.addWidget(self._advanced_toggle)
        workspace_row.addStretch(1)
        root.addLayout(workspace_row)
        self._projection_controls = QWidget(self)
        projection_controls_layout = QVBoxLayout(self._projection_controls)
        projection_controls_layout.setContentsMargins(0, 0, 0, 0)
        projection_controls_layout.setSpacing(0)
        projection_row = QHBoxLayout()
        self._projection_note = QLabel('Проекции: выберите вершину или прямую трубу.', self)
        self._projection_note.setFixedHeight(30)
        projection_row.addWidget(self._projection_note, 1)
        self._projection_cancel = QPushButton('Закрыть ввод проекции', self)
        self._projection_cancel.setEnabled(False)
        self._projection_cancel.clicked.connect(self._close_projection_session)
        projection_row.addWidget(self._projection_cancel)
        projection_controls_layout.addLayout(projection_row)
        radius_row = QHBoxLayout()
        radius_label = QLabel('Радиус выбранного изгиба, мм', self)
        radius_row.addWidget(radius_label)
        self._projection_radius = QLineEdit(self)
        self._projection_radius.setObjectName('free_arm_projection_radius')
        self._projection_radius.setAccessibleName('Радиус осевой линии выбранного изгиба, мм')
        self._projection_radius.setMaximumWidth(120)
        self._projection_radius.setMaxLength(64)
        self._projection_radius.setEnabled(False)
        radius_row.addWidget(self._projection_radius)
        self._projection_radius_apply = QPushButton('Применить радиус', self)
        self._projection_radius_apply.setAutoDefault(False)
        self._projection_radius_apply.setEnabled(False)
        self._projection_radius_apply.clicked.connect(self._apply_projection_radius)
        radius_row.addWidget(self._projection_radius_apply)
        self._projection_radius_reset = QPushButton('Сброс радиуса', self)
        self._projection_radius_reset.setAutoDefault(False)
        self._projection_radius_reset.setEnabled(False)
        self._projection_radius_reset.clicked.connect(self._reset_projection_radius)
        radius_row.addWidget(self._projection_radius_reset)
        radius_row.addStretch(1)
        projection_controls_layout.addLayout(radius_row)
        root.addWidget(self._projection_controls)
        self._cad_pick_controls = QWidget(self)
        pick_row = QHBoxLayout(self._cad_pick_controls)
        pick_row.setContentsMargins(0, 0, 0, 0)
        self._cad_pick_status = QLabel('Выберите вторую деталь.', self._cad_pick_controls)
        self._cad_pick_status.setWordWrap(True)
        pick_row.addWidget(self._cad_pick_status, 1)
        self._cad_pick_cancel = QPushButton('Отменить выбор', self._cad_pick_controls)
        self._cad_pick_cancel.setAutoDefault(False)
        self._cad_pick_cancel.clicked.connect(self._cancel_cad_cut_pick)
        pick_row.addWidget(self._cad_pick_cancel)
        self._cad_pick_controls.hide()
        root.addWidget(self._cad_pick_controls)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(split, 1)
        scroll = QScrollArea(split)
        self._parameters_scroll = scroll
        self._settings_toggle.toggled.connect(scroll.setVisible)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        panel = QWidget(scroll)
        self._parameter_panel = panel
        scroll.setWidget(panel)
        form = QFormLayout(panel)
        self._fields: dict[str, QLineEdit] = {}
        for prefix, title in (('front', 'Передняя опора'), ('rear', 'Задняя опора'), ('outer', 'Наружная опора')):
            for axis in 'XYZ':
                self._add_field(form, f'{prefix}_{axis}', f'{title} · {axis}, мм')
        self._add_field(form, 'radius', 'Наружный радиус трубы, мм', '10')
        self._add_field(form, 'wall', 'Толщина стенки, мм', '2')
        self._bend_checks: dict[str, QCheckBox] = {}
        for leg, title in (('front', 'Передняя'), ('rear', 'Задняя')):
            check = QCheckBox(f'{title} труба: один изгиб', panel)
            check.toggled.connect(self._edited)
            self._bend_checks[leg] = check
            form.addRow(check)
            for axis in 'XYZ':
                self._add_field(form, f'{leg}_bend_{axis}', f'{title} · вершина {axis}, мм')
            self._add_field(form, f'{leg}_bend_radius', f'{title} · радиус изгиба, мм')
            for suffix in ('X', 'Y', 'Z', 'radius'):
                field = self._fields[f'{leg}_bend_{suffix}']
                field.setEnabled(False)
                check.toggled.connect(field.setEnabled)
        self._housing_check = QCheckBox('Центральный корпус с подрезкой труб', panel)
        self._housing_check.setObjectName('free_arm_housing_enabled')
        self._housing_check.toggled.connect(self._edited)
        form.addRow(self._housing_check)
        housing_fields = [('housing_outer', 'Корпус · наружный диаметр, мм', '120'),
                          ('housing_bore', 'Корпус · диаметр отверстия, мм', '30'),
                          ('housing_length', 'Корпус · длина, мм', '200')]
        housing_fields += [(f'housing_axis_{axis}', f'Ось корпуса · {axis}', '1' if axis == 'Z' else '0')
                           for axis in 'XYZ']
        housing_fields += [(f'housing_offset_{axis}', f'Смещение центра от наружной опоры · {axis}, мм', '0')
                           for axis in 'XYZ']
        for key, label, default in housing_fields:
            self._add_field(form, key, label, default)
            self._fields[key].setEnabled(False)
            self._housing_check.toggled.connect(self._fields[key].setEnabled)
        self._miter_check = QCheckBox('Общий стык труб на ус (нулевой зазор)', panel)
        self._miter_check.setObjectName('free_arm_miter_enabled')
        self._miter_check.setToolTip('Несовместим с центральным корпусом; CAD проверяет конечную геометрию')
        self._miter_check.toggled.connect(self._edited)
        form.addRow(self._miter_check)
        self._tube_joint_choice = QComboBox(panel)
        self._tube_joint_choice.setObjectName('free_arm_tube_joint')
        self._tube_joint_choice.addItem('Не подрезать по другой трубе', None)
        self._tube_joint_choice.addItem('Подрезать переднюю по задней', 'front')
        self._tube_joint_choice.addItem('Подрезать заднюю по передней', 'rear')
        form.addRow('Подрезка по другой трубе', self._tube_joint_choice)
        self._add_field(form, 'tube_joint_clearance', 'Радиальный зазор подрезки, мм')
        self._fields['tube_joint_clearance'].setEnabled(False)
        self._tube_joint_choice.currentIndexChanged.connect(self._edited)
        self._tube_joint_choice.currentIndexChanged.connect(self._update_tube_joint_controls)
        self._inner_check = QCheckBox('Два корпуса внутренних опор', panel)
        self._inner_check.setObjectName('free_arm_inner_enabled')
        self._inner_check.toggled.connect(self._edited)
        form.addRow(self._inner_check)
        self._inner_confirm: dict[str, QCheckBox] = {}
        self._inner_notch: dict[str, QCheckBox] = {}
        for leg, title in (('front', 'Передний'), ('rear', 'Задний')):
            confirm = QCheckBox(f'{title}: центр совпадает с опорой', panel)
            self._inner_confirm[leg] = confirm
            confirm.setEnabled(False)
            self._inner_check.toggled.connect(confirm.setEnabled)
            confirm.toggled.connect(self._edited)
            form.addRow(confirm)
            fields = [(f'{leg}_inner_outer', f'{title} корпус · наружный диаметр, мм', '40'),
                      (f'{leg}_inner_bore', f'{title} корпус · отверстие, мм', '25'),
                      (f'{leg}_inner_length', f'{title} корпус · длина, мм', '32')]
            fields += [(f'{leg}_inner_axis_{axis}', f'{title} корпус · ось {axis}', '1' if axis == 'Z' else '0')
                       for axis in 'XYZ']
            for key, label, default in fields:
                self._add_field(form, key, label, default)
                self._fields[key].setEnabled(False)
                self._inner_check.toggled.connect(self._fields[key].setEnabled)
            notch = QCheckBox(f'{title}: подрезать по корпусу', panel)
            self._inner_notch[leg] = notch
            notch.setEnabled(False)
            self._inner_check.toggled.connect(notch.setEnabled)
            notch.toggled.connect(self._edited)
            form.addRow(notch)
            key = f'{leg}_inner_clearance'
            self._add_field(form, key, f'{title}: радиальный зазор, мм', '0')
            self._fields[key].setEnabled(False)
            notch.toggled.connect(self._update_inner_controls)
        self._inner_check.toggled.connect(self._update_inner_controls)
        history_label = QLabel('История подрезок', panel)
        history_label.setWordWrap(True)
        form.addRow(history_label)
        self._trim_undo = QPushButton('Отменить', panel)
        self._trim_undo.setObjectName('free_arm_trim_undo')
        self._trim_undo.setAccessibleName('Отменить последний принятый шаг подрезок')
        self._trim_undo.setAutoDefault(False)
        self._trim_undo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._trim_undo.setEnabled(False)
        self._trim_undo.setToolTip('Отменить один принятый шаг подрезок, который может менять несколько резов. '
                                   'Незавершённый ввод сначала примените или верните.')
        self._trim_undo.clicked.connect(self._undo_trim)
        form.addRow(self._trim_undo)
        self._trim_redo = QPushButton('Повторить', panel)
        self._trim_redo.setObjectName('free_arm_trim_redo')
        self._trim_redo.setAccessibleName('Повторить отменённый шаг подрезок')
        self._trim_redo.setAutoDefault(False)
        self._trim_redo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._trim_redo.setEnabled(False)
        self._trim_redo.setToolTip('История сбрасывается при изменении труб или корпусов и при открытии файла')
        self._trim_redo.clicked.connect(self._redo_trim)
        form.addRow(self._trim_redo)
        apply = QPushButton('Применить точки и размеры', panel)
        apply.clicked.connect(self.apply_fields)
        form.addRow(apply)
        reset = QPushButton('Вернуть последний применённый ввод', panel)
        reset.clicked.connect(self._restore_draft)
        form.addRow(reset)
        self._status = QLabel('Введите три опоры и примените. Координаты не берутся из проекта.', panel)
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self._status)
        buttons = QHBoxLayout()
        open_button = QPushButton('Открыть независимый .slarm…', panel)
        open_button.clicked.connect(self._open_file)
        self._save = QPushButton('Сохранить новый .slarm…', panel)
        self._save.setEnabled(False)
        self._save.clicked.connect(self._save_file)
        buttons.addWidget(open_button)
        buttons.addWidget(self._save)
        form.addRow(buttons)
        self._tabs = QTabWidget(split)
        self._scene = FixedArmScene(self._tabs, outer_label='Наружная опора')
        self._scene.legend_override = 'ЛКМ: вращение · ПКМ: сдвиг · колесо: масштаб'
        self._tabs.addTab(self._scene, '3D · осевые линии')
        self._projections = [SkeletonProjection(axes, self._tabs, outer_title='До наружной опоры',
                                                outer_label='Наружная опора')
                             for axes in ((0, 1), (0, 2), (1, 2))]
        for title, projection in zip(('XY', 'XZ', 'YZ'), self._projections, strict=True):
            projection.pointPicked.connect(lambda code, canvas=projection: self._projection_point(canvas, code))
            projection.ambiguousPick.connect(self._projection_ambiguous)
            projection.segmentPicked.connect(lambda leg, point, canvas=projection:
                                               self._projection_segment(canvas, leg, point))
            projection.dragStarted.connect(lambda code, canvas=projection: self._projection_drag_start(canvas, code))
            projection.dragCancelled.connect(self._projection_drag_cancel)
            projection.dragReleased.connect(lambda code, axes, point, canvas=projection:
                                            self._projection_drag_apply(canvas, code, axes, point))
            projection.dimensionsApplied.connect(lambda code, axes, point, canvas=projection:
                                                   self._projection_dimension_apply(canvas, code, axes, point))
            self._tabs.addTab(projection, title + ' · эскиз')
        self._cad = Weldment3D(self._tabs, is_current=self._is_current, fixed_skeleton=True)
        self._advanced_toggle.toggled.connect(lambda expanded: self._cad.set_workspace_compact(not expanded))
        self._cad.partContextRequested.connect(self._cad_context_menu)
        self._cad.partPicked.connect(self._cad_part_picked)
        self._cad._view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._cad._view.installEventFilter(self)
        self._projection_radius.installEventFilter(self)
        self._inline_sketch = InlineTubeSketch(self._cad._view)
        self._inline_sketch.applied.connect(self._apply_inline_sketch)
        self._inline_sketch.candidateChanged.connect(self._preview_inline_sketch)
        self._inline_sketch.cancelled.connect(self._close_inline_sketch)
        self._cad._view.sketch_dimension_requested.connect(self._focus_inline_dimension)
        self._inline_sketch.move(8, 8)
        self._cad.availabilityChanged.connect(self._cad_availability_changed)
        self._tabs.addTab(self._cad, 'Предварительный CAD')
        split.addWidget(scroll)
        split.addWidget(self._tabs)
        split.setStretchFactor(1, 1)
        self._tabs.currentChanged.connect(self._update_projection_controls)
        self._tabs.currentChanged.connect(self._cancel_cut_on_tab_change)
        self._update_projection_controls()
        self._saved_form = self._form()

    def _update_projection_controls(self, _index: int = -1) -> None:
        # Keep cancellation accessible even if code changes tabs during an active session.
        self._projection_controls.setVisible(self._projection_session is not None or
                                             self._tabs.currentWidget() in self._projections)

    def _add_field(self, form: QFormLayout, key: str, label: str, value: str = '') -> None:
        field = QLineEdit(value, self)
        field.setObjectName('free_arm_' + key)
        field.setAccessibleName(label)
        field.setMaxLength(64)
        field.textChanged.connect(self._edited)
        self._fields[key] = field
        form.addRow(label, field)

    def _form(self) -> tuple[object, ...]:
        return (tuple(field.text() for field in self._fields.values()),
                tuple(check.isChecked() for check in self._bend_checks.values()),
                self._housing_check.isChecked(), self._miter_check.isChecked(), self._tube_joint_choice.currentData(),
                self._inner_check.isChecked(),
                tuple(c.isChecked() for c in self._inner_confirm.values()),
                tuple(c.isChecked() for c in self._inner_notch.values()))

    def _edited(self, *_args: object) -> None:
        if self._loading:
            return
        self._cancel_cad_cut_pick()
        self._close_projection_session()
        self._close_inline_sketch()
        self._accepted_form = None
        self._scene.set_scene(None)
        for projection in self._projections:
            projection.set_preview(None)
        self._cad.set_document(None)
        self._save.setEnabled(False)
        self._update_trim_history_buttons()
        self._status.setText('Ввод изменён: прежний эскиз и CAD скрыты. Примените или верните ввод.')

    def _trim_context(self, draft: FreeArmDraft, housing: FreeArmBallHousing | None) -> tuple[object, ...]:
        inner = self.inner_housings
        return (draft, housing, inner.front if inner else None, inner.rear if inner else None)

    def _trim_state(self) -> _TrimState:
        return _TrimState(self.inner_housings, self.miter, self.tube_joint,
                          self._inner_notch['front'].isChecked(), self._fields['front_inner_clearance'].text(),
                          self._inner_notch['rear'].isChecked(), self._fields['rear_inner_clearance'].text(),
                          self._tube_joint_choice.currentData(), self._fields['tube_joint_clearance'].text())

    def _update_trim_history_buttons(self) -> None:
        if not hasattr(self, '_trim_undo'):
            return
        active = (bool(self._trim_history) and self.draft is not None and self._accepted_form == self._form() and
                  self._projection_session is None and self._inline_session is None and
                  self._cad_cut_pick is None and not self._cad._closed)
        self._trim_undo.setEnabled(active and self._trim_history_index > 0)
        self._trim_redo.setEnabled(active and self._trim_history_index + 1 < len(self._trim_history))

    def _record_trim_history(self, draft: FreeArmDraft, housing: FreeArmBallHousing | None) -> None:
        context, state = self._trim_context(draft, housing), self._trim_state()
        if not self._trim_history or context != self._trim_history_context:
            self._trim_history, self._trim_history_index = [state], 0
            self._trim_history_context = context
        elif state != self._trim_history[self._trim_history_index]:
            del self._trim_history[self._trim_history_index + 1:]
            self._trim_history.append(state)
            if len(self._trim_history) > 101:
                self._trim_history.pop(0)
            self._trim_history_index = len(self._trim_history) - 1
        self._update_trim_history_buttons()

    def _reset_trim_history(self) -> None:
        self._trim_history.clear()
        self._trim_history_index = 0
        self._trim_history_context = None
        if self.draft is not None:
            self._record_trim_history(self.draft, self.housing)
        else:
            self._update_trim_history_buttons()

    def _set_trim_fields(self, state: _TrimState) -> None:
        self._loading = True
        try:
            self._inner_notch['front'].setChecked(state.front_checked)
            self._fields['front_inner_clearance'].setText(state.front_text)
            self._inner_notch['rear'].setChecked(state.rear_checked)
            self._fields['rear_inner_clearance'].setText(state.rear_text)
            self._miter_check.setChecked(state.miter)
            self._tube_joint_choice.setCurrentIndex(self._tube_joint_choice.findData(state.joint_target))
            self._fields['tube_joint_clearance'].setText(state.joint_text)
        finally:
            self._loading = False

    def _restore_trim_history(self, index: int) -> None:
        if (self.draft is None or self._cad._closed or self._accepted_form != self._form() or
                self._projection_session is not None or self._inline_session is not None or
                self._cad_cut_pick is not None or not 0 <= index < len(self._trim_history) or
                self._trim_context(self.draft, self.housing) != self._trim_history_context or
                self._trim_state() != self._trim_history[self._trim_history_index]):
            return
        state = self._trim_history[index]
        self._set_trim_fields(state)
        self.inner_housings, self.miter, self.tube_joint = state.inner, state.miter, state.joint
        self._trim_history_index = index
        self._install(self.draft, self.housing)
        self._status.setText('Восстановлены принятые параметры подрезок; CAD проверяется отдельно.')

    def _undo_trim(self) -> None:
        self._restore_trim_history(self._trim_history_index - 1)

    def _redo_trim(self) -> None:
        self._restore_trim_history(self._trim_history_index + 1)

    @staticmethod
    def _paths(draft: FreeArmDraft, housing: FreeArmBallHousing | None) -> tuple[tuple[tuple[float, float, float], ...], ...]:
        return FreeArmHousingDraft(draft, housing).centerlines() if housing is not None else draft.centerlines()

    def _document_for(self, draft: FreeArmDraft, housing: FreeArmBallHousing | None) -> dict[str, Any]:
        if self.tube_joint is not None:
            if housing is not None or self.miter:
                raise HousingError('Подрезка по трубе несовместима с центральным корпусом или стыком на ус')
            return joint_to_data(FreeArmTubeJointDraft(draft, self.tube_joint, self.inner_housings))
        if self.miter:
            if housing is not None:
                raise FreeArmMiterError('Общий стык несовместим с центральным корпусом')
            return miter_to_data(FreeArmMiterDraft(draft, self.inner_housings))
        if self.inner_housings is not None:
            return inner_to_data(FreeArmInnerHousingDraft(draft, self.inner_housings, housing))
        return housing_to_data(FreeArmHousingDraft(draft, housing)) if housing is not None else to_data(draft)

    def _is_current(self, document: dict[str, Any]) -> bool:
        return (self.draft is not None and self._accepted_form == self._form() and
                document == self._document_for(self.draft, self.housing))

    def _projection_text(self) -> tuple[str, ...] | None:
        if self._projection_session is None:
            return None
        canvas = self._projection_session.canvas
        return tuple(field.text() for field in (*canvas._dimension_fields, *canvas._distance_fields,
                                                self._projection_radius))

    def _projection_current(self, canvas: SkeletonProjection, code: str) -> bool:
        session = self._projection_session
        return bool(session is not None and session.canvas is canvas and session.code == code and
                    session.draft is self.draft and session.housing is self.housing and session.form == self._form() and
                    session.form == self._accepted_form and self._tabs.currentWidget() is canvas and
                    canvas.preview is session.preview and
                    canvas.points == (session.original_points + ((code, session.new_vertex),)
                                      if session.new_vertex is not None else session.original_points) and
                    canvas.selected_point == code and self._inline_session is None)

    def _close_projection_session(self) -> None:
        session, self._projection_session = self._projection_session, None
        self._projection_gesture = None
        if session is None:
            return
        session.canvas._cancel_drag()
        if session.canvas.preview is session.preview and session.new_vertex is not None:
            session.canvas.set_preview(session.preview, session.original_points)
        else:
            session.canvas.select_point(None)
        for index in range(self._tabs.count()):
            self._tabs.setTabEnabled(index, True)
        self._parameter_panel.setEnabled(True)
        self._projection_radius.setEnabled(False)
        self._projection_radius_apply.setEnabled(False)
        self._projection_radius_reset.setEnabled(False)
        self._projection_radius.clear()
        self._projection_cancel.setEnabled(False)
        self._projection_note.setText('Проекции: выберите вершину или прямую трубу.')
        self._update_projection_controls()
        self._save.setEnabled(self._inline_session is None and self.draft is not None and
                              self._accepted_form == self._form())
        self._update_trim_history_buttons()

    def _projection_point(self, canvas: SkeletonProjection, code: str) -> None:
        if self._projection_session is not None:
            if self._projection_session.canvas is not canvas or self._projection_session.code != code:
                self._projection_note.setText('Сначала примените или закройте текущий ввод проекции.')
            return
        if self._inline_session is not None:
            self._projection_note.setText('Сначала примените или закройте эскиз CAD.')
            return
        if (self._tabs.currentWidget() is not canvas or code not in ('bend_front', 'bend_rear') or
                self.draft is None or self._accepted_form != self._form()):
            self._projection_note.setText('Опоры задаются в полях слева; выберите вершину существующего изгиба.')
            return
        bend = self.draft.front_bend if code == 'bend_front' else self.draft.rear_bend
        if bend is None or canvas.preview is None:
            return
        self._begin_projection_session(canvas, code)

    def _begin_projection_session(self, canvas: SkeletonProjection, code: str,
                                  vertex: tuple[float, float, float] | None = None) -> None:
        if self.draft is None or canvas.preview is None or self._projection_session is not None:
            return
        original_points = canvas.points
        if vertex is not None:
            canvas.set_preview(canvas.preview, (*canvas.points, (code, vertex)))
        canvas.select_point(code)
        if canvas.selected_point != code or canvas._dimension_point is None:
            canvas.set_preview(canvas.preview, original_points)
            return
        bend = self.draft.front_bend if code == 'bend_front' else self.draft.rear_bend
        if vertex is None and bend is None:
            canvas.select_point(None)
            return
        self._projection_radius.setText(repr(bend.radius_mm) if vertex is None and bend is not None else '')
        self._projection_radius.setEnabled(vertex is None)
        self._projection_radius_apply.setEnabled(vertex is None)
        self._projection_radius_reset.setEnabled(vertex is None)
        initial = tuple(field.text() for field in (*canvas._dimension_fields, *canvas._distance_fields,
                                                   self._projection_radius))
        self._projection_session = _ProjectionSession(canvas, code, self._form(), self.draft, self.housing,
                                                      canvas.preview, initial, original_points, vertex)
        self._parameter_panel.setEnabled(False)
        for index in range(self._tabs.count()):
            self._tabs.setTabEnabled(index, self._tabs.widget(index) is canvas)
        self._projection_cancel.setEnabled(True)
        self._save.setEnabled(False)
        self._update_trim_history_buttons()
        self._projection_note.setText('Черновая вершина: сместите и задайте радиус.' if vertex is not None else
                                      'Ввод проекции: примените размеры или закройте без изменений.')

    def _projection_ambiguous(self) -> None:
        self._projection_note.setText('Маркеры перекрываются: используйте другую проекцию или поля слева.')

    def _projection_segment(self, canvas: SkeletonProjection, leg: str, point: object) -> None:
        draft = self.draft
        if self._projection_session is not None or self._inline_session is not None:
            self._projection_note.setText('Сначала завершите текущий ввод.')
            return
        if (self._tabs.currentWidget() is not canvas or leg not in ('front', 'rear') or draft is None or
                self._accepted_form != self._form() or canvas.preview is None or
                canvas.preview.anchors != draft.anchors or
                canvas.preview.centerlines != self._paths(draft, self.housing) or
                not isinstance(point, tuple) or len(point) != 3 or
                not all(isinstance(v, (float, int)) and not isinstance(v, bool) and isfinite(v) for v in point)):
            return
        bend = draft.front_bend if leg == 'front' else draft.rear_bend
        if bend is not None:
            return
        start = draft.front_mm if leg == 'front' else draft.rear_mm
        end = canvas.preview.centerlines[0 if leg == 'front' else 1][-1]
        length = dist(start, end)
        fraction = sum((point[i] - start[i]) * (end[i] - start[i]) for i in range(3)) / (length * length)
        expected = tuple(start[i] + fraction * (end[i] - start[i]) for i in range(3))
        if not 0.05 < fraction < 0.95 or dist(point, expected) > max(1e-7, length * 1e-9):
            return
        # Reject possible overlap with the other path, including its curved samples.
        # The emitted point can be up to 9 px from the actual click, so use 18 px here.
        pos = canvas._screen_point(point)
        other = canvas.preview.centerlines[1 if leg == 'front' else 0]
        for first, second in zip(other, other[1:], strict=False):
            a, b = canvas._screen_point(first), canvas._screen_point(second)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            square = dx * dx + dy * dy
            t = max(0., min(1., ((pos.x() - a.x()) * dx + (pos.y() - a.y()) * dy) / square)) if square else 0.
            if (pos.x() - a.x() - t * dx) ** 2 + (pos.y() - a.y() - t * dy) ** 2 <= 18 ** 2:
                self._projection_ambiguous()
                return
        self._begin_projection_session(canvas, f'bend_{leg}', point)

    def _projection_drag_start(self, canvas: SkeletonProjection, code: str) -> None:
        session = self._projection_session
        if (session is None or not self._projection_current(canvas, code) or
                self._projection_text() != session.initial_text):
            canvas._cancel_drag()
            self._projection_note.setText('Перед перемещением примените или сбросьте введённые размеры.')
            return
        self._projection_gesture = session

    def _projection_drag_cancel(self) -> None:
        self._projection_gesture = None

    def _projection_drag_apply(self, canvas: SkeletonProjection, code: str, axes: object, point: object) -> None:
        session, self._projection_gesture = self._projection_gesture, None
        if (session is None or session is not self._projection_session or
                self._projection_text() != session.initial_text):
            return
        self._apply_projection_candidate(canvas, code, axes, point)

    def _projection_dimension_apply(self, canvas: SkeletonProjection, code: str, axes: object, point: object) -> None:
        self._apply_projection_candidate(canvas, code, axes, point)

    def _apply_projection_candidate(self, canvas: SkeletonProjection, code: str, axes: object, point: object) -> None:
        session = self._projection_session
        if self._projection_radius_pending:
            return
        if (session is None or not self._projection_current(canvas, code) or axes != canvas.axes or
                not isinstance(point, tuple) or len(point) != 3):
            self._close_projection_session()
            self._projection_note.setText('Данные изменились: изменение на проекции не принято.')
            return
        if self._projection_radius.text() != session.initial_text[-1]:
            canvas._show_dimension_error('Сначала примените или сбросьте изменённый радиус.')
            return
        bend = session.draft.front_bend if code == 'bend_front' else session.draft.rear_bend
        if (bend is None) != (session.new_vertex is not None):
            self._close_projection_session()
            return
        original = session.new_vertex if bend is None else bend.vertex_mm
        assert original is not None
        vertex = list(original)
        for axis in canvas.axes:
            vertex[axis] = point[axis]
        radius = bend.radius_mm if bend is not None else None
        if radius is None:
            text_before = self._projection_text()
            self._projection_radius_pending = True
            hidden = next(axis for axis in range(3) if axis not in canvas.axes)
            try:
                radius, accepted = QInputDialog.getDouble(
                    self, 'Радиус нового изгиба',
                    f'Радиус осевой линии, мм. Скрытая {"XYZ"[hidden]} = {original[hidden]!r} мм '
                    '(интерполяция по исходной прямой):', 0., 0., 1_000_000., 4)
            finally:
                self._projection_radius_pending = False
            if session is not self._projection_session:
                return
            if not self._projection_current(canvas, code):
                self._close_projection_session()
                self._projection_note.setText('Данные изменились во время ввода радиуса; изгиб не принят.')
                return
            if self._projection_text() != text_before:
                canvas._show_dimension_error('Размеры изменились во время ввода радиуса; повторите применение.')
                return
            if not accepted:
                canvas._show_dimension_error('Радиус не задан. Черновая вершина не применена.')
                return
        try:
            new_bend = FreeArmBend(tuple(vertex), radius)  # type: ignore[arg-type]
            candidate = (replace(session.draft, front_bend=new_bend) if code == 'bend_front'
                         else replace(session.draft, rear_bend=new_bend))
            self._paths(candidate, self.housing)
        except (FreeArmError, TypeError, ValueError) as error:
            canvas._show_dimension_error(f'Не принято: {error}. Прежняя форма сохранена.')
            return
        if not self._projection_current(canvas, code):
            self._close_projection_session()
            self._projection_note.setText('Данные изменились: изменение на проекции не принято.')
            return
        self._close_projection_session()
        if candidate != session.draft:
            self._set_fields(candidate)
            self._install(candidate, self.housing)
        self._projection_note.setText('Изменение применено; опоры и скрытая координата сохранены.')

    def _reset_projection_radius(self) -> None:
        session = self._projection_session
        if (session is not None and session.new_vertex is None and
                self._projection_current(session.canvas, session.code)):
            self._projection_radius.setText(session.initial_text[-1])
            session.canvas._dimension_error.hide()
            session.canvas._place_dimensions()

    def _apply_projection_radius(self) -> None:
        session = self._projection_session
        if session is None or session.new_vertex is not None or self._projection_radius_pending:
            return
        canvas, code = session.canvas, session.code
        if not self._projection_current(canvas, code):
            self._close_projection_session()
            self._projection_note.setText('Данные изменились: радиус не принят.')
            return
        if self._projection_gesture is not None or canvas._drag is not None:
            canvas._show_dimension_error('Сначала завершите или отмените перетаскивание.')
            return
        text = self._projection_text()
        if text is None or text[:-1] != session.initial_text[:-1]:
            canvas._show_dimension_error('Сначала примените или сбросьте изменённые смещения и расстояния.')
            return
        bend = session.draft.front_bend if code == 'bend_front' else session.draft.rear_bend
        if bend is None:
            self._close_projection_session()
            return
        try:
            radius = float(self._projection_radius.text().strip().replace(',', '.'))
        except (ValueError, OverflowError):
            canvas._show_dimension_error('Введите конечное число для радиуса, мм.')
            return
        try:
            new_bend = FreeArmBend(bend.vertex_mm, radius)
            candidate = (replace(session.draft, front_bend=new_bend) if code == 'bend_front'
                         else replace(session.draft, rear_bend=new_bend))
            self._paths(candidate, self.housing)
        except (FreeArmError, ValueError, OverflowError) as error:
            canvas._show_dimension_error(f'Радиус не принят: {error}. Прежняя форма сохранена.')
            return
        if (session is not self._projection_session or not self._projection_current(canvas, code) or
                self._projection_text() != text):
            return
        self._close_projection_session()
        if candidate != session.draft:
            self._set_fields(candidate)
            self._install(candidate, self.housing)
        self._projection_note.setText('Радиус применён; вершина и опоры сохранены.')

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (watched is self._projection_radius and isinstance(event, QKeyEvent) and
                event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self._apply_projection_radius()
            return True
        if (watched is self._cad._view and isinstance(event, QKeyEvent) and
                event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and
                self._cad_cut_pick is not None):
            self._cancel_cad_cut_pick()
            return True
        if (watched is self._cad._view and isinstance(event, QKeyEvent) and
                event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and
                self._inline_session is not None):
            self._close_inline_sketch()
            return True
        return super().eventFilter(watched, event)

    def _inline_text(self) -> tuple[str, ...] | None:
        if self._inline_session is None:
            return None
        return tuple(self._inline_sketch.fields[key].text() for key in ('X', 'Y', 'Z', 'R'))

    def _close_inline_sketch(self) -> None:
        self._inline_session = None
        self._inline_initial = None
        if hasattr(self, '_inline_sketch'):
            self._inline_sketch.hide()
            self._cad._view.set_sketch_overlay()
            self._cad._parts_tree.setEnabled(True)
            self._cad._parts_filter.setEnabled(True)
        if hasattr(self, '_save'):
            self._save.setEnabled(self._projection_session is None and self.draft is not None and
                                  self._accepted_form == self._form())
        self._update_trim_history_buttons()

    def _inline_current(self) -> bool:
        session = self._inline_session
        return bool(session is not None and self.draft is session[3] and self._form() == session[2] and
                    self._accepted_form == session[2] and self._cad.generation == session[1] and
                    self._cad._ready and self._cad._view.mesh is session[4] and
                    self._cad._document is not None and self._is_current(self._cad._document))

    def _cad_availability_changed(self, _available: bool) -> None:
        if self._cad_cut_pick is not None and not self._cad._ready:
            self._cancel_cad_cut_pick()
        if self._inline_session is not None and not self._inline_current():
            self._close_inline_sketch()
            self._status.setText('CAD изменился или отключён: незавершённый эскиз отменён.')

    def _retain_inline_selection(self) -> None:
        if self._inline_session is None:
            return
        mesh = self._cad._view.mesh
        root = self._cad._parts_tree.topLevelItem(0)
        identifier = 'tube_' + self._inline_session[0]
        if mesh is not None and root is not None and identifier in mesh.part_names:
            item = root.child(mesh.part_names.index(identifier))
            if item is not None:
                self._cad._parts_tree.setCurrentItem(item)
        self._inline_sketch.status.setText('Сначала примените или закройте текущий эскиз.')

    def _cad_part_picked(self, part: str) -> None:
        if self._inline_session is not None and part != 'tube_' + self._inline_session[0]:
            self._retain_inline_selection()
        elif self._cad_cut_pick is not None:
            self._cad_cutter_picked(part)

    def _cad_context_menu(self, part: str, position: QPoint) -> None:
        if self._inline_session is not None:
            self._retain_inline_selection()
            return
        document = self._cad._document
        tube = part in ('tube_front', 'tube_rear')
        inner = part in ('housing_front', 'housing_rear')
        mesh, item = self._cad._view.mesh, self._cad._parts_tree.currentItem()
        if (not (tube or inner or part == 'ball_housing') or self.draft is None or
                (part == 'ball_housing' and self.housing is None) or (inner and self.inner_housings is None) or
                self._cad._closed or not self._cad._ready or mesh is None or part not in mesh.part_names or
                item is None or item.data(0, Qt.ItemDataRole.UserRole) != mesh.part_names.index(part) or
                document is None or not self._is_current(document)):
            return
        self._cancel_cad_cut_pick()
        state, generation, draft = self._form(), self._cad.generation, self.draft
        housing, inner_housings = self.housing, self.inner_housings
        menu = QMenu(self)
        action = menu.addAction('Редактировать эскиз на модели' if tube else
                                'Параметры центрального корпуса' if part == 'ball_housing' else
                                'Параметры выбранного внутреннего корпуса')
        length_action = projection_action = notch_action = miter_action = tube_joint_action = cut_action = None
        other_projection_actions: dict[object, int] = {}
        if tube:
            cut_action = menu.addAction('Обрезать по выбранному элементу…' if housing is None or inner_housings is not None else
                                        'Выбор реза недоступен: задан только центральный корпус')
            cut_action.setEnabled(housing is None or inner_housings is not None)
            projection_action = menu.addAction('Форма и изгиб на проекции XY…')
            projection_menu = menu.addMenu('Другие проекции…')
            other_projection_actions = {projection_menu.addAction(f'Форма и изгиб на проекции {name}…'): index
                                        for index, name in ((1, 'XZ'), (2, 'YZ'))}
            miter_action = menu.addAction('Стык на ус недоступен с центральным корпусом' if housing is not None else
                                          'Стык на ус недоступен: выбран рез трубы' if self.tube_joint is not None else
                                          'Общий стык труб на ус…')
            miter_action.setEnabled(housing is None and self.tube_joint is None)
            tube_joint_action = menu.addAction('Подрезка по трубе недоступна с центральным корпусом'
                                               if housing is not None else
                                               'Подрезка недоступна: выбран стык на ус' if self.miter else
                                               'Подрезка по другой трубе…')
            tube_joint_action.setEnabled(housing is None and not self.miter)
            length_action = menu.addAction('Длина осевой линии до подрезок…' if housing is None else
                                           'Длина осевой линии недоступна с центральным корпусом')
            length_action.setEnabled(housing is None)
            notch_action = menu.addAction('Подрезка по своему внутреннему корпусу…' if inner_housings is not None else
                                          'Подрезка недоступна: внутренние корпуса не заданы')
            notch_action.setEnabled(inner_housings is not None)
        chosen = menu.exec(position)
        if isValid(menu):
            menu.deleteLater()
        if not isValid(self):
            return
        if (self._cad._closed or self._form() != state or self._cad.generation != generation or self.draft is not draft or
                self.housing is not housing or self.inner_housings is not inner_housings or
                self._cad._view.mesh is not mesh or self._cad._parts_tree.currentItem() is not item or
                not self._cad._ready or
                self._cad._document is None or not self._is_current(self._cad._document)):
            return
        if chosen == action:
            if tube:
                self._open_inline_sketch(part.removeprefix('tube_'))
            else:
                key = 'housing_outer' if part == 'ball_housing' else f'{part.removeprefix("housing_")}_inner_outer'
                self._focus_parameter(self._fields[key])
        elif cut_action is not None and chosen == cut_action and cut_action.isEnabled():
            self._cad_cut_pick = _CutPick(part, generation, state, draft, housing, inner_housings,
                                          self.miter, self.tube_joint, mesh)
            self._cad_pick_status.setText(
                'Выберите свой внутренний корпус для подрезки. Рез между трубами недоступен с центральным корпусом. Esc — отмена.'
                if housing is not None else
                'Выберите вторую трубу для стыка на ус. Внутренние корпуса не заданы. Esc — отмена.'
                if inner_housings is None else
                'Выберите вторую трубу для стыка на ус или свой внутренний корпус для подрезки. Esc — отмена.')
            self._cad_pick_controls.show()
            self._update_trim_history_buttons()
            self._cad._view.setFocus()
        elif length_action is not None and chosen == length_action:
            self._edit_tube_length(part.removeprefix('tube_'))
        elif projection_action is not None and chosen == projection_action:
            self._open_projection_from_cad(part.removeprefix('tube_'))
        elif chosen in other_projection_actions:
            self._open_projection_from_cad(part.removeprefix('tube_'), other_projection_actions[chosen])
        elif miter_action is not None and chosen == miter_action and miter_action.isEnabled():
            self._focus_parameter(self._miter_check)
        elif tube_joint_action is not None and chosen == tube_joint_action and tube_joint_action.isEnabled():
            self._focus_parameter(self._tube_joint_choice)
        elif notch_action is not None and chosen == notch_action and notch_action.isEnabled():
            leg = part.removeprefix('tube_')
            target = self._fields[f'{leg}_inner_clearance'] if self._inner_notch[leg].isChecked() else self._inner_notch[leg]
            self._focus_parameter(target)

    def _cancel_cad_cut_pick(self) -> None:
        self._cad_cut_pick = None
        if hasattr(self, '_cad_pick_controls'):
            self._cad_pick_controls.hide()
        if hasattr(self, '_cad'):
            self._update_trim_history_buttons()

    def _cancel_cut_on_tab_change(self, _index: int) -> None:
        if self._cad_cut_pick is not None and self._tabs.currentWidget() is not self._cad:
            self._cancel_cad_cut_pick()

    def _cad_cut_pick_current(self, pick: _CutPick) -> bool:
        return bool(isValid(self) and self._cad_cut_pick is pick and not self._cad._closed and
                    self._tabs.currentWidget() is self._cad and self._inline_session is None and
                    self._projection_session is None and self._cad.generation == pick.generation and
                    self._cad._ready and self._cad._view.mesh is pick.mesh and self.draft is pick.draft and
                    self.housing is pick.housing and self.inner_housings is pick.inner and self.miter == pick.miter and
                    self.tube_joint == pick.joint and self._form() == pick.form and
                    self._cad._document is not None and self._is_current(self._cad._document))

    def _cad_cutter_picked(self, part: str) -> None:
        pick = self._cad_cut_pick
        if pick is None or self._cad_cut_prompting:
            return
        if not self._cad_cut_pick_current(pick):
            self._cancel_cad_cut_pick()
            return
        item = self._cad._parts_tree.currentItem()
        if (part not in pick.mesh.part_names or item is None or
                item.data(0, Qt.ItemDataRole.UserRole) != pick.mesh.part_names.index(part)):
            return
        leg = pick.part.removeprefix('tube_')
        other = 'rear' if leg == 'front' else 'front'

        def still_current() -> bool:
            return (self._cad_cut_pick_current(pick) and isValid(item) and
                    self._cad._parts_tree.currentItem() is item)

        if part == f'tube_{other}' and pick.housing is None:
            replacement = ('Текущая подрезка по другой трубе будет заменена.\n' if pick.joint is not None else '')
            self._cad_cut_prompting = True
            try:
                answer = QMessageBox.question(self, 'Общий стык на ус', replacement +
                    'Подрезать обе трубы общей плоскостью без зазора?\n'
                    'Конечные прямые участки временно продолжаются.\n'
                    'Это не проверка монтажа, сварки или прочности.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            finally:
                self._cad_cut_prompting = False
            if not isValid(self):
                return
            if not still_current():
                self._cancel_cad_cut_pick()
                return
            if answer != QMessageBox.StandardButton.Yes:
                return
            if pick.miter:
                self._cancel_cad_cut_pick()
                return
            self._cancel_cad_cut_pick()
            self._loading = True
            try:
                self._miter_check.setChecked(True)
                self._tube_joint_choice.setCurrentIndex(0)
            finally:
                self._loading = False
            self.miter, self.tube_joint = True, None
            self._install(pick.draft, pick.housing)
        elif part == f'housing_{leg}' and pick.inner is not None:
            old = getattr(pick.inner, f'{leg}_clearance_mm')
            self._cad_cut_prompting = True
            try:
                clearance, ok = QInputDialog.getDouble(self, 'Подрезка по корпусу',
                    'Радиальный зазор до наружного цилиндра\nсвоего корпуса, мм (0–100):',
                    old if old is not None else 0., 0., 100., 2)
            finally:
                self._cad_cut_prompting = False
            if not isValid(self):
                return
            if not still_current():
                self._cancel_cad_cut_pick()
                return
            if not ok:
                return
            try:
                inner = (replace(pick.inner, front_clearance_mm=clearance) if leg == 'front' else
                         replace(pick.inner, rear_clearance_mm=clearance))
            except (HousingError, ValueError, TypeError):
                self._cad_pick_status.setText('Недопустимый зазор. Выберите корпус и укажите 0–100 мм.')
                return
            if inner == pick.inner:
                self._cancel_cad_cut_pick()
                return
            self._cancel_cad_cut_pick()
            self._loading = True
            try:
                self._inner_notch[leg].setChecked(True)
                self._fields[f'{leg}_inner_clearance'].setText(repr(clearance))
            finally:
                self._loading = False
            self.inner_housings = inner
            self._install(pick.draft, pick.housing)
        else:
            self._cad_pick_status.setText('Выберите другую трубу для стыка на ус без центрального корпуса '
                                          'или собственный внутренний корпус. Другие резы не поддерживаются.')

    def _focus_parameter(self, widget: QWidget) -> None:
        self._settings_toggle.setChecked(True)
        self._parameters_scroll.ensureWidgetVisible(widget)
        widget.setFocus(Qt.FocusReason.MouseFocusReason)
        if isinstance(widget, QLineEdit):
            widget.selectAll()

    def _open_projection_from_cad(self, leg: str, projection: int = 0) -> None:
        if (leg not in ('front', 'rear') or projection not in (0, 1, 2) or self.draft is None or
                self._inline_session is not None or self._projection_session is not None):
            return
        canvas = self._projections[projection]
        self._tabs.setCurrentWidget(canvas)
        bend = self.draft.front_bend if leg == 'front' else self.draft.rear_bend
        if bend is not None:
            if len(canvas._point_hits(canvas._screen_point(bend.vertex_mm))) != 1:
                self._projection_ambiguous()
                return
            self._projection_point(canvas, f'bend_{leg}')
        elif canvas.preview is not None:
            path = canvas.preview.centerlines[0 if leg == 'front' else 1]
            first, last = canvas._screen_point(path[0]), canvas._screen_point(path[-1])
            midpoint = ((path[0][0] + path[-1][0]) / 2, (path[0][1] + path[-1][1]) / 2,
                        (path[0][2] + path[-1][2]) / 2)
            if (dist((first.x(), first.y()), (last.x(), last.y())) < 24 or
                    canvas._point_hits(canvas._screen_point(midpoint))):
                self._projection_ambiguous()
                return
            self._projection_segment(canvas, leg, midpoint)


    def _edit_tube_length(self, leg: str) -> None:
        draft, mesh = self.draft, self._cad._view.mesh
        if (leg not in ('front', 'rear') or draft is None or self.housing is not None or
                self._inline_session is not None or self._projection_session is not None or
                self._tabs.currentWidget() is not self._cad or self._cad._closed or
                not self._cad._ready or mesh is None or self._cad._document is None or
                not self._is_current(self._cad._document)):
            return
        bend = draft.front_bend if leg == 'front' else draft.rear_bend
        if bend is None:
            QMessageBox.information(self, 'Длина осевой линии',
                                    'Сначала создайте изгиб и задайте радиус: у прямой трубы '
                                    'направление изменения неоднозначно.')
            return
        state, generation = self._form(), self._cad.generation
        start = draft.front_mm if leg == 'front' else draft.rear_mm
        end = draft.outer_mm
        current = make_bend_path(start, bend.vertex_mm, end, bend.radius_mm, draft.radius_mm).length

        def still_current() -> bool:
            # A modal input can outlive window shutdown and deferred deletion.
            return (not self._cad._closed and self.draft is draft and self.housing is None and self._form() == state and
                    self._inline_session is None and self._projection_session is None and
                    self._tabs.currentWidget() is self._cad and self._cad.generation == generation and self._cad._view.mesh is mesh and
                    self._cad._ready and self._cad._document is not None and self._is_current(self._cad._document))

        length, ok = QInputDialog.getDouble(
            self, 'Длина осевой линии',
            'Длина оси до CAD-подрезок, мм;\nне длина готовой детали.\n'
            'Опоры и радиус закреплены. Вершина движется\n'
            'поперёк линии опор по текущему направлению.\n'
            'Проверяется конечная форма; другие решения возможны.\n'
            'Промежуточные формы не проверяются.', current, 0., 1000000., 4)
        if not ok or not still_current() or abs(length - current) <= 0.000050000001:
            return
        try:
            vertex = vertex_for_length(start, end, bend.vertex_mm, bend.radius_mm, draft.radius_mm, length)
            changed = FreeArmBend(vertex, bend.radius_mm)
            candidate = (replace(draft, front_bend=changed) if leg == 'front' else replace(draft, rear_bend=changed))
        except (FreeArmError, ValueError) as error:
            if still_current():
                QMessageBox.warning(self, 'Длина не изменена', f'{error}. Прежняя геометрия сохранена.')
            return
        if not still_current():
            return
        self._set_fields(candidate)
        self._install(candidate, None)

    def _focus_inline_dimension(self, key: str) -> None:
        if not self._inline_current():
            self._close_inline_sketch()
            return
        self._inline_sketch.focus_dimension(key)

    def _open_inline_sketch(self, leg: str) -> None:
        document, draft, mesh = self._cad._document, self.draft, self._cad._view.mesh
        if (self._projection_session is not None or leg not in ('front', 'rear') or draft is None or
                document is None or not self._cad._ready or mesh is None or not self._is_current(document)):
            return
        if self._inline_session is not None:
            self._retain_inline_selection()
            return
        bend = draft.front_bend if leg == 'front' else draft.rear_bend
        path = self._paths(draft, self.housing)[0 if leg == 'front' else 1]
        vertex = bend.vertex_mm if bend else ((path[0][0] + path[-1][0]) / 2,
                                               (path[0][1] + path[-1][1]) / 2,
                                               (path[0][2] + path[-1][2]) / 2)
        self._inline_session = (leg, self._cad.generation, self._form(), draft, mesh)
        dimensions = (*vertex, bend.radius_mm) if bend else None
        self._cad._view.set_sketch_overlay(path, vertex if bend else None, dimensions=dimensions)
        self._inline_sketch.begin(leg, vertex, bend.radius_mm if bend else None)
        self._inline_initial = self._inline_text()
        self._cad._parts_tree.setEnabled(False)
        self._cad._parts_filter.setEnabled(False)
        self._save.setEnabled(False)
        self._update_trim_history_buttons()

    def _draft_with_inline_bend(self, values: object) -> FreeArmDraft:
        if self._inline_session is None or not isinstance(values, tuple) or len(values) != 4:
            raise FreeArmError('Введите координаты XYZ и радиус')
        bend = FreeArmBend(values[:3], values[3])  # type: ignore[arg-type]
        draft = self._inline_session[3]
        candidate = (replace(draft, front_bend=bend) if self._inline_session[0] == 'front'
                     else replace(draft, rear_bend=bend))
        self._paths(candidate, self.housing)
        return candidate

    def _preview_inline_sketch(self, values: object) -> None:
        if not self._inline_current() or self._inline_session is None:
            self._close_inline_sketch()
            return
        try:
            candidate = self._draft_with_inline_bend(values)
            path = self._paths(candidate, self.housing)[0 if self._inline_session[0] == 'front' else 1]
        except (FreeArmError, ValueError) as error:
            self._cad._view.set_sketch_overlay()
            self._inline_sketch.status.setText(f'Черновик не построен: {error}')
            return
        bend = candidate.front_bend if self._inline_session[0] == 'front' else candidate.rear_bend
        assert bend is not None
        self._cad._view.set_sketch_overlay(path, bend.vertex_mm, dimensions=(*bend.vertex_mm, bend.radius_mm))
        self._inline_sketch.status.setText('Жёлтая линия — черновик; объём перестроится после применения.')

    def _apply_inline_sketch(self, values: object) -> None:
        if not self._inline_current():
            self._close_inline_sketch()
            return
        try:
            candidate = self._draft_with_inline_bend(values)
        except (FreeArmError, ValueError) as error:
            self._inline_sketch.status.setText(f'Не применено: {error}')
            return
        if not self._inline_current():
            self._close_inline_sketch()
            return
        self._close_inline_sketch()
        self._set_fields(candidate)
        self._install(candidate, self.housing)

    def _read_number(self, key: str) -> float:
        text = self._fields[key].text().strip().replace(',', '.')
        try:
            return float(text)
        except ValueError as error:
            raise FreeArmError(f'Введите число: {self._fields[key].accessibleName()}') from error

    def _read_point(self, prefix: str) -> tuple[float, float, float]:
        return tuple(self._read_number(f'{prefix}_{axis}') for axis in 'XYZ')  # type: ignore[return-value]

    def _candidate(self) -> FreeArmDraft:
        def bend(leg: str) -> FreeArmBend | None:
            return (FreeArmBend(self._read_point(f'{leg}_bend'), self._read_number(f'{leg}_bend_radius'))
                    if self._bend_checks[leg].isChecked() else None)
        return FreeArmDraft(self._read_point('front'), self._read_point('rear'), self._read_point('outer'),
                            self._read_number('radius'), self._read_number('wall'), bend('front'), bend('rear'))

    def _candidate_housing(self) -> FreeArmBallHousing | None:
        if not self._housing_check.isChecked():
            return None
        return FreeArmBallHousing(self._read_number('housing_outer'), self._read_number('housing_bore'),
                                  self._read_number('housing_length'), self._read_point('housing_axis'),
                                  self._read_point('housing_offset'))

    def _update_inner_controls(self, *_args: object) -> None:
        for leg, check in self._inner_notch.items():
            self._fields[f'{leg}_inner_clearance'].setEnabled(self._inner_check.isChecked() and check.isChecked())

    def _update_tube_joint_controls(self, *_args: object) -> None:
        self._fields['tube_joint_clearance'].setEnabled(self._tube_joint_choice.currentData() is not None)

    def _set_tube_joint_fields(self, joint: FreeArmTubeJoint | None) -> None:
        self._loading = True
        try:
            self._tube_joint_choice.setCurrentIndex(self._tube_joint_choice.findData(joint.target if joint else None))
            self._fields['tube_joint_clearance'].setText(repr(joint.radial_clearance_mm) if joint else '')
        finally:
            self._loading = False

    def _candidate_inner(self) -> FreeArmInnerHousings | None:
        if not self._inner_check.isChecked():
            return None
        def housing(leg: str) -> FreeArmInnerHousing:
            return FreeArmInnerHousing(self._read_number(f'{leg}_inner_outer'),
                                       self._read_number(f'{leg}_inner_bore'),
                                       self._read_number(f'{leg}_inner_length'),
                                       self._read_point(f'{leg}_inner_axis'), self._inner_confirm[leg].isChecked())
        return FreeArmInnerHousings(housing('front'), housing('rear'),
                                    *(self._read_number(f'{leg}_inner_clearance')
                                      if self._inner_notch[leg].isChecked() else None for leg in ('front', 'rear')))

    def _set_inner_fields(self, inner: FreeArmInnerHousings | None) -> None:
        self._loading = True
        try:
            self._inner_check.setChecked(inner is not None)
            for leg in ('front', 'rear'):
                item = getattr(inner, leg) if inner is not None else None
                self._inner_confirm[leg].setChecked(item is not None and item.center_on_pivot)
                clearance = getattr(inner, f'{leg}_clearance_mm') if inner is not None else None
                self._inner_notch[leg].setChecked(clearance is not None)
                if item is not None:
                    for field, value in (('outer', item.outer_diameter_mm), ('bore', item.bore_diameter_mm),
                                         ('length', item.length_mm)):
                        self._fields[f'{leg}_inner_{field}'].setText(repr(value))
                    for axis, value in zip('XYZ', item.axis, strict=True):
                        self._fields[f'{leg}_inner_axis_{axis}'].setText(repr(value))
                    self._fields[f'{leg}_inner_clearance'].setText(repr(clearance) if clearance is not None else '0')
        finally:
            self._loading = False

    def apply_fields(self) -> None:
        try:
            candidate = self._candidate()
            housing = self._candidate_housing()
            inner = self._candidate_inner()
            miter = self._miter_check.isChecked()
            joint_target = self._tube_joint_choice.currentData()
            if joint_target is not None and (miter or housing is not None):
                raise HousingError('Подрезка по трубе несовместима со стыком на ус или центральным корпусом')
            joint = FreeArmTubeJoint(joint_target, self._read_number('tube_joint_clearance')) if joint_target is not None else None
            if miter and housing is not None:
                raise FreeArmMiterError('Общий стык на ус несовместим с центральным корпусом')
            self._paths(candidate, housing)
            if inner is not None:
                FreeArmInnerHousingDraft(candidate, inner, housing)
        except (FreeArmError, FreeArmHousingError, HousingError, FreeArmMiterError) as error:
            self._status.setText(f'Данные не применены: {error}')
            return
        self.inner_housings = inner
        self.miter = miter
        self.tube_joint = joint
        self._install(candidate, housing)

    def _install(self, candidate: FreeArmDraft, housing: FreeArmBallHousing | None = None) -> None:
        # Validate the combined geometry before replacing any accepted state.
        paths = self._paths(candidate, housing)
        document = self._document_for(candidate, housing)
        self._cancel_cad_cut_pick()
        self._close_projection_session()
        self.draft, self.housing = candidate, housing
        self._accepted_form = self._form()
        preview = SkeletonPreview(paths, candidate.anchors)
        # The outer anchor and shifted housing center remain distinct markers.
        scene = skeleton_scene(preview, {}, show_ball_housing=housing is not None)
        self._scene.set_scene(scene, preview.centerlines)
        points = (tuple(zip(('lca_f_in', 'lca_r_in', 'lbj'), candidate.anchors, strict=True)) +
                  tuple((f'bend_{leg}', bend.vertex_mm) for leg, bend in
                        (('front', candidate.front_bend), ('rear', candidate.rear_bend)) if bend is not None))
        if housing is not None and paths[0][-1] != candidate.outer_mm:
            points += (('ball_housing_center', paths[0][-1]),)
        for projection in self._projections:
            projection.set_preview(preview, points)
        self._cad.set_document(document)
        self._save.setEnabled(True)
        self._record_trim_history(candidate, housing)
        self._status.setText('Черновик применён. Выбранные подрезки проверяются при построении CAD.'
                             if housing is not None or self.inner_housings is not None or self.miter or self.tube_joint is not None else
                             'Независимый черновик применён. CAD — только предварительные неподрезанные трубы.')

    def _set_fields(self, draft: FreeArmDraft) -> None:
        self._loading = True
        try:
            for name, point in (('front', draft.front_mm), ('rear', draft.rear_mm), ('outer', draft.outer_mm)):
                for axis, number in zip('XYZ', point, strict=True):
                    self._fields[f'{name}_{axis}'].setText(repr(number))
            self._fields['radius'].setText(repr(draft.radius_mm))
            self._fields['wall'].setText(repr(draft.wall_mm))
            for leg, bend in (('front', draft.front_bend), ('rear', draft.rear_bend)):
                self._bend_checks[leg].setChecked(bend is not None)
                for index, axis in enumerate('XYZ'):
                    self._fields[f'{leg}_bend_{axis}'].setText(repr(bend.vertex_mm[index]) if bend is not None else '')
                self._fields[f'{leg}_bend_radius'].setText(repr(bend.radius_mm) if bend is not None else '')
        finally:
            self._loading = False

    def _set_housing_fields(self, housing: FreeArmBallHousing | None) -> None:
        self._loading = True
        try:
            self._housing_check.setChecked(housing is not None)
            if housing is not None:
                self._fields['housing_outer'].setText(repr(housing.outer_diameter_mm))
                self._fields['housing_bore'].setText(repr(housing.bore_diameter_mm))
                self._fields['housing_length'].setText(repr(housing.length_mm))
                for prefix, point in (('housing_axis', housing.axis), ('housing_offset', housing.offset_mm)):
                    for axis, number in zip('XYZ', point, strict=True):
                        self._fields[f'{prefix}_{axis}'].setText(repr(number))
        finally:
            self._loading = False

    def _set_miter_field(self, enabled: bool) -> None:
        self._loading = True
        try:
            self._miter_check.setChecked(enabled)
        finally:
            self._loading = False

    def _restore_draft(self) -> None:
        if self.draft is not None:
            self._set_fields(self.draft)
            self._set_housing_fields(self.housing)
            self._set_inner_fields(self.inner_housings)
            self._set_miter_field(self.miter)
            self._set_tube_joint_fields(self.tube_joint)
            if self._trim_history and self._trim_context(self.draft, self.housing) == self._trim_history_context:
                self._set_trim_fields(self._trim_history[self._trim_history_index])
            self._install(self.draft, self.housing)

    def confirm_close(self) -> bool:
        inline, projection = self._inline_text(), self._projection_text()
        session = self._projection_session
        if self._closing_confirmed or (self._form() == self._saved_form and
                                       (inline is None or inline == self._inline_initial) and
                                       (projection is None or (session is not None and session.new_vertex is None and
                                                               projection == session.initial_text))):
            return True
        state = (self._form(), inline, projection, session, self.draft, self.housing, self._cad.generation)
        answer = QMessageBox.question(self, 'Несохранённый черновик', 'Несохранённый ввод будет потерян. Продолжить?',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return (answer == QMessageBox.StandardButton.Yes and
                (self._form(), self._inline_text(), self._projection_text(), self._projection_session,
                 self.draft, self.housing, self._cad.generation) == state)

    def _open_file(self) -> None:
        if self._projection_session is not None or not self.confirm_close():
            return
        previous = (self._form(), self._inline_text(), self._projection_session, self.draft, self.housing,
                    self._cad.generation)
        selected, _ = QFileDialog.getOpenFileName(self, 'Открыть независимый рычаг', '', 'Рычаг (*.slarm)')
        if not selected or (self._form(), self._inline_text(), self._projection_session, self.draft, self.housing,
                            self._cad.generation) != previous:
            return
        try:
            loaded = read_independent_arm(selected)
        except FreeArmFileError as error:
            QMessageBox.warning(self, 'Не удалось открыть', str(error))
            return
        if (self._form(), self._inline_text(), self._projection_session, self.draft, self.housing,
                self._cad.generation) != previous:
            return
        draft = loaded.arm if isinstance(loaded, (FreeArmHousingDraft, FreeArmInnerHousingDraft, FreeArmMiterDraft, FreeArmTubeJointDraft)) else loaded
        housing = (loaded.housing if isinstance(loaded, FreeArmHousingDraft) else
                   loaded.ball_housing if isinstance(loaded, FreeArmInnerHousingDraft) else None)
        self.inner_housings = loaded.housings if isinstance(loaded, (FreeArmInnerHousingDraft, FreeArmMiterDraft, FreeArmTubeJointDraft)) else None
        self.miter = isinstance(loaded, FreeArmMiterDraft)
        self.tube_joint = loaded.joint if isinstance(loaded, FreeArmTubeJointDraft) else None
        self._close_inline_sketch()
        self._set_fields(draft)
        self._set_housing_fields(housing)
        self._set_inner_fields(self.inner_housings)
        self._set_miter_field(self.miter)
        self._set_tube_joint_fields(self.tube_joint)
        self._install(draft, housing)
        self._reset_trim_history()
        self._saved_form = self._form()

    def _save_file(self) -> None:
        if (self._inline_session is not None or self._projection_session is not None or
                self.draft is None or self._accepted_form != self._form()):
            return
        previous, draft, housing, generation = self._form(), self.draft, self.housing, self._cad.generation
        selected, _ = QFileDialog.getSaveFileName(self, 'Сохранить новый независимый рычаг', '', 'Рычаг (*.slarm)')
        if (not selected or previous != self._form() or self.draft is not draft or self.housing is not housing or
                self._inline_session is not None or self._projection_session is not None or
                self._cad.generation != generation):
            return
        path = Path(selected)
        if not path.suffix:
            path = path.with_suffix('.slarm')
        try:
            if self.tube_joint is not None:
                write_free_arm_tube_joint(path, FreeArmTubeJointDraft(draft, self.tube_joint, self.inner_housings))
            elif self.miter:
                write_free_arm_miter(path, FreeArmMiterDraft(draft, self.inner_housings))
            elif self.inner_housings is not None:
                write_free_arm_inner_housings(path, FreeArmInnerHousingDraft(draft, self.inner_housings, housing))
            elif housing is None:
                write_free_arm(path, draft)
            else:
                write_free_arm_housing(path, FreeArmHousingDraft(draft, housing))
        except (FreeArmFileError, FreeArmHousingError) as error:
            QMessageBox.warning(self, 'Не удалось сохранить', str(error))
            return
        if previous == self._form() and self.draft is draft and self.housing is housing:
            self._saved_form = previous
            self._status.setText('Независимый черновик сохранён как новый файл. Это не расчёт подвески.')

    def shutdown(self) -> bool:
        self._cancel_cad_cut_pick()
        self._close_projection_session()
        self._close_inline_sketch()
        stopped = self._cad.shutdown()
        self._update_trim_history_buttons()
        return stopped

    def reject(self) -> None:
        if self.confirm_close() and self.shutdown():
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.confirm_close() or not self.shutdown():
            event.ignore()
            return
        self._closing_confirmed = True
        try:
            super().closeEvent(event)
        finally:
            self._closing_confirmed = False

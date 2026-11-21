"""Редактирование точек и экспериментальный дискретный расчёт в одной области."""
from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.kinematics_workspace import (
    ElementMeasurement,
    WorkspaceResult,
    calculate,
    moved_link_end,
    static_scene,
    supported,
)
from ..core.scene3d import Segment3D
from ..core.sweep_plot import PlotPoint
from ..core.vehicle_schematic_scene import SelectableLink
from ..i18n import tr
from ..model.cad_handoff import CadHandoff, ClearanceSettings, HandoffError, prepare_cad_handoff
from ..model.kinematic_elements import ElementSetup, KinematicElements
from ..model.param_specs import point_specs
from ..model.suspension_types import types_for_role
from .cad_handoff_dialog import CadHandoffDialog
from .canvas.scene3d_preview import Scene3DPreview
from .canvas.sweep_plot import SweepPlot
from .clearance_dialog import ClearanceDialog, _label
from .controller import AppController, Selection
from .rocker_setup_dialog import RockerSetupDialog
from .widgets.camera_views import CameraViews
from .widgets.slider_field import SliderField

LOG = logging.getLogger(__name__)


def _cad_handoff_text(handoff: CadHandoff) -> str:
    axle = handoff.snapshot.project_copy().front
    samples = handoff.sweep.samples
    pairs = [pair for sample in samples for pair in sample.pairs]
    measured = [pair for pair in pairs if pair.measurement is not None]
    conflict = sum(pair.status in ('overlap', 'touch', 'low_clearance', 'limit') for pair in pairs)
    unknown = sum(pair.status in ('unknown_no_pose', 'unknown_geometry') for pair in pairs)
    excluded = sum(pair.status == 'excluded_shared_point' for pair in pairs)
    omitted = ', '.join(_label(axle, code) for code in handoff.sweep.omitted) or 'нет'
    selected = ', '.join(f'{_label(axle, code)}: {radius:g} мм' for code, radius in handoff.settings.radii)
    wheel = (f'; ширина цилиндра {handoff.settings.wheel_width_mm:g} мм'
             if handoff.settings.wheel_width_mm is not None else '')
    minimum = min(pair.measurement.clearance_mm for pair in measured if pair.measurement is not None)
    names = {'overlap': 'наложение', 'touch': 'касание', 'low_clearance': 'меньше запаса',
             'limit': 'у границы', 'unknown_no_pose': 'нет решения', 'unknown_geometry': 'нет геометрии'}
    examples_text = ''
    for heading, statuses in (('Требуют внимания', {'overlap', 'touch', 'low_clearance', 'limit'}),
                              ('Не проверено', {'unknown_no_pose', 'unknown_geometry'})):
        examples = [(sample.travel_mm, pair) for sample in samples for pair in sample.pairs if pair.status in statuses]
        if examples:
            examples_text += f'{heading} (первые до трёх):\n'
            examples_text += ''.join(f'  {travel:+.3f} мм: {_label(axle, pair.first)} / {_label(axle, pair.second)} — '
                                     f'{names[pair.status]}\n' for travel, pair in examples[:3])
            if len(examples) > 3:
                examples_text += f'  И ещё {len(examples) - 3} событий.\n'
    extra = (f'Уточнение: дополнительных поз {handoff.refinement.added}, подозрительных интервалов '
             f'{len(handoff.refinement.unresolved)}, исходных интервалов без средней точки '
             f'{len(handoff.refinement.unprobed_initial)}; непрерывное движение не проверено.\n'
             if handoff.refinement is not None else 'Уточнение выключено; промежутки не проверены.\n')
    return (f'Передний нижний левый рычаг: две прямые трубы, радиус {handoff.radius_mm:g} мм, '
            f'стенка {handoff.wall_mm:g} мм.\n'
            f'Выбранные радиусы: {selected}{wheel}; запас {handoff.settings.margin_mm:g} мм.\n'
            f'Расчёт повторён на снимке проекта с округлением координат до 0,0001 мм. '
            f'Поз {len(samples)}, без решения {sum(not sample.pose_available for sample in samples)}, '
            f'измерений пар {len(measured)}, требующих внимания {conflict}, '
            f'неизвестных {unknown}, исключённых {excluded}. Минимальный условный зазор {minimum:.3f} мм.\n'
            f'Невыбранные формы не проверены: {omitted}. Кулак, кузов, привод и реальные детали не проверены.\n'
            f'{examples_text}{extra}'
            'Даже при выявленных проблемах можно открыть черновик для изучения; это не подтверждение безопасности. '
            'Сгибы, корпуса и реальные CAD-детали в этой проверке не участвовали. '
            'Результат проверки в файл скелета не переносится; после изменения формы необходима новая проверка.\n\n'
            'Открыть предварительную заготовку?')


def _element_text(measurement: ElementMeasurement | None) -> str:
    if measurement is None:
        return 'не рассчитано'
    if measurement.length_mm is None:
        return f'не проверено: {measurement.detail}'
    incomplete = '; полностью не проверено: пределы заданы не полностью' if not measurement.limits_complete and measurement.status in ('below', 'above', 'limit') else ''
    return f'{measurement.length_mm:.2f} мм — {measurement.detail}{incomplete}'


def _summary_text(result: WorkspaceResult) -> str:
    total = len(result.samples)
    solved = [sample for sample in result.samples if sample.scene is not None]
    sections = [f'положения {len(solved)}/{total}, отказов {total - len(solved)}']
    first_failure = next((sample.error for sample in result.samples if sample.error), None)
    if first_failure:
        sections.append(f'пример отказа: {first_failure}')
    for name, label in (('spring', 'пружина'), ('damper', 'амортизатор')):
        measurements = [getattr(sample, name) for sample in solved]
        complete = sum(m is not None and m.limits_complete for m in measurements)
        conflicts = sum(m is not None and m.status in ('below', 'above') for m in measurements)
        boundary = sum(m is not None and m.status == 'limit' for m in measurements)
        invalid = sum(m is not None and m.status in ('invalid', 'error') for m in measurements)
        text = f'{label}: полные пределы {complete}/{total}, выходы {conflicts}, у границы {boundary}'
        if invalid:
            text += f', ошибок {invalid}'
        missing_mounts = sum(m is not None and m.status == 'unknown' for m in measurements)
        partial_limits = sum(m is not None and m.length_mm is not None and not m.limits_complete and
                             m.status != 'invalid' for m in measurements)
        if missing_mounts:
            text += f', крепления не заданы/не применимы: {missing_mounts}'
        if partial_limits:
            text += f', неполные пределы: {partial_limits}'
        if complete < total:
            text += ' (не полностью проверено)'
        sections.append(text)
    return '; '.join(sections)


class KinematicsWorkspace(QWidget):
    """Редактируется статическая схема; расчёт не меняет проект."""

    cadHandoffRequested = Signal(object)

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.result: WorkspaceResult | None = None
        self._rows: dict[tuple[str, str], SliderField] = {}
        self._menu: QMenu | None = None
        self._revision = 0
        self._clearance_dialog: ClearanceDialog | None = None
        self._clearance_settings: ClearanceSettings | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._calculate)
        self._sidebar_width_timer = QTimer(self)
        self._sidebar_width_timer.setSingleShot(True)
        self._sidebar_width_timer.timeout.connect(self._update_sidebar_minimum_width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        title_row = QHBoxLayout()
        title = QLabel(tr('workspace_flow.title'), self)
        title.setObjectName('WorkspaceTitle')
        title_row.addWidget(title)
        subtitle = QLabel(tr('workspace_flow.subtitle'), self)
        subtitle.setObjectName('WorkspaceSubtitle')
        title_row.addWidget(subtitle)
        title_row.addStretch(1)
        outer.addLayout(title_row)

        splitter = QSplitter(self)
        splitter.setChildrenCollapsible(False)
        self.editor_scroll = QScrollArea(splitter)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setMinimumWidth(380)
        sidebar = QWidget(self.editor_scroll)
        self._sidebar = sidebar
        sidebar.installEventFilter(self)
        sidebar.setObjectName('WorkspaceSidebar')
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_heading = QLabel(tr('workspace_flow.sidebar'), sidebar)
        sidebar_heading.setObjectName('WorkspaceSectionTitle')
        sidebar_layout.addWidget(sidebar_heading)
        sidebar_hint = QLabel(tr('workspace_flow.intro'), sidebar)
        sidebar_hint.setObjectName('WorkspaceSubtitle')
        sidebar_hint.setWordWrap(True)
        sidebar_layout.addWidget(sidebar_hint)

        self.role = QComboBox(sidebar)
        self.role.addItem(tr('workspace_flow.front'), 'front')
        self.role.addItem(tr('workspace_flow.rear'), 'rear')
        self.role.hide()  # The two visible buttons use the same selection model.
        role_row = QHBoxLayout()
        self.front_button = QPushButton(tr('workspace_flow.front'), sidebar)
        self.rear_button = QPushButton(tr('workspace_flow.rear'), sidebar)
        for button in (self.front_button, self.rear_button):
            button.setCheckable(True)
            button.setObjectName('WorkspaceAxisButton')
            role_row.addWidget(button)
        self.front_button.clicked.connect(lambda: self._choose_role(0))
        self.rear_button.clicked.connect(lambda: self._choose_role(1))
        sidebar_layout.addLayout(role_row)
        sidebar_layout.addWidget(QLabel(tr('workspace_flow.type'), sidebar))
        self.suspension_type = QComboBox(sidebar)
        self.suspension_type.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.suspension_type.setMinimumContentsLength(8)
        self.suspension_type.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.suspension_type.setAccessibleName(tr('workspace_flow.type'))
        self.suspension_type.currentTextChanged.connect(self.suspension_type.setToolTip)
        sidebar_layout.addWidget(self.suspension_type)
        self.support_hint = QLabel(sidebar)
        self.support_hint.setObjectName('WorkspaceSubtitle')
        self.support_hint.setWordWrap(True)
        sidebar_layout.addWidget(self.support_hint)
        sidebar_layout.addWidget(QLabel(tr('workspace_flow.part'), sidebar))
        self.part = QComboBox(sidebar)
        self.part.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.part.setMinimumContentsLength(8)
        self.part.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.part.setAccessibleName(tr('workspace_flow.part'))
        self.part.currentTextChanged.connect(self.part.setToolTip)
        sidebar_layout.addWidget(self.part)
        self.editor = QWidget(sidebar)
        self.editor_layout = QVBoxLayout(self.editor)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(self.editor)
        sidebar_layout.addStretch(1)
        self.editor_scroll.setWidget(sidebar)
        splitter.addWidget(self.editor_scroll)

        self.view_scroll = QScrollArea(splitter)
        self.view_scroll.setWidgetResizable(True)
        main = QWidget(self.view_scroll)
        self.view_scroll.setWidget(main)
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(6, 0, 0, 0)
        controls = QHBoxLayout()
        self.camera = CameraViews(self)
        self.reset = QPushButton(tr('workspace_flow.reset'), self)
        self.volume_button = QToolButton(self)
        self.volume_button.setText(tr('workspace_flow.volume'))
        self.volume_button.setToolTip(tr('workspace_flow.volume_tip'))
        self.volume_button.setCheckable(True)
        self.volume_button.setChecked(True)
        controls.addWidget(self.camera)
        controls.addWidget(self.reset)
        controls.addWidget(self.volume_button)
        controls.addStretch(1)
        main_layout.addLayout(controls)
        self.preview = Scene3DPreview(self, schematic=True, title_override=tr('workspace_flow.scene_title'),
                                      legend_override=tr('workspace_flow.scene_hint'))
        self.preview.volumetric = True
        self.preview.point_selection_enabled = True
        self.preview.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.drag_point_button = QToolButton(self)
        self.drag_point_button.setText(tr('workspace_flow.point_drag'))
        self.drag_point_button.setToolTip(tr('workspace_flow.point_drag_hint'))
        self.drag_point_button.setCheckable(True)
        main_layout.addWidget(self.drag_point_button, 0, Qt.AlignmentFlag.AlignLeft)
        point_hint = QLabel(tr('workspace_flow.point_pick_hint'), self)
        point_hint.setWordWrap(True)
        main_layout.addWidget(point_hint)
        self.volume_button.toggled.connect(self._set_volumetric)
        self.preview.setMinimumSize(240, 180)
        main_layout.addWidget(self.preview, 1)
        grid = QHBoxLayout()
        self.start = self._spin(-150, 0, -30, ' мм')
        self.end = self._spin(0, 150, 30, ' мм')
        self.spacing = self._spin(5, 30, 10, ' мм')
        for text, widget in ((tr('workspace_flow.from'), self.start), (tr('workspace_flow.to'), self.end),
                             (tr('workspace_flow.step'), self.spacing)):
            widget.setMaximumWidth(90)
            grid.addWidget(QLabel(text, self))
            grid.addWidget(widget)
        grid.addStretch(1)
        main_layout.addLayout(grid)
        self.travel = QSlider(Qt.Orientation.Horizontal, self)
        self.travel.setEnabled(False)
        self.travel.setAccessibleName(tr('workspace_flow.travel'))
        main_layout.addWidget(self.travel)

        self.results_tabs = QTabWidget(self)
        self.results_tabs.setMinimumHeight(180)
        self.results_tabs.setMaximumHeight(220)
        results_scroll = QScrollArea(self.results_tabs)
        results_scroll.setWidgetResizable(True)
        results = QWidget(results_scroll)
        result_layout = QVBoxLayout(results)
        result_layout.setContentsMargins(8, 8, 8, 8)
        self.status = QLabel(results)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        result_layout.addWidget(self.status)
        self.sample = QLabel(results)
        self.sample.setWordWrap(True)
        result_layout.addWidget(self.sample)
        self.elements_sample = QLabel(results)
        self.elements_sample.setWordWrap(True)
        result_layout.addWidget(self.elements_sample)
        self.clearance_button = QPushButton('Проверить условные формы…', results)
        self.clearance_button.setToolTip('Только выбранные формы с явно заданными размерами на дискретных позах')
        self.clearance_button.setEnabled(False)
        self.clearance_button.clicked.connect(self._open_clearance)
        result_layout.addWidget(self.clearance_button)
        self.cad_handoff_button = QPushButton('Передний нижний рычаг → CAD-заготовка…', results)
        self.cad_handoff_button.setToolTip('Передача возможна после проверки нижнего рычага с другой выбранной формой')
        self.cad_handoff_button.setEnabled(False)
        self.cad_handoff_button.clicked.connect(self._prepare_cad_handoff)
        result_layout.addWidget(self.cad_handoff_button)
        self.cad_handoff_hint = QLabel('Для перехода в CAD сначала проверьте нижний рычаг с другой формой.', results)
        self.cad_handoff_hint.setWordWrap(True)
        result_layout.addWidget(self.cad_handoff_hint)
        self.summary_toggle = QToolButton(results)
        self.summary_toggle.setText(tr('workspace_flow.summary'))
        self.summary_toggle.setCheckable(True)
        self.summary_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.summary_toggle.setArrowType(Qt.ArrowType.RightArrow)
        result_layout.addWidget(self.summary_toggle)
        self.summary = QLabel(results)
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.hide()
        result_layout.addWidget(self.summary)
        self.summary_toggle.toggled.connect(self.summary.setVisible)
        self.summary_toggle.toggled.connect(
            lambda checked: self.summary_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
        warning = QLabel(tr('workspace_flow.warning'), results)
        warning.setWordWrap(True)
        result_layout.addWidget(warning)
        result_layout.addStretch(1)
        results_scroll.setWidget(results)
        self.results_tabs.addTab(results_scroll, tr('workspace_flow.results'))

        graph_scroll = QScrollArea(self.results_tabs)
        graph_scroll.setWidgetResizable(True)
        self.plot_panel = QWidget(graph_scroll)
        plot_layout = QVBoxLayout(self.plot_panel)
        plot_layout.setContentsMargins(8, 8, 8, 8)
        metrics = ('camber', 'toe', 'spring_length', 'damper_length', 'rocker_ratio')
        self.plot_metric = QComboBox(self.plot_panel)
        for metric in metrics:
            self.plot_metric.addItem(tr(f'workspace_flow.graph_labels.{metric}'), metric)
        plot_layout.addWidget(self.plot_metric)
        self.plot = SweepPlot(self.plot_panel, metrics=metrics, label_prefix='workspace_flow.graph_labels')
        plot_layout.addWidget(self.plot)
        plot_notice = QLabel(tr('workspace_flow.graph_notice'), self.plot_panel)
        plot_notice.setWordWrap(True)
        plot_layout.addWidget(plot_notice)
        graph_scroll.setWidget(self.plot_panel)
        self.results_tabs.addTab(graph_scroll, tr('workspace_flow.graph_tab'))
        self.plot_metric.currentIndexChanged.connect(self.plot.set_metric)
        self.plot.rowSelected.connect(self.travel.setValue)
        main_layout.addWidget(self.results_tabs)
        splitter.addWidget(self.view_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 800])
        outer.addWidget(splitter, 1)
        self.camera.viewSelected.connect(lambda _view: self.drag_point_button.setChecked(False))
        self.camera.viewSelected.connect(self.preview.set_standard_view)
        self.reset.clicked.connect(lambda: self.drag_point_button.setChecked(False))
        self.reset.clicked.connect(self.preview.reset_camera)
        self.drag_point_button.toggled.connect(self._set_point_drag_mode)
        self.preview.linksClicked.connect(self._select_hits)
        self.preview.pointsClicked.connect(self._select_point_hits)
        self.preview.pointDragged.connect(self._commit_point_drag)
        self.role.currentIndexChanged.connect(self._role_changed)
        self.suspension_type.activated.connect(self._choose_suspension_type)
        self.part.currentIndexChanged.connect(self._part_changed)
        self.travel.valueChanged.connect(self._show_sample)
        self.travel.valueChanged.connect(self._disable_drag_for_nonzero)
        for field in (self.start, self.end, self.spacing):
            field.valueChanged.connect(self._invalidate)
        controller.modelChanged.connect(self._model_changed)
        controller.projectReplaced.connect(self._role_changed)
        controller.unitsChanged.connect(self._rebuild_editor)
        controller.selectionChanged.connect(self._external_selection)
        self._role_changed()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (watched is getattr(self, '_sidebar', None) and event.type() in
                (QEvent.Type.LayoutRequest, QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.Show)):
            # Wait for Qt to finish the current layout/style pass before measuring.
            self._sidebar_width_timer.start(0)
        return super().eventFilter(watched, event)

    def _update_sidebar_minimum_width(self) -> None:
        layout = self._sidebar.layout()
        if layout is not None:
            layout.activate()
        # The vertical scrollbar consumes viewport width even though it belongs
        # to the scroll area, not the sidebar's minimum size hint.
        bar = self.editor_scroll.verticalScrollBar()
        needed = (max(self._sidebar.minimumSizeHint().width(), self._sidebar.minimumWidth()) +
                  bar.sizeHint().width() + 2 * self.editor_scroll.frameWidth() + 4)
        minimum = max(380, needed)
        if self.editor_scroll.minimumWidth() != minimum:
            self.editor_scroll.setMinimumWidth(minimum)

    def _choose_role(self, index: int) -> None:
        self.role.setCurrentIndex(index)
        self.front_button.setChecked(index == 0)
        self.rear_button.setChecked(index == 1)

    def _set_volumetric(self, enabled: bool) -> None:
        self.preview.volumetric = enabled
        self.preview.update()

    def _set_point_drag_mode(self, enabled: bool) -> None:
        self.preview.cancel_point_drag()
        self.preview.point_drag_enabled = False
        if not enabled:
            return
        code = self.preview.selected_point
        if code is None:
            self.sample.setText(tr('workspace_flow.drag_select_first'))
            self.drag_point_button.setChecked(False)
            return
        result = self.result
        if result is not None:
            index = min(range(len(result.samples)), key=lambda i: abs(result.samples[i].travel_mm))
            self.travel.setValue(index)
        frame = self.preview.frame
        point = self._axle().hardpoints.get(code)
        shown = frame.point(code) if frame is not None else None
        if (frame is None or point is None or shown is None or abs(frame.travel_mm) > 1e-7 or
                any(abs(a - b) > 1e-4 for a, b in zip(shown, point.as_tuple(), strict=True))):
            self.sample.setText(tr('workspace_flow.drag_no_original'))
            self.drag_point_button.setChecked(False)
            return
        self.preview.set_standard_view('top')
        self.preview.point_drag_enabled = True
        self.sample.setText(tr('workspace_flow.drag_active'))

    def _disable_drag_for_nonzero(self, *_args) -> None:
        if self.preview.frame is None or abs(self.preview.frame.travel_mm) > 1e-7:
            self.drag_point_button.setChecked(False)

    def _commit_point_drag(self, code: str, frame, dx: float, dy: float) -> None:
        if (not self.drag_point_button.isChecked() or not self.preview.point_drag_enabled or
                frame is not self.preview.frame or code != self.preview.selected_point or
                abs(frame.travel_mm) > 1e-7):
            return
        point = self._axle().hardpoints.get(code)
        shown = frame.point(code)
        if (point is None or shown is None or
                any(abs(a - b) > 1e-4 for a, b in zip(shown, point.as_tuple(), strict=True))):
            return
        old = point.as_tuple()
        xyz = (old[0] + dx, old[1] + dy, old[2])
        try:
            if any(abs(value) > 1_000_000 for value in xyz):
                raise ValueError('Out of display range')
            self.controller.move_points({(self.role.currentData(), code): xyz})
        except (ValueError, KeyError):
            self.sample.setText(tr('workspace_flow.drag_locked'))

    def _spin(self, minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setRange(minimum, maximum)
        box.setDecimals(1)
        box.setValue(value)
        box.setSuffix(suffix)
        return box

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._invalidate()

    def _axle(self):
        return self.controller.project.axle(self.role.currentData())

    def _part_index(self, data: object) -> int:
        return next((i for i in range(self.part.count()) if self.part.itemData(i) == data), -1)

    def _role_changed(self, *_args) -> None:
        self.drag_point_button.setChecked(False)
        axle = self._axle()
        self.preview.editable_point_codes = frozenset(p.code for p in axle.spec.points if p.code in axle.hardpoints)
        self.front_button.setChecked(axle.role == 'front')
        self.rear_button.setChecked(axle.role == 'rear')
        self._sync_suspension_type()
        old = self.part.currentData()
        self.part.blockSignals(True)
        self.part.clear()
        self.part.addItem('Все точки', ('all', ''))
        for spec in axle.spec.links:
            self.part.addItem(tr(spec.name_key), ('link', spec.code))
        group_names = {'upper_arm': 'Верхний рычаг', 'lower_arm': 'Нижний рычаг',
                       'upper_links': 'Верхние тяги', 'lower_links': 'Нижние тяги', 'steering': 'Рулевое',
                       'spring': 'Пружина', 'damper': 'Амортизатор', 'arb': 'Стабилизатор',
                       'drivetrain': 'Привод', 'wheel': 'Колесо', 'trailing_links': 'Продольные тяги',
                       'axle': 'Мост', 'triangulated': 'Треугольные тяги', 'lateral': 'Поперечные тяги',
                       'torque_arm': 'Реактивная тяга', 'strut': 'Стойка'}
        for group in axle.spec.point_groups:
            self.part.addItem('Точки: ' + group_names.get(group, group), ('group', group))
        index = self._part_index(old) if old is not None else -1
        if index < 0:
            index = self._part_index(('link', 'lower_arm'))
        if index < 0 and axle.spec.links:
            index = self._part_index(('link', axle.spec.links[0].code))
        self.part.setCurrentIndex(max(0, index))
        self.part.blockSignals(False)
        self.part.setToolTip(self.part.currentText())
        self._rebuild_editor()
        self._invalidate()
        self._show_sample()

    def _sync_suspension_type(self) -> None:
        axle = self._axle()
        self.suspension_type.blockSignals(True)
        self.suspension_type.clear()
        for code in types_for_role(axle.role):
            # Only these two explicit models have an implemented travel solver.
            has_solver = (axle.role, code) in (('front', 'double_wishbone'), ('rear', 'multilink_rear'))
            suffix = tr('workspace_flow.solver_available' if has_solver else 'workspace_flow.solver_unavailable')
            self.suspension_type.addItem(f'{tr(f"type.{code}.name")} — {suffix}', code)
        self.suspension_type.setCurrentIndex(self.suspension_type.findData(axle.type_code))
        self.suspension_type.blockSignals(False)
        self.suspension_type.setToolTip(self.suspension_type.currentText())
        self.support_hint.setText(tr('workspace_flow.supported' if supported(axle) else 'workspace_flow.unsupported'))

    def _choose_suspension_type(self, _index: int) -> None:
        axle = self._axle()
        code = self.suspension_type.currentData()
        if not isinstance(code, str) or code == axle.type_code:
            return
        old_type = axle.type_code
        answer = QMessageBox.question(
            self, tr('workspace_flow.change_title'), tr('workspace_flow.change_notice'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if (answer != QMessageBox.StandardButton.Yes or self._axle() is not axle or axle.type_code != old_type):
            self._sync_suspension_type()
            return
        self.controller.set_axle_type(axle.role, code)

    def _point_codes(self) -> list[str]:
        axle = self._axle()
        kind, code = self.part.currentData() or ('all', '')
        if kind == 'link':
            spec = axle.spec.link(code)
            return [p for p in (*spec.pivot, spec.end) if p in axle.hardpoints] if spec else []
        return [spec.code for spec in axle.spec.points
                if spec.code in axle.hardpoints and (kind == 'all' or spec.group == code)]

    def _part_changed(self, *_args) -> None:
        kind, code = self.part.currentData() or ('all', '')
        if kind == 'link':
            self.controller.select(Selection('link', self.role.currentData(), code))
        else:
            self.controller.select(Selection('axle', self.role.currentData()))
        self._rebuild_editor()
        self._show_sample()

    def _external_selection(self, selection: Selection | None) -> None:
        if selection is None or selection.kind != 'link' or selection.role != self.role.currentData():
            return
        index = self._part_index(('link', selection.code))
        if index >= 0 and index != self.part.currentIndex():
            self.part.setCurrentIndex(index)

    def _rebuild_editor(self, *_args) -> None:
        self.preview.select_point(None)
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._rows.clear()
        self._element_controls: dict[str, QComboBox | QDoubleSpinBox] = {}
        self._rocker_status: QLabel | None = None
        axle = self._axle()
        role = self.role.currentData()
        kind, code = self.part.currentData() or ('all', '')
        hint = QLabel('Координаты исходной схемы: X — вдоль, Y — влево, Z — вверх. '
                      'Для симметричных осей редактируется левая сторона.', self.editor)
        hint.setWordWrap(True)
        self.editor_layout.addWidget(hint)
        self.length: QDoubleSpinBox | None = None
        if kind == 'link':
            group = QGroupBox('Длина детали', self.editor)
            form = QVBoxLayout(group)
            form.addWidget(QLabel('От оси до конца', group))
            self.length = self._spin(0.001, 1_000_000, max(0.001, axle.link_length(code)), ' мм')
            self.length.setDecimals(3)
            self.length.setKeyboardTracking(False)
            self.length.valueChanged.connect(lambda value: self._change_length(code, value))
            form.addWidget(self.length)
            note = QLabel('Меняется наружная точка, перпендикулярно оси. Общие точки меняют и соседние детали.')
            note.setWordWrap(True)
            form.addWidget(note)
            self.editor_layout.addWidget(group)
        if kind == 'group' and code in ('spring', 'damper'):
            self._add_element_editor(code)
        self.point_toggles: dict[str, QToolButton] = {}
        for index, point_code in enumerate(self._point_codes()):
            point = axle.hardpoints[point_code]
            ps = axle.spec.point(point_code)
            group = QGroupBox(self.editor)
            layout = QVBoxLayout(group)
            toggle = QToolButton(group)
            toggle.setText(tr(ps.name_key) if ps else point_code)
            toggle.setToolTip(toggle.text())
            toggle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toggle.setCheckable(True)
            toggle.setChecked(index == 0)
            toggle.setArrowType(Qt.ArrowType.DownArrow if index == 0 else Qt.ArrowType.RightArrow)
            self.point_toggles[point_code] = toggle
            layout.addWidget(toggle)
            coordinates = QWidget(group)
            coordinate_layout = QVBoxLayout(coordinates)
            coordinate_layout.setContentsMargins(0, 0, 0, 0)
            coordinates.setVisible(index == 0)
            toggle.toggled.connect(coordinates.setVisible)
            toggle.toggled.connect(lambda checked, code=point_code: self._select_editor_point(code, checked))
            toggle.toggled.connect(lambda checked, button=toggle: button.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
            layout.addWidget(coordinates)
            for original_spec in point_specs(point, point_code)[0].params[:3]:
                value = float(original_spec.value())
                spec = replace(original_spec, minimum=min(original_spec.minimum, value - 100),
                               maximum=max(original_spec.maximum, value + 100))
                key = f'{role}.{spec.key}'
                field = SliderField(spec, self.controller.units, value, group,
                                    auto_extend=self.controller.auto_extend_slider,
                                    locked=point.locked or self.controller.is_locked(key))
                field._title.setText(spec.attr.upper())
                field._title.setMinimumWidth(24)
                field._lock_button.setEnabled(not point.locked)
                field.valueChanged.connect(lambda value, p=point_code, a=spec.attr: self._change_point(p, a, value))
                field.lockChanged.connect(lambda locked, k=key: self.controller.set_lock(k, locked))
                field.helpRequested.connect(self._show_help)
                self._rows[(point_code, spec.attr)] = field
                coordinate_layout.addWidget(field)
            self.editor_layout.addWidget(group)
        self.editor_layout.addStretch(1)
        self._refresh_element_controls()

    def _select_editor_point(self, code: str, expanded: bool) -> None:
        if expanded:
            self.preview.select_point(code)
        elif self.preview.selected_point == code:
            self.preview.select_point(None)

    def _active_setup(self, name: str) -> ElementSetup:
        axle = self._axle()
        config = axle.kinematic_elements
        return getattr(config, name) if config is not None and config.type_code == axle.type_code else ElementSetup()

    def _add_element_editor(self, name: str) -> None:
        axle = self._axle()
        title = 'Проверка пружины' if name == 'spring' else 'Проверка амортизатора'
        group = QGroupBox(title, self.editor)
        form = QFormLayout(group)
        hint = QLabel('Укажите, к чему жёстко прикреплён каждый центр. '
                      'Пределы — расстояния между центрами, не длина штока и не длина витков.', group)
        hint.setWordWrap(True)
        form.addRow(hint)
        if not supported(axle):
            text = QLabel('Для этой схемы движение креплений не рассчитывается.', group)
            text.setWordWrap(True)
            form.addRow(text)
            self.editor_layout.addWidget(group)
            return
        setup = self._active_setup(name)
        if name == 'damper':
            rocker_button = QPushButton(tr('rocker_setup.button'), group)
            rocker_button.clicked.connect(self._edit_rocker)
            form.addRow(rocker_button)
            self._rocker_status = QLabel(group)
            self._rocker_status.setWordWrap(True)
            form.addRow(self._rocker_status)
        for attr, label in (('lower', 'Нижняя точка'), ('upper', 'Верхняя точка')):
            combo = QComboBox(group)
            combo.addItem('Не задано', None)
            combo.addItem('Кузов', 'body')
            combo.addItem('Кулак', 'upright')
            if axle.type_code == 'double_wishbone':
                combo.addItem('Нижний рычаг', 'lower_arm')
            value = getattr(setup, attr)
            index = next((i for i in range(combo.count()) if combo.itemData(i) == value), 0)
            combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(lambda _i, field=attr: self._change_element(name, field))
            self._element_controls[attr] = combo
            form.addRow(label, combo)
        for attr, label in (('minimum_mm', 'Минимум, мм'), ('maximum_mm', 'Максимум, мм')):
            box = QDoubleSpinBox(group)
            box.setRange(0, 1_000_000)
            box.setDecimals(3)
            box.setSpecialValueText('Не задано')
            box.setSuffix(' мм')
            box.setKeyboardTracking(False)
            box.setValue(getattr(setup, attr) or 0)
            box.valueChanged.connect(lambda _v, field=attr: self._change_element(name, field))
            self._element_controls[attr] = box
            form.addRow(label, box)
        self.editor_layout.addWidget(group)

    def _edit_rocker(self) -> None:
        axle = self._axle()
        old = axle.kinematic_elements
        initial = old.rocker if old is not None and old.type_code == axle.type_code else None
        revision = self._revision
        dialog = RockerSetupDialog(axle.type_code, initial, self)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            result = dialog.result_setup
        finally:
            dialog.deleteLater()
        if not accepted:
            return
        if self._axle() is not axle or axle.kinematic_elements != old or revision != self._revision:
            self.sample.setText(tr('rocker_setup.changed'))
            return
        if old is None and result is None:
            return
        config = old if old is not None and old.type_code == axle.type_code else KinematicElements(axle.type_code)
        self.controller.set_value(axle, 'kinematic_elements', replace(config, rocker=result),
                                  merge_key=f'rocker-setup:{id(axle)}:{self._revision}')

    def _change_element(self, name: str, field: str) -> None:
        axle = self._axle()
        if not supported(axle) or len(self._element_controls) != 4:
            return
        lower, upper = self._element_controls['lower'], self._element_controls['upper']
        minimum, maximum = self._element_controls['minimum_mm'], self._element_controls['maximum_mm']
        assert isinstance(lower, QComboBox) and isinstance(upper, QComboBox)
        assert isinstance(minimum, QDoubleSpinBox) and isinstance(maximum, QDoubleSpinBox)
        setup = ElementSetup(lower.currentData(), upper.currentData(), minimum.value() or None, maximum.value() or None)
        config = axle.kinematic_elements
        if config is None or config.type_code != axle.type_code:
            config = KinematicElements(axle.type_code)
        updated = replace(config, **{name: setup})
        self.controller.set_value(axle, 'kinematic_elements', updated,
                                  merge_key=f'kinematic-elements:{id(axle)}:{name}:{field}:{self._revision}')

    def _refresh_element_controls(self) -> None:
        kind, name = self.part.currentData() or ('all', '')
        if kind != 'group' or name not in ('spring', 'damper') or not self._element_controls:
            return
        setup = self._active_setup(name)
        config = self._axle().kinematic_elements
        rocker_active = (name == 'damper' and config is not None and config.type_code == self._axle().type_code and
                         config.rocker is not None and config.rocker.enabled)
        if self._rocker_status is not None:
            self._rocker_status.setText(tr('rocker_setup.rocker_status' if rocker_active else 'rocker_setup.direct_status'))
        if name == 'damper':
            for toggle in self.point_toggles.values():
                container = toggle.parentWidget()
                if container is not None:
                    container.setVisible(not rocker_active)
            if rocker_active and self.preview.selected_point in self.point_toggles:
                self.preview.select_point(None)
        for attr, widget in self._element_controls.items():
            if attr in ('lower', 'upper'):
                widget.setEnabled(not rocker_active)
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                value = getattr(setup, attr)
                index = next((i for i in range(widget.count()) if widget.itemData(i) == value), 0)
                widget.setCurrentIndex(index)
            else:
                widget.setValue(getattr(setup, attr) or 0)
            widget.blockSignals(False)

    def _show_help(self, key: str) -> None:
        QMessageBox.information(self, tr('insp.info'), tr(key))

    def _change_point(self, code: str, axis: str, value: float) -> None:
        point = self._axle().hardpoints.get(code)
        if point is None:
            return
        values = list(point.as_tuple())
        values['xyz'.index(axis)] = value
        try:
            if abs(value) > 1_000_000:
                raise ValueError('Координата вне диапазона отображения')
            self.controller.move_points({(self.role.currentData(), code): tuple(values)})
        except (ValueError, KeyError):
            self._refresh_fields()
            self.sample.setText('Точка зафиксирована или координата вне диапазона отображения.')

    def _change_length(self, code: str, value: float) -> None:
        try:
            target, xyz = moved_link_end(self._axle(), code, value)
            self.controller.move_points({(self.role.currentData(), target): xyz})
        except (ValueError, KeyError):
            self._refresh_fields()
            self.sample.setText('Длину изменить не удалось: точка зафиксирована или направление не определено.')

    def _refresh_fields(self) -> None:
        axle = self._axle()
        role = self.role.currentData()
        for (code, axis), widget in self._rows.items():
            point = axle.hardpoints.get(code)
            if point is not None:
                value = getattr(point, axis)
                if value < widget._minimum or value > widget._maximum:
                    widget._minimum = min(widget._minimum, value - 100)
                    widget._maximum = max(widget._maximum, value + 100)
                    widget._update_slider_range()
                widget.set_value(value)
                widget.set_locked(point.locked or self.controller.is_locked(f'{role}.point.{code}.{axis}'))
                widget._lock_button.setEnabled(not point.locked)
        kind, code = self.part.currentData() or ('all', '')
        if kind == 'link' and self.length is not None:
            self.length.blockSignals(True)
            self.length.setValue(max(0.001, axle.link_length(code)))
            self.length.blockSignals(False)

    def _model_changed(self) -> None:
        self._refresh_fields()
        self._refresh_element_controls()
        self._invalidate()

    def _invalidate(self, *_args) -> None:
        self._revision += 1
        if self._clearance_dialog is not None:
            self._clearance_dialog.invalidate()
        self.clearance_button.setEnabled(False)
        self._clearance_settings = None
        self.cad_handoff_button.setEnabled(False)
        self.cad_handoff_hint.setText('Для перехода в CAD сначала проверьте нижний рычаг с другой формой.')
        self.result = None
        self.plot.set_points(())
        self._timer.stop()
        self.travel.setEnabled(False)
        self.sample.setText('')
        self.elements_sample.setText('')
        self.summary.setText('Сводка обеих осей: ожидает пересчёта.')
        try:
            scene, links = static_scene(self._axle())
            self.preview.link_targets = links
            self.preview.configure([scene])
            self.preview.show_frame(scene)
        except (ValueError, KeyError, OverflowError):
            self.preview.clear('Не удалось показать статическую схему.')
        self.status.setText('Параметры изменены: расчёт ожидает обновления.')
        if self.isVisible():
            self._timer.start()

    def _calculate(self) -> None:
        axle = self._axle()
        results: dict[str, WorkspaceResult] = {}
        errors: dict[str, str] = {}
        summaries = []
        for role, label in (('front', 'Передняя'), ('rear', 'Задняя')):
            other = self.controller.project.axle(role)
            if not supported(other):
                errors[role] = 'Расчёт хода для этой схемы пока не реализован. Показана только статическая компоновка.'
                summaries.append(f'{label}: только статическая схема; не проверено')
                continue
            try:
                calculated = calculate(other, self.start.value(), self.end.value(), self.spacing.value())
                results[role] = calculated
                summaries.append(f'{label}: {_summary_text(calculated)}')
            except (ValueError, KeyError, OverflowError, ArithmeticError) as error:
                errors[role] = f'Расчёт не выполнен: {error}. Показана статическая схема.'
                summaries.append(f'{label}: расчёт не выполнен: {error}; не проверено')
            except Exception:
                LOG.exception('Неожиданная ошибка кинематического расчёта')
                errors[role] = 'Расчёт не выполнен из-за ошибки. Показана статическая схема.'
                summaries.append(f'{label}: ошибка расчёта; не проверено')
        self.summary.setText('Сводка (на заданной сетке хода):\n' + '\n'.join(summaries))
        result = results.get(axle.role)
        if result is None:
            self.status.setText(errors[axle.role])
            return
        self.result = result
        self.clearance_button.setEnabled(True)
        points = []
        for sample in result.samples:
            metrics = sample.metrics if sample.scene is not None else None
            spring = sample.spring if sample.scene is not None else None
            damper = sample.damper if sample.scene is not None else None
            values = (metrics.camber_deg if metrics else None, metrics.toe_deg if metrics else None,
                      spring.length_mm if spring else None, damper.length_mm if damper else None,
                      sample.rocker.motion_ratio if sample.rocker is not None and sample.scene is not None else None)
            conflict = any(element is not None and element.status in ('below', 'above', 'invalid', 'error')
                           for element in (spring, damper))
            points.append(PlotPoint(sample.travel_mm, values, conflict))
        self.plot.set_points(tuple(points))
        success = sum(sample.scene is not None for sample in result.samples)
        failures = [sample for sample in result.samples if sample.error]
        model_description = ('Левая сторона, неподвижная рейка' if axle.role == 'front' else
                             'Левая сторона, пять тяг, неподвижный кузов')
        text = (f'{model_description}. Решено положений: {success} из {len(result.samples)}; '
                f'последние достигнутые ходы {result.reached_droop_mm:.1f}…{result.reached_bump_mm:.1f} мм.')
        if failures:
            text += f' Пример отказа: {failures[0].error}'
        self.status.setText(text)
        frames = [sample.scene for sample in result.samples if sample.scene is not None]
        self.preview.configure(frames)
        self.travel.blockSignals(True)
        self.travel.setRange(0, len(result.samples) - 1)
        self.travel.setValue(min(range(len(result.samples)), key=lambda i: abs(result.samples[i].travel_mm)))
        self.travel.blockSignals(False)
        self.travel.setEnabled(True)
        self._show_sample()

    def _open_clearance(self) -> None:
        if self.result is None or self._clearance_dialog is not None:
            return
        axle, revision = self._axle(), self._revision
        self._clearance_settings = None
        self.cad_handoff_button.setEnabled(False)
        dialog = ClearanceDialog(axle, self.start.value(), self.end.value(), self.spacing.value(),
                                 lambda: self._revision == revision and self._axle() is axle, self)
        self._clearance_dialog = dialog
        try:
            dialog.exec()
            if self._revision == revision and self._axle() is axle and self.result is not None:
                self._clearance_settings = dialog.last_setup
                selected = dict(dialog.last_setup.radii) if dialog.last_setup is not None else {}
                ready = axle.role == 'front' and axle.type_code == 'double_wishbone' and 'lower_arm' in selected and len(selected) >= 2
                self.cad_handoff_button.setEnabled(ready)
                self.cad_handoff_hint.setText(
                    'Настройки проверки запомнены до изменения проекта; при передаче проверка будет повторена.' if ready else
                    'Для перехода в CAD сначала проверьте передний нижний рычаг с другой формой.')
        finally:
            self._clearance_dialog = None
            dialog.deleteLater()

    def _prepare_cad_handoff(self) -> None:
        settings, project, revision = self._clearance_settings, self.controller.project, self._revision
        if settings is None or self.result is None or self.role.currentData() != 'front':
            return
        radius = dict(settings.radii).get('lower_arm')
        if radius is None or radius < .02 or radius > 10000 or round(radius, 2) != radius:
            QMessageBox.warning(self, 'Передача в CAD', 'Радиус нижнего рычага в проверке должен быть от 0,02 до '
                                '10000 мм и иметь не более двух знаков после запятой. Повторите проверку с этим радиусом.')
            return
        wall, accepted = QInputDialog.getDouble(self, 'Толщина стенки',
            'Толщина стенки двух прямых труб, мм. Это черновая геометрия, не проверка прочности:',
            min(2., round(radius - .01, 2)), .01, round(radius - .01, 2), 2)
        if not accepted:
            return
        if (self._revision != revision or self.controller.project is not project or self._clearance_settings is not settings):
            QMessageBox.warning(self, 'Передача в CAD', 'Проект или параметры изменились; повторите проверку.')
            return
        try:
            handoff = prepare_cad_handoff(project, self.start.value(), self.end.value(), self.spacing.value(), settings, wall)
        except HandoffError as error:
            QMessageBox.warning(self, 'Передача в CAD', str(error))
            return
        if self._revision != revision or self.controller.project is not project or not handoff.matches(project):
            QMessageBox.warning(self, 'Передача в CAD', 'Проект изменился во время расчёта; повторите проверку.')
            return
        confirmation = CadHandoffDialog(_cad_handoff_text(handoff), self)
        try:
            accepted = confirmation.exec() == QDialog.DialogCode.Accepted
        finally:
            confirmation.deleteLater()
        if not accepted:
            return
        if (self._revision != revision or self.controller.project is not project or
                self._clearance_settings is not settings or not handoff.matches(project)):
            QMessageBox.warning(self, 'Передача в CAD', 'Проект изменился во время подтверждения; передача отменена.')
            return
        self.cadHandoffRequested.emit(handoff)

    def _show_sample(self, *_args) -> None:
        kind, code = self.part.currentData() or ('all', '')
        self.preview.selected_link = (self.role.currentData(), code) if kind == 'link' else None
        if self.result is None:
            self.preview.update()
            return
        sample = self.result.samples[self.travel.value()]
        self.plot.set_row(self.travel.value())
        self.preview.show_frame(sample.scene, 'Нет решения для этого положения')
        self.preview.link_targets = ()
        if sample.scene is not None:
            targets = []
            for spec in self._axle().spec.links:
                end = sample.scene.point(spec.end)
                for pivot in spec.pivot:
                    start = sample.scene.point(pivot)
                    if start is not None and end is not None:
                        targets.append(SelectableLink(self.role.currentData(), spec.code, Segment3D(start, end, 'arm')))
            self.preview.link_targets = tuple(targets)
        elements_text = (f'Пружина: {_element_text(sample.spring)}\n'
                         f'Амортизатор: {_element_text(sample.damper)}')
        if sample.rocker is not None and sample.rocker.pose is not None:
            from math import degrees

            ratio = sample.rocker.motion_ratio
            ratio_text = f'{ratio:+.4f}' if ratio is not None else 'не определено'
            elements_text += (f'\nКоромысло: {degrees(sample.rocker.pose.angle_rad):+.2f}°; '
                              f'−dL/dh ≈ {ratio_text} (по соседним точкам).')
        self.elements_sample.setText(elements_text)
        if sample.error:
            self.sample.setText(f'Ход {sample.travel_mm:+.1f} мм: нет решения. {sample.error}')
        elif sample.metrics is None:
            self.sample.setText(f'Ход {sample.travel_mm:+.1f} мм: положение найдено, углы не рассчитаны.')
        else:
            self.sample.setText(f'Ход {sample.travel_mm:+.1f} мм • развал {sample.metrics.camber_deg:+.2f}° '
                                f'• схождение одного колеса {sample.metrics.toe_deg:+.2f}°')

    def _select_point_hits(self, hits, position) -> None:
        revision, frame = self._revision, self.preview.frame
        if len(hits) == 1:
            self._apply_point_hit(hits[0], revision, frame)
            return
        if not hits:
            return
        if self._menu is not None:
            self._menu.close()
        menu = QMenu(self)
        self._menu = menu
        for code in hits:
            spec = self._axle().spec.point(code)
            if spec is not None:
                action = menu.addAction(f'{tr(spec.name_key)} ({code})')
                action.triggered.connect(lambda _checked=False, c=code, r=revision, f=frame:
                                         self._apply_point_hit(c, r, f))
        menu.aboutToHide.connect(lambda: self._close_pick_menu(menu))
        menu.popup(self.preview.mapToGlobal(position))

    def _close_pick_menu(self, menu: QMenu) -> None:
        if self._menu is menu:
            self._menu = None
        menu.deleteLater()

    def _apply_point_hit(self, code: str, revision: int, frame) -> None:
        if revision != self._revision or frame is None or frame is not self.preview.frame:
            return
        spec = self._axle().spec.point(code)
        if spec is None or code not in self._axle().hardpoints or frame.point(code) is None:
            return
        if code not in self.point_toggles:
            index = self._part_index(('group', spec.group))
            if index < 0:
                index = self._part_index(('all', ''))
            if index < 0:
                return
            self.part.setCurrentIndex(index)
        toggle = self.point_toggles.get(code)
        if toggle is not None:
            toggle.setChecked(True)
            self.preview.select_point(code)  # also works when the toggle was already open
            self.editor_scroll.ensureWidgetVisible(toggle)

    def _select_hits(self, hits, position) -> None:
        if not hits:
            return
        if len(hits) == 1:
            self._apply_hit(hits[0].code, self._revision)
            return
        if self._menu is not None:
            self._menu.close()
        menu = QMenu(self)
        self._menu = menu
        revision = self._revision
        for hit in hits:
            spec = self._axle().spec.link(hit.code)
            if spec:
                action = menu.addAction(tr(spec.name_key))
                action.triggered.connect(lambda _checked=False, code=hit.code, rev=revision: self._apply_hit(code, rev))
        menu.aboutToHide.connect(lambda: self._close_pick_menu(menu))
        menu.popup(self.preview.mapToGlobal(position))

    def _apply_hit(self, code: str, revision: int) -> None:
        if revision != self._revision:
            return
        index = self._part_index(('link', code))
        if index >= 0:
            self.part.setCurrentIndex(index)

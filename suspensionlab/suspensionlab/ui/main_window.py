"""Главное окно приложения: меню, панели, вкладки, статусная строка."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
)

from .. import APP_NAME, __version__
from ..config import diagnostic_log_path, log_file_path, settings_path
from ..i18n import tr
from ..model.project_io import ProjectIOError
from ..model.session_arm_assembly import SessionArmAssembly
from ..model.suspension_types import types_for_role
from ..model.units import LENGTH_UNITS, RATE_UNITS, UnitKind, UnitSettings
from .analysis_dialog import AnalysisDialog
from .antiroll_dialog import AntiRollDialog
from .arm_concept_dialog import ArmConceptDialog
from .cad_preview_dialog import CadPreviewDialog
from .cad_preview_settings import CadPreviewSettingsDialog
from .cad_registration_dialog import CadRegistrationDialog
from .canvas.axle_view import AxleCanvas
from .canvas.vehicle_schematic import VehicleSchematicView
from .controller import AppController, Selection
from .dialogs import RestoreSnapshotDialog, SnapshotDialog, TemplateDialog
from .docks.diagnostics import DiagnosticsPanel
from .docks.inspector import Inspector
from .docks.project_tree import ProjectTree
from .equilibrium_dialog import EquilibriumDialog
from .fixed_arm_skeleton_dialog import FixedArmSkeletonDialog
from .front_tubes_dialog import FrontTubesDialog
from .joint_concept_dialog import JointConceptDialog
from .niva_arms_dialog import NivaArmsDialog
from .point_table_dialog import PointTableDialog
from .rear_tube_dialog import RearTubeDialog
from .sketch_draft_dialog import SketchDraftDialog
from .snapshot_compare_dialog import SnapshotCompareDialog
from .step_inventory_dialog import StepInventoryDialog
from .theme import THEMES, apply_theme
from .weldment_dialog import WeldmentDialog
from .widgets.empty_state import EmptyState

LOG = logging.getLogger(__name__)

#: Период автосохранения, мс.
AUTOSAVE_INTERVAL_MS = 60_000


class MainWindow(QMainWindow):
    """Главное окно «Подвеска.Про»."""

    def __init__(self, controller: AppController | None = None, settings: QSettings | None = None) -> None:
        super().__init__()
        self.controller = controller or AppController(self)
        self._settings = settings or QSettings(str(settings_path()), QSettings.Format.IniFormat)
        self._syncing_view = False
        self._front_tubes_dialog: FrontTubesDialog | None = None
        self._joint_concept_dialog: JointConceptDialog | None = None
        self._rear_tube_dialog: RearTubeDialog | None = None
        self._niva_arms_dialog: NivaArmsDialog | None = None
        self._arm_concept_dialog: ArmConceptDialog | None = None
        self._fixed_arm_skeleton_dialog: FixedArmSkeletonDialog | None = None
        self._weldment_dialog: WeldmentDialog | None = None
        self._theme = str(self._settings.value("view/theme", self.controller.project.view.theme))

        self.setWindowTitle(tr("app.title"))
        self.setMinimumSize(1100, 700)
        self.resize(1366, 800)
        self.setDockNestingEnabled(True)

        self._build_canvas_tabs()
        self._build_docks()
        self._vehicle_view.schemeRequested.connect(self._open_schematic_axle)
        self._vehicle_view.linkSelected.connect(self._inspector_dock.show)
        self._vehicle_view.newAssemblyRequested.connect(self._new_selected_arm_assembly)
        self._vehicle_view.openSessionAssemblyRequested.connect(self._open_session_arm_assembly)
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._restore_settings()
        self._apply_theme(self._theme, initial=True)
        self._connect_controller()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._on_autosave)
        self._autosave_timer.start()

        self.controller.check_autosave_protection()
        self._refresh_undo_actions()
        self._update_title()
        self._update_status()

    # ------------------------------------------------------------------ центральная часть
    def _build_canvas_tabs(self) -> None:
        """Создаёт вкладки со схемами передней и задней осей."""
        self._stack = QStackedWidget(self)
        self._empty = EmptyState(self._stack)
        self._empty.newRequested.connect(self._new_project)
        self._empty.openRequested.connect(self._open_project)
        self._empty.templateRequested.connect(self._new_from_template)

        self._tabs = QTabWidget(self._stack)
        self._canvases: dict[str, AxleCanvas] = {}
        for key, roles in (
            ("front", ("front",)),
            ("rear", ("rear",)),
            ("both", ("front", "rear")),
        ):
            canvas = AxleCanvas(self.controller, self._tabs)
            canvas.set_roles(roles)
            canvas.viewChanged.connect(self._on_canvas_view_changed)
            self._canvases[key] = canvas
            self._tabs.addTab(canvas, tr(f"view.tab.{key}"))
        self._vehicle_view = VehicleSchematicView(self.controller, self._tabs)
        self._tabs.addTab(self._vehicle_view, tr("vehicle_schematic.tab"))
        self._tabs.currentChanged.connect(lambda _index: self._update_status())

        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._tabs)
        self.setCentralWidget(self._stack)

    def _current_canvas(self) -> AxleCanvas:
        """Схема на активной вкладке."""
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, AxleCanvas) else self._canvases["front"]

    def _open_schematic_axle(self, role: str) -> None:
        if role in ("front", "rear"):
            self._tabs.setCurrentWidget(self._canvases[role])

    def _show_workspace(self) -> None:
        """Показывает рабочую область вместо стартового экрана."""
        self._stack.setCurrentWidget(self._tabs)

    def _open_sketch_draft(self) -> None:
        SketchDraftDialog(self).exec()

    def _open_scheme_arm_part(self) -> None:
        from ..model.kim_format import SCHEME_ARM_PART_VERSIONS, KimFormatError, read_document
        from .kim_scheme_arm_dialog import KimSchemeArmDialog

        selected, _ = QFileDialog.getOpenFileName(self, "Открыть схему и заготовку .kim", "", "Деталь KIM (*.kim)")
        if not selected:
            return
        try:
            document = read_document(selected, "part")
            if document["version"] not in SCHEME_ARM_PART_VERSIONS:
                raise KimFormatError("unsupported part version")
            dialog = KimSchemeArmDialog(self.controller, document, Path(selected), self)
        except (KimFormatError, OSError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, "Открытие .kim", "Не удалось открыть файл. Поддерживается только новый экспериментальный .kim со схемой и двумя прямыми трубами; исходный файл не изменён.")
            return
        dialog.exec()
        dialog.deleteLater()

    def _new_selected_arm_assembly(self) -> None:
        if not self._vehicle_view.create_assembly_button.isEnabled():
            return
        self._new_scheme_arm_assembly(from_selection=True)

    def _remember_session_assembly(self, project, dialog) -> None:
        """Только явно сохранённый файл; сессия не изменяет .susp или исходники."""
        from ..model.kim_format import KimFormatError

        if self.controller.project is not project or dialog.path is None or dialog._saved is None:
            return
        try:
            link = SessionArmAssembly.from_saved(project, dialog.path, dialog._saved)
        except (KimFormatError, OSError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, 'Сборка этого сеанса',
                                'Не удалось проверить сохранённый файл .kima. Ссылка в сеансе не обновлена; '
                                'проект и файл не изменены.')
            return
        self._vehicle_view.set_session_assembly(link)

    def _open_session_arm_assembly(self) -> None:
        from ..model.kim_format import KimFormatError
        from .scheme_arm_assembly_dialog import SchemeArmAssemblyDialog

        link = self._vehicle_view.session_assembly
        if link is None:
            return
        project = self.controller.project
        try:
            document = link.load_verified(project)
            dialog = SchemeArmAssemblyDialog(self.controller, document, link.path, self)
        except (KimFormatError, OSError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, 'Открытие сборки этого сеанса',
                                'Файл недоступен, изменился снаружи или проект заменён. '
                                'Ничего не открыто и не изменено. Для другого файла используйте меню открытия .kima.')
            return
        dialog.exec()
        self._remember_session_assembly(project, dialog)
        dialog.deleteLater()

    def _new_scheme_arm_assembly(self, *, from_selection: bool = False) -> None:
        from copy import deepcopy

        from ..model.kim_format import KimFormatError
        from ..model.scheme_arm_assembly import make_scheme_arm_assembly
        from .scheme_arm_assembly_dialog import NewAssemblyParametersDialog, SchemeArmAssemblyDialog

        project = self.controller.project
        before = deepcopy(project.to_dict())
        selection = self.controller.selection
        parameters = NewAssemblyParametersDialog(self)
        if parameters.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if (project is not self.controller.project or before != self.controller.project.to_dict() or
                    (from_selection and (self.controller.selection != selection or
                                         not self._vehicle_view.create_assembly_button.isEnabled()))):
                raise KimFormatError('project or selection changed during input')
            radius, wall = parameters.tube_values()
            doc = make_scheme_arm_assembly(self.controller.project, radius, wall, parameters.values())
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Новая сборка', 'Схема несовместима, данные некорректны или проект изменился.')
            return
        dialog = SchemeArmAssemblyDialog(self.controller, doc, parent=self)
        dialog.exec()
        if from_selection:
            self._remember_session_assembly(project, dialog)
        dialog.deleteLater()

    def _open_scheme_arm_assembly(self) -> None:
        from ..model.kim_format import KimFormatError, read_document
        from ..model.scheme_arm_assembly import validate_scheme_arm_assembly
        from .scheme_arm_assembly_dialog import SchemeArmAssemblyDialog

        selected, _ = QFileDialog.getOpenFileName(self, 'Открыть сборку рычага', '', 'Сборка KIMA (*.kima)')
        if not selected:
            return
        try:
            doc = read_document(selected, 'assembly')
            validate_scheme_arm_assembly(doc)
            dialog = SchemeArmAssemblyDialog(self.controller, doc, Path(selected), self)
        except (KimFormatError, OSError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Открытие сборки', 'Нужна предварительная сборка .kima 0.15/0.16; файл не изменён.')
            return
        dialog.exec()
        dialog.deleteLater()

    def _open_step_inventory(self) -> None:
        StepInventoryDialog(self).exec()

    def _open_cad_preview(self) -> None:
        CadPreviewDialog(self, settings=self._settings).exec()

    def _open_cad_registration(self) -> None:
        CadRegistrationDialog(self.controller, self).exec()

    def _open_joint_concept(self) -> None:
        if self._joint_concept_dialog is None:
            dialog = JointConceptDialog(self.controller, self)
            self._joint_concept_dialog = dialog
            dialog.finished.connect(self._close_joint_concept)
        self._joint_concept_dialog.show()
        self._joint_concept_dialog.raise_()
        self._joint_concept_dialog.activateWindow()

    def _close_joint_concept(self, _result: int) -> None:
        dialog = self._joint_concept_dialog
        self._joint_concept_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _open_front_tubes(self) -> None:
        if self._front_tubes_dialog is None:
            dialog = FrontTubesDialog(self.controller, self)
            self._front_tubes_dialog = dialog
            dialog.finished.connect(self._close_front_tubes)
        self._front_tubes_dialog.show()
        self._front_tubes_dialog.raise_()
        self._front_tubes_dialog.activateWindow()

    def _close_front_tubes(self, _result: int) -> None:
        dialog = self._front_tubes_dialog
        self._front_tubes_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _open_rear_tube(self) -> None:
        if self._rear_tube_dialog is None:
            dialog = RearTubeDialog(self.controller, self)
            self._rear_tube_dialog = dialog
            dialog.finished.connect(self._close_rear_tube)
        self._rear_tube_dialog.show()
        self._rear_tube_dialog.raise_()
        self._rear_tube_dialog.activateWindow()

    def _close_rear_tube(self, _result: int) -> None:
        dialog = self._rear_tube_dialog
        self._rear_tube_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _open_niva_arms(self) -> None:
        if self._niva_arms_dialog is None:
            dialog = NivaArmsDialog(self.controller, self)
            self._niva_arms_dialog = dialog
            dialog.finished.connect(self._close_niva_arms)
        self._niva_arms_dialog.show()
        self._niva_arms_dialog.raise_()
        self._niva_arms_dialog.activateWindow()

    def _close_niva_arms(self, _result: int) -> None:
        dialog = self._niva_arms_dialog
        self._niva_arms_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _open_arm_concept(self) -> None:
        if self._arm_concept_dialog is None:
            dialog = ArmConceptDialog(self.controller, self)
            self._arm_concept_dialog = dialog
            dialog.finished.connect(self._close_arm_concept)
        self._arm_concept_dialog.show()
        self._arm_concept_dialog.raise_()
        self._arm_concept_dialog.activateWindow()

    def _close_arm_concept(self, _result: int) -> None:
        dialog = self._arm_concept_dialog
        self._arm_concept_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _open_fixed_arm_skeleton(self) -> None:
        if self._fixed_arm_skeleton_dialog is None:
            dialog = FixedArmSkeletonDialog(self.controller, self)
            self._fixed_arm_skeleton_dialog = dialog
            dialog.finished.connect(self._close_fixed_arm_skeleton)
        self._fixed_arm_skeleton_dialog.show()
        self._fixed_arm_skeleton_dialog.raise_()
        self._fixed_arm_skeleton_dialog.activateWindow()

    def _close_fixed_arm_skeleton(self, _result: int) -> None:
        dialog = self._fixed_arm_skeleton_dialog
        self._fixed_arm_skeleton_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _open_weldment(self) -> None:
        if self._weldment_dialog is None:
            dialog = WeldmentDialog(self.controller, self)
            self._weldment_dialog = dialog
            dialog.finished.connect(self._close_weldment)
        self._weldment_dialog.show()
        self._weldment_dialog.raise_()
        self._weldment_dialog.activateWindow()

    def _close_weldment(self, _result: int) -> None:
        dialog = self._weldment_dialog
        self._weldment_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _open_cad_preview_settings(self) -> None:
        dialog = CadPreviewSettingsDialog(self._settings, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    # ------------------------------------------------------------------ панели
    def _build_docks(self) -> None:
        """Создаёт док-панели: проект, инспектор, диагностика."""
        self._tree = ProjectTree(self.controller, self)
        self._tree_dock = QDockWidget(tr("tree.project"), self)
        self._tree_dock.setObjectName("ProjectDock")
        self._tree_dock.setWidget(self._tree)
        self._tree_dock.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._tree_dock)

        self._inspector = Inspector(self.controller, self)
        self._inspector_dock = QDockWidget(tr("insp.header"), self)
        self._inspector_dock.setObjectName("InspectorDock")
        self._inspector_dock.setWidget(self._inspector)
        self._inspector_dock.setMinimumWidth(330)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._inspector_dock)

        self._diagnostics = DiagnosticsPanel(self.controller, self)
        self._diagnostics_dock = QDockWidget(tr("diag.title"), self)
        self._diagnostics_dock.setObjectName("DiagnosticsDock")
        self._diagnostics_dock.setWidget(self._diagnostics)
        self._diagnostics_dock.setMinimumHeight(110)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._diagnostics_dock)
        self.resizeDocks([self._diagnostics_dock], [150], Qt.Orientation.Vertical)

    # ------------------------------------------------------------------ действия
    def _build_actions(self) -> None:
        """Создаёт общие действия с горячими клавишами."""
        self.action_new = QAction(tr("menu.file.new"), self)
        self.action_new.setShortcut(QKeySequence.StandardKey.New)
        self.action_new.triggered.connect(self._new_project)

        self.action_open = QAction(tr("menu.file.open"), self)
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open.triggered.connect(self._open_project)

        self.action_recover_autosave = QAction(tr("autosave.recover_menu"), self)
        self.action_recover_autosave.triggered.connect(self._recover_autosave)
        self.action_allow_autosave = QAction(tr("autosave.allow_menu"), self)
        self.action_allow_autosave.triggered.connect(self._allow_autosave_overwrite)

        self.action_save = QAction(tr("menu.file.save"), self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save.triggered.connect(self._save_project)

        self.action_save_as = QAction(tr("menu.file.save_as"), self)
        self.action_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.action_save_as.triggered.connect(self._save_project_as)

        self.action_templates = QAction(tr("menu.file.templates"), self)
        self.action_templates.triggered.connect(self._new_from_template)

        self.action_step_inventory = QAction(tr("step_inventory.menu"), self)
        self.action_step_inventory.triggered.connect(self._open_step_inventory)

        self.action_cad_preview = QAction(tr("cad_preview.menu"), self)
        self.action_cad_preview.triggered.connect(self._open_cad_preview)

        self.action_cad_registration = QAction(tr("cad_registration.menu"), self)
        self.action_cad_registration.triggered.connect(self._open_cad_registration)

        self.action_joint_concept = QAction(tr("joint_concept.menu"), self)
        self.action_joint_concept.triggered.connect(self._open_joint_concept)

        self.action_front_tubes = QAction(tr("front_tubes.menu"), self)
        self.action_front_tubes.triggered.connect(self._open_front_tubes)

        self.action_rear_tube = QAction(tr("rear_tube.menu"), self)
        self.action_rear_tube.triggered.connect(self._open_rear_tube)

        self.action_sketch_draft = QAction("Плоский эскиз (отдельный документ)", self)
        self.action_sketch_draft.triggered.connect(self._open_sketch_draft)

        self.action_new_scheme_assembly = QAction("Эксперимент: новая сборка рычага из деталей…", self)
        self.action_new_scheme_assembly.triggered.connect(self._new_scheme_arm_assembly)
        self.action_open_scheme_assembly = QAction("Эксперимент: открыть сборку рычага из деталей .kima…", self)
        self.action_open_scheme_assembly.triggered.connect(self._open_scheme_arm_assembly)
        self.action_scheme_arm_part = QAction("Прежний эксперимент: открыть схему и заготовку .kim…", self)
        self.action_scheme_arm_part.triggered.connect(self._open_scheme_arm_part)

        self.action_niva_arms = QAction(tr("niva_arms.menu"), self)
        self.action_niva_arms.triggered.connect(self._open_niva_arms)

        self.action_arm_concept = QAction(tr("arm_concept.menu"), self)
        self.action_arm_concept.triggered.connect(self._open_arm_concept)

        self.action_fixed_arm_skeleton = QAction("Эксперимент: скелет рычага по расчётному снимку…", self)
        self.action_fixed_arm_skeleton.triggered.connect(self._open_fixed_arm_skeleton)

        self.action_weldment = QAction(tr("weldment.menu"), self)
        self.action_weldment.triggered.connect(self._open_weldment)

        self.action_cad_settings = QAction(tr("cad_preview.settings_menu"), self)
        self.action_cad_settings.triggered.connect(self._open_cad_preview_settings)

        self.action_exit = QAction(tr("menu.file.exit"), self)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_exit.triggered.connect(self.close)

        self.action_undo = QAction(tr("menu.edit.undo"), self)
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self.controller.undo_last)

        self.action_redo = QAction(tr("menu.edit.redo"), self)
        self.action_redo.setShortcut(QKeySequence(QKeySequence.StandardKey.Redo))
        self.action_redo.triggered.connect(self.controller.redo_last)

        self.action_point_table = QAction(tr("point_table.menu"), self)
        self.action_point_table.triggered.connect(self._open_point_table)

        self.action_snapshot = QAction(tr("menu.edit.snapshot"), self)
        self.action_snapshot.triggered.connect(self._save_snapshot)

        self.action_compare_snapshot = QAction(tr("snapshot_compare.menu"), self)
        self.action_compare_snapshot.triggered.connect(self._compare_snapshot)

        self.action_restore_snapshot = QAction(tr("snapshot_restore.menu"), self)
        self.action_restore_snapshot.triggered.connect(self._restore_snapshot)

        self.action_theme = QAction(tr("menu.view.theme"), self)
        self.action_theme.setCheckable(True)
        self.action_theme.triggered.connect(self._toggle_theme)

        self.view_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for mode, key, shortcut in (
            ("front", "menu.view.front", "1"),
            ("side", "menu.view.side", "2"),
            ("top", "menu.view.top", "3"),
        ):
            action = QAction(tr(key), self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda _checked=False, m=mode: self._set_view_mode(m))
            group.addAction(action)
            self.view_actions[mode] = action
        self.view_actions["front"].setChecked(True)

        self.action_fit = QAction(tr("menu.view.fit"), self)
        self.action_fit.setShortcut(QKeySequence("F"))
        self.action_fit.triggered.connect(self._fit_active_view)

        self.action_zoom_in = QAction("+", self)
        self.action_zoom_in.setShortcut(QKeySequence("+"))
        self.action_zoom_in.triggered.connect(lambda: self._zoom_active_view(1.25))

        self.action_zoom_out = QAction("−", self)
        self.action_zoom_out.setShortcut(QKeySequence("-"))
        self.action_zoom_out.triggered.connect(lambda: self._zoom_active_view(1 / 1.25))

        self.action_analysis = QAction(tr("analysis.menu_action"), self)
        self.action_analysis.triggered.connect(self._open_analysis)

        self.action_antiroll = QAction(tr("antiroll_ui.menu_action"), self)
        self.action_antiroll.triggered.connect(self._open_antiroll)

        self.action_equilibrium = QAction(tr("equilibrium_ui.menu"), self)
        self.action_equilibrium.triggered.connect(self._open_equilibrium)

        self.action_events = QAction(tr("diagnostic_events.menu"), self)
        self.action_events.triggered.connect(self._open_events)

        self.action_log = QAction(tr("menu.help.log"), self)
        self.action_log.triggered.connect(self._open_log)

        self.action_manual = QAction(tr("menu.help.manual"), self)
        self.action_manual.triggered.connect(self._open_manual)

        self.action_about = QAction(tr("menu.help.about"), self)
        self.action_about.triggered.connect(self._show_about)

    # ------------------------------------------------------------------ меню
    def _build_menus(self) -> None:
        """Собирает меню приложения."""
        bar = self.menuBar()

        menu_file = bar.addMenu(tr("menu.file"))
        menu_file.addAction(self.action_new)
        menu_file.addAction(self.action_open)
        menu_file.addAction(self.action_step_inventory)
        menu_file.addAction(self.action_cad_preview)
        menu_file.addAction(self.action_cad_registration)
        menu_file.addAction(self.action_sketch_draft)
        menu_file.addAction(self.action_niva_arms)
        menu_file.addAction(self.action_joint_concept)
        menu_file.addAction(self.action_front_tubes)
        menu_file.addAction(self.action_rear_tube)
        menu_file.addAction(self.action_arm_concept)
        menu_file.addAction(self.action_fixed_arm_skeleton)
        menu_file.addAction(self.action_new_scheme_assembly)
        menu_file.addAction(self.action_open_scheme_assembly)
        menu_file.addAction(self.action_scheme_arm_part)
        menu_file.addAction(self.action_weldment)
        menu_file.addAction(self.action_recover_autosave)
        menu_file.addAction(self.action_allow_autosave)
        menu_file.addAction(self.action_templates)
        menu_file.addSeparator()
        menu_file.addAction(self.action_save)
        menu_file.addAction(self.action_save_as)
        menu_file.addSeparator()
        menu_file.addAction(self.action_exit)

        menu_edit = bar.addMenu(tr("menu.edit"))
        menu_edit.addAction(self.action_undo)
        menu_edit.addAction(self.action_redo)
        menu_edit.addSeparator()
        menu_edit.addAction(self.action_point_table)
        menu_edit.addSeparator()
        menu_edit.addAction(self.action_snapshot)
        menu_edit.addAction(self.action_restore_snapshot)
        menu_edit.addAction(self.action_compare_snapshot)

        menu_view = bar.addMenu(tr("menu.view"))
        menu_view.addAction(self.view_actions["front"])
        menu_view.addAction(self.view_actions["side"])
        menu_view.addAction(self.view_actions["top"])
        menu_view.addSeparator()
        menu_view.addAction(self.action_fit)
        menu_view.addAction(self.action_zoom_in)
        menu_view.addAction(self.action_zoom_out)
        menu_view.addSeparator()
        menu_view.addAction(self._tree_dock.toggleViewAction())
        menu_view.addAction(self._inspector_dock.toggleViewAction())
        menu_view.addAction(self._diagnostics_dock.toggleViewAction())
        menu_view.addSeparator()
        menu_view.addAction(self.action_theme)

        menu_settings = bar.addMenu(tr("menu.settings"))
        menu_settings.addAction(self.action_cad_settings)

        self.menu_axle = bar.addMenu(tr("menu.axle"))
        self._rebuild_axle_menu()

        menu_analysis = bar.addMenu(tr("analysis.menu"))
        menu_analysis.addAction(self.action_analysis)
        menu_analysis.addAction(self.action_antiroll)
        menu_analysis.addAction(self.action_equilibrium)

        menu_help = bar.addMenu(tr("menu.help"))
        menu_help.addAction(self.action_manual)
        menu_help.addAction(self.action_events)
        menu_help.addAction(self.action_log)
        menu_help.addSeparator()
        menu_help.addAction(self.action_about)

    def _rebuild_axle_menu(self) -> None:
        """Пересобирает пункты выбора типа подвески для обеих осей."""
        self.menu_axle.clear()
        for role, title_key in (("front", "menu.axle.front_type"), ("rear", "menu.axle.rear_type")):
            submenu = self.menu_axle.addMenu(tr(title_key))
            group = QActionGroup(self)
            group.setExclusive(True)
            current = self.controller.project.axle(role).type_code
            for code in types_for_role(role):
                action = QAction(tr(f"type.{code}.name"), self)
                action.setCheckable(True)
                action.setChecked(code == current)
                action.triggered.connect(lambda _checked=False, r=role, c=code: self._change_axle_type(r, c))
                group.addAction(action)
                submenu.addAction(action)

    # ------------------------------------------------------------------ панель инструментов
    def _build_toolbar(self) -> None:
        """Панель быстрых действий, единицы измерения и тема."""
        toolbar = QToolBar(tr("menu.view"), self)
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        toolbar.addAction(self.action_new)
        toolbar.addAction(self.action_open)
        toolbar.addAction(self.action_save)
        toolbar.addSeparator()
        toolbar.addAction(self.action_undo)
        toolbar.addAction(self.action_redo)
        toolbar.addSeparator()
        toolbar.addAction(self.view_actions["front"])
        toolbar.addAction(self.view_actions["side"])
        toolbar.addAction(self.view_actions["top"])
        toolbar.addSeparator()

        self._length_combo = QComboBox(toolbar)
        self._length_combo.setFixedWidth(64)
        self._length_combo.setToolTip(tr("menu.units.length"))
        for code in LENGTH_UNITS:
            self._length_combo.addItem(tr(f"unit.length.{code}"), code)
        self._length_combo.currentIndexChanged.connect(self._on_units_changed)
        toolbar.addWidget(self._length_combo)

        self._angle_combo = QComboBox(toolbar)
        self._angle_combo.setFixedWidth(64)
        self._angle_combo.setToolTip(tr("menu.units.angle"))
        for code in ("deg", "degmin"):
            self._angle_combo.addItem(tr(f"unit.angle.{code}"), code)
        self._angle_combo.currentIndexChanged.connect(self._on_units_changed)
        toolbar.addWidget(self._angle_combo)

        self._rate_combo = QComboBox(toolbar)
        self._rate_combo.setFixedWidth(84)
        self._rate_combo.setToolTip(tr("menu.units.rate"))
        for code in RATE_UNITS:
            self._rate_combo.addItem(tr(f"unit.rate.{code}"), code)
        self._rate_combo.currentIndexChanged.connect(self._on_units_changed)
        toolbar.addWidget(self._rate_combo)

        toolbar.addSeparator()
        toolbar.addAction(self.action_theme)
        self.addToolBar(toolbar)
        self._toolbar = toolbar

    # ------------------------------------------------------------------ статусная строка
    def _build_statusbar(self) -> None:
        """Строка состояния с проектом, единицами и подсказками."""
        self._status_project = QLabel(self)
        self._status_selection = QLabel(self)
        self._status_units = QLabel(self)
        self._status_autosave = QLabel(self)
        self._status_autosave.setToolTip(tr("autosave.existing_paused"))
        status = self.statusBar()
        status.addWidget(self._status_selection, 1)
        status.addPermanentWidget(self._status_autosave)
        status.addPermanentWidget(self._status_project)
        status.addPermanentWidget(self._status_units)
        self.controller.statusMessage.connect(lambda key: status.showMessage(tr(key), 4000))

    # ------------------------------------------------------------------ настройки
    def _restore_settings(self) -> None:
        """Восстанавливает единицы, тему и раскладку окна."""
        units = UnitSettings(
            length=str(self._settings.value("units/length", "mm")),
            angle=str(self._settings.value("units/angle", "deg")),
            rate=str(self._settings.value("units/rate", "N_mm")),
        )
        self.controller.set_units(units)
        self._sync_unit_combos(units)
        self.controller.auto_extend_slider = str(self._settings.value("slider/auto_extend", "true")) != "false"

        geometry = self._settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self._settings.value("window/state")
        if state is not None:
            self.restoreState(state)

    def _sync_unit_combos(self, units: UnitSettings) -> None:
        """Приводит выпадающие списки единиц в соответствие с настройками."""
        for combo, value in (
            (self._length_combo, units.length),
            (self._angle_combo, units.angle),
            (self._rate_combo, units.rate),
        ):
            index = combo.findData(value)
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)

    def _save_settings(self) -> None:
        """Сохраняет настройки окна в файл."""
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.setValue("view/theme", self._theme)
        units = self.controller.units
        self._settings.setValue("units/length", units.length)
        self._settings.setValue("units/angle", units.angle)
        self._settings.setValue("units/rate", units.rate)
        self._settings.setValue("slider/auto_extend", "true" if self.controller.auto_extend_slider else "false")
        self._settings.sync()

    # ------------------------------------------------------------------ связи
    def _connect_controller(self) -> None:
        """Подписывается на сигналы контроллера."""
        self.controller.selectionChanged.connect(self._on_selection_changed)
        self.controller.modelChanged.connect(self._on_model_changed)
        self.controller.projectReplaced.connect(self._on_project_replaced)
        self.controller.dirtyChanged.connect(lambda _dirty: self._update_title())
        self.controller.unitsChanged.connect(self._update_status)
        self.controller.autosaveProtectionChanged.connect(self._update_title)
        self._tree.selectionRequested.connect(self.controller.select)
        self._diagnostics.issueSelected.connect(self.controller.select)

    # ------------------------------------------------------------------ реакции
    def _on_selection_changed(self, selection: Selection | None) -> None:
        """Обновляет статусную строку при выборе элемента."""
        self._update_status()

    def _on_model_changed(self) -> None:
        """Обновляет действия, заголовок и статус после правки модели."""
        self._refresh_undo_actions()
        self._update_title()
        self._update_status()

    def _on_project_replaced(self) -> None:
        """Полная перезагрузка структуры (новый проект, смена типа, файл)."""
        self._refresh_undo_actions()
        self._rebuild_axle_menu()
        self._update_title()
        self._update_status()

    def _refresh_undo_actions(self) -> None:
        """Включает/выключает «Отменить» и «Повторить» с подписью шага."""
        stack = self.controller.undo
        self.action_undo.setEnabled(stack.can_undo)
        self.action_redo.setEnabled(stack.can_redo)
        label = tr(stack.undo_label_key())
        self.action_undo.setText(tr("undo.action.undo", label=label))
        self.action_redo.setText(tr("undo.action.redo", label=tr(stack.redo_label_key())))

    def _update_title(self) -> None:
        """Заголовок окна и метка проекта в статусной строке."""
        project = self.controller.project
        name = project.meta.name.strip() or tr("status.project_untitled").split(": ", 1)[-1]
        marker = " •" if self.controller.dirty else ""
        recovery = f" — {tr('autosave.paused_title')}" if self.controller.recovery_pending or self.controller.autosave_waiting else ""
        self.setWindowTitle(f"{APP_NAME} — {name}{marker}{recovery}")
        self._status_autosave.setText(tr("autosave.paused_title") if recovery else "")
        self._status_autosave.setToolTip(tr("autosave.paused") if self.controller.recovery_pending else
                                         tr("autosave.busy") if self.controller.autosave_busy else
                                         tr("autosave.existing_paused"))
        self._status_project.setText(tr("status.project", name=name))
        self._status_project.setToolTip(project.path or "")

    def _update_status(self) -> None:
        """Обновляет информационные поля статусной строки."""
        units = self.controller.units
        self._status_units.setText(
            tr(
                "status.units",
                length=tr("unit.length." + units.length),
                angle=tr("unit.angle." + units.angle),
                rate=tr("unit.rate." + units.rate),
            )
        )
        canvas = self._current_canvas() if hasattr(self, "_canvases") else None
        if self._tabs.currentWidget() is self._vehicle_view:
            self._status_selection.setText(tr("vehicle_schematic.title"))
        elif canvas is not None:
            mode = canvas.view_mode()
            self._status_selection.setText(
                tr("status.canvas_hint") + "   ·   " + tr("status.view", view=tr(f"view.{mode}"))
            )
        selection = self.controller.selection
        if selection is not None:
            self._status_selection.setText(self._selection_text(selection))

    def _selection_text(self, selection: Selection) -> str:
        """Текст выбранного элемента для статусной строки."""
        project = self.controller.project
        if selection.kind == "point" and selection.role:
            axle = project.axle(selection.role)
            point = axle.hardpoints.get(selection.code)
            spec = axle.spec.point(selection.code)
            if point is None or spec is None:
                return ""
            units = self.controller.units
            return tr(
                "status.point_selected",
                name=tr(spec.name_key),
                x=units.display(point.x, UnitKind.LENGTH),
                y=units.display(point.y, UnitKind.LENGTH),
                z=units.display(point.z, UnitKind.LENGTH),
            )
        if selection.kind == "axle" and selection.role:
            return tr(f"tree.{selection.role}")
        if selection.kind == "link" and selection.role:
            axle = project.axle(selection.role)
            link_spec = axle.spec.link(selection.code)
            if link_spec is not None:
                units = self.controller.units
                length = units.display(axle.link_length(selection.code), UnitKind.LENGTH)
                return f"{tr(link_spec.name_key)}: {length} {tr('unit.length.' + units.length)}"
        return ""

    def _open_point_table(self) -> None:
        dialog = PointTableDialog(self.controller, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _open_analysis(self) -> None:
        """Показывает экспериментальный расчёт выбранной стороны оси."""
        dialog = AnalysisDialog(self.controller, self)
        dialog.exec()
        dialog.deleteLater()

    def _open_antiroll(self) -> None:
        """Показывает отдельную идеализированную модель стабилизатора."""
        dialog = AntiRollDialog(self.controller, self)
        dialog.exec()
        dialog.deleteLater()

    def _open_equilibrium(self) -> None:
        """Открывает экспериментальный баланс одной стороны."""
        dialog = EquilibriumDialog(self.controller, self)
        dialog.exec()
        dialog.deleteLater()

    # ------------------------------------------------------------------ файлы
    def _new_project(self) -> None:
        """Новый пустой проект."""
        if self._confirm_discard_changes():
            self.controller.new_project()
            self._show_workspace()

    def _new_from_template(self) -> None:
        """Создать проект из шаблона."""
        if not self._confirm_discard_changes():
            return
        dialog = TemplateDialog(self)
        if dialog.exec():
            project = dialog.selected_project()
            if project is not None:
                self.controller.new_project(project=project)
                self._tabs.setCurrentWidget(self._vehicle_view)
                self._show_workspace()
            elif dialog.selected_key():
                self.controller.new_project(dialog.selected_key())
                self._tabs.setCurrentWidget(self._vehicle_view)
                self._show_workspace()

    def _open_project(self) -> None:
        """Открыть файл проекта."""
        if not self._confirm_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dialog.open_project"), "", tr("dialog.filter.project") + ";;" + tr("dialog.filter.all")
        )
        if not path:
            return
        try:
            self.controller.open_project(path)
        except ProjectIOError as error:
            self._show_error(error)
            return
        self._show_workspace()

    def _recover_autosave(self) -> None:
        """Восстанавливает копию по явному запросу, не записывая исходный файл."""
        running = self._autosave_timer.isActive()
        self._autosave_timer.stop()
        try:
            answer = QMessageBox.question(
                self, tr("autosave.recover_title"), tr("autosave.recover_notice"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                project, source = self.controller.read_autosave()
            except ProjectIOError as error:
                self._show_error(error)
                return
            with self.controller.guard_autosave(source):
                if not self._confirm_discard_changes():
                    return
                self.controller.recover_autosave(project, source)
                self._show_workspace()
        finally:
            if running:
                self._autosave_timer.start()

    def _allow_autosave_overwrite(self) -> None:
        """Подтверждение относится только к копии, прочитанной до вопроса."""
        if self.controller.recovery_pending:
            QMessageBox.information(self, tr("autosave.allow_title"), tr("autosave.paused"))
            return
        try:
            expected = self.controller.prepare_autosave_overwrite()
        except (OSError, RuntimeError):
            self.controller.check_autosave_protection()
            QMessageBox.warning(self, tr("autosave.allow_title"), tr("autosave.allow_error"))
            return
        if expected is None:
            self.controller.check_autosave_protection()
            QMessageBox.information(self, tr("autosave.allow_title"), tr("autosave.allow_absent"))
            return
        answer = QMessageBox.question(self, tr("autosave.allow_title"), tr("autosave.allow_notice"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.allow_autosave_overwrite(expected)
        except (OSError, RuntimeError):
            self.controller.check_autosave_protection()
            QMessageBox.warning(self, tr("autosave.allow_title"), tr("autosave.allow_error"))
            return
        self.statusBar().showMessage(tr("autosave.allow_done"), 4000)

    def _save_project(self) -> bool:
        """Сохранить текущий проект."""
        if not self.controller.project.path:
            return self._save_project_as()
        try:
            self.controller.save_project()
        except ProjectIOError as error:
            self._show_error(error)
            return False
        return True

    def _save_project_as(self) -> bool:
        """Сохранить проект под новым именем."""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dialog.save_project"), "", tr("dialog.filter.project")
        )
        if not path:
            return False
        try:
            self.controller.save_project(path)
        except ProjectIOError as error:
            self._show_error(error)
            return False
        self._update_title()
        return True

    def _save_snapshot(self) -> None:
        """Сохраняет снимок настройки в проект."""
        dialog = SnapshotDialog(self.controller.project.meta.name, self)
        if dialog.exec() and dialog.name():
            self.controller.add_snapshot(dialog.name())

    def _compare_snapshot(self) -> None:
        """Сравнивает снимок с текущей геометрией без восстановления."""
        dialog = SnapshotCompareDialog(self.controller, self)
        try:
            if dialog.exec() and dialog.selection is not None:
                self._show_workspace()
                self.controller.select(dialog.selection)
        finally:
            dialog.deleteLater()

    def _restore_snapshot(self) -> None:
        """Восстанавливает выбранный снимок без сохранения в файл."""
        dialog = RestoreSnapshotDialog(self.controller.project, self)
        if not dialog.exec():
            return
        try:
            self.controller.restore_snapshot(dialog.selected_index())
        except ValueError:
            QMessageBox.warning(self, tr("snapshot_restore.title"), tr("snapshot_restore.invalid"))
            return
        self._show_workspace()

    def _show_error(self, error: ProjectIOError) -> None:
        """Показывает понятное сообщение об ошибке с кнопкой журнала."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(tr("dialog.error.title"))
        box.setText(tr(error.message_key, **error.params))
        box.setInformativeText(tr("dialog.error.hint"))
        open_log = box.addButton(tr("menu.help.log"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("dialog.ok"), QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_log:
            self._open_log()

    # ------------------------------------------------------------------ вид
    def _fit_active_view(self) -> None:
        if self._tabs.currentWidget() is self._vehicle_view:
            self._vehicle_view.preview.reset_camera()
        else:
            self._current_canvas().fit_to_view()

    def _zoom_active_view(self, factor: float) -> None:
        if self._tabs.currentWidget() is self._vehicle_view:
            self._vehicle_view.zoom_by(factor)
        else:
            self._current_canvas().zoom_by(factor)

    def _set_view_mode(self, mode: str) -> None:
        """Переключает проекцию на всех вкладках и в меню."""
        if self._tabs.currentWidget() is self._vehicle_view:
            self._tabs.setCurrentWidget(self._canvases["both"])
        self._syncing_view = True
        try:
            for canvas in self._canvases.values():
                canvas.set_view_mode(mode)
            self.view_actions[mode].setChecked(True)
        finally:
            self._syncing_view = False
        self._update_status()

    def _on_canvas_view_changed(self, mode: str) -> None:
        """Синхронизирует вид между вкладками (без рекурсии)."""
        if self._syncing_view:
            return
        self._set_view_mode(mode)

    def _toggle_theme(self) -> None:
        """Переключает тёмную и светлую темы."""
        self._apply_theme("light" if self._theme == "dark" else "dark")

    def _apply_theme(self, theme: str, initial: bool = False) -> None:
        """Применяет тему к приложению и обновляет схему."""
        self._theme = theme if theme in THEMES else "dark"
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, self._theme)
        self.controller.project.view.theme = self._theme
        self.action_theme.setChecked(self._theme == "light")
        self.action_theme.setText(tr(f"view.theme.{self._theme}"))
        for canvas in getattr(self, "_canvases", {}).values():
            canvas.update()
        if not initial:
            self._save_settings()
        self._update_status()

    def _on_units_changed(self) -> None:
        """Меняет единицы отображения."""
        units = UnitSettings(
            length=str(self._length_combo.currentData()),
            angle=str(self._angle_combo.currentData()),
            rate=str(self._rate_combo.currentData()),
        )
        self.controller.set_units(units)
        self._save_settings()

    def _change_axle_type(self, role: str, type_code: str) -> None:
        """Смена типа подвески из меню."""
        self.controller.set_axle_type(role, type_code)
        self._rebuild_axle_menu()

    def _on_autosave(self) -> None:
        """Автосохранение раз в минуту при наличии изменений."""
        if self.controller.dirty:
            self.controller.autosave()

    # ------------------------------------------------------------------ справка
    def _show_text_file(self, path: Path, title: str) -> None:
        """Открывает локальный текст в нативном окне, без внешних приложений."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            QMessageBox.warning(self, title, tr("log.failed", path=str(path)))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        content = QPlainTextEdit(dialog)
        content.setReadOnly(True)
        content.setPlainText(text)
        layout.addWidget(content)
        dialog.exec()

    def _open_log(self) -> None:
        """Показывает журнал в нативном окне."""
        self._show_text_file(log_file_path(), tr("menu.help.log"))

    def _open_events(self) -> None:
        """Отдельный журнал основных событий, без данных проекта."""
        try:
            path = diagnostic_log_path()
        except OSError:
            QMessageBox.warning(self, tr("diagnostic_events.menu"), tr("diagnostic_events.unavailable"))
            return
        self._show_text_file(path, tr("diagnostic_events.menu"))

    def _open_manual(self) -> None:
        """Показывает руководство из комплекта ресурсов."""
        from ..config import resources_dir

        self._show_text_file(resources_dir() / "help" / "user_manual_ru.txt", tr("menu.help.manual"))

    def _show_about(self) -> None:
        """Окно «О программе» с версией и дисклеймером."""
        box = QMessageBox(self)
        box.setWindowTitle(tr("app.about_title"))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(tr("app.about", version=__version__))
        box.setInformativeText(tr("app.disclaimer_full"))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    # ------------------------------------------------------------------ закрытие
    def _confirm_discard_changes(self) -> bool:
        """Предлагает сохранить изменения перед заменой или закрытием проекта."""
        if not self.controller.dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("dialog.unsaved.title"))
        box.setText(tr("dialog.unsaved.text"))
        save_button = box.addButton(tr("dialog.yes"), QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton(tr("dialog.no"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("dialog.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save_button:
            return self._save_project()
        return box.clickedButton() is discard_button

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Спрашивает о сохранении и запоминает раскладку окна."""
        if not self._confirm_discard_changes():
            event.ignore()
            return
        if self._weldment_dialog is not None and not self._weldment_dialog.confirm_close():
            event.ignore()
            return
        if self._fixed_arm_skeleton_dialog is not None and not self._fixed_arm_skeleton_dialog.confirm_close():
            event.ignore()
            return
        if self._joint_concept_dialog is not None and not self._joint_concept_dialog.confirm_close():
            event.ignore()
            return
        if self._front_tubes_dialog is not None and not self._front_tubes_dialog.confirm_close():
            event.ignore()
            return
        if self._rear_tube_dialog is not None and not self._rear_tube_dialog.confirm_close():
            event.ignore()
            return
        arm_stopped = self._arm_concept_dialog is None or self._arm_concept_dialog.shutdown()
        fixed_arm_stopped = self._fixed_arm_skeleton_dialog is None or self._fixed_arm_skeleton_dialog.shutdown()
        weldment_stopped = self._weldment_dialog is None or self._weldment_dialog.shutdown()
        rear_stopped = self._rear_tube_dialog is None or self._rear_tube_dialog.shutdown()
        front_stopped = self._front_tubes_dialog is None or self._front_tubes_dialog.shutdown()
        joint_stopped = self._joint_concept_dialog is None or self._joint_concept_dialog.shutdown()
        if (not arm_stopped or not fixed_arm_stopped or not weldment_stopped or not rear_stopped or
                not front_stopped or not joint_stopped):
            event.ignore()
            return
        self._save_settings()
        super().closeEvent(event)

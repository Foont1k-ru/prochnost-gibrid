"""Ограниченная автоматическая проверка собранного приложения, не UI-валидация."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSettings, QTimer

from .app import create_application
from .config import diagnostic_log_path, log_file_path, resources_dir
from .core.equilibrium import SpringEquilibrium
from .core.sweep_plot import ANTIROLL_METRICS, PLOT_METRICS
from .export.csv_report import write_csv_report
from .i18n import tr
from .model.project_io import load_project
from .model.templates import list_templates
from .ui.analysis_dialog import AnalysisDialog
from .ui.antiroll_dialog import AntiRollDialog
from .ui.cad_registration_dialog import CadRegistrationDialog
from .ui.cad_registration_overlay_dialog import CadRegistrationOverlayDialog
from .ui.damper_conversion_dialog import DamperConversionDialog
from .ui.equilibrium_dialog import EquilibriumDialog
from .ui.equilibrium_path_dialog import EquilibriumPathDialog
from .ui.main_window import MainWindow
from .ui.point_import_dialog import PointImportDialog
from .ui.point_table_dialog import PointTableDialog
from .ui.snapshot_compare_dialog import SnapshotCompareDialog
from .ui.snapshot_overlay_dialog import SnapshotOverlayDialog
from .ui.spring_rate_dialog import SpringRateDialog
from .ui.table_export import make_plot_report


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_startup_check() -> None:
    """Настоящий main с циклом Qt; CI должен изолировать APPDATA до вызова."""
    from . import app as application

    original = application.create_application
    opened: list[bool] = []

    def create_and_schedule(argv: list[str] | None = None):
        app = original(argv)

        def inspect_and_quit() -> None:
            opened.append(any(isinstance(widget, MainWindow) and widget.isVisible() for widget in app.topLevelWidgets()))
            app.quit()

        QTimer.singleShot(100, inspect_and_quit)
        return app

    application.create_application = create_and_schedule
    try:
        exit_code = application.main([])
        _require(exit_code == 0 and opened == [True], "Обычный запуск не открыл главное окно")
        _require("Запуск" in log_file_path().read_text(encoding="utf-8"), "Нет записи о запуске в журнале")
        events = diagnostic_log_path().read_text(encoding="utf-8")
        _require('"event":"session.start"' in events and '"event":"session.end"' in events,
                 "Журнал событий запуска недоступен")
    finally:
        application.create_application = original


def run_cad_check() -> None:
    """Искусственный STEP и отдельный процесс именно собранного приложения."""
    import numpy as np
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.GC import GC_MakeSegment
    from OCP.Geom import Geom_SurfaceOfRevolution
    from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer
    from OCP.TopoDS import TopoDS_Face

    from .core.cad_assembly_projection_job import CadAssemblyProjectionJob
    from .core.cad_recovery import recover_revolution_face
    from .core.cad_transport import CadJob
    from .export.cad_assembly_svg import write_new_projection_svg
    from .model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint
    from .model.entities import Project
    from .model.scheme_arm_assembly import make_plate, make_scheme_arm_assembly, set_assembly_plate

    assembly = make_scheme_arm_assembly(Project.create_default(), 12., 2.,
                                        {'axis': 'x', 'outer_radius_mm': 14.,
                                         'bore_radius_mm': 7., 'length_mm': 24.})
    assembly = set_assembly_plate(assembly, make_plate(40., 20., 3., 5.),
                                  {'normal': 'z', 'offset_mm': [0., 0., 0.]})
    projection = CadAssemblyProjectionJob().run(assembly)
    _require(len(projection.views) == 3 and all(len(lines) > 4 for lines in projection.views) and
             all(projection.bounds_mm[i] < projection.bounds_mm[i + 3] for i in range(3)),
             "В собранном приложении недоступны CAD-проекции предварительной сборки")

    # Искусственная поверхность с единственным круговым контуром, как отдельный
    # тест наличия кода восстановления в собранной программе.
    axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0))
    profile = GC_MakeSegment(gp_Pnt(0, 5, 0), gp_Pnt(2, 0, 0)).Value()
    surface = Geom_SurfaceOfRevolution(profile, axis)
    circle = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), 2)
    wire = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire()
    face = TopoDS_Face()
    builder = BRep_Builder()
    builder.MakeFace(face, surface, 1e-7)
    builder.Add(face, wire)
    _require(recover_revolution_face(face, 10.) is not None, "Восстановление тестовой поверхности недоступно")

    with TemporaryDirectory(prefix="suspensionlab-cad-check-") as directory:
        svg = Path(directory) / "виды.svg"
        write_new_projection_svg(svg, projection, assembly, dimensions=True)
        svg_text = svg.read_text(encoding='utf-8')
        _require('НЕ ПРОИЗВОДСТВЕННЫЙ ЧЕРТЁЖ' in svg_text and
                 assembly_snapshot_fingerprint(assembly) in svg_text,
                 "В собранном приложении недоступен SVG предварительных CAD-видов")
        path = Path(directory) / "fixture.step"
        unicode_path = Path(directory) / "проверка сборки.step"
        writer = STEPControl_Writer()
        _require(writer.Transfer(BRepPrimAPI_MakeBox(2., 3., 5.).Shape(),
                                 STEPControl_StepModelType.STEPControl_AsIs) == IFSelect_ReturnStatus.IFSelect_RetDone,
                 "Не удалось подготовить тестовый STEP")
        _require(writer.Write(str(path)) == IFSelect_ReturnStatus.IFSelect_RetDone,
                 "Не удалось записать тестовый STEP")
        path.rename(unicode_path)
        meshes = [CadJob().run(unicode_path, deviation, timeout=90) for deviation in (10., 2., 0.2)]
        _require(all(item.face_count == 6 and len(item.triangles) >= 12 for item in meshes),
                 "Режимы детализации STEP недоступны")
        mesh = meshes[1]
        vertices = mesh.triangles.reshape(-1, 3)
        _require(mesh.face_count == 6 and len(mesh.triangles) >= 12 and
                 np.allclose(vertices.min(axis=0), (0., 0., 0.), atol=1e-6, rtol=0) and
                 np.allclose(vertices.max(axis=0), (2., 3., 5.), atol=1e-6, rtol=0),
                 "Неверная сетка тестового STEP")
        _require(mesh.triangle_parts is not None and len(mesh.part_names) > 1 and
                 len(np.unique(mesh.triangle_parts)) == 1 and mesh.triangle_parts[0] != 0 and
                 len(mesh.isolated(int(mesh.triangle_parts[0])).triangles) == len(mesh.triangles),
                 "Неверные группы деталей тестового STEP")
        _require(mesh.triangle_instances is not None and len(np.unique(mesh.triangle_instances)) == 1 and
                 mesh.triangle_instances[0] != 0 and
                 len(mesh.isolated_instance(int(mesh.triangle_instances[0])).triangles) == len(mesh.triangles),
                 "Неверные экземпляры тестового STEP")

        # Замороженный exe должен запускать отдельный CAD-процесс и создавать
        # аналитическое STEP-тело, которое затем читается существующим CAD worker.
        from .core.sketch_solid_job import SketchSolidJob
        from .model.sketch_draft import make_entity, rectangle_entities
        from .model.sketch_io import SketchDocument

        solid_path = Path(directory) / "тело из эскиза.step"
        doc = SketchDocument("XZ", 12., rectangle_entities((0., 0.), (100., 50.)))
        SketchSolidJob().run(doc, 5., solid_path)
        solid_mesh = CadJob().run(solid_path, 2., timeout=90)
        solid_vertices = solid_mesh.triangles.reshape(-1, 3)
        _require(solid_mesh.face_count == 6 and
                 np.allclose(solid_vertices.min(axis=0), (0., 12., 0.), atol=1e-6, rtol=0) and
                 np.allclose(solid_vertices.max(axis=0), (100., 17., 50.), atol=1e-6, rtol=0),
                 "В собранном приложении недоступно точное STEP-тело из эскиза")

        holes_path = Path(directory) / "тело с отверстием.step"
        hole = make_entity("circle", (25., 25.), (35., 25.))
        hole_doc = SketchDocument("XZ", 12., (*doc.entities, hole))
        SketchSolidJob().run(hole_doc, 5., holes_path, direction="symmetric")
        holes_mesh = CadJob().run(holes_path, 0.2, timeout=90)
        _require(holes_mesh.face_count == 7 and holes_mesh.skipped_faces == 0 and
                 np.allclose(holes_mesh.triangles.reshape(-1, 3).min(axis=0), (0., 9.5, 0.), atol=1e-6, rtol=0) and
                 np.allclose(holes_mesh.triangles.reshape(-1, 3).max(axis=0), (100., 14.5, 50.), atol=1e-6, rtol=0),
                 "В собранном приложении недоступно симметричное STEP-тело со сквозным отверстием")

        blind_path = Path(directory) / "тело с глухим отверстием.step"
        second_hole = make_entity("circle", (70., 25.), (75., 25.))
        mixed_doc = SketchDocument("XZ", 12., (*hole_doc.entities, second_hole))
        SketchSolidJob().run(mixed_doc, 5., blind_path, direction="negative",
                             hole_overrides=((4, 2., "negative"),))
        blind_mesh = CadJob().run(blind_path, 0.2, timeout=90)
        triangles = blind_mesh.triangles
        floor = np.all(np.abs(triangles[:, :, 1] - 9.) < 1e-6, axis=1)
        _require(blind_mesh.face_count == 9 and blind_mesh.skipped_faces == 0 and bool(np.any(floor)) and
                 np.allclose(triangles.reshape(-1, 3).min(axis=0), (0., 7., 0.), atol=1e-6, rtol=0) and
                 np.allclose(triangles.reshape(-1, 3).max(axis=0), (100., 12., 50.), atol=1e-6, rtol=0),
                 "В собранном приложении недоступно STEP-тело с глухим и сквозным отверстиями")

    # 3D труб проверяется именно из собранного приложения, включая повторный
    # запуск замороженного исполняемого файла как CAD-процесса и Qt-отрисовку.
    from time import monotonic, sleep

    from .ui.arm_concept_dialog import ArmConceptDialog
    from .ui.controller import AppController

    app = create_application([])
    controller = AppController()
    for code, xyz in {
        "lca_f_in": (0., 0., 0.), "lca_r_in": (100., 0., 0.), "lbj": (0., 100., 0.),
    }.items():
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    dialog = ArmConceptDialog(controller)
    dialog.show()
    dialog._tabs.setCurrentIndex(1)
    panel = dialog._three_d

    def wait_for_mesh():
        deadline = monotonic() + 45
        while panel._view.mesh is None and monotonic() < deadline:
            app.processEvents()
            sleep(0.02)
        _require(panel._view.mesh is not None, "3D труб в собранном приложении не построен: " + panel._status.text())
        return panel._view.mesh

    try:
        panel._enable.setChecked(True)
        first = wait_for_mesh()
        assert first is not None
        _require(dialog._save_assembly.isEnabled() and not panel._view.grab().isNull(),
                 "3D труб в собранном приложении не отображается")
        dialog._radius.setValue(20.)
        _require(panel._view.mesh is None and not dialog._save_assembly.isEnabled(),
                 "Старая 3D-модель не очищена после изменения размера")
        second = wait_for_mesh()
        assert second is not None
        _require(np.ptp(second.triangles[:, :, 2]) > np.ptp(first.triangles[:, :, 2]) + 10,
                 "3D труб не перестроен по новому размеру")
        for field, value in zip(dialog._bend_fields["front"], ("100", "0", "0", "30"), strict=True):
            field.setText(value)
        dialog._bend_checks["front"].setChecked(True)
        _require(panel._view.mesh is None and not dialog._save_assembly.isEnabled(),
                 "Старая сетка не очищена при задании изгиба")
        curved = wait_for_mesh()
        _require(curved is not None and dialog._candidate is not None and
                 dialog._candidate["version"] == "0.3" and
                 dialog._candidate["parts"][0]["geometry"]["kind"] == "prototype_arm_bent_tube",
                 "В собранном приложении недоступен гнутый 3D-черновик")
    finally:
        dialog.close()
        app.processEvents()

    # Проверка нового снимка 0.4 тем же изолированным процессом собранного exe.
    from .core.cad_weldment_job import WeldmentCadJob
    from .model.entities import Project
    from .model.rear_tube import make_rear_tube

    project = Project.create_default()
    project.rear.type_code, project.rear.layout = "live_axle_coil", "4link_panhard"
    project.rear.ensure_points(overwrite=True)
    for code, xyz in {"ll_in_l": (0., 0., 0.), "ll_out_l": (100., 100., 0.)}.items():
        point = project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    for bend in (None, {"vertex_mm": [100., 0., 0.], "radius_mm": 20.}):
        document = make_rear_tube(project, "rear_lower_left", 10., 2., bend)
        result = WeldmentCadJob().run(document)
        _require(len(result.triangles) > 0 and result.skipped_faces == result.recovered_faces == 0,
                 "В собранном приложении не построена труба задней тяги")

    # Проверяем и пользовательский путь повторного открытия в упакованном Qt.
    from unittest.mock import patch

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from .model.kim_format import read_document, write_document
    from .ui.rear_tube_dialog import RearTubeDialog

    controller = AppController()
    controller.set_axle_type("rear", "live_axle_coil")
    for code, xyz in {"ll_in_l": (0., 0., 0.), "ll_out_l": (100., 100., 0.)}.items():
        point = controller.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    with TemporaryDirectory(prefix="suspensionlab-rear-reopen-") as directory:
        source, target = Path(directory) / "source.kima", Path(directory) / "copy.kima"
        document = make_rear_tube(controller.project, "rear_lower_left", 10., 2.,
                                  {"vertex_mm": [100., 0., 0.], "radius_mm": 20.})
        write_document(source, "assembly", document, overwrite=False)
        original = source.read_bytes()
        rear_dialog = RearTubeDialog(controller)
        rear_dialog.show()
        panel = rear_dialog._three_d
        try:
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")), \
                    patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
                rear_dialog._open_file()
            _require(rear_dialog._source == document and not rear_dialog._active,
                     "Сохранённая задняя тяга не открылась")
            rear_dialog._start_preview()
            panel._enable.setChecked(True)
            wait_for_mesh()
            rear_dialog._fields[3].setText("25")
            _require(panel._view.mesh is None and not rear_dialog._save.isEnabled(),
                     "Старая сетка задней тяги не очищена")
            wait_for_mesh()
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
                    patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
                rear_dialog._save_copy()
            _require(target.exists() and read_document(target, "assembly")["bend"]["radius_mm"] == 25 and
                     source.read_bytes() == original, "Копия задней тяги не сохранена или исходник изменён")
        finally:
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                rear_dialog.close()
                app.processEvents()


    # Компоновки новых форматов проверяем во вложенном CAD-процессе frozen exe,
    # а не только через импорт в обычном Python. Оси узлов условны.
    from .model.front_joint_layout import make_front_joint_layout
    from .model.front_pair_snapshot import make_front_pair_snapshot
    from .model.front_same_pair import make_front_same_pair
    from .model.front_tube_arm import make_front_tube_arm
    from .model.joint_concept import DEFAULTS, make_joint_concept
    from .model.rear_joint_layout import make_rear_joint_layout
    from .model.rear_pair_snapshot import make_rear_pair_snapshot
    from .ui.front_tubes_dialog import FrontTubesDialog

    controller = AppController()
    for code, xyz in {"uca_f_in": (0., 0., 0.), "uca_r_in": (0., -100., 0.),
                      "ubj": (100., 100., 0.)}.items():
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    arm = make_front_tube_arm(controller.project, "front_upper_left", 10., 2.)
    ball = make_joint_concept("ball", DEFAULTS["ball"])
    bushing = make_joint_concept("bushing", DEFAULTS["bushing"])
    layouts = [make_front_joint_layout(make_front_pair_snapshot(arm), ball, bushing),
               make_front_joint_layout(make_front_same_pair(arm), ball, bushing),
               make_front_joint_layout(make_front_pair_snapshot(arm), ball, bushing, axis="x"),
               make_front_joint_layout(make_front_same_pair(arm), ball, bushing, axis="x")]
    rear = Project.create_default()
    rear.rear.type_code, rear.rear.layout = "live_axle_coil", "4link_panhard"
    rear.rear.ensure_points(overwrite=True)
    for code, xyz in {"ll_in_l": (0., 0., 0.), "ll_out_l": (100., 100., 0.),
                      "ll_in_r": (0., 0., 0.), "ll_out_r": (100., -100., 0.)}.items():
        point = rear.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    rear_pair = make_rear_pair_snapshot(make_rear_tube(rear, "rear_lower_left", 10., 2.), "mirror")
    layouts.append(make_rear_joint_layout(rear_pair, bushing, "x"))
    for layout in layouts:
        result = WeldmentCadJob().run(layout)
        _require(len(result.triangles) > 0 and result.skipped_faces == result.recovered_faces == 0,
                 f"Не построена компоновка {layout['version']} в собранном приложении")
    with TemporaryDirectory(prefix="suspensionlab-front-layout-reopen-") as directory:
        source, target = Path(directory) / "source.kima", Path(directory) / "copy.kima"
        write_document(source, "assembly", layouts[1], overwrite=False)
        original = source.read_bytes()
        front_dialog = FrontTubesDialog(controller)
        front_dialog.show()
        panel = front_dialog._layout_3d
        try:
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")), \
                    patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
                front_dialog._open_file()
            _require(not front_dialog._active and front_dialog._pair_mode.currentData() == "same" and
                     front_dialog._layout_3d._document == layouts[1], "Компоновка 0.12 не открылась")
            front_dialog._start_preview()
            panel._enable.setChecked(True)
            wait_for_mesh()
            front_dialog._radius.setText("11")
            _require(panel._view.mesh is None and not front_dialog._save_layout.isEnabled(),
                     "Старая компоновка не очищена")
            wait_for_mesh()
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
                    patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
                front_dialog._save_layout_copy()
            _require(target.exists() and read_document(target, "assembly")["pair"]["source"]["radius_mm"] == 11 and
                     source.read_bytes() == original, "Копия компоновки не сохранена или исходник изменён")
        finally:
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                front_dialog.close()
                app.processEvents()


def run_packaging_check() -> None:
    """Проверяет ресурсы, окно, один расчёт и проект во временном каталоге.

    Использует отдельные настройки, не открывает пользовательские проекты и не
    запускает автоматическое сохранение. На CI вызывается с Qt offscreen.
    """
    root = resources_dir()
    for relative in ("themes/dark.qss", "themes/light.qss", "help/user_manual_ru.txt"):
        _require(bool((root / relative).read_text(encoding="utf-8").strip()), f"Пустой ресурс: {relative}")
    json.loads((root / "schema/project-1.0.schema.json").read_text(encoding="utf-8"))
    _require(tr("app.title") != "‹app.title›", "Не загружена локализация")
    _require("ring" in {item.key for item in list_templates()}, "Не загружен шаблон Кольцо")

    app = create_application([])
    # Проверяем именно GUI-отрисовку и наличие растеризатора в упаковке.
    # Эскиз и DXF проверяются именно в замороженной сборке, а не только в исходниках.
    from unittest.mock import patch

    import ezdxf
    import numpy as np
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QInputDialog, QLineEdit, QMessageBox

    from .core.cad_measurement import measurement_distance, point_on_projected_triangle
    from .core.cad_mesh import CadMesh
    from .core.cad_raster import pick_triangle
    from .core.camera_views import camera_view_angles
    from .ui.cad_preview_dialog import CadPreviewDialog
    from .ui.cad_preview_settings import CadPreviewSettingsDialog
    from .ui.canvas.cad_preview import CadPreview
    from .ui.sketch_draft_dialog import FilletChoiceDialog, SketchDraftDialog, SketchExtrusionPreview
    from .ui.widgets.camera_views import CameraViews

    with TemporaryDirectory(prefix="suspensionlab-sketch-check-") as sketch_dir:
        sketch = SketchDraftDialog()
        sketch.show()
        sketch.tool.setCurrentIndex(3)  # прямоугольник
        sketch.canvas.add_point((0., 0.))
        sketch.canvas.add_point((100., 40.))
        with patch.object(QMessageBox, "information") as report:
            sketch._check_contours()
        _require(report.called and "Замечаний не найдено" in str(report.call_args), "Проверка контуров недоступна")
        from .model.sketch_draft import dimension_text
        from .model.sketch_io import read_sketch, write_new_sketch

        sketch.canvas.draft.add_dimension(0, (50., -15.), "horizontal")
        sketch._fillet((0, 1))
        _require(sketch.canvas.draft.entities[-1].kind == "arc" and
                 dimension_text(sketch.canvas.draft.dimensions[0], sketch.canvas.draft.entities[0]) == "90.000 мм",
                 "Сопряжение и связанный справочный размер недоступны")
        # Один щелчок по числу открывает изменение геометрии; отмена восстанавливает её.
        label = sketch.canvas._dimension_label_rect(sketch.canvas.draft.dimensions[0]).center()
        with patch.object(QInputDialog, "getDouble", return_value=(80., True)):
            app.sendEvent(sketch.canvas, QMouseEvent(QEvent.Type.MouseButtonPress, label,
                          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        _require(abs(sketch.canvas.draft.entities[0].size - 80.) < 1e-6, "Изменение размера по щелчку недоступно")
        sketch._undo()
        from .model.sketch_extrusion import extrusion_mesh

        sketch_preview = SketchExtrusionPreview(extrusion_mesh(sketch._document(), 10.))
        _require(sketch_preview.view.mesh is not None and not sketch_preview.view.grab().isNull(), "3D-предпросмотр эскиза недоступен")
        sketch_preview.close()
        saved = Path(sketch_dir) / "размер.slsketch"
        write_new_sketch(saved, sketch._document())
        _require(read_sketch(saved) == sketch._document(), "Размер не сохранился в отдельном эскизе")
        sketch.tool.setCurrentIndex(6)  # аналитическая дуга
        sketch.arc_angle.setValue(-90.)
        sketch.canvas.add_point((150., 0.))
        sketch.canvas.add_point((160., 0.))
        _require(sketch.canvas.draft.entities[-1].kind == "arc", "Построение дуги недоступно")
        sketch.tool.setCurrentIndex(0)
        sketch.canvas.add_point((155., -20.))
        sketch.canvas.add_point((155., 20.))
        sketch._trim(5, (157.071, -7.071))
        _require(sketch.canvas.draft.entities[5].kind == "arc" and
                 abs(sketch.canvas.draft.entities[5].sweep_deg or 0) < 90., "Обрезка дуги недоступна")
        with patch.object(QMessageBox, "information") as arc_report:
            sketch._check_contours()
        _require(arc_report.called, "Проверка контуров с дугой недоступна")
        destination = Path(sketch_dir) / "эскиз.dxf"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
            _require(sketch._export_dxf(), "DXF эскиза не создан")
        dxf = ezdxf.readfile(destination)
        _require(dxf.header["$INSUNITS"] == 4 and len(dxf.modelspace()) == 7 and
                 len(dxf.modelspace().query("ARC")) == 2,
                 "DXF эскиза содержит неверные единицы или геометрию")
        sketch._saved = sketch._document()
        sketch.close()

        from .model.sketch_draft import SketchDraft, dimension_value, make_entity

        sketch2 = SketchDraftDialog()
        line = make_entity("line", (10., 0.), (30., 0.))
        arc = make_entity("arc", (0., 0.), (10., 0.), 90.)
        sketch2.canvas.draft = SketchDraft((arc, line))
        sketch2.fillet_radius.setValue(2.)
        sketch2._fillet((0, 1))
        _require(len(sketch2.canvas.draft.entities) == 3 and sketch2.canvas.draft.entities[-1].kind == "arc",
                 "Сопряжение дуги и отрезка недоступно")
        sketch2._undo()
        _require(tuple(sketch2.canvas.draft.entities) == (arc, line), "Отмена сопряжения дуги недоступна")
        arc_a = make_entity("arc", (-10., 0.), (0., 0.), 90.)
        arc_b = make_entity("arc", (0., -10.), (0., 0.), 90.)
        sketch2.canvas.draft = SketchDraft((arc_a, arc_b))
        sketch2._fillet((0, 1))
        _require(len(sketch2.canvas.draft.entities) == 3, "Сопряжение двух дуг недоступно")
        sketch2._undo()
        _require(tuple(sketch2.canvas.draft.entities) == (arc_a, arc_b), "Отмена сопряжения дуг недоступна")
        circle = make_entity("circle", (0., 0.), (10., 0.))
        sketch2.canvas.draft = SketchDraft((circle, line))
        with patch.object(FilletChoiceDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            sketch2._fillet((0, 1))
        _require([e.kind for e in sketch2.canvas.draft.entities] == ["arc", "line", "arc"],
                 "Сопряжение отрезка и окружности недоступно")
        sketch2._undo()
        _require(tuple(sketch2.canvas.draft.entities) == (circle, line), "Окружность не восстановлена отменой")
        first = make_entity("line", (0., 0.), (50., 0.))
        second = make_entity("line", (0., 0.), (0., 50.))
        sketch2.canvas.draft = SketchDraft((first, second))
        sketch2.canvas.draft.add_dimension(0, (20., 20.), "between", 1)
        with patch.object(QInputDialog, "getDouble", return_value=(60., True)):
            sketch2._edit_dimension(0)
        dim = sketch2.canvas.draft.dimensions[0]
        _require(abs(dimension_value(dim, *sketch2.canvas.draft.entities) - 60.) < 1e-6,
                 "Изменение угла между отрезками недоступно")
        angled = Path(sketch_dir) / "угол.slsketch"
        write_new_sketch(angled, sketch2._document())
        _require(read_sketch(angled) == sketch2._document(), "Угол между отрезками не сохранился")
        sketch2._saved = sketch2._document()
        sketch2.close()

    preview = CadPreview()
    preview.resize(320, 280)
    preview.set_mesh(CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 0, 10]]]), 1),
                     np.array([True]), through=True)
    _require(not preview.grab().isNull() and preview._frame is not None and preview._through,
             "CAD-просмотр с подсветкой не отрисован")
    for button, start, end in ((Qt.MouseButton.RightButton, QPointF(40, 40), QPointF(65, 50)),
                               (Qt.MouseButton.LeftButton, QPointF(50, 50), QPointF(50, 250))):
        app.sendEvent(preview, QMouseEvent(QEvent.Type.MouseButtonPress, start, button, button, Qt.KeyboardModifier.NoModifier))
        app.sendEvent(preview, QMouseEvent(QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, button, Qt.KeyboardModifier.NoModifier))
        app.sendEvent(preview, QMouseEvent(QEvent.Type.MouseButtonRelease, end, button, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    _require((preview.pan_x, preview.pan_y) == (25., 10.) and preview.elevation > 1.35 and not preview.grab().isNull(),
             "Управление камерой CAD-просмотра недоступно")
    menu = CameraViews(cad=True)
    menu.viewSelected.connect(preview.set_standard_view)
    menu.actions_by_view["bottom"].trigger()
    _require((preview.yaw, preview.elevation) == camera_view_angles("bottom")
             and (preview.pan_x, preview.pan_y) == (25., 10.) and not preview.grab().isNull(),
             "Стандартные направления CAD-просмотра недоступны")
    menu.close()
    preview.reset_camera()
    _require((preview.pan_x, preview.pan_y) == (0., 0.), "Сброс камеры CAD-просмотра недоступен")
    preview.close()
    with TemporaryDirectory(prefix="suspensionlab-quality-check-") as quality_dir:
        quality_settings = QSettings(str(Path(quality_dir) / "settings.ini"), QSettings.Format.IniFormat)
        quality_dialog = CadPreviewDialog(settings=quality_settings)
        quality_dialog._show_mesh(CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 0, 10]]]), 1))

        def change_quality() -> None:
            settings_dialog = app.activeModalWidget()
            _require(isinstance(settings_dialog, CadPreviewSettingsDialog), "Меню качества недоступно")
            assert isinstance(settings_dialog, CadPreviewSettingsDialog)
            settings_dialog._quality.setCurrentIndex(settings_dialog._quality.findData(0.2))
            settings_dialog.accept()

        QTimer.singleShot(0, change_quality)
        quality_dialog._quality_settings.click()
        _require(quality_dialog._selected_deviation == 0.2 and "Перестроить" in quality_dialog._quality_status.text(),
                 "Настройки не отражают ожидающее перестроение")
        quality_dialog.close()
    sample = np.array([[[-2., 0., -2.], [2., 0., -2.], [0., 0., 2.]]])
    _require(pick_triangle(sample, np.zeros(3), 3., 0., 0., 1., 100, 100, 50, 50) == 0,
             "Выбор детали CAD-просмотра недоступен")
    selected = point_on_projected_triangle(sample[0], np.array([[0., 0.], [2., 0.], [0., 2.]]), 1., 0.)
    _require(selected is not None and measurement_distance(selected, (0., 0., -2.)) == 0.,
             "Замер по сетке недоступен")
    with TemporaryDirectory(prefix="suspensionlab-package-check-") as directory:
        temporary = Path(directory)
        settings = QSettings(str(temporary / "settings.ini"), QSettings.Format.IniFormat)
        window = MainWindow(settings=settings)
        window.show()
        window.controller.new_project("ring")
        window._show_workspace()
        app.processEvents()
        point_table = PointTableDialog(window.controller, window)
        _require(bool(window.action_point_table.text()) and bool(point_table._rows), "Таблица исходных точек недоступна")
        first_role, first_code = point_table._rows[0]
        first_point = window.controller.project.axle(first_role).hardpoints[first_code]
        old_x = first_point.x
        cell = point_table._table.item(0, 4)
        _require(cell is not None, "Координата точки недоступна")
        assert cell is not None
        cell.setText(str(old_x + 1))
        point_table._apply_changes()
        _require(first_point.x == old_x + 1, "Правка точки не применена")
        point_table.export_csv(temporary / "model-points.csv")
        _require((temporary / "model-points.csv").read_bytes().startswith(b"\xef\xbb\xbf"),
                 "CSV исходных точек не записан")
        csv_path = temporary / "model-points.csv"
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.reader(stream))
        csv_rows[1][5] = str(old_x + 2)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows(csv_rows)
        preview_seen: list[bool] = []

        def confirm_point_import() -> None:
            preview = point_table.findChild(PointImportDialog)
            if preview is not None:
                preview_seen.append(preview._table.rowCount() == 1 and preview._apply.isEnabled())
                if preview._apply.isEnabled():
                    preview._apply.click()
                else:
                    preview.reject()

        QTimer.singleShot(0, confirm_point_import)
        point_table.import_csv(csv_path)
        _require(preview_seen == [True] and first_point.x == old_x + 2, "Предпросмотр импорта CSV недоступен")
        point_table.close()
        point_table.deleteLater()
        window.controller.undo_last()
        _require(first_point.x == old_x + 1, "Отмена импорта точек недоступна")
        window.controller.undo_last()
        _require(first_point.x == old_x, "Отмена правки точки недоступна")
        app.processEvents()
        registration = CadRegistrationDialog(window.controller, window)
        registration._add_row()
        for row, code in enumerate(("ubj", "lbj", "lca_f_in", "lca_r_in")):
            index = next(i for i, p in enumerate(registration._records) if p.role == "front" and p.code == code)
            combo = registration._table.cellWidget(row, 0)
            purpose = registration._table.cellWidget(row, 4)
            assert isinstance(combo, QComboBox) and isinstance(purpose, QComboBox)
            combo.setCurrentIndex(combo.findData(index))
            if row == 3:
                purpose.setCurrentIndex(1)
            for column, coordinate in enumerate(registration._records[index].xyz, 1):
                coordinate_edit = registration._table.cellWidget(row, column)
                assert isinstance(coordinate_edit, QLineEdit)
                coordinate_edit.setText(str(coordinate))
        registration._confirmed.setChecked(True)
        registration._run()
        _require(registration._export.isEnabled() and registration._report is not None,
                 "Совмещение и контрольные точки недоступны")
        assert registration._report is not None
        write_csv_report(registration._report, temporary / "registration.csv")
        _require(b"control" in (temporary / "registration.csv").read_bytes(), "Отчёт совмещения недоступен")
        overlay_seen: list[bool] = []
        def check_registration_overlay() -> None:
            overlay = registration.findChild(CadRegistrationOverlayDialog)
            if overlay is not None:
                overlay._confirm.setChecked(True)
                overlay._show_mesh(CadMesh(np.array([[[0., 0, 0], [100., 0, 0], [0, 100., 0]]]), 1))
                overlay.show()
                app.processEvents()
                overlay._canvas.grab()
                overlay_seen.append(overlay._canvas.mesh is not None and len(overlay._canvas.positions()) == 4)
                overlay.reject()
        QTimer.singleShot(0, check_registration_overlay)
        registration._open_overlay()
        _require(overlay_seen == [True], "Просмотр совмещения недоступен")
        registration.close()
        registration.deleteLater()
        app.processEvents()
        window.controller.project.add_snapshot("Проверка сравнения")
        window.controller.project.add_snapshot("Проверка второго снимка")
        compare = SnapshotCompareDialog(window.controller, window)
        _require(bool(window.action_compare_snapshot.text()) and compare._result is not None,
                 "Сравнение снимка недоступно")
        _require(bool(compare._report().rows), "Отчёт сравнения снимка пуст")
        compare._target.setCurrentIndex(2)
        _require(compare._result is not None and not compare._choose.isEnabled(),
                 "Сравнение двух снимков недоступно")
        assert compare._result is not None
        overlay = SnapshotOverlayDialog(window.controller, compare._result.points, compare)
        overlay.show()
        app.processEvents()
        _require(bool(overlay._canvas.screen_points()) and not overlay._canvas.grab().isNull(),
                 "Наложение точек снимков недоступно")
        overlay._list.setCurrentRow(0)
        _require(overlay._choose.isEnabled(), "Выбор точки в наложении недоступен")
        overlay.close()
        overlay.deleteLater()
        compare._tabs.setCurrentIndex(2)
        _require(bool(compare._parameters) and bool(compare._report().rows),
                 "Сравнение параметров снимка недоступно")
        compare.close()
        compare.deleteLater()
        window.controller.project.snapshots.pop()
        window.controller.project.snapshots.pop()
        dialog = AnalysisDialog(window.controller, window)
        dialog.show()
        dialog._from.setValue(0)
        dialog._to.setValue(1)
        dialog._run.click()
        app.processEvents()
        _require(dialog._table.rowCount() == 2, "Таблица хода не рассчитана")
        dialog._preview_mode.setCurrentIndex(1)
        dialog._camera_views.actions_by_view["front"].trigger()
        _require((dialog._preview3d.yaw, dialog._preview3d.elevation) == camera_view_angles("front")
                 and not dialog._preview3d.grab().isNull(), "Стандартные направления 3D-каркаса недоступны")
        dialog._point_choice.setCurrentIndex(dialog._point_choice.findData("ubj"))
        app.processEvents()
        _require(dialog._preview3d.frame is not None and dialog._preview3d.frame.point("ubj") is not None
                 and "X" in dialog._point_info.text(), "Выделение расчётной точки недоступно")
        _require(dialog._point_export.isEnabled(), "Экспорт координат точки недоступен")
        point_report = dialog._make_point_report()
        point_csv = write_csv_report(point_report, temporary / "point.csv")
        _require(len(point_report.rows) == 2 and point_report.rows[0][2] != "—"
                 and point_csv.read_bytes().startswith(b"\xef\xbb\xbf"), "CSV координат точки не записан")
        dialog._point_samples.setChecked(True)
        app.processEvents()
        _require(len(dialog._preview3d.sample_positions) == 2 and "2 из 2" in dialog._point_info.text()
                 and not dialog._preview3d.grab().isNull(), "Дискретные положения точки недоступны")
        dialog._point_choice.setCurrentIndex(0)
        _require(not dialog._preview3d.sample_positions and not dialog._point_export.isEnabled(), "Положения точки не очищены")
        dialog._parameters_toggle.click()
        app.processEvents()
        _require(not dialog._parameters.isVisible() and dialog._preview3d.height() >= 250
                 and bool(dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint),
                 "Размер или управление окном 3D-просмотра недоступны")
        dialog._parameters_toggle.click()
        app.processEvents()
        _require(dialog._parameters.isVisible() and dialog._table.rowCount() == 2,
                 "Параметры расчёта не восстановлены")
        camber = dialog._table.item(0, 1)
        if camber is None:
            raise RuntimeError("Не отображён развал")
        float(camber.text())
        _require(dialog._export_button.isEnabled(), "Результат анализа недоступен")
        dialog._view_tabs.setCurrentIndex(1)
        app.processEvents()
        _require(not dialog._plot.grab().isNull() and len(dialog._plot.points) == 2, "График хода недоступен")
        _require(len(dialog._summary.groups) == 1 and dialog._summary.groups[0].first.status == "incomplete",
                 "Сводка не указывает незаданные проверки")
        plot_report = make_plot_report(
            window.controller, dialog._table, tr("analysis.title"), dialog._report_parameters(),
            dialog._plot.points, tuple(tr(f"analysis.column.{key}") for key in PLOT_METRICS),
            tr("analysis.column.travel"), (8,),
        )
        csv_path = write_csv_report(plot_report, temporary / "graph.csv")
        _require(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"), "CSV точек не записан")
        dialog._spring.setChecked(True)
        dialog._spring_length.setValue(320)
        dialog._coil_bind.setValue(115)
        dialog._damper.setChecked(True)
        dialog._damper_min.setValue(205)
        dialog._damper_max.setValue(325)
        _require(dialog._copy_damper.isEnabled(), "Перенос длин из проекта недоступен")
        dialog._run.click()
        _require(dialog._spring_summary is not None and dialog._spring_summary.total == 2
                 and dialog._spring_summary.missing == 0 and dialog._spring_shortest.isEnabled()
                 and "из 2; пропусков: 0" in dialog._spring_range.toPlainText(),
                 "Сводка пружины недоступна")
        assert dialog._spring_summary is not None and dialog._spring_summary.shortest is not None
        spring_row = dialog._spring_summary.shortest.row
        dialog._spring_shortest.click()
        _require(dialog._table.currentRow() == spring_row, "Переход к точке сводки пружины недоступен")
        _require(dialog._axis_compare_button.isEnabled(), "Сравнение линий опор недоступно")
        dialog._axis_compare_button.click()
        alignment = dialog._axis_dialog
        _require(alignment is not None, "Сравнение линий опор не открылось")
        assert alignment is not None
        _require(alignment._report is not None, "Отчёт линий опор недоступен")
        assert alignment._report is not None
        _require(len(alignment._report.rows) == 2 and alignment._report.rows[0][9] == tr("axis_alignment.status.available")
                 and len(alignment._report.rows[0]) == 15 and alignment._report.rows[0][5] != "—"
                 and alignment._report.rows[0][7] != "—", "Сравнение линий опор недоступно")
        for key, value in (("angle", "90"), ("lower", "1000"), ("upper", "1000")):
            alignment._limit_fields[key].setText(value)
        _require(alignment._report is not None and alignment._report.rows[0][14] == tr("axis_alignment.limits.combined.within"),
                 "Численные условия линий опор не рассчитаны")
        alignment._filter.setCurrentIndex(alignment._filter.findData("exceeded"))
        _require(alignment._table.isRowHidden(0) and alignment._table.isRowHidden(1), "Фильтр пределов не работает")
        alignment._plot.rowSelected.emit(1)
        _require(not alignment._table.isRowHidden(1) and alignment._table.currentRow() == 1,
                 "Выбор на графике линий опор не работает")
        alignment._tabs.setCurrentIndex(1)
        app.processEvents()
        _require(alignment._plot._geometry() is not None and not alignment._plot.grab().isNull(),
                 "График линий опор недоступен")
        assert alignment._report is not None
        write_csv_report(alignment._report, temporary / "axis-alignment.csv")
        alignment._table.setCurrentCell(1, 0)
        alignment._choose.click()
        _require(dialog._axis_dialog is None and dialog._table.currentRow() == 1,
                 "Переход к строке сравнения линий опор недоступен")
        _require(dialog._spring_compare_button.isEnabled(), "Сравнение пружины недоступно")
        dialog._spring_compare_button.click()
        spring_candidate = dialog._spring_candidate_dialog
        _require(spring_candidate is not None, "Окно сравнения пружины не открылось")
        assert spring_candidate is not None
        for key, value in (("free", "350"), ("installed", "310"), ("coil", "120"),
                           ("coil_reserve", "10"), ("compression_reserve", "5")):
            spring_candidate._fields[key].setText(value)
        spring_candidate._compare.click()
        _require(spring_candidate.comparison is not None and len(spring_candidate.comparison.points) == 2
                 and "Всего строк: 2" in spring_candidate._result.toPlainText(), "Сравнение пружины не выполнено")
        _require(spring_candidate.report is not None and spring_candidate._export.isEnabled(),
                 "Отчёт сравнения пружины недоступен")
        assert spring_candidate.report is not None
        spring_csv = write_csv_report(spring_candidate.report, temporary / "spring-candidate.csv")
        _require(len(spring_candidate.report.rows) == 2 and spring_csv.read_bytes().startswith(b"\xef\xbb\xbf"),
                 "CSV сравнения пружины не записан")
        _require(spring_candidate._details.isEnabled(), "Просмотр точек сравнения пружины недоступен")
        spring_candidate._details.click()
        spring_detail = spring_candidate._details_dialog
        _require(spring_detail is not None and spring_detail._table.rowCount() == 2,
                 "Точки сравнения пружины не открылись")
        assert spring_detail is not None
        spring_detail._tabs.setCurrentIndex(1)
        app.processEvents()
        _require(spring_detail._plot._geometry() is not None and not spring_detail._plot.grab().isNull(),
                 "График сравнения пружины недоступен")
        spring_detail._filter.setCurrentIndex(spring_detail._filter.findData("missing"))
        _require(spring_detail._table.isRowHidden(0) and spring_detail._table.isRowHidden(1),
                 "Фильтр точек пружины работает неправильно")
        spring_candidate._fields["installed"].setText("315")
        _require(spring_candidate._details_dialog is None and not spring_candidate._details.isEnabled(),
                 "Устаревшие точки пружины не очищены")
        _require(spring_candidate.report is None and not spring_candidate._export.isEnabled(),
                 "Устаревший отчёт пружины не очищен")
        def enter_spring_rate() -> None:
            helper = app.activeModalWidget()
            _require(isinstance(helper, SpringRateDialog), "Оценка жёсткости не открыта")
            assert isinstance(helper, SpringRateDialog)
            for key, value in (("length1", "300"), ("force1", "625"), ("length2", "280"), ("force2", "875")):
                helper._fields[key].setText(value)
            _require(helper._apply.isEnabled() and helper.estimate is not None
                     and helper.estimate.rate_n_mm == 12.5, "Оценка по двум точкам недоступна")
            helper._apply.click()

        QTimer.singleShot(0, enter_spring_rate)
        spring_candidate._estimate_rate.click()
        _require(spring_candidate._force_enable.isChecked() and spring_candidate._force_rate.text() == "12.5",
                 "Жёсткость по двум точкам не перенесена")
        spring_candidate._compare.click()
        _require(spring_candidate.comparison is not None and spring_candidate.report is not None
                 and spring_candidate.comparison.points[0].force_n is not None
                 and spring_candidate.report.rows[0][8] != "—", "Линейная оценка силы пружины недоступна")
        assert spring_candidate.report is not None
        _require(dict(spring_candidate.report.metadata).get(tr("spring_rate.length1")) == "300.0"
                 and dict(spring_candidate.report.metadata).get(tr("spring_rate.force2")) == "875.0",
                 "Исходные точки жёсткости потеряны в отчёте сравнения")
        _require(spring_candidate._force_min_button.isEnabled() and spring_candidate._force_max_button.isEnabled()
                 and "Наименьшая" in spring_candidate._result.toPlainText(), "Сводка силы пружины недоступна")
        spring_candidate._details.click()
        force_detail = spring_candidate._details_dialog
        _require(force_detail is not None, "Просмотр силы пружины не открылся")
        assert force_detail is not None
        force_detail._tabs.setCurrentIndex(2)
        app.processEvents()
        _require(force_detail._force_plot._geometry() is not None and not force_detail._force_plot.grab().isNull(),
                 "График силы пружины недоступен")
        force_detail._force_filter.setCurrentIndex(force_detail._force_filter.findData("unavailable"))
        _require(all(force_detail._table.isRowHidden(row) for row in range(2)),
                 "Фильтр отсутствующей силы работает неправильно")
        force_detail._select_plot_row(0)
        _require(force_detail._force_filter.currentData() == "all", "Скрытая точка не раскрыта фильтром силы")
        _require(force_detail._table.currentRow() == 0 and force_detail._force_plot.row == 0,
                 "Выбор на графике силы не синхронизирован")
        _require(spring_candidate._balance.isEnabled(), "Баланс кандидата недоступен")

        def inspect_candidate_balance() -> None:
            from .core.spring_characteristics import SpringCharacteristic

            balance = app.activeModalWidget()
            _require(isinstance(balance, EquilibriumDialog) and balance._candidate is not None,
                     "Баланс кандидата не открылся")
            assert isinstance(balance, EquilibriumDialog) and balance._candidate is not None
            c = balance._candidate
            assert c.linear_rate_n_mm is not None
            characteristic = SpringCharacteristic(c.free_mm, c.linear_rate_n_mm, coil_bind_length_mm=c.coil_bind_mm)
            problem = SpringEquilibrium(window.controller.project.front, c.installed_mm,
                                        coil_bind_length_mm=c.coil_bind_mm, spring_characteristic=characteristic)
            balance._load.setValue(problem.evaluate(12, 1).wheel_support_n)
            balance._run.click()
            _require(balance._result is not None and balance._display_values is not None and
                     "candidate_coil_condition" in balance._display_values and
                     "Только в оценке середины" in balance._output.text() and "кандидат" in
                     dict(balance._report_parameters())[tr("equilibrium_ui.spring_source")],
                     "Условный баланс кандидата или сводка запасов недоступны")
            path = balance._path
            _require(path is not None, "Путь кандидата недоступен")
            assert path is not None
            view = EquilibriumPathDialog(path, balance, candidate=c)
            report = balance._path_report(path, view._table)
            graph = balance._path_graph_report(path, view._table, view._plot.points, view._plot_metric.currentText())
            _require(dict(report.metadata).get(tr("spring_rate.length1")) == "300.0"
                     and dict(graph.metadata).get(tr("spring_rate.force2")) == "875.0",
                     "Исходные точки жёсткости потеряны в отчётах пути")
            column = tr("equilibrium_path.column.candidate_status")
            _require(column in report.columns and column in graph.columns and len(report.rows) == len(path.samples)
                     and "отказ без данных" in view._candidate_summary.text()
                     and view._candidate_min_coil.isEnabled() and view._candidate_min_compression.isEnabled()
                     and tr("equilibrium_path.candidate_report_coil_min") in dict(report.metadata),
                     "Запасы кандидата по сохранённым точкам не показаны")
            if path.samples:
                opposite = "short" if view._candidate_geometries[0].coil_reserve_ok else "ok"
                view._coil_filter.setCurrentIndex(view._coil_filter.findData(opposite))
                _require(view._table.isRowHidden(0) and balance._path_report(path, view._table) == report,
                         "Фильтр пути изменил CSV или не скрыл строку")
                assert view._candidate_plot is not None
                view._candidate_plot.rowSelected.emit(0)
                _require(not view._table.isRowHidden(0) and view._coil_filter.currentData() == "all",
                         "Выбор скрытой точки пути не восстановил строку")
            view._candidate_min_coil.click()
            _require(view._table.currentRow() >= 0 and view._plot.row == view._table.currentRow(),
                     "Переход к минимуму запасов не работает")
            _require(view._candidate_plot is not None, "График запасов кандидата отсутствует")
            assert view._candidate_plot is not None
            view.show()
            view._views.setCurrentIndex(2)
            app.processEvents()
            _require(view._candidate_plot._geometry() is not None and not view._candidate_plot.grab().isNull()
                     and view._candidate_plot.row == view._table.currentRow(),
                     "График запасов кандидата недоступен")
            write_csv_report(report, temporary / "candidate-path.csv")
            view.close()
            balance.reject()

        QTimer.singleShot(0, inspect_candidate_balance)
        spring_candidate._balance.click()
        spring_candidate.reject()
        _require(dialog._spring_candidate_dialog is None, "Окно сравнения пружины не закрыто")
        _require("Точек на упоре или за ним: 2" in dialog._damper_range.toPlainText(),
                 "Сводка подбора амортизатора не выявила конфликт")
        dialog._candidate_min.setText("200")
        dialog._candidate_max.setText("500")
        dialog._candidate_reserve.setText("10")
        dialog._candidate_compare.click()
        _require("На упоре или за ним: 0" in dialog._candidate_result.toPlainText()
                 and "запас меньше заданного: 0" in dialog._candidate_result.toPlainText()
                 and dialog._table.rowCount() == 2, "Сравнение кандидата не выполнено")
        _require(dialog._candidate_export.isEnabled() and dialog._candidate_report is not None,
                 "Отчёт кандидата недоступен")
        assert dialog._candidate_report is not None
        candidate_path = write_csv_report(dialog._candidate_report, temporary / "candidate.csv")
        _require(candidate_path.read_bytes().startswith(b"\xef\xbb\xbf") and len(dialog._candidate_report.rows) == 2,
                 "CSV сравнения кандидата не записан")
        _require(dialog._candidate_details.isEnabled(), "Просмотр точек кандидата недоступен")
        dialog._candidate_details.click()
        details = dialog._candidate_detail_dialog
        _require(details is not None, "Окно точек кандидата не открыто")
        assert details is not None
        details._filter.setCurrentIndex(details._filter.findData("clear"))
        details._tabs.setCurrentIndex(1)
        _require(not details._plot.grab().isNull() and details._plot._geometry() is not None,
                 "График кандидата недоступен")
        details._table.setCurrentCell(1, 0)
        details._choose.click()
        _require(dialog._table.currentRow() == 1 and dialog._candidate_detail_dialog is None,
                 "Переход к точке кандидата недоступен")
        dialog._candidate_reserve.setText("15")
        _require(not dialog._candidate_export.isEnabled(), "Отчёт кандидата не очищен после правки")
        dialog._static_button.click()
        _require(dialog._static_export.isEnabled() and dialog._static_report is not None,
                 "Не получен отчёт статики")
        assert dialog._static_report is not None
        static_rows = {row[0]: row for row in dialog._static_report.rows}
        extension = float(static_rows[tr("analysis.static.report.metric.damper_extension_clearance")][1])
        _require(-70 < extension < -69, "В отчёте статики не обнаружен ожидаемый конфликт отбоя")
        _require("сжатие 0.00 мм" in dialog._static_explanation.toPlainText(), "Нет пояснения несжатой пружины")
        write_csv_report(dialog._static_report, temporary / "static.csv")
        converter = DamperConversionDialog(dialog)
        converter._compression_force.setText("235")
        converter._compression_speed.setText("300")
        points = converter.points()
        _require(converter._apply.isEnabled() and points[0] is not None and points[1] is None,
                 "Недоступен пересчёт характеристики амортизатора")
        assert points[0] is not None
        _require(abs(points[0].coefficient_n_s_mm - 235 / 300) < 1e-12, "Неверный пересчёт коэффициента")
        converter.close()
        antiroll = AntiRollDialog(window.controller, window)
        antiroll.show()
        antiroll._from.setValue(0)
        antiroll._to.setValue(1)
        antiroll._axis_x.setText("-250")
        antiroll._axis_z.setText("320")
        antiroll._rate.setText("1000")
        antiroll._run.click()
        antiroll._view_tabs.setCurrentIndex(1)
        antiroll._plot_pair.setChecked(True)
        app.processEvents()
        _require(antiroll._table.rowCount() == 2 and antiroll._plot._secondary_metric == ANTIROLL_METRICS.index("right_angle"),
                 "Сравнение сторон стабилизатора недоступно")
        _require(not antiroll._plot.grab().isNull(), "График стабилизатора недоступен")
        _require(antiroll._summary.groups[0].first.status == "incomplete", "Сводка стабилизатора некорректна")
        equilibrium = EquilibriumDialog(window.controller, window)
        from .ui.mass_load_dialog import MassLoadDialog

        def enter_mass_load() -> None:
            helper = equilibrium.findChild(MassLoadDialog)
            _require(helper is not None, "Окно оценки нагрузки по массе не открыто")
            assert helper is not None
            for key, value in (("mass", "1200"), ("axle_percent", "55"), ("unsprung", "35")):
                helper._fields[key].setText(value)
            helper._calculate_button.click()
            _require(helper._apply.isEnabled(), "Оценка нагрузки по массе не рассчитана")
            helper._apply.click()

        QTimer.singleShot(0, enter_mass_load)
        equilibrium._mass_load_button.click()
        _require(equilibrium._load.value() == 2893.0 and equilibrium._load_source is not None,
                 "Нагрузка по массе не перенесена в баланс")

        def enter_corner_load() -> None:
            helper = app.activeModalWidget()
            _require(isinstance(helper, MassLoadDialog), "Окно оценки по колесу не открыто")
            assert isinstance(helper, MassLoadDialog)
            helper._mode.setCurrentIndex(helper._mode.findData("weighed"))
            helper._fields["wheel"].setText("340")
            helper._fields["unsprung"].setText("40")
            helper._calculate_button.click()
            _require(helper._apply.isEnabled(), "Оценка по колесу не рассчитана")
            helper._apply.click()

        QTimer.singleShot(0, enter_corner_load)
        equilibrium._mass_load_button.click()
        _require(equilibrium._load.value() == 2942.0 and equilibrium._load_source is not None
                 and "показание весов" in dict(equilibrium._report_parameters())[tr("equilibrium_ui.load_source")],
                 "Нагрузка по колесу не перенесена или потерян источник")

        def enter_four_wheels() -> None:
            helper = app.activeModalWidget()
            _require(isinstance(helper, MassLoadDialog), "Окно четырёх колёс не открыто")
            assert isinstance(helper, MassLoadDialog)
            helper._mode.setCurrentIndex(helper._mode.findData("four_weighed"))
            for key, value in (("front_left", "350"), ("front_right", "300"), ("rear_left", "250"),
                               ("rear_right", "200"), ("unsprung", "30")):
                helper._fields[key].setText(value)
            helper._calculate_button.click()
            _require(helper._apply.isEnabled() and "1100.000" in helper._result.text()
                     and "переднее левое + заднее правое 550.000 кг (50.00%)" in helper._result.text(),
                     "Сводка четырёх колёс и диагоналей недоступна")
            helper._apply.click()

        QTimer.singleShot(0, enter_four_wheels)
        equilibrium._mass_load_button.click()
        _require(equilibrium._load.value() == 3138.1 and equilibrium._load_source is not None
                 and "Четыре введённых" in dict(equilibrium._report_parameters())[tr("equilibrium_ui.load_source")]
                 and "переднее левое + заднее правое: 550.0 (50.0%)" in
                 dict(equilibrium._report_parameters())[tr("equilibrium_ui.load_mass_inputs")],
                 "Нагрузка по четырём колёсам не перенесена или потерян источник")
        equilibrium._length.setValue(230)
        equilibrium._load.setValue(SpringEquilibrium(window.controller.project.front, 230).evaluate(12, 1).wheel_support_n)
        equilibrium._run.click()
        path = equilibrium._path
        _require(path is not None and path.completed, "Не рассчитан учебный путь баланса")
        assert path is not None
        path_view = EquilibriumPathDialog(path, equilibrium)
        path_view.show()
        path_view._views.setCurrentIndex(1)
        app.processEvents()
        _require(bool(path_view._plot.points) and not path_view._plot.grab().isNull(), "График пути недоступен")
        path_report = equilibrium._path_graph_report(path, path_view._table, path_view._plot.points,
                                                       path_view._plot_metric.currentText())
        _require(len(path_report.rows) == len(path.samples), "Отчёт графика пути неполон")
        write_csv_report(path_report, temporary / "path-graph.csv")
        path_view.close()
        equilibrium.close()
        antiroll.close()
        project_path = window.controller.save_project(temporary / "test.susp.json")
        loaded = load_project(project_path, require_complete=True)
        _require(loaded.front.type_code == "double_wishbone", "Проект не восстановлен")
        dialog.close()
        window.close()
        app.processEvents()

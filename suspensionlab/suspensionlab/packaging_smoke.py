"""Ограниченная автоматическая проверка собранного приложения, не UI-валидация."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSettings, QTimer

from .app import create_application
from .config import log_file_path, resources_dir
from .core.equilibrium import SpringEquilibrium
from .core.sweep_plot import ANTIROLL_METRICS, PLOT_METRICS
from .export.csv_report import write_csv_report
from .i18n import tr
from .model.project_io import load_project
from .model.templates import list_templates
from .ui.analysis_dialog import AnalysisDialog
from .ui.antiroll_dialog import AntiRollDialog
from .ui.damper_conversion_dialog import DamperConversionDialog
from .ui.equilibrium_dialog import EquilibriumDialog
from .ui.equilibrium_path_dialog import EquilibriumPathDialog
from .ui.main_window import MainWindow
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

    from .core.cad_recovery import recover_revolution_face
    from .core.cad_transport import CadJob

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
        path = Path(directory) / "fixture.step"
        unicode_path = Path(directory) / "проверка сборки.step"
        writer = STEPControl_Writer()
        _require(writer.Transfer(BRepPrimAPI_MakeBox(2., 3., 5.).Shape(),
                                 STEPControl_StepModelType.STEPControl_AsIs) == IFSelect_ReturnStatus.IFSelect_RetDone,
                 "Не удалось подготовить тестовый STEP")
        _require(writer.Write(str(path)) == IFSelect_ReturnStatus.IFSelect_RetDone,
                 "Не удалось записать тестовый STEP")
        path.rename(unicode_path)
        mesh = CadJob().run(unicode_path, 2., timeout=90)
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
    import numpy as np
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from .core.cad_measurement import measurement_distance, point_on_projected_triangle
    from .core.cad_mesh import CadMesh
    from .core.cad_raster import pick_triangle
    from .ui.canvas.cad_preview import CadPreview

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
    preview.reset_camera()
    _require((preview.pan_x, preview.pan_y) == (0., 0.), "Сброс камеры CAD-просмотра недоступен")
    preview.close()
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
        dialog = AnalysisDialog(window.controller, window)
        dialog.show()
        dialog._from.setValue(0)
        dialog._to.setValue(1)
        dialog._run.click()
        app.processEvents()
        _require(dialog._table.rowCount() == 2, "Таблица хода не рассчитана")
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
        _require("Точек на упоре или за ним: 2" in dialog._damper_range.toPlainText(),
                 "Сводка подбора амортизатора не выявила конфликт")
        dialog._candidate_min.setText("200")
        dialog._candidate_max.setText("500")
        dialog._candidate_reserve.setText("10")
        dialog._candidate_compare.click()
        _require("На упоре или за ним: 0" in dialog._candidate_result.toPlainText()
                 and "запас меньше заданного: 0" in dialog._candidate_result.toPlainText()
                 and dialog._table.rowCount() == 2, "Сравнение кандидата не выполнено")
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

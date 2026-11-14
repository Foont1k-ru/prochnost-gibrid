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

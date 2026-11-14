"""Ограниченная автоматическая проверка собранного приложения, не UI-валидация."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSettings

from .app import create_application
from .config import resources_dir
from .i18n import tr
from .model.project_io import load_project
from .model.templates import list_templates
from .ui.analysis_dialog import AnalysisDialog
from .ui.main_window import MainWindow


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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
        dialog._to.setValue(0)
        dialog._run.click()
        app.processEvents()
        _require(dialog._table.rowCount() == 1, "Таблица хода не рассчитана")
        camber = dialog._table.item(0, 1)
        if camber is None:
            raise RuntimeError("Не отображён развал")
        float(camber.text())
        _require(dialog._export_button.isEnabled(), "Результат анализа недоступен")
        project_path = window.controller.save_project(temporary / "test.susp.json")
        loaded = load_project(project_path, require_complete=True)
        _require(loaded.front.type_code == "double_wishbone", "Проект не восстановлен")
        dialog.close()
        window.close()
        app.processEvents()

"""Пути пользовательской конфигурации и настройки приложения.

Windows: ``%APPDATA%/SuspensionLab``.
Linux:   ``$XDG_CONFIG_HOME/SuspensionLab`` или ``~/.config/SuspensionLab``.
macOS:   ``~/Library/Application Support/SuspensionLab``.

Все данные хранятся локально; сетевые обращения отсутствуют полностью.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID


def _base_dir() -> Path:
    """Возвращает каталог данных приложения для текущей ОС."""
    if sys.platform == "win32":
        root = os.environ.get("APPDATA")
        if root:
            return Path(root) / APP_ID
        return Path.home() / "AppData" / "Roaming" / APP_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_ID
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_ID
    return Path.home() / ".config" / APP_ID


def app_data_dir() -> Path:
    """Каталог данных приложения (создаётся при обращении)."""
    path = _base_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    """Каталог журналов работы приложения."""
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file_path() -> Path:
    """Путь к основному файлу журнала."""
    return logs_dir() / "suspensionlab.log"


def autosave_path() -> Path:
    """Путь к файлу автосохранения текущего проекта."""
    return app_data_dir() / "autosave.susp.json"


def settings_path() -> Path:
    """Путь к ini-файлу пользовательских настроек (тема, единицы, окно)."""
    return app_data_dir() / "settings.ini"


def resources_dir() -> Path:
    """Каталог ресурсов в комплекте поставки (темы, локализация, шаблоны)."""
    return Path(__file__).resolve().parent / "resources"

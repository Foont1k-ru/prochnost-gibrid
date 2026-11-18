"""Темы оформления: тёмная и светлая.

Цвета интерфейса задаются таблицами стилей Qt (``resources/themes``),
палитра виджетов и цвета схемы — здесь. Внешних шрифтов и иконок нет:
используется системный шрифт, все значки — стандартные средства Qt или
векторная отрисовка.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..config import resources_dir

#: Доступные темы.
THEMES = ("dark", "light")


@dataclass(frozen=True, slots=True)
class CanvasColors:
    """Цвета схемы подвески."""

    background: str
    grid: str
    grid_major: str
    ground: str
    axis: str
    body: str
    link: str
    link_selected: str
    upright: str
    wheel: str
    wheel_fill: str
    spring: str
    damper: str
    point: str
    point_selected: str
    point_locked: str
    label: str
    hint: str
    marker: str


#: Цвета схемы для каждой темы (спокойная инженерная палитра).
CANVAS_COLORS: dict[str, CanvasColors] = {
    "dark": CanvasColors(
        background="#1e2228",
        grid="#2b3138",
        grid_major="#39414b",
        ground="#6b7683",
        axis="#4c5a68",
        body="#5f6b7a",
        link="#5fa8ff",
        link_selected="#ffc857",
        upright="#9fb4cc",
        wheel="#c3ccd8",
        wheel_fill="#2f3a46",
        spring="#7fd1a0",
        damper="#d1a07f",
        point="#e8edf3",
        point_selected="#ffc857",
        point_locked="#ff8a80",
        label="#c7d1dc",
        hint="#8a97a5",
        marker="#ff6b6b",
    ),
    "light": CanvasColors(
        background="#f7f8fa",
        grid="#e3e7ec",
        grid_major="#cfd6de",
        ground="#495057",
        axis="#9aa6b2",
        body="#7b8794",
        link="#1c6dd0",
        link_selected="#c77700",
        upright="#3d4c5c",
        wheel="#4a5560",
        wheel_fill="#e9edf2",
        spring="#1f8a4c",
        damper="#a35f26",
        point="#27313b",
        point_selected="#c77700",
        point_locked="#c62828",
        label="#3d4c5c",
        hint="#6b7783",
        marker="#c62828",
    ),
}


def canvas_colors(theme: str) -> CanvasColors:
    """Цвета схемы для темы (по умолчанию — тёмная)."""
    return CANVAS_COLORS.get(theme, CANVAS_COLORS["dark"])


def _palette(theme: str) -> QPalette:
    """Палитра Qt для темы."""
    dark = theme == "dark"
    palette = QPalette()
    window = QColor("#20242a") if dark else QColor("#f2f4f7")
    base = QColor("#171a1f") if dark else QColor("#ffffff")
    text = QColor("#e6ebf1") if dark else QColor("#1d2530")
    disabled = QColor("#6b7683") if dark else QColor("#9aa4b0")
    highlight = QColor("#2f6fd0") if dark else QColor("#1c6dd0")
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#262b32") if dark else QColor("#eef1f5"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor("#2a3038") if dark else QColor("#e7ebf0"))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2a3038") if dark else QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, highlight)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    return palette


def apply_theme(app: QApplication, theme: str) -> None:
    """Применяет тему к приложению: палитра + таблица стилей."""
    name = theme if theme in THEMES else "dark"
    app.setPalette(_palette(name))
    path = resources_dir() / "themes" / f"{name}.qss"
    try:
        app.setStyleSheet(path.read_text(encoding="utf-8"))
    except OSError:
        app.setStyleSheet("")

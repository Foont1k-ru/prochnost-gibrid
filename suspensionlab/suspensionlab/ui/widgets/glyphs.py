"""Подбор символов для интерфейса с учётом возможностей шрифта.

В комплекте нет внешних иконочных шрифтов (требование офлайн-поставки),
поэтому используются обычные символы Unicode. Если выбранный системный
шрифт не содержит нужного символа, подставляется текстовый заменитель —
интерфейс остаётся читаемым на любой ОС (в том числе в headless-тестах).

Значения вычисляются при первом обращении: до создания QApplication
шрифтовой базы ещё нет, поэтому модуль экспортирует имена лениво
(механизм ``__getattr__`` модуля, PEP 562).
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

#: Имя -> (желаемый символ, запасной текст).
_SYMBOLS: dict[str, tuple[str, str]] = {
    "LOCK": ("🔒", "■"),
    "UNLOCK": ("🔓", "□"),
    "RESET": ("↺", "R"),
    "MORE": ("⋯", "..."),
    "INFO": ("ⓘ", "i"),
    "STATUS_OK": ("🟢", "●"),
    "STATUS_WARN": ("🟡", "▲"),
    "STATUS_ERROR": ("🔴", "▮"),
}

_cache: dict[str, str] = {}


def glyph(preferred: str, fallback: str) -> str:
    """Возвращает ``preferred``, если все символы есть в шрифте, иначе ``fallback``."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        # до создания QApplication шрифтовой базы нет — используем заменитель
        return fallback
    metrics = QFontMetrics(QFont(app.font()))
    for char in preferred:
        if not metrics.inFontUcs4(ord(char)):
            return fallback
    return preferred


def __getattr__(name: str) -> str:
    """Ленивая выдача символов по имени константы."""
    if name in _SYMBOLS:
        if name not in _cache:
            preferred, fallback = _SYMBOLS[name]
            _cache[name] = glyph(preferred, fallback)
        return _cache[name]
    raise AttributeError(name)

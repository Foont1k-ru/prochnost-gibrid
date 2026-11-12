"""Журналирование работы приложения в файл и в консоль.

Журнал пишется в ``%APPDATA%/SuspensionLab/logs/suspensionlab.log``
с ротацией (5 файлов по 1 МБ). В интерфейсе пользователю показываются
только понятные сообщения; технические подробности остаются в журнале,
который можно открыть из меню «Справка → Открыть журнал».
"""

from __future__ import annotations

import logging
import logging.handlers
import os

from .config import log_file_path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"
_configured = False


def setup_logging(level: int | None = None) -> logging.Logger:
    """Настраивает корневой журнал (идемпотентно) и возвращает его."""
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    if level is None:
        level = logging.DEBUG if os.environ.get("SUSPENSIONLAB_DEBUG") else logging.INFO
    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path(), maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
    except OSError:  # защита от файловой системы только для чтения
        file_handler = None
    if file_handler is not None:
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(max(level, logging.INFO))
    root.addHandler(console)

    _configured = True
    root.debug("Журналирование запущено, уровень %s", logging.getLevelName(level))
    return root

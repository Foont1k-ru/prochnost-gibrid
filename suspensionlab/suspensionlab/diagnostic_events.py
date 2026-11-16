"""Ограниченный локальный журнал событий; не содержит пользовательских текстов.

Это не трассировка действий и не доказательство корректности расчётов. Каждый
вызов использует только контролируемые коды и агрегированные счётчики.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import re
import secrets
from pathlib import Path

from .config import diagnostic_log_path

_LOG = logging.getLogger("suspensionlab.events")
_LOG.propagate = False
_LOG.addHandler(logging.NullHandler())
_SESSION = secrets.token_hex(6)
_TOKEN = re.compile(r"[A-Za-z0-9_.+-]{1,80}\Z")
_EVENTS: dict[str, frozenset[str]] = {
    "session.start": frozenset({"app", "python", "pyside", "os", "arch", "frozen"}),
    "session.end": frozenset({"exit_code"}),
    "session.exception": frozenset({"error_type"}),
    "project.open": frozenset({"result", "error_code"}),
    "project.save": frozenset({"result", "error_code"}),
    "project.recovery": frozenset({"result"}),
    "project.autosave": frozenset({"result"}),
    "cad.start": frozenset({"operation", "deviation_um"}),
    "cad.result": frozenset({"operation", "result", "duration_ms", "faces", "skipped", "recovered", "triangles"}),
    "inventory.start": frozenset({"operation"}),
    "inventory.result": frozenset({"operation", "result", "duration_ms", "products", "occurrences", "unresolved"}),
    "antiroll.result": frozenset({"axis", "result", "rows", "missing"}),
    "equilibrium.result": frozenset({"axis", "side", "result", "samples", "failure_kind"}),
    "analysis.start": frozenset({"axis", "side", "spring", "damper"}),
    "analysis.result": frozenset({"axis", "side", "result", "rows", "missing", "spring_conflicts", "damper_conflicts", "frames_missing"}),
    "points.import": frozenset({"result", "reason", "points", "cells"}),
    "points.apply": frozenset({"result", "points", "cells"}),
}
_configured = False


def setup_event_logging(path: Path | None = None) -> bool:
    """Создаёт журнал с ротацией; ошибка записи не останавливает работу."""
    global _configured
    if _configured:
        return True
    try:
        handler = logging.handlers.RotatingFileHandler(
            path if path is not None else diagnostic_log_path(),
            maxBytes=1_000_000, backupCount=5, encoding="utf-8",
        )
    except OSError:
        logging.getLogger(__name__).warning("Журнал событий недоступен")
        return False
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _configured = True
    return True


def event(name: str, *, warning: bool = False, **fields: str | int | bool) -> None:
    """Записывает только предусмотренные поля и простые токены, без путей или текста исключений."""
    allowed = _EVENTS.get(name)
    if allowed is None or not fields.keys() <= allowed:
        return
    for value in fields.values():
        if isinstance(value, str):
            if not _TOKEN.fullmatch(value):
                return
        elif not isinstance(value, (int, bool)):
            return
    record = {"session": _SESSION, "event": name, **fields}
    _LOG.log(logging.WARNING if warning else logging.INFO, json.dumps(record, ensure_ascii=False, separators=(",", ":")))

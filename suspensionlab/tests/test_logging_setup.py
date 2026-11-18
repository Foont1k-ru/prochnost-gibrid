"""Журнал работает и в оконной сборке Windows без stderr."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

from suspensionlab import logging_setup


@pytest.mark.parametrize("with_console", [False, True])
def test_file_logging_with_and_without_stderr(tmp_path: Path, monkeypatch, with_console: bool) -> None:
    logger = logging.Logger("isolated")
    stream = io.StringIO() if with_console else None
    monkeypatch.setattr(logging_setup, "_configured", False)
    monkeypatch.setattr(logging_setup.logging, "getLogger", lambda: logger)
    monkeypatch.setattr(logging_setup, "log_file_path", lambda: tmp_path / "application.log")
    monkeypatch.setattr(logging_setup.sys, "stderr", stream)
    try:
        assert logging_setup.setup_logging() is logger
        assert logging_setup.setup_logging() is logger
        logger.warning("тест диагностики")
        for handler in logger.handlers:
            handler.flush()
        assert "тест диагностики" in (tmp_path / "application.log").read_text(encoding="utf-8")
        assert len(logger.handlers) == 1 + int(with_console)
        if stream is not None:
            assert "тест диагностики" in stream.getvalue()
    finally:
        for handler in logger.handlers:
            handler.close()

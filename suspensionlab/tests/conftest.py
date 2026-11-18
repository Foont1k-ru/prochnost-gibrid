"""Общая настройка тестов: headless-режим Qt и изоляция пользовательских данных."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Qt работает без графической сессии (в CI и в песочнице нет дисплея).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Настройки и журналы пишутся во временный каталог, а не в домашний.
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="suspensionlab-tests-"))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def qapp():
    """Единый QApplication на всю сессию тестов."""
    from suspensionlab.app import create_application

    app = create_application([])
    yield app


@pytest.fixture()
def project():
    """Проект из шаблона «Кольцо» (реальные координаты из комплекта поставки)."""
    from suspensionlab.model.templates import load_template

    return load_template("ring")

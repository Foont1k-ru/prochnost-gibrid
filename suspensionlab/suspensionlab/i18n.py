"""Локализация интерфейса.

Все пользовательские строки хранятся в ``resources/i18n/<язык>.json`` и
достаются по точечному ключу (``menu.file``, ``hp.ubj.name`` …). В коде
GUI кириллических литералов быть не должно — это проверяется тестом
``tests/test_i18n.py``.

Структура файла локализации повторяет структуру ключей: вложенные
словари, на нижнем уровне — строки. В строки разрешена подстановка
именованных параметров в стиле ``{name}``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import resources_dir

#: Язык по умолчанию (и единственный, поставляемый с M0).
DEFAULT_LANGUAGE = "ru"

#: Поддерживаемые языки: код -> ключ названия языка для меню.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("ru",)


class Translator:
    """Загрузчик и поставщик переведённых строк."""

    def __init__(self, language: str = DEFAULT_LANGUAGE, directory: Path | None = None) -> None:
        self._directory = directory or (resources_dir() / "i18n")
        self._language = language
        self._strings: dict[str, Any] = {}
        self._fallback: dict[str, Any] = {}
        self._missing: set[str] = set()
        self.load(language)

    # ------------------------------------------------------------------ загрузка
    def load(self, language: str) -> None:
        """Загружает файл локализации; при ошибке остаётся прежний словарь."""
        self._language = language
        self._strings = self._read(language)
        if language != DEFAULT_LANGUAGE:
            self._fallback = self._read(DEFAULT_LANGUAGE)
        else:
            self._fallback = {}

    def _read(self, language: str) -> dict[str, Any]:
        """Читает файл локализации и «сплющивает» его в словарь точечных ключей.

        Ключи в JSON можно писать как вложенными, так и плоскими строками
        с точками (``"file.new"``) — оба варианта дают один и тот же ключ
        ``menu.file.new``. Это удобно для больших файлов локализации.
        """
        path = self._directory / f"{language}.json"
        if not path.is_file():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        flat: dict[str, Any] = {}
        self._flatten(raw, "", flat)
        return flat

    @classmethod
    def _flatten(cls, tree: Any, prefix: str, target: dict[str, Any]) -> None:
        """Рекурсивно превращает вложенный словарь в плоский набор ключей."""
        if isinstance(tree, dict):
            for key, value in tree.items():
                full = f"{prefix}.{key}" if prefix else str(key)
                cls._flatten(value, full, target)
        elif isinstance(tree, str):
            target[prefix] = tree

    # ------------------------------------------------------------------ доступ
    @property
    def language(self) -> str:
        """Текущий код языка."""
        return self._language

    def has(self, key: str) -> bool:
        """Есть ли ключ в текущем словаре (или в резервном)."""
        return self._lookup(self._strings, key) is not None or self._lookup(self._fallback, key) is not None

    def tr(self, key: str, **params: object) -> str:
        """Возвращает строку по ключу с подстановкой параметров.

        Если ключ отсутствует, возвращается сам ключ в угловых скобках —
        так недостающий перевод сразу виден на экране и в тестах
        (тест ``test_i18n_keys_exist`` не даёт такому случиться).
        """
        value = self._lookup(self._strings, key)
        if value is None:
            value = self._lookup(self._fallback, key)
        if value is None:
            self._missing.add(key)
            return f"‹{key}›"
        if params:
            try:
                return value.format(**params)
            except (KeyError, IndexError):
                return value
        return value

    def missing_keys(self) -> frozenset[str]:
        """Ключи, которых не нашлось при работе (для диагностики)."""
        return frozenset(self._missing)

    @staticmethod
    def _lookup(tree: dict[str, Any], key: str) -> str | None:
        """Прямой поиск строки по точечному ключу в плоском словаре."""
        value = tree.get(key)
        return value if isinstance(value, str) else None


_translator: Translator | None = None


def translator() -> Translator:
    """Глобальный переводчик (создаётся при первом обращении)."""
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def tr(key: str, **params: object) -> str:
    """Сокращение для ``translator().tr(...)``."""
    return translator().tr(key, **params)


def set_language(language: str) -> None:
    """Переключает язык интерфейса."""
    translator().load(language)

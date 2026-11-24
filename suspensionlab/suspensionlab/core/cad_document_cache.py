"""Ограниченный кеш проверенных сеток по полному временному CAD-документу.

Никаких предположений о числе деталей. Ключ и сетка остаются в памяти окна;
кеш не проверяет проект/файлы и не заменяет проверку актуальности вызывающим кодом.
"""
from __future__ import annotations

import json
import math
from collections import OrderedDict
from typing import Any

from .cad_cache import mesh_bytes
from .cad_mesh import CadMesh

DOCUMENT_BYTES = 128 * 1024
DOCUMENT_NODES = 100_000
DOCUMENT_DEPTH = 64
CACHE_BYTES = 16 * 1024 * 1024
CACHE_ENTRIES = 8
CacheKey = tuple[bytes, float]


def document_key(document: dict[str, Any], deviation: float) -> CacheKey | None:
    """Только точные JSON-типы; сомнительные или большие документы не кешируются.

    Порядок словарей намеренно сохраняется: лишний промах безопаснее ложного
    совпадения. Не используются хеши, скрытые поля или ссылки на исходный объект.
    """
    if type(document) is not dict or not math.isfinite(deviation) or deviation <= 0:
        return None
    stack: list[tuple[Any, int]] = [(document, 0)]
    seen: set[int] = set()
    nodes = chars = 0
    try:
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if nodes > DOCUMENT_NODES or depth > DOCUMENT_DEPTH:
                return None
            kind = type(value)
            if kind in (dict, list):
                if len(value) > DOCUMENT_NODES - nodes:
                    return None
                # Cycles and shared mutable containers are deliberately uncacheable.
                identity = id(value)
                if identity in seen:
                    return None
                seen.add(identity)
                if kind is dict:
                    if any(type(key) is not str for key in value):
                        return None
                    chars += sum(len(key) for key in value)
                    stack.extend((item, depth + 1) for item in value.values())
                else:
                    stack.extend((item, depth + 1) for item in value)
            elif kind is str:
                chars += len(value)
            elif kind is int:
                if value.bit_length() > 256:
                    return None
            elif kind is float:
                if not math.isfinite(value):
                    return None
            elif kind not in (bool, type(None)):
                return None
            if chars > DOCUMENT_BYTES:
                return None
        data = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError, RuntimeError, UnicodeError, MemoryError):
        return None
    return (data, float(deviation)) if len(data) <= DOCUMENT_BYTES else None


def copy_mesh(mesh: CadMesh) -> CadMesh:
    """Отдельное владение массивами и повторная проверка при помещении/извлечении."""
    return CadMesh(mesh.triangles, mesh.face_count, mesh.skipped_faces, mesh.recovered_faces,
                   mesh.part_names, mesh.triangle_parts, mesh.instance_groups, mesh.triangle_instances)


class DocumentMeshCache:
    """LRU до 8 результатов; бюджет — массивы и байты ключей, не вся память Qt."""

    def __init__(self, budget: int = CACHE_BYTES, entries: int = CACHE_ENTRIES) -> None:
        if budget < 0 or entries < 0:
            raise ValueError('cache limits')
        self.budget, self.entries = budget, entries
        self._items: OrderedDict[CacheKey, CadMesh] = OrderedDict()
        self._bytes = 0

    def get(self, key: CacheKey) -> CadMesh | None:
        mesh = self._items.get(key)
        if mesh is None:
            return None
        try:
            result = copy_mesh(mesh)
        except (MemoryError, ValueError):
            self.discard(key)
            return None
        self._items.move_to_end(key)
        return result

    def discard(self, key: CacheKey) -> None:
        mesh = self._items.pop(key, None)
        if mesh is not None:
            self._bytes -= len(key[0]) + mesh_bytes(mesh)

    def put(self, key: CacheKey, mesh: CadMesh) -> None:
        self.discard(key)
        size = len(key[0]) + mesh_bytes(mesh)
        if not self.entries or size > self.budget:
            return
        try:
            saved = copy_mesh(mesh)
        except (MemoryError, ValueError):
            return
        while self._items and (self._bytes + size > self.budget or len(self._items) >= self.entries):
            oldest = next(iter(self._items))
            self.discard(oldest)
        self._items[key] = saved
        self._bytes += size

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0

"""Временная проверка известных источников поверхностных CAD-точек.

Хеш относится к содержимому на момент построения сетки; ручные данные и
последующие изменения файлов не проверяются. Идентификаторы нигде не записываются.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceSummary:
    known_points: int
    unknown_points: int
    distinct_sources: int

    @property
    def has_conflict(self) -> bool:
        return self.distinct_sources > 1


def summarize_sources(digests: tuple[bytes | None, ...]) -> SourceSummary:
    if any(value is not None and (not isinstance(value, bytes) or len(value) != 32) for value in digests):
        raise ValueError("digest")
    known = [value for value in digests if value is not None]
    return SourceSummary(len(known), len(digests) - len(known), len(set(known)))

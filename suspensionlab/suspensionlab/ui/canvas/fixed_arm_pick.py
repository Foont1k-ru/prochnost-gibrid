"""Однозначный выбор прямой ветви по экранной проекции, без угадывания глубины."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF

from ...core.pose_view import Point


def straight_leg_hits(position: QPointF, paths: tuple[tuple[Point, ...], ...],
                      project: Callable[[Point], QPointF]) -> list[tuple[str, Point]]:
    hits: list[tuple[str, Point]] = []
    for leg, path in zip(('front', 'rear'), paths, strict=True):
        # У одной ветви пока только одна вершина. Не предлагаем вставку поверх дуги.
        if len(path) != 2:
            continue
        a, b = path
        pa, pb = project(a), project(b)
        dx, dy = pb.x() - pa.x(), pb.y() - pa.y()
        square = dx * dx + dy * dy
        if square < 1:
            continue
        t = ((position.x() - pa.x()) * dx + (position.y() - pa.y()) * dy) / square
        if not 0.05 < t < 0.95:
            continue
        distance2 = (pa.x() + t * dx - position.x()) ** 2 + (pa.y() + t * dy - position.y()) ** 2
        if distance2 <= 9 ** 2:
            point: Point = tuple(a[i] + t * (b[i] - a[i]) for i in range(3))  # type: ignore[assignment]
            hits.append((leg, point))
    return hits

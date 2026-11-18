"""Выбор связей по проекции осевых линий, без вывода о видимости/коллизиях."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .pose_view import Point
from .scene3d import project_orthographic
from .vehicle_schematic_scene import SelectableLink


@dataclass(frozen=True, slots=True)
class LinkHit:
    role: str
    code: str
    distance_px: float


def projected_link_hits(
    links: tuple[SelectableLink, ...], *, center: Point, yaw: float, elevation: float,
    scale: float, origin: tuple[float, float], click: tuple[float, float], tolerance_px: float,
) -> tuple[LinkHit, ...]:
    """Все связи в пределах допуска; совпадающие ветви и стороны объединяются.

    Порядок — от ближайшей линии в пикселях, а не по глубине. Никакой
    гарантии выбора видимой поверхности: пересечения показываются списком.
    """
    if not all(math.isfinite(x) for x in (*center, yaw, elevation, scale, *origin, *click, tolerance_px)):
        raise ValueError('non-finite projection')
    if scale <= 0 or tolerance_px < 0:
        raise ValueError('invalid projection scale or tolerance')
    found: dict[tuple[str, str], float] = {}
    for link in links:
        u, v = (project_orthographic(p, center, yaw, elevation) for p in (link.segment.start, link.segment.end))
        a = (origin[0] + u[0] * scale, origin[1] - u[1] * scale)
        b = (origin[0] + v[0] * scale, origin[1] - v[1] * scale)
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = max(0., min(1., ((click[0] - a[0]) * dx + (click[1] - a[1]) * dy) / length2)) if length2 else 0.
        distance = math.hypot(click[0] - a[0] - t * dx, click[1] - a[1] - t * dy)
        key = (link.role, link.code)
        if distance <= tolerance_px:
            found[key] = min(found.get(key, float('inf')), distance)
    return tuple(LinkHit(role, code, distance) for (role, code), distance in sorted(
        found.items(), key=lambda item: (item[1], item[0])))

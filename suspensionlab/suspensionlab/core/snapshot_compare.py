"""Сравнение исходной схемы со снимком, без восстановления или расчёта хода."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..model.entities import Axle, Project
from ..model.point_csv import PointRecord, capture_points
from ..model.suspension_types import LinkSpec
from .geometry import axis_length

Point = tuple[float, float, float]
Status = Literal["changed", "unchanged", "added", "removed", "incompatible", "invalid"]


@dataclass(frozen=True, slots=True)
class PointComparison:
    role: str
    code: str
    old_type: str
    new_type: str
    old: PointRecord | None
    new: PointRecord | None
    status: Status
    delta: Point | None
    distance: float | None


@dataclass(frozen=True, slots=True)
class LinkComparison:
    role: str
    code: str
    old_type: str
    new_type: str
    old_exists: bool
    new_exists: bool
    old_length: float | None
    new_length: float | None
    status: Status
    delta: float | None


@dataclass(frozen=True, slots=True)
class SnapshotComparison:
    points: tuple[PointComparison, ...]
    links: tuple[LinkComparison, ...]


def _finite_point(point: PointRecord | None) -> bool:
    return point is None or all(math.isfinite(value) for value in point.xyz)


def _link_length(axle: Axle, spec: LinkSpec | None) -> float | None:
    if spec is None or not 1 <= len(spec.pivot) <= 2:
        return None
    codes = (*spec.pivot, spec.end)
    if any(code not in axle.hardpoints for code in codes):
        return None
    points = [axle.hardpoints[code].as_tuple() for code in codes]
    if not all(math.isfinite(value) for point in points for value in point):
        return None
    if len(spec.pivot) == 2 and math.dist(points[0], points[1]) < 1e-9:
        return None
    value = axis_length(points)
    return value if math.isfinite(value) else None


def compare_projects(reference: Project, current: Project) -> SnapshotComparison:
    """Значения локальны для оси; одноимённые коды разных типов не сопоставляются.

    Порядок: текущие коды по реестру, затем только бывшие; максимум с равенством
    выбирает первый в этом порядке. Отсутствующие и неконечные значения не равны нулю.
    """
    old_points = {(p.role, p.code): p for p in capture_points(reference)}
    new_points = {(p.role, p.code): p for p in capture_points(current)}
    point_rows = []
    link_rows = []
    for role in ("front", "rear"):
        old_axle, new_axle = reference.axle(role), current.axle(role)
        old_type, new_type = old_axle.type_code, new_axle.type_code
        keys = list(dict.fromkeys([*(k for k in new_points if k[0] == role), *(k for k in old_points if k[0] == role)]))
        for key in keys:
            old, new = old_points.get(key), new_points.get(key)
            delta: Point | None = None
            dist: float | None = None
            status: Status
            if not _finite_point(old) or not _finite_point(new):
                status = "invalid"
            elif old is None:
                status = "added"
            elif new is None:
                status = "removed"
            elif old_type != new_type or old.representation != new.representation:
                status = "incompatible"
            else:
                d = tuple(new.xyz[i] - old.xyz[i] for i in range(3))
                length = math.hypot(*d)
                if not all(math.isfinite(v) for v in d) or not math.isfinite(length):
                    status = "invalid"
                else:
                    delta = (d[0], d[1], d[2])
                    dist = length
                    status = "changed" if any(v != 0 for v in delta) else "unchanged"
            point_rows.append(PointComparison(role, key[1], old_type, new_type, old, new, status, delta, dist))
        old_specs = {spec.code: spec for spec in old_axle.spec.links}
        new_specs = {spec.code: spec for spec in new_axle.spec.links}
        for code in dict.fromkeys([*new_specs, *old_specs]):
            old_spec, new_spec = old_specs.get(code), new_specs.get(code)
            old_length, new_length = _link_length(old_axle, old_spec), _link_length(new_axle, new_spec)
            link_delta: float | None = None
            if (old_spec is not None and old_length is None) or (new_spec is not None and new_length is None):
                status = "invalid"
            elif old_spec is None:
                status = "added"
            elif new_spec is None:
                status = "removed"
            elif old_type != new_type or old_spec.pivot != new_spec.pivot or old_spec.end != new_spec.end:
                status = "incompatible"
            else:
                assert old_length is not None and new_length is not None
                difference = new_length - old_length
                if not math.isfinite(difference):
                    status = "invalid"
                else:
                    link_delta = difference
                    status = "changed" if difference != 0 else "unchanged"
            link_rows.append(LinkComparison(role, code, old_type, new_type, old_spec is not None, new_spec is not None,
                                             old_length, new_length, status, link_delta))
    return SnapshotComparison(tuple(point_rows), tuple(link_rows))


def max_point_displacement(rows: tuple[PointComparison, ...]) -> int | None:
    available = [(i, row.distance) for i, row in enumerate(rows) if row.distance is not None]
    return max(available, key=lambda pair: pair[1])[0] if available else None


def max_link_delta(rows: tuple[LinkComparison, ...]) -> int | None:
    available = [(i, abs(row.delta)) for i, row in enumerate(rows) if row.delta is not None]
    return max(available, key=lambda pair: pair[1])[0] if available else None

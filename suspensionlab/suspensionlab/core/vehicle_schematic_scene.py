"""Статический 3D-каркас проекта для просмотра; это не CAD или расчёт движения."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..model.entities import Axle, Project
from .pose_view import Point
from .scene3d import Scene3D, Segment3D, SegmentKind

MAX_COORDINATE_MM = 1_000_000.0


@dataclass(frozen=True)
class VehicleSchematic:
    scene: Scene3D
    missing: tuple[str, ...]


def _finite(value: float, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('invalid schematic value')
    number = float(value)
    if not math.isfinite(number) or abs(number) > MAX_COORDINATE_MM or (positive and number <= 0):
        raise ValueError('invalid schematic value')
    return number


def vehicle_schematic_scene(project: Project) -> VehicleSchematic:
    """Линии связей и габариты колёс по схеме; задняя ось сдвинута на базу по −X.

    Отдельные стороны осей с явными точками не зеркалируются. Пружины и
    амортизаторы — прямые линии, колесо — условный вертикальный цилиндр без
    углов установки. Отсутствующие связи перечислены, физики и CAD здесь нет.
    """
    wheelbase = _finite(project.vehicle.wheelbase_mm, positive=True)
    segments: list[Segment3D] = []
    points: list[tuple[str, Point]] = []
    missing: list[str] = []

    def transform(p: tuple[float, float, float], offset: float, side: float) -> Point:
        x, y, z = (_finite(value) for value in p)
        transformed = (x + offset, y * side, z)
        if any(abs(value) > MAX_COORDINATE_MM for value in transformed):
            raise ValueError('schematic coordinates out of range')
        return transformed

    def pair(axle: Axle, first: str, second: str, side: float) -> tuple[Point, Point] | None:
        suffix = ('_l' if side > 0 else '_r') if axle.has_explicit_sides else ''
        a, b = axle.hardpoints.get(first + suffix), axle.hardpoints.get(second + suffix)
        if a is None or b is None:
            return None
        offset = -wheelbase if axle.role == 'rear' else 0.0
        mirror = 1.0 if axle.has_explicit_sides else side
        return transform(a.as_tuple(), offset, mirror), transform(b.as_tuple(), offset, mirror)

    for axle in (project.front, project.rear):
        offset = -wheelbase if axle.role == 'rear' else 0.0
        sides = (1.0,) if axle.has_explicit_sides else (1.0, -1.0)
        for spec in axle.spec.links:
            if spec.code in ('driveshaft', 'driveshaft_to_differential'):
                continue
            if spec.group == 'drivetrain' and not axle.drivetrain.driven:
                continue
            if any(code not in axle.hardpoints for code in (*spec.pivot, spec.end)):
                missing.append(f'{axle.role}:{spec.code}')
                continue
            for side in sides:
                for start, end in axle.link_endpoints(spec.code):
                    a, b = transform(start, offset, side), transform(end, offset, side)
                    if math.dist(a, b) < 1e-9:
                        missing.append(f'{axle.role}:{spec.code}')
                        continue
                    kind: SegmentKind = 'steering' if spec.group == 'steering' else 'arm'
                    segments.append(Segment3D(a, b, kind))
        for point_spec in axle.spec.points:
            if point_spec.code == 'driveshaft_front' or (point_spec.group == 'drivetrain' and not axle.drivetrain.driven):
                continue
            point = axle.hardpoints.get(point_spec.code)
            if point is None:
                missing.append(f'{axle.role}:{point_spec.code}')
                continue
            for side in sides:
                side_name = point_spec.side if axle.has_explicit_sides else ("left" if side > 0 else "right")
                point_code = f"{axle.role}:{point_spec.code}:{side_name}"
                points.append((point_code, transform(point.as_tuple(), offset, side)))
        for first, last, kind in (('spring_lo', 'spring_up', 'spring'), ('damper_lo', 'damper_up', 'damper')):
            for side in (1.0, -1.0):
                ends = pair(axle, first, last, side)
                if ends is not None:
                    if math.dist(*ends) < 1e-9:
                        missing.append(f"{axle.role}:{first}:{side:g}")
                    else:
                        segments.append(Segment3D(ends[0], ends[1], kind))  # type: ignore[arg-type]
        radius = _finite(axle.wheel.r_dynamic_mm, positive=True)
        width = _finite(axle.wheel.width_mm, positive=True)
        for side in (1.0, -1.0):
            wheel_code = ('wheel_center_l' if side > 0 else 'wheel_center_r') if axle.has_explicit_sides else axle.wheel_center_code()
            center = axle.hardpoints.get(wheel_code) if wheel_code else None
            if center is None:
                missing.append(f'{axle.role}:wheel_center:{side:g}')
                continue
            x, y, z = transform(center.as_tuple(), offset, 1.0 if axle.has_explicit_sides else side)
            rings: list[list[Point]] = []
            for sign in (-1, 1):
                ring = [(x + radius * math.cos(2 * math.pi * i / 24), y + sign * width / 2,
                         z + radius * math.sin(2 * math.pi * i / 24)) for i in range(24)]
                if any(abs(v) > MAX_COORDINATE_MM for vertex in ring for v in vertex):
                    raise ValueError('wheel exceeds display limits')
                rings.append(ring)
                segments.extend(Segment3D(ring[i], ring[(i + 1) % 24], 'wheel') for i in range(24))
            segments.extend(Segment3D(rings[0][i], rings[1][i], 'wheel') for i in range(0, 24, 4))
    return VehicleSchematic(Scene3D(0.0, tuple(segments), tuple(points)), tuple(sorted(set(missing))))

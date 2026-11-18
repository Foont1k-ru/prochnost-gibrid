"""Осевые эскизные виды снимка .kima; не HLR, не чертёж и не замер CAD."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .scheme_arm_assembly import PLATE_VERSION, validate_scheme_arm_assembly

Point3 = tuple[float, float, float]
Point2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Line3:
    start: Point3
    end: Point3
    kind: str


@dataclass(frozen=True, slots=True)
class ReferenceDimension:
    label: str
    value_mm: float


@dataclass(frozen=True, slots=True)
class AssemblyViews:
    lines: tuple[Line3, ...]
    dimensions: tuple[ReferenceDimension, ...]
    axis: str
    has_plate: bool

    def project(self, plane: str) -> tuple[tuple[Point2, Point2, str], ...]:
        axes = {'XY': (0, 1), 'XZ': (0, 2), 'YZ': (1, 2)}
        if plane not in axes:
            raise ValueError('unknown projection')
        u, v = axes[plane]
        return tuple(((s.start[u], s.start[v]), (s.end[u], s.end[v]), s.kind) for s in self.lines)


def assembly_views(document: dict[str, Any]) -> AssemblyViews:
    """Центральные линии труб/корпусов и контур средней плоскости пластины.

    Числа — введённые размеры и длины осей по округлённым сохранённым точкам;
    это не габариты, не контуры труб/корпусов и не результаты CAD-проекции.
    Невидимые линии не удаляются, контакты и подрезки не определяются.
    """
    validate_scheme_arm_assembly(document)
    parts = document['parts']
    points = [tuple(float(x) for x in p) for p in parts[0]['geometry']['source']['coordinates_mm']]
    lines: list[Line3] = []
    dimensions: list[ReferenceDimension] = []
    for index, title in enumerate(('Передняя труба', 'Задняя труба')):
        geom = parts[index]['geometry']
        a, b = points[index], points[2]
        lines.append(Line3(a, b, 'tube'))  # type: ignore[arg-type]
        dimensions.extend((ReferenceDimension(f'{title}: расстояние между центрами', math.dist(a, b)),
                           ReferenceDimension(f'{title}: наружный диаметр', 2 * geom['radius_mm']),
                           ReferenceDimension(f'{title}: стенка', geom['wall_mm'])))
    axis = document['axis']
    index = {'x': 0, 'y': 1, 'z': 2}[axis]
    for part, center, title in zip(parts[2:4], points[:2], ('Передний корпус', 'Задний корпус'), strict=True):
        geom = part['geometry']
        start, end = list(center), list(center)
        start[index] -= geom['length_mm'] / 2
        end[index] += geom['length_mm'] / 2
        lines.append(Line3(tuple(start), tuple(end), 'housing'))  # type: ignore[arg-type]
        dimensions.extend((ReferenceDimension(f'{title}: длина', geom['length_mm']),
                           ReferenceDimension(f'{title}: наружный диаметр', 2 * geom['outer_radius_mm']),
                           ReferenceDimension(f'{title}: диаметр отверстия', 2 * geom['bore_radius_mm'])))
    if document['version'] == PLATE_VERSION:
        plate = parts[4]['geometry']
        placement = document['plate_placement']
        origin = tuple(points[2][i] + placement['offset_mm'][i] for i in range(3))
        # Matches the rigid rotations used in build_scheme_arm_assembly_preview.
        basis = {'x': ((0., 0., -1.), (0., 1., 0.)),
                 'y': ((1., 0., 0.), (0., 0., -1.)),
                 'z': ((1., 0., 0.), (0., 1., 0.))}[placement['normal']]
        def in_plane(u: float, v: float) -> Point3:
            return tuple(origin[i] + u * basis[0][i] + v * basis[1][i] for i in range(3))  # type: ignore[return-value]
        w, h = plate['width_mm'] / 2, plate['height_mm'] / 2
        corners = (in_plane(-w, -h), in_plane(w, -h), in_plane(w, h), in_plane(-w, h))
        lines.extend(Line3(corners[i], corners[(i + 1) % 4], 'plate') for i in range(4))
        count = 32
        r = plate['hole_radius_mm']
        circle = tuple(in_plane(r * math.cos(2 * math.pi * i / count),
                                r * math.sin(2 * math.pi * i / count)) for i in range(count))
        lines.extend(Line3(circle[i], circle[(i + 1) % count], 'hole') for i in range(count))
        dimensions.extend((ReferenceDimension('Пластина: ширина локальная X', plate['width_mm']),
                           ReferenceDimension('Пластина: высота локальная Y', plate['height_mm']),
                           ReferenceDimension('Пластина: толщина', plate['thickness_mm']),
                           ReferenceDimension('Пластина: диаметр отверстия', 2 * r)))
    return AssemblyViews(tuple(lines), tuple(dimensions), axis, document['version'] == PLATE_VERSION)

"""Ограниченный полигональный 3D-предпросмотр одного контура, не CAD-тело."""
from __future__ import annotations

from math import ceil, cos, isfinite, pi, sin

import numpy as np

from .sketch_contours import check_contours
from .sketch_curves import NUMERIC_EPS_MM, distance, endpoints, point_at
from .sketch_draft import Entity, Point
from .sketch_io import SketchDocument

MAX_VERTICES = 500


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _polygon(entities: tuple[Entity, ...]) -> list[Point]:
    report = check_contours(entities)
    if report.total_issues or report.closed_loops != 1:
        raise ValueError("Нужен один замкнутый контур без разрывов и пересечений; отверстия пока не поддерживаются")
    if len(entities) == 1 and entities[0].kind == "circle":
        e = entities[0]
        return [(e.start[0] + e.size * cos(2 * pi * i / 96), e.start[1] + e.size * sin(2 * pi * i / 96))
                for i in range(96)]
    if any(e.kind == "circle" for e in entities):
        raise ValueError("Поддерживается только один контур без отверстий")
    points: list[Point] = []
    unused = set(range(len(entities)))
    current = endpoints(entities[0])[0]
    for step in range(len(entities)):
        matches = ([(0, 0)] if step == 0 else
                   [(index, k) for index in sorted(unused) for k, p in enumerate(endpoints(entities[index]))
                    if distance(current, p) <= NUMERIC_EPS_MM])
        if len(matches) != 1:
            raise ValueError("Не удалось однозначно упорядочить контур")
        index, side = matches[0]
        unused.remove(index)
        e = entities[index]
        count = max(1, ceil(abs(e.sweep_deg or 0) / 10)) if e.kind == "arc" else 1
        if len(points) + count > MAX_VERTICES:
            raise ValueError("Контур слишком сложен для 3D-предпросмотра")
        for i in range(count):
            t = i / count if side == 0 else 1 - i / count
            points.append(point_at(e, t))
        current = endpoints(e)[1 - side]
    if unused or distance(current, points[0]) > NUMERIC_EPS_MM:
        raise ValueError("Контур не замкнут")
    return points


def _triangulate(points: list[Point]) -> tuple[list[Point], list[tuple[int, int, int]]]:
    # Remove exactly collinear vertices; this keeps ear clipping deterministic.
    points = list(points)
    changed = True
    while changed and len(points) > 3:
        changed = False
        for i, point in enumerate(points):
            a, b = points[i - 1], points[(i + 1) % len(points)]
            if abs(_cross(a, point, b)) <= 1e-12 and (point[0] - a[0]) * (point[0] - b[0]) + (point[1] - a[1]) * (point[1] - b[1]) <= 0:
                del points[i]
                changed = True
                break
    if len(points) < 3:
        raise ValueError("В контуре недостаточно различных точек")
    def on_segment(a: Point, b: Point, p: Point) -> bool:
        return (abs(_cross(a, b, p)) <= 1e-10 and
                min(a[0], b[0]) - NUMERIC_EPS_MM <= p[0] <= max(a[0], b[0]) + NUMERIC_EPS_MM and
                min(a[1], b[1]) - NUMERIC_EPS_MM <= p[1] <= max(a[1], b[1]) + NUMERIC_EPS_MM)

    for i in range(len(points)):
        a, b = points[i], points[(i + 1) % len(points)]
        if distance(a, b) <= NUMERIC_EPS_MM:
            raise ValueError("Слишком короткая грань 3D-предпросмотра")
        for j in range(i + 1, len(points)):
            if j == i + 1 or (i == 0 and j == len(points) - 1):
                continue
            c, d = points[j], points[(j + 1) % len(points)]
            u, v, w, x = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
            if ((u * v < 0 and w * x < 0) or on_segment(a, b, c) or on_segment(a, b, d) or
                    on_segment(c, d, a) or on_segment(c, d, b)):
                raise ValueError("При приближении дуг возникло пересечение; измените контур")
    origin = points[0]
    area2 = sum(_cross(origin, points[i], points[(i + 1) % len(points)]) for i in range(len(points)))
    if abs(area2) <= 1e-12:
        raise ValueError("Площадь контура слишком мала")
    if area2 < 0:
        points.reverse()
    indices = list(range(len(points)))
    triangles: list[tuple[int, int, int]] = []
    while len(indices) > 3:
        for k, j in enumerate(indices):
            i, h = indices[k - 1], indices[(k + 1) % len(indices)]
            a, b, c = points[i], points[j], points[h]
            if _cross(a, b, c) <= 1e-12:
                continue
            if any(_cross(a, b, points[n]) >= -1e-12 and _cross(b, c, points[n]) >= -1e-12 and
                   _cross(c, a, points[n]) >= -1e-12 for n in indices if n not in (i, j, h)):
                continue
            triangles.append((i, j, h))
            del indices[k]
            break
        else:
            raise ValueError("Не удалось разбить контур на грани; уточните геометрию")
    triangles.append((indices[0], indices[1], indices[2]))
    return points, triangles


def extrusion_mesh(document: SketchDocument, depth: float) -> np.ndarray:
    """Только замкнутая сетка для просмотра, глубина вдоль положительной нормали.

    Один контур без отверстий; кривые аппроксимируются отрезками по 10°.
    Не создаёт CAD-геометрию, STEP или параметрическую связь.
    """
    if not isfinite(depth) or not 0 < depth <= 1_000_000:
        raise ValueError("Глубина должна быть больше нуля и не более 1 000 000 мм")
    if document.plane not in ("XY", "XZ", "YZ") or not isfinite(document.offset_mm):
        raise ValueError("Некорректная плоскость эскиза")
    points, caps = _triangulate(_polygon(document.entities))
    def xyz(p: Point, z: float) -> tuple[float, float, float]:
        x, y = p
        if document.plane == "XY":
            return x, y, z
        if document.plane == "XZ":
            return x, z, y
        return z, x, y
    bottom = [xyz(p, document.offset_mm) for p in points]
    top = [xyz(p, document.offset_mm + depth) for p in points]
    # XZ has opposite handedness from XY/YZ.
    flip = document.plane == "XZ"
    faces: list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]] = []
    for a, b, c in caps:
        faces.extend(((bottom[c], bottom[b], bottom[a]), (top[a], top[b], top[c])))
    for i in range(len(points)):
        j = (i + 1) % len(points)
        faces.extend(((bottom[i], bottom[j], top[j]), (bottom[i], top[j], top[i])))
    if flip:
        faces = [(a, c, b) for a, b, c in faces]
    return np.asarray(faces, dtype=np.float64)

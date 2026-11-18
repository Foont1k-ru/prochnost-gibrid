"""Условные объёмы исключительно для экрана: не модель деталей и не CAD."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .pose_view import Point
from .scene3d import Scene3D, SegmentKind

# Масштабы символов не читаются из модели и не являются размерами деталей.
TUBE_RADIUS_MM = 20.0
JOINT_RADIUS_MM = 27.0
TUBE_SIDES = 10


@dataclass(frozen=True, slots=True)
class VisualFace:
    vertices: tuple[Point, Point, Point]
    kind: SegmentKind
    shade: float


@dataclass(frozen=True, slots=True)
class VisualJoint:
    center: Point
    kind: SegmentKind


@dataclass(frozen=True, slots=True)
class SchematicVisual:
    faces: tuple[VisualFace, ...]
    joints: tuple[VisualJoint, ...]


def _point(value: np.ndarray) -> Point:
    return (float(value[0]), float(value[1]), float(value[2]))


def make_schematic_visual(scene: Scene3D) -> SchematicVisual:
    """Цилиндры на имеющихся линиях рычагов и условные круглые шарниры.

    Никаких перемычек, пластин, креплений или допущений о типе шарнира не
    добавляется. Пустые/вырожденные линии пропускаются. Все размеры символов
    визуальные, в модель и экспорт не попадают.
    """
    faces: list[VisualFace] = []
    joints: dict[Point, VisualJoint] = {}
    light = np.array([0.3, -0.4, 0.8660254])

    def add_face(a: np.ndarray, b: np.ndarray, c: np.ndarray, normal: np.ndarray, kind: SegmentKind) -> None:
        shade = 0.52 + 0.48 * max(0., float(np.dot(normal, light)))
        faces.append(VisualFace((_point(a), _point(b), _point(c)), kind, shade))

    for segment in scene.segments:
        if segment.kind not in ('arm', 'steering'):
            continue
        a, b = np.array(segment.start, dtype=float), np.array(segment.end, dtype=float)
        if not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError('non-finite visual segment')
        axis = b - a
        length = float(np.linalg.norm(axis))
        if length < 1e-9:
            continue
        axis /= length
        ref = np.array([0., 0., 1.]) if abs(axis[2]) < 0.9 else np.array([0., 1., 0.])
        u = np.cross(axis, ref)
        u /= np.linalg.norm(u)
        v = np.cross(axis, u)
        directions = [u * math.cos(2 * math.pi * i / TUBE_SIDES) +
                      v * math.sin(2 * math.pi * i / TUBE_SIDES) for i in range(TUBE_SIDES)]
        for i, direction in enumerate(directions):
            nxt = directions[(i + 1) % TUBE_SIDES]
            normal = direction + nxt
            normal /= np.linalg.norm(normal)
            ai, aj = a + TUBE_RADIUS_MM * direction, a + TUBE_RADIUS_MM * nxt
            bi, bj = b + TUBE_RADIUS_MM * direction, b + TUBE_RADIUS_MM * nxt
            add_face(ai, aj, bj, normal, segment.kind)
            add_face(ai, bj, bi, normal, segment.kind)
            add_face(a, aj, ai, -axis, segment.kind)
            add_face(b, bi, bj, axis, segment.kind)
        for p in (segment.start, segment.end):
            joints.setdefault(p, VisualJoint(p, segment.kind))
    return SchematicVisual(tuple(faces), tuple(joints.values()))

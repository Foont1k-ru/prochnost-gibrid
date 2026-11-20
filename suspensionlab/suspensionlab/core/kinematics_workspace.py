"""Дискретная кинематика для рабочей области; не заключение о безопасности."""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, pi, sin

from ..model.entities import Axle
from .double_wishbone import DoubleWishbone
from .metrics import CornerMetrics, corner_metrics
from .pose_view import Point, pose_view
from .scene3d import Scene3D, Segment3D, pose_scene
from .sweep import limited_sweep, travel_grid
from .vehicle_schematic_scene import SelectableLink


@dataclass(frozen=True)
class WorkspaceSample:
    travel_mm: float
    scene: Scene3D | None
    metrics: CornerMetrics | None
    error: str | None


@dataclass(frozen=True)
class WorkspaceResult:
    samples: tuple[WorkspaceSample, ...]
    reached_droop_mm: float
    reached_bump_mm: float


def static_scene(axle: Axle) -> tuple[Scene3D, tuple[SelectableLink, ...]]:
    """Левая сторона независимой схемы или явно заданные точки моста; без кинематики."""
    points: list[tuple[str, Point]] = []
    for point_spec in axle.spec.points:
        point = axle.hardpoints.get(point_spec.code)
        if point is not None:
            xyz = point.as_tuple()
            if not all(isfinite(x) and abs(x) <= 1_000_000 for x in xyz):
                raise ValueError('Координаты вне диапазона отображения')
            points.append((point_spec.code, xyz))
    segments: list[Segment3D] = []
    targets: list[SelectableLink] = []
    for spec in axle.spec.links:
        if any(code not in axle.hardpoints for code in (*spec.pivot, spec.end)):
            continue
        for start, end in axle.link_endpoints(spec.code):
            segment = Segment3D(start, end, 'steering' if spec.group == 'steering' else 'arm')
            segments.append(segment)
            targets.append(SelectableLink(axle.role, spec.code, segment))
    for prefix, kind in (('spring', 'spring'), ('damper', 'damper')):
        low, high = axle.hardpoints.get(prefix + '_lo'), axle.hardpoints.get(prefix + '_up')
        if low is not None and high is not None:
            segments.append(Segment3D(low.as_tuple(), high.as_tuple(), kind))  # type: ignore[arg-type]
    wheel = axle.hardpoints.get(axle.wheel_center_code() or '')
    radius, width = axle.wheel.r_dynamic_mm, axle.wheel.width_mm
    if wheel is not None and all(isfinite(v) and 0 < v <= 100_000 for v in (radius, width)):
        x, y, z = wheel.as_tuple()
        rings = [[(x + radius * cos(2*pi*i/24), y + side*width/2, z + radius*sin(2*pi*i/24))
                  for i in range(24)] for side in (-1, 1)]
        for ring in rings:
            segments.extend(Segment3D(ring[i], ring[(i+1) % 24], 'wheel') for i in range(24))
        segments.extend(Segment3D(rings[0][i], rings[1][i], 'wheel') for i in range(0, 24, 4))
    return Scene3D(0., tuple(segments), tuple(points)), tuple(targets)


def calculate(axle: Axle, start: float, end: float, spacing: float) -> WorkspaceResult:
    """Левая передняя двухрычажная сторона, неподвижная рейка, дискретная сетка."""
    if axle.role != 'front' or axle.type_code != 'double_wishbone':
        raise ValueError('Расчёт хода для этого типа пока не реализован')
    if not (-150 <= start <= 0 <= end <= 150) or not (5 <= spacing <= 30):
        raise ValueError('Диапазон должен включать ноль и быть в пределах −150…+150 мм; шаг 5…30 мм')
    travels = travel_grid(start, end, max_spacing_mm=spacing)
    model = DoubleWishbone(axle, 'left')
    sweep = limited_sweep(model, travels, max_step_mm=2)
    samples = []
    for item in sweep.points:
        if item.pose is None:
            samples.append(WorkspaceSample(item.travel_mm, None, None, str(item.error)))
            continue
        pose = item.pose
        frame = pose_view(model, pose, axle, spring=False, damper=False)
        scene = pose_scene(model, pose, axle, frame)
        try:
            metrics = corner_metrics(model, pose, static_camber_deg=axle.setup.camber_deg,
                                     static_toe_deg=axle.setup.toe_deg_total / 2)
        except ValueError:
            metrics = None
        samples.append(WorkspaceSample(item.travel_mm, scene, metrics, None))
    return WorkspaceResult(tuple(samples), sweep.reachable_droop_mm, sweep.reachable_bump_mm)


def moved_link_end(axle: Axle, code: str, length: float) -> tuple[str, Point]:
    """Задаёт расстояние до оси, передвигая только наружную точку перпендикулярно оси."""
    import numpy as np

    spec = axle.spec.link(code)
    if spec is None or not spec.movable_end or not isfinite(length) or not 0 < length <= 1_000_000:
        raise ValueError('Недопустимая длина или неподвижный конец')
    if len(spec.pivot) not in (1, 2) or any(k not in axle.hardpoints for k in (*spec.pivot, spec.end)):
        raise ValueError('Не хватает точек')
    a = np.array(axle.hardpoints[spec.pivot[0]].as_tuple())
    end = np.array(axle.hardpoints[spec.end].as_tuple())
    if len(spec.pivot) == 2:
        axis = np.array(axle.hardpoints[spec.pivot[1]].as_tuple()) - a
        norm = float(np.linalg.norm(axis))
        if norm < 1e-9:
            raise ValueError('Точки оси совпадают')
        unit = axis / norm
        base = a + np.dot(end - a, unit) * unit
    else:
        base = a
    radial = end - base
    distance = float(np.linalg.norm(radial))
    if not isfinite(distance) or distance < 1e-9:
        raise ValueError('Направление длины не определено')
    result = base + radial * (length / distance)
    if not all(isfinite(v) and abs(v) <= 1_000_000 for v in result):
        raise ValueError('Координаты вне допустимого диапазона')
    return spec.end, (float(result[0]), float(result[1]), float(result[2]))

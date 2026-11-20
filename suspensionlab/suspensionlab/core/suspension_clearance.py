"""Ограниченная проверка выбранных условных форм на дискретных позах.

Не является проверкой CAD, столкновений всей подвески или непрерывного хода.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from math import dist, isfinite

from ..model.entities import Axle
from .cylinder_clearance import CylinderClearance, capsule_cylinder_clearance
from .kinematics_workspace import WorkspaceSample, calculate, supported
from .scene3d import Scene3D
from .segment_clearance import CapsuleClearance, Point, capsule_clearance

_FRONT_LINKS = ('upper_arm', 'lower_arm', 'tierod')
_REAR_LINKS = ('upper_front', 'upper_rear', 'lower_front', 'lower_rear', 'toe_link')
_EXTRA = ('spring_capsule', 'damper_capsule', 'rod_capsule', 'rocker_capsule', 'wheel_cylinder')
_NOT_CHECKED = ('knuckle', 'body', 'drivetrain', 'real_parts')
_EXTRA_KINDS = {'spring_capsule': ('spring', 1), 'damper_capsule': ('damper', 1),
                'rod_capsule': ('rod', 1), 'rocker_capsule': ('rocker', 2)}


@dataclass(frozen=True, slots=True)
class LinkClearance:
    first: str
    second: str
    status: str
    measurement: CapsuleClearance | CylinderClearance | None
    first_pivot: str | None = None
    second_pivot: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ClearanceSample:
    travel_mm: float
    pairs: tuple[LinkClearance, ...]
    pose_error: str | None = None


@dataclass(frozen=True, slots=True)
class ClearanceSweep:
    """Только выбранные условные формы в рассчитанных позах."""
    samples: tuple[ClearanceSample, ...]
    selected: tuple[str, ...]
    omitted: tuple[str, ...]
    not_checked: tuple[str, ...] = _NOT_CHECKED


def eligible_links(axle: Axle) -> tuple[str, ...]:
    """Коды поддерживаемых осевых связей, без подразумеваемых размеров."""
    if not supported(axle):
        return ()
    return _FRONT_LINKS if axle.role == 'front' else _REAR_LINKS


def eligible_objects(axle: Axle) -> tuple[str, ...]:
    return (*eligible_links(axle), *_EXTRA) if supported(axle) else ()


def _branches(axle: Axle, scene: Scene3D, code: str) -> list[tuple[str, Point, Point]] | None:
    """Возвращает только полные данные одной решённой позы, без статической подстановки."""
    if code in _EXTRA_KINDS:
        kind, count = _EXTRA_KINDS[code]
        segments = [segment for segment in scene.segments if segment.kind == kind]
        if len(segments) != count or any(dist(s.start, s.end) < 1e-9 for s in segments):
            return None
        names = ('плечо тяги', 'плечо амортизатора') if code == 'rocker_capsule' else ('ось',)
        return [(name, segment.start, segment.end) for name, segment in zip(names, segments, strict=True)]
    spec = axle.spec.link(code)
    if spec is None or not spec.pivot:
        return None
    end = scene.point(spec.end)
    pivots = [(p, scene.point(p)) for p in spec.pivot]
    if (end is None or any(p is None for _, p in pivots) or
            any(p is not None and dist(p, end) < 1e-9 for _, p in pivots)):
        return None
    return [(name, point, end) for name, point in pivots if point is not None]


def _shared_joint(axle: Axle, first: str, second: str) -> bool:
    links = eligible_links(axle)
    if first in links and second in links:
        a, b = axle.spec.link(first), axle.spec.link(second)
        return bool(a and b and {*a.pivot, a.end} & {*b.pivot, b.end})
    config = axle.kinematic_elements
    if config is None or config.type_code != axle.type_code:
        return False
    rocker = config.rocker
    active = rocker is not None and rocker.enabled
    pair = {first, second}
    if active and 'rocker_capsule' in pair and pair & {'rod_capsule', 'damper_capsule'}:
        return True
    if 'lower_arm' not in pair:
        return False
    if active and 'rod_capsule' in pair and rocker is not None and rocker.mount == 'lower_arm':
        return True
    for code, setup in (('spring_capsule', config.spring), ('damper_capsule', config.damper)):
        if (code in pair and not (code == 'damper_capsule' and active) and
                'lower_arm' in (setup.lower, setup.upper)):
            return True
    return False


def _wheel_axis(scene: Scene3D) -> tuple[Point, Point] | None:
    # wheel_segments emits 32 edges for each ring followed by 8 matching cross-rim segments.
    # Do not infer an axis from an arbitrary or partial drawing.
    segments = [segment for segment in scene.segments if segment.kind == 'wheel']
    center = scene.point('wheel_center')
    if center is None or len(segments) != 72:
        return None
    connector = segments[64]
    axis: Point = tuple(connector.end[i] - connector.start[i] for i in range(3))  # type: ignore[assignment]
    if dist(connector.start, connector.end) < 1e-9:
        return None
    return center, axis


def _missing_detail(sample: WorkspaceSample, code: str) -> str:
    if code == 'wheel_cylinder':
        return 'недоступны центр или направление колеса'
    if code in ('rod_capsule', 'rocker_capsule'):
        if sample.damper is not None and sample.damper.detail.startswith('коромысло:'):
            return sample.damper.detail
        return 'тяга/коромысло не рассчитаны или геометрия неполная'
    measurement = sample.spring if code == 'spring_capsule' else sample.damper if code == 'damper_capsule' else None
    if measurement is not None and measurement.length_mm is None:
        return measurement.detail
    return 'недоступны или вырождены точки'


def calculate_link_clearance(axle: Axle, start_mm: float, end_mm: float, spacing_mm: float,
                             radii_mm: Mapping[str, float], required_clearance_mm: float,
                             *, wheel_width_mm: float | None = None) -> ClearanceSweep:
    """Все пары выбранных форм на свежем расчёте левой оси, только дискретно.

    Для связей и элементов — капсулы с явными радиусами. Рычаг и коромысло —
    по две капсулы, а не пластины. Колесо — сплошной конечный цилиндр с явно
    заданными радиусом и шириной. Внутри одной формы пары не сравниваются.
    Общие именованные шарниры и известные крепления целиком исключают пару.
    Вырожденные и недоступные формы, отказы кинематики и коромысла — unknown;
    неподтверждённые точки не заменяются статическими. Отрицательный зазор
    цилиндра не является глубиной проникновения. axle нельзя менять из других
    потоков. Это не проверка CAD, непрерывного хода или безопасности.
    """
    if not supported(axle):
        raise ValueError('Проверка условных форм для этой схемы не реализована')
    eligible = eligible_objects(axle)
    if not isinstance(radii_mm, Mapping) or not 2 <= len(radii_mm) <= len(eligible):
        raise ValueError('Выберите не менее двух форм с заданными радиусами')
    if any(code not in eligible for code in radii_mm):
        raise ValueError('Эта форма не поддерживается проверкой')
    for radius in radii_mm.values():
        if type(radius) not in (int, float) or not isfinite(radius) or not 0 < radius <= 1_000_000:
            raise ValueError('Радиусы должны быть конечными и положительными')
    if 'wheel_cylinder' in radii_mm and (wheel_width_mm is None or type(wheel_width_mm) not in (int, float) or
            not isfinite(wheel_width_mm) or not 0 < wheel_width_mm <= 1_000_000):
        raise ValueError('Укажите конечную положительную ширину цилиндра колеса')
    if (type(required_clearance_mm) not in (int, float) or not isfinite(required_clearance_mm) or
            not 0 <= required_clearance_mm <= 1_000_000):
        raise ValueError('Укажите конечный неотрицательный запас')
    selected = tuple(code for code in eligible if code in radii_mm)
    omitted = tuple(code for code in eligible if code not in radii_mm)
    result = calculate(axle, start_mm, end_mm, spacing_mm)
    samples = []
    for sample in result.samples:
        pairs = []
        scene = sample.scene
        for first, second in combinations(selected, 2):
            if _shared_joint(axle, first, second):
                pairs.append(LinkClearance(first, second, 'excluded_shared_point', None))
                continue
            if scene is None:
                pairs.append(LinkClearance(first, second, 'unknown_no_pose', None))
                continue
            # wheel_cylinder is always last in eligible_objects.
            branches = _branches(axle, scene, first)
            if second == 'wheel_cylinder':
                wheel = _wheel_axis(scene)
                if branches is None or wheel is None:
                    code = first if branches is None else second
                    pairs.append(LinkClearance(first, second, 'unknown_geometry', None,
                                               detail=_missing_detail(sample, code)))
                    continue
                assert wheel_width_mm is not None
                measured = [(capsule_cylinder_clearance(a, b, radii_mm[first], wheel[0], wheel[1],
                                                        radii_mm[second], wheel_width_mm, required_clearance_mm), name)
                            for name, a, b in branches]
                worst, name = min(measured, key=lambda item: item[0].clearance_mm)
                pairs.append(LinkClearance(first, second, worst.status, worst, name, 'цилиндр'))
                continue
            other = _branches(axle, scene, second)
            if branches is None or other is None:
                missing = [code for code, shape in ((first, branches), (second, other)) if shape is None]
                detail = '; '.join(f'{code}: {_missing_detail(sample, code)}' for code in missing)
                pairs.append(LinkClearance(first, second, 'unknown_geometry', None, detail=detail))
                continue
            measured_capsules = [(capsule_clearance(a, b, radii_mm[first], c, d, radii_mm[second],
                                                    required_clearance_mm), name_a, name_b)
                                 for name_a, a, b in branches for name_b, c, d in other]
            worst_cap, name_a, name_b = min(measured_capsules, key=lambda item: item[0].clearance_mm)
            pairs.append(LinkClearance(first, second, worst_cap.status, worst_cap, name_a, name_b))
        samples.append(ClearanceSample(sample.travel_mm, tuple(pairs), sample.error if scene is None else None))
    return ClearanceSweep(tuple(samples), selected, omitted)

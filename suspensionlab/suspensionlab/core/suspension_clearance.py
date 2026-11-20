"""Ограниченная проверка выбранных осевых капсул на дискретных позах.

Не является проверкой CAD, столкновений всей подвески или непрерывного хода.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from math import dist, isfinite

from ..model.entities import Axle
from .kinematics_workspace import calculate, supported
from .scene3d import Scene3D
from .segment_clearance import CapsuleClearance, capsule_clearance

_FRONT_LINKS = ('upper_arm', 'lower_arm', 'tierod')
_REAR_LINKS = ('upper_front', 'upper_rear', 'lower_front', 'lower_rear', 'toe_link')
_NOT_CHECKED = ('wheel', 'knuckle', 'body', 'spring', 'damper', 'rod', 'rocker', 'drivetrain', 'real_parts')


@dataclass(frozen=True, slots=True)
class LinkClearance:
    first: str
    second: str
    status: str
    measurement: CapsuleClearance | None
    first_pivot: str | None = None
    second_pivot: str | None = None


@dataclass(frozen=True, slots=True)
class ClearanceSample:
    travel_mm: float
    pairs: tuple[LinkClearance, ...]
    pose_error: str | None = None


@dataclass(frozen=True, slots=True)
class ClearanceSweep:
    """Только выбранные осевые капсулы в рассчитанных позах."""
    samples: tuple[ClearanceSample, ...]
    selected: tuple[str, ...]
    omitted: tuple[str, ...]
    not_checked: tuple[str, ...] = _NOT_CHECKED


def eligible_links(axle: Axle) -> tuple[str, ...]:
    """Коды поддерживаемых осевых представлений, без подразумеваемых размеров."""
    if not supported(axle):
        return ()
    return _FRONT_LINKS if axle.role == 'front' else _REAR_LINKS


def calculate_link_clearance(axle: Axle, start_mm: float, end_mm: float, spacing_mm: float,
                             radii_mm: Mapping[str, float], required_clearance_mm: float) -> ClearanceSweep:
    """Все пары выбранных связей и все их ветви на свежем расчёте левой оси.

    Для каждой связи задан пользователем единый радиус условной капсулы вокруг
    линии от внутреннего к наружному шарниру. Двухопорный рычаг представлен
    двумя капсулами, а не треугольной пластиной и не настоящим изделием.
    Внутри одной связи пары не сравниваются. Связи с общей именованной точкой
    исключаются целиком, явно со статусом excluded: дальше от шарнира они
    *тоже не проверены*. Несовпадающие имена с совпадающими координатами не
    исключаются автоматически. При отсутствующей позе/точке или вырожденной
    линии пара unknown, без ранее вычисленных значений.

    Проверка только выбранных пар на заданной сетке. Промежуточные положения,
    геометрия кулака, колеса, тяг амортизатора и кузова и реальные детали не
    проверены. Нужно не изменять axle из других потоков во время вычисления.
    """
    if not supported(axle):
        raise ValueError('Проверка осевых капсул для этой схемы не реализована')
    eligible = eligible_links(axle)
    if not isinstance(radii_mm, Mapping) or not 2 <= len(radii_mm) <= len(eligible):
        raise ValueError('Выберите не менее двух связей с заданными радиусами')
    if any(code not in eligible for code in radii_mm):
        raise ValueError('Эта связь не поддерживается проверкой осевых капсул')
    for radius in radii_mm.values():
        if type(radius) not in (int, float) or not isfinite(radius) or not 0 < radius <= 1_000_000:
            raise ValueError('Радиусы должны быть конечными и положительными')
    if (type(required_clearance_mm) not in (int, float) or not isfinite(required_clearance_mm) or
            not 0 <= required_clearance_mm <= 1_000_000):
        raise ValueError('Укажите конечный неотрицательный запас')
    selected = tuple(code for code in eligible if code in radii_mm)
    omitted = tuple(code for code in eligible if code not in radii_mm)
    specs = {code: axle.spec.link(code) for code in selected}
    if any(spec is None or not spec.pivot for spec in specs.values()):
        raise ValueError('Не удалось определить точки выбранных связей')
    result = calculate(axle, start_mm, end_mm, spacing_mm)
    samples = []
    for sample in result.samples:
        pairs = []
        for first, second in combinations(selected, 2):
            first_spec, second_spec = specs[first], specs[second]
            assert first_spec is not None and second_spec is not None
            if {*first_spec.pivot, first_spec.end} & {*second_spec.pivot, second_spec.end}:
                pairs.append(LinkClearance(first, second, 'excluded_shared_point', None))
                continue
            scene: Scene3D | None = sample.scene
            if scene is None:
                pairs.append(LinkClearance(first, second, 'unknown_no_pose', None))
                continue
            end_a, end_b = scene.point(first_spec.end), scene.point(second_spec.end)
            pivots_a = [(code, scene.point(code)) for code in first_spec.pivot]
            pivots_b = [(code, scene.point(code)) for code in second_spec.pivot]
            if (end_a is None or end_b is None or any(p is None for _, p in (*pivots_a, *pivots_b)) or
                    any(p is not None and dist(p, end_a) < 1e-9 for _, p in pivots_a) or
                    any(p is not None and dist(p, end_b) < 1e-9 for _, p in pivots_b)):
                pairs.append(LinkClearance(first, second, 'unknown_geometry', None))
                continue
            measured = []
            for code_a, a in pivots_a:
                for code_b, b in pivots_b:
                    assert a is not None and b is not None
                    clearance = capsule_clearance(a, end_a, radii_mm[first], b, end_b, radii_mm[second],
                                                  required_clearance_mm)
                    measured.append((clearance.clearance_mm, code_a, code_b, clearance))
            _, code_a, code_b, worst = min(measured, key=lambda item: item[0])
            pairs.append(LinkClearance(first, second, worst.status, worst, code_a, code_b))
        samples.append(ClearanceSample(sample.travel_mm, tuple(pairs), sample.error if sample.scene is None else None))
    return ClearanceSweep(tuple(samples), selected, omitted)

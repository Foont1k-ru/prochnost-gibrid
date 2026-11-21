"""Явный переход от дискретной проверки к черновику переднего нижнего рычага.

Это не допуск к изготовлению и не проверка реальной CAD-геометрии.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite

from ..core.clearance_refinement import RefinementReport, refine_link_clearance
from ..core.suspension_clearance import ClearanceSweep, calculate_link_clearance
from .entities import Axle, Project
from .fixed_arm_skeleton import FixedArmSnapshot, SkeletonError, capture_fixed_arm, preview_fixed_arm


class HandoffError(ValueError):
    """Передача не выполнена; проект и файлы не изменены."""


@dataclass(frozen=True, slots=True)
class ClearanceSettings:
    """Временные параметры явно выбранных форм, не сохранённый сертификат."""
    radii: tuple[tuple[str, float], ...]
    margin_mm: float
    wheel_width_mm: float | None
    refine: bool
    alert_band_mm: float
    min_spacing_mm: float


@dataclass(frozen=True, slots=True)
class CadHandoff:
    snapshot: FixedArmSnapshot
    source_front: Axle
    settings: ClearanceSettings
    sweep: ClearanceSweep
    refinement: RefinementReport | None
    radius_mm: float
    wall_mm: float

    def matches(self, project: Project) -> bool:
        """Также сравнить неокруглённую ось, в том числе точки креплений и колесо."""
        return self.snapshot.matches(project) and self.source_front == project.front


def prepare_cad_handoff(project: Project, start: float, end: float, spacing: float,
                        settings: ClearanceSettings, wall_mm: float) -> CadHandoff:
    """Независимо пересчитать выбранные проверки на том же снимке, что и скелет.

    Только передний левый нижний рычаг. Условная проверка должна содержать его
    и ещё форму, а хотя бы одна их пара должна быть измерена. Отказы, наложения,
    непроверенные пары и пропуски передаются пользователю для явного решения;
    они не объявляются исправленными. Проект и документы не изменяются.
    """
    if project.front.type_code != 'double_wishbone':
        raise HandoffError('Передача доступна только для передней двухрычажной подвески')
    if not isinstance(settings, ClearanceSettings) or type(settings.refine) is not bool:
        raise HandoffError('Сначала выполните проверку условных форм')
    try:
        radii = dict(settings.radii)
    except (TypeError, ValueError) as error:
        raise HandoffError('Некорректные параметры проверки') from error
    if len(radii) != len(settings.radii) or 'lower_arm' not in radii or len(radii) < 2:
        raise HandoffError('В проверке выберите нижний рычаг и хотя бы одну другую форму')
    radius = radii['lower_arm']
    # The existing .slarm editor and format accept at most two decimal places.
    if (type(radius) not in (int, float) or not isfinite(radius) or not .01 <= radius <= 10000 or
            round(radius, 2) != radius):
        raise HandoffError('Для передачи радиус нижнего рычага должен быть 0,01…10000 мм с точностью до 0,01 мм')
    if (type(wall_mm) not in (int, float) or not isfinite(wall_mm) or not .01 <= wall_mm <= 10000 or
            round(wall_mm, 2) != wall_mm or radius - wall_mm < .01 - 1e-10):
        raise HandoffError('Толщина стенки должна оставлять внутренний радиус не менее 0,01 мм; точность — 0,01 мм')
    source_front = deepcopy(project.front)
    try:
        snapshot = capture_fixed_arm(project, start, end, spacing_mm=spacing)
        frozen = snapshot.project_copy()
        if settings.refine:
            refinement = refine_link_clearance(frozen.front, start, end, spacing, radii, settings.margin_mm,
                                                wheel_width_mm=settings.wheel_width_mm,
                                                alert_band_mm=settings.alert_band_mm,
                                                min_spacing_mm=settings.min_spacing_mm)
            sweep = refinement.sweep
        else:
            refinement = None
            sweep = calculate_link_clearance(frozen.front, start, end, spacing, radii, settings.margin_mm,
                                             wheel_width_mm=settings.wheel_width_mm)
        if not any(pair.measurement is not None and 'lower_arm' in (pair.first, pair.second)
                   for sample in sweep.samples for pair in sample.pairs):
            raise HandoffError('Ни одна выбранная пара с нижним рычагом не измерена; проверьте крепления и исключения')
        preview_fixed_arm(snapshot, project, float(radius), float(wall_mm))
    except HandoffError:
        raise
    except (SkeletonError, ValueError, KeyError, TypeError, OverflowError, ArithmeticError) as error:
        raise HandoffError(f'Повторный расчёт или создание заготовки не выполнены: {error}') from error
    result = CadHandoff(snapshot, source_front, settings, sweep, refinement, float(radius), float(wall_mm))
    if not result.matches(project):
        raise HandoffError('Проект изменился во время подготовки; повторите проверку')
    return result

"""Проверки корректности модели (геометрия, а не физика).

Модуль выдаёт структурированные сообщения, которые интерфейс показывает
в панели диагностики. Все тексты — ключи локализации с параметрами;
готовые русские формулировки лежат в ``resources/i18n/ru.json``.

Кинематические проверки (собираемость, метрики, конфликты) появятся в
ядре расчёта (этапы M1–M4) и будут добавляться сюда же — интерфейс
панели диагностики от этого не меняется.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..core.geometry import distance
from .entities import SCHEMA_VERSION, Axle, Project
from .suspension_types import REGISTRY

Severity = Literal["error", "warning", "info"]

#: Порядок важности для сортировки сообщений.
_SEVERITY_ORDER: dict[str, int] = {"error": 0, "warning": 1, "info": 2}

#: Минимально допустимая длина тяги/рычага, мм.
MIN_LINK_LENGTH_MM = 20.0


@dataclass(frozen=True, slots=True)
class Issue:
    """Сообщение диагностики.

    ``node`` — ссылка на объект модели (роль оси и код точки/рычага),
    чтобы интерфейс мог подсветить виновника.
    """

    severity: Severity
    key: str
    params: tuple[tuple[str, str], ...] = ()
    role: str = ""
    code: str = ""

    def text_params(self) -> dict[str, str]:
        """Параметры подстановки в строку локализации."""
        return dict(self.params)


def _issue(
    severity: Severity,
    key: str,
    role: str = "",
    node_code: str = "",
    **params: object,
) -> Issue:
    """Короткая запись создания сообщения."""
    return Issue(
        severity=severity,
        key=key,
        params=tuple((name, str(value)) for name, value in params.items()),
        role=role,
        code=node_code,
    )


def validate_axle(axle: Axle, project: Project | None = None) -> list[Issue]:
    """Проверяет одну ось и возвращает список сообщений."""
    issues: list[Issue] = []
    role = axle.role
    spec = REGISTRY.get(axle.type_code)
    if spec is None:
        issues.append(_issue("error", "diag.unknown_type", role, type=axle.type_code))
        return issues
    if spec.role != role:
        issues.append(_issue("error", "diag.type_role_mismatch", role, type=axle.type_code))

    if axle.type_code != "double_wishbone":
        issues.append(_issue("info", "diag.no_kinematic_solver", role))
    if axle.drivetrain.driven:
        issues.append(_issue("info", "diag.drive_geometry_only", role))

    # --- наличие обязательных точек -------------------------------------
    for point_spec in spec.points:
        if point_spec.code not in axle.hardpoints:
            issues.append(
                _issue(
                    "error",
                    "diag.point_missing",
                    role,
                    point_spec.code,
                    point=point_spec.name_key,
                )
            )

    # --- совпадающие координаты ----------------------------------------
    codes = [code for code in axle.point_codes() if code in axle.hardpoints]
    for index, first in enumerate(codes):
        for second in codes[index + 1 :]:
            if distance(axle.hardpoints[first].as_tuple(), axle.hardpoints[second].as_tuple()) < 0.5:
                issues.append(
                    _issue(
                        "error",
                        "diag.points_coincide",
                        role,
                        first,
                        first_code=first,
                        second_code=second,
                    )
                )

    # --- зоны компоновки -------------------------------------------------
    for code in codes:
        point = axle.hardpoints[code]
        if not point.in_zone():
            issues.append(_issue("error", "diag.point_out_of_zone", role, code, code=code))
        if point.z < 0.0:
            issues.append(_issue("warning", "diag.point_below_ground", role, code, code=code))

    # --- длины рычагов ---------------------------------------------------
    for link_spec in spec.links:
        length = axle.link_length(link_spec.code)
        if length < MIN_LINK_LENGTH_MM:
            issues.append(
                _issue(
                    "error",
                    "diag.link_too_short",
                    role,
                    link_spec.code,
                    link=link_spec.name_key,
                    length=f"{length:.1f}",
                )
            )

    # --- колесо и геометрия ---------------------------------------------
    wheel = axle.wheel
    if wheel.r_dynamic_mm <= 0 or wheel.r_static_mm <= 0:
        issues.append(_issue("error", "diag.wheel_radius_invalid", role))
    elif wheel.r_static_mm > wheel.r_dynamic_mm:
        issues.append(_issue("warning", "diag.wheel_radius_swapped", role))
    theoretical = wheel.theoretical_radius_mm
    if theoretical > 0 and abs(theoretical - wheel.r_dynamic_mm) > 0.15 * theoretical:
        issues.append(
            _issue(
                "warning",
                "diag.wheel_radius_mismatch",
                role,
                tire=wheel.tire,
                theory=f"{theoretical:.0f}",
                value=f"{wheel.r_dynamic_mm:.0f}",
            )
        )

    track = axle.track_mm()
    if track <= 0:
        issues.append(_issue("warning", "diag.no_wheel_center", role))
    elif project is not None:
        declared = project.vehicle.track_front_mm if role == "front" else project.vehicle.track_rear_mm
        if declared > 0 and abs(declared - track) > 50.0:
            issues.append(
                _issue(
                    "warning",
                    "diag.track_mismatch",
                    role,
                    declared=f"{declared:.0f}",
                    actual=f"{track:.0f}",
                )
            )

    # --- настройка -------------------------------------------------------
    setup = axle.setup
    if not -10.0 <= setup.camber_deg <= 10.0:
        issues.append(_issue("warning", "diag.camber_out_of_range", role, value=f"{setup.camber_deg:.2f}"))
    if not -5.0 <= setup.toe_deg_total <= 5.0:
        issues.append(_issue("warning", "diag.toe_out_of_range", role, value=f"{setup.toe_deg_total:.2f}"))
    if not 0.0 <= setup.caster_deg <= 15.0:
        issues.append(_issue("warning", "diag.caster_out_of_range", role, value=f"{setup.caster_deg:.2f}"))

    # --- ходы и пружина ---------------------------------------------------
    travel = axle.travel
    if travel.bump_mm <= 0 or travel.droop_mm <= 0:
        issues.append(_issue("error", "diag.travel_invalid", role))
    elif travel.bump_mm + travel.droop_mm > 400.0:
        issues.append(
            _issue(
                "warning",
                "diag.travel_too_large",
                role,
                value=f"{travel.bump_mm + travel.droop_mm:.0f}",
            )
        )
    if travel.sweep_points < 11:
        issues.append(_issue("warning", "diag.sweep_points_too_small", role, value=str(travel.sweep_points)))
    if axle.spring.rate_N_mm <= 0:
        issues.append(_issue("error", "diag.spring_rate_invalid", role))
    if axle.spring.free_len_mm <= 0:
        issues.append(_issue("error", "diag.spring_free_length_invalid", role))

    # --- привод -----------------------------------------------------------
    if axle.drivetrain.driven and not spec.supports_driven:
        issues.append(_issue("warning", "diag.drive_not_supported", role))
    if axle.drivetrain.driven:
        drive_points = ("differential_center", "pinion_center", "driveshaft_front") if axle.is_live_axle else ("differential_center", "driveshaft_front", "halfshaft_in", "halfshaft_out")
        for code in drive_points:
            if code not in axle.hardpoints:
                issues.append(_issue("warning", "diag.drive_points_missing", role, code=code))

    return issues


def validate_project(project: Project) -> list[Issue]:
    """Проверяет проект целиком (обе оси, автомобиль, версия схемы)."""
    issues: list[Issue] = []
    for axle in project.axles():
        issues.extend(validate_axle(axle, project))

    vehicle = project.vehicle
    if vehicle.mass_kg <= 0:
        issues.append(_issue("error", "diag.vehicle_mass_invalid"))
    if not 30.0 <= vehicle.front_weight_pct <= 70.0:
        issues.append(_issue("warning", "diag.front_weight_range", value=f"{vehicle.front_weight_pct:.0f}"))
    if vehicle.wheelbase_mm <= 0:
        issues.append(_issue("error", "diag.wheelbase_invalid"))
    if vehicle.cg_height_mm <= 0:
        issues.append(_issue("error", "diag.cg_height_invalid"))
    if not project.meta.name.strip():
        issues.append(_issue("info", "diag.project_name_empty"))
    if SCHEMA_VERSION != "1.0":
        issues.append(_issue("info", "diag.schema_version", value=SCHEMA_VERSION))

    issues.sort(key=lambda issue: (_SEVERITY_ORDER.get(issue.severity, 3), issue.role, issue.code))
    return issues


def count_by_severity(issues: list[Issue]) -> dict[str, int]:
    """Количество сообщений по уровням важности."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts

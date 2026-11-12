"""Декларативные описания параметров для инспектора.

Инспектор не содержит вёрстки под конкретный тип подвески: он получает
список групп и параметров (имя, единицы, диапазон, шаг, точность,
подсказка) и строит элементы сам. Это требование архитектуры (§8 ТЗ):
новый тип подвески = новые данные в реестре, а не новая панель.

Модуль не зависит от Qt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .entities import Axle, Hardpoint, Link, Project, Vehicle, Wheel
from .units import UnitKind


@dataclass(slots=True)
class ParamSpec:
    """Описание одного редактируемого параметра."""

    key: str
    title_key: str
    help_key: str
    owner: Any
    attr: str = ""
    kind: str = "float"  # float | int | bool | text | enum | readonly
    unit: UnitKind = UnitKind.PLAIN
    minimum: float = 0.0
    maximum: float = 1000.0
    step: float = 1.0
    merge_key: str = ""
    options: tuple[tuple[str, str], ...] = ()
    getter: Callable[[], float] | None = None
    suffix_key: str = ""

    def value(self) -> Any:
        """Текущее значение параметра из модели."""
        if self.getter is not None:
            return self.getter()
        return getattr(self.owner, self.attr)


@dataclass(slots=True)
class GroupSpec:
    """Группа параметров с заголовком."""

    title_key: str
    params: list[ParamSpec] = field(default_factory=list)


def _num(
    owner: Any,
    attr: str,
    key: str,
    minimum: float,
    maximum: float,
    step: float,
    unit: UnitKind,
    kind: str = "float",
    title_key: str | None = None,
    help_key: str | None = None,
) -> ParamSpec:
    """Короткая запись числового параметра."""
    return ParamSpec(
        key=key,
        title_key=title_key or f"param.{attr}.name",
        help_key=help_key or f"param.{attr}.help",
        owner=owner,
        attr=attr,
        kind=kind,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
        step=step,
        merge_key=key,
    )


def _bool(owner: Any, attr: str, key: str) -> ParamSpec:
    """Короткая запись логического параметра."""
    return ParamSpec(
        key=key,
        title_key=f"param.{attr}.name",
        help_key=f"param.{attr}.help",
        owner=owner,
        attr=attr,
        kind="bool",
        merge_key=key,
    )


def _text(owner: Any, attr: str, key: str) -> ParamSpec:
    """Короткая запись текстового параметра."""
    return ParamSpec(
        key=key,
        title_key=f"param.{attr}.name",
        help_key=f"param.{attr}.help",
        owner=owner,
        attr=attr,
        kind="text",
        merge_key=key,
    )


def _enum(owner: Any, attr: str, key: str, options: tuple[tuple[str, str], ...]) -> ParamSpec:
    """Короткая запись параметра-перечисления."""
    return ParamSpec(
        key=key,
        title_key=f"param.{attr}.name" if attr else f"insp.{key}.title",
        help_key=f"param.{attr}.help" if attr else f"insp.{key}.help",
        owner=owner,
        attr=attr,
        kind="enum",
        options=options,
        merge_key=key,
    )


# ---------------------------------------------------------------------------
# Проект и автомобиль
# ---------------------------------------------------------------------------


def project_specs(project: Project) -> list[GroupSpec]:
    """Параметры проекта (название, автор, ревизия)."""
    meta = project.meta
    return [
        GroupSpec(
            "insp.group.project",
            [
                ParamSpec(
                    key="project.name",
                    title_key="param.name.name",
                    help_key="param.name.help",
                    owner=meta,
                    attr="name",
                    kind="text",
                    merge_key="project.name",
                ),
                ParamSpec(
                    key="project.comment",
                    title_key="param.comment.name",
                    help_key="param.comment.help",
                    owner=meta,
                    attr="comment",
                    kind="text",
                    merge_key="project.comment",
                ),
            ],
        )
    ]


def vehicle_specs(vehicle: Vehicle) -> list[GroupSpec]:
    """Параметры автомобиля."""
    return [
        GroupSpec(
            "insp.group.vehicle",
            [
                _text(vehicle, "name", "vehicle.name"),
                _num(vehicle, "mass_kg", "vehicle.mass", 500, 3000, 10, UnitKind.MASS, title_key="param.mass_kg.name", help_key="param.mass_kg.help"),
                _num(vehicle, "front_weight_pct", "vehicle.front_weight", 30, 70, 0.5, UnitKind.PLAIN, title_key="param.front_weight_pct.name", help_key="param.front_weight_pct.help"),
                _num(vehicle, "cg_height_mm", "vehicle.cg_height", 200, 900, 5, UnitKind.LENGTH, title_key="param.cg_height_mm.name", help_key="param.cg_height_mm.help"),
                _num(vehicle, "cg_x_from_front_mm", "vehicle.cg_x", 500, 3000, 5, UnitKind.LENGTH, title_key="param.cg_x_from_front_mm.name", help_key="param.cg_x_from_front_mm.help"),
                _num(vehicle, "wheelbase_mm", "vehicle.wheelbase", 1800, 4000, 5, UnitKind.LENGTH, title_key="param.wheelbase_mm.name", help_key="param.wheelbase_mm.help"),
                _num(vehicle, "track_front_mm", "vehicle.track_front", 1000, 2200, 5, UnitKind.LENGTH, title_key="param.track_front_mm.name", help_key="param.track_front_mm.help"),
                _num(vehicle, "track_rear_mm", "vehicle.track_rear", 1000, 2200, 5, UnitKind.LENGTH, title_key="param.track_rear_mm.name", help_key="param.track_rear_mm.help"),
                _num(vehicle, "unsprung_front_kg", "vehicle.unsprung_front", 10, 120, 1, UnitKind.MASS, title_key="param.unsprung_front_kg.name", help_key="param.unsprung_front_kg.help"),
                _num(vehicle, "unsprung_rear_kg", "vehicle.unsprung_rear", 10, 150, 1, UnitKind.MASS, title_key="param.unsprung_rear_kg.name", help_key="param.unsprung_rear_kg.help"),
            ],
        )
    ]


# ---------------------------------------------------------------------------
# Ось: колесо, пружина, амортизатор, стабилизатор, рулевое, привод
# ---------------------------------------------------------------------------


def wheel_specs(wheel: Wheel) -> list[GroupSpec]:
    """Параметры колеса и шины."""
    return [
        GroupSpec(
            "insp.group.wheel",
            [
                _text(wheel, "tire", "wheel.tire"),
                _num(wheel, "r_dynamic_mm", "wheel.r_dynamic", 150, 600, 1, UnitKind.LENGTH, title_key="param.r_dynamic_mm.name", help_key="param.r_dynamic_mm.help"),
                _num(wheel, "r_static_mm", "wheel.r_static", 150, 600, 1, UnitKind.LENGTH, title_key="param.r_static_mm.name", help_key="param.r_static_mm.help"),
                _num(wheel, "width_mm", "wheel.width", 120, 400, 5, UnitKind.LENGTH, title_key="param.width_mm.name", help_key="param.width_mm.help"),
                _num(wheel, "et_mm", "wheel.et", -20, 120, 1, UnitKind.LENGTH, title_key="param.et_mm.name", help_key="param.et_mm.help"),
                _num(wheel, "spacer_mm", "wheel.spacer", 0, 60, 1, UnitKind.LENGTH, title_key="param.spacer_mm.name", help_key="param.spacer_mm.help"),
                _num(wheel, "k_tire_N_mm", "wheel.k_tire", 80, 500, 5, UnitKind.RATE, title_key="param.k_tire_N_mm.name", help_key="param.k_tire_N_mm.help"),
            ],
        )
    ]


def spring_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры пружины."""
    spring = axle.spring
    return [
        GroupSpec(
            "insp.group.spring",
            [
                _num(spring, "rate_N_mm", "spring.rate", 5, 400, 1, UnitKind.RATE, title_key="param.rate_N_mm.name", help_key="param.rate_N_mm.help"),
                _num(spring, "free_len_mm", "spring.free_len", 80, 600, 1, UnitKind.LENGTH, title_key="param.free_len_mm.name", help_key="param.free_len_mm.help"),
                _num(spring, "preload_mm", "spring.preload", 0, 60, 0.5, UnitKind.LENGTH, title_key="param.preload_mm.name", help_key="param.preload_mm.help"),
            ],
        )
    ]


def damper_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры амортизатора."""
    damper = axle.damper
    return [
        GroupSpec(
            "insp.group.damper",
            [
                _num(damper, "len_extended_mm", "damper.len_extended", 100, 900, 1, UnitKind.LENGTH, title_key="param.len_extended_mm.name", help_key="param.len_extended_mm.help"),
                _num(damper, "len_compressed_mm", "damper.len_compressed", 80, 800, 1, UnitKind.LENGTH, title_key="param.len_compressed_mm.name", help_key="param.len_compressed_mm.help"),
                _num(damper, "bump_rate_Ns_mm", "damper.bump", 0, 30, 0.1, UnitKind.PLAIN, title_key="param.bump_rate_Ns_mm.name", help_key="param.bump_rate_Ns_mm.help"),
                _num(damper, "rebound_rate_Ns_mm", "damper.rebound", 0, 40, 0.1, UnitKind.PLAIN, title_key="param.rebound_rate_Ns_mm.name", help_key="param.rebound_rate_Ns_mm.help"),
            ],
        )
    ]


def arb_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры стабилизатора."""
    arb = axle.arb
    return [
        GroupSpec(
            "insp.group.arb",
            [
                _bool(arb, "enabled", "arb.enabled"),
                _num(arb, "wheel_rate_N_mm", "arb.wheel_rate", 0, 300, 1, UnitKind.RATE, title_key="param.wheel_rate_N_mm.name", help_key="param.wheel_rate_N_mm.help"),
                _num(arb, "diameter_mm", "arb.diameter", 10, 40, 0.5, UnitKind.LENGTH, title_key="param.diameter_mm.name", help_key="param.diameter_mm.help"),
                _num(arb, "arm_length_mm", "arb.arm_length", 50, 600, 5, UnitKind.LENGTH, title_key="param.arm_length_mm.name", help_key="param.arm_length_mm.help"),
            ],
        )
    ]


def bump_stop_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры отбойника."""
    stop = axle.bump_stop
    return [
        GroupSpec(
            "insp.group.bump_stop",
            [
                _num(stop, "engage_travel_pct", "bump_stop.engage", 30, 100, 1, UnitKind.PLAIN, title_key="param.engage_travel_pct.name", help_key="param.engage_travel_pct.help"),
                _num(stop, "rate_N_mm", "bump_stop.rate", 20, 3000, 10, UnitKind.RATE, title_key="param.rate_N_mm.name", help_key="param.rate_N_mm.help"),
            ],
        )
    ]


def steering_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры рулевого управления."""
    steering = axle.steering
    return [
        GroupSpec(
            "insp.group.steering",
            [
                _num(steering, "rack_travel_mm", "steering.rack_travel", 40, 300, 1, UnitKind.LENGTH, title_key="param.rack_travel_mm.name", help_key="param.rack_travel_mm.help"),
                _num(steering, "max_steer_deg", "steering.max_steer", 10, 55, 0.5, UnitKind.ANGLE, title_key="param.max_steer_deg.name", help_key="param.max_steer_deg.help"),
                _num(steering, "ratio", "steering.ratio", 5, 30, 0.5, UnitKind.PLAIN, title_key="param.ratio.name", help_key="param.ratio.help"),
                _num(steering, "rack_height_offset_mm", "steering.rack_height", -60, 60, 1, UnitKind.LENGTH, title_key="param.rack_height_offset_mm.name", help_key="param.rack_height_offset_mm.help"),
            ],
        )
    ]


def drivetrain_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры привода."""
    drive = axle.drivetrain
    return [
        GroupSpec(
            "insp.group.drivetrain",
            [
                _bool(drive, "driven", "drivetrain.driven"),
                _num(drive, "cv_inner_limit_deg", "drivetrain.cv_inner", 10, 40, 0.5, UnitKind.ANGLE, title_key="param.cv_inner_limit_deg.name", help_key="param.cv_inner_limit_deg.help"),
                _num(drive, "cv_outer_limit_deg", "drivetrain.cv_outer", 20, 60, 0.5, UnitKind.ANGLE, title_key="param.cv_outer_limit_deg.name", help_key="param.cv_outer_limit_deg.help"),
                _num(drive, "plunge_min_mm", "drivetrain.plunge", 0, 20, 0.5, UnitKind.LENGTH, title_key="param.plunge_min_mm.name", help_key="param.plunge_min_mm.help"),
            ],
        )
    ]


def setup_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры статической настройки."""
    setup = axle.setup
    return [
        GroupSpec(
            "insp.group.setup",
            [
                _num(setup, "ride_height_mm", "setup.ride_height", 0, 400, 1, UnitKind.LENGTH, title_key="param.ride_height_mm.name", help_key="param.ride_height_mm.help"),
                _num(setup, "camber_deg", "setup.camber", -8, 8, 0.05, UnitKind.ANGLE, title_key="param.camber_deg.name", help_key="param.camber_deg.help"),
                _num(setup, "toe_deg_total", "setup.toe", -3, 3, 0.02, UnitKind.ANGLE, title_key="param.toe_deg_total.name", help_key="param.toe_deg_total.help"),
                _num(setup, "caster_deg", "setup.caster", -2, 14, 0.05, UnitKind.ANGLE, title_key="param.caster_deg.name", help_key="param.caster_deg.help"),
                _num(setup, "corner_weight_kg", "setup.corner_weight", 50, 800, 5, UnitKind.MASS, title_key="param.corner_weight_kg.name", help_key="param.corner_weight_kg.help"),
            ],
        )
    ]


def travel_specs(axle: Axle) -> list[GroupSpec]:
    """Параметры ходов подвески."""
    travel = axle.travel
    return [
        GroupSpec(
            "insp.group.travel",
            [
                _num(travel, "bump_mm", "travel.bump", 5, 300, 1, UnitKind.LENGTH, title_key="param.bump_mm.name", help_key="param.bump_mm.help"),
                _num(travel, "droop_mm", "travel.droop", 5, 300, 1, UnitKind.LENGTH, title_key="param.droop_mm.name", help_key="param.droop_mm.help"),
                _num(travel, "sweep_points", "travel.sweep_points", 11, 1001, 10, UnitKind.PLAIN, kind="int", title_key="param.sweep_points.name", help_key="param.sweep_points.help"),
            ],
        )
    ]


# ---------------------------------------------------------------------------
# Точки и рычаги
# ---------------------------------------------------------------------------


def point_specs(point: Hardpoint, name: str) -> list[GroupSpec]:
    """Координаты X/Y/Z выбранной точки крепления (Р-2)."""
    return [
        GroupSpec(
            "insp.group.point",
            [
                ParamSpec(
                    key=f"point.{point.code}.x",
                    title_key="param.point_x.name",
                    help_key=f"hp.{point.code}.help",
                    owner=point,
                    attr="x",
                    kind="float",
                    unit=UnitKind.LENGTH,
                    minimum=-600.0,
                    maximum=1200.0,
                    step=1.0,
                    merge_key=f"point:{id(point)}:x",
                ),
                ParamSpec(
                    key=f"point.{point.code}.y",
                    title_key="param.point_y.name",
                    help_key=f"hp.{point.code}.help",
                    owner=point,
                    attr="y",
                    kind="float",
                    unit=UnitKind.LENGTH,
                    minimum=0.0,
                    maximum=1000.0,
                    step=1.0,
                    merge_key=f"point:{id(point)}:y",
                ),
                ParamSpec(
                    key=f"point.{point.code}.z",
                    title_key="param.point_z.name",
                    help_key=f"hp.{point.code}.help",
                    owner=point,
                    attr="z",
                    kind="float",
                    unit=UnitKind.LENGTH,
                    minimum=-50.0,
                    maximum=900.0,
                    step=1.0,
                    merge_key=f"point:{id(point)}:z",
                ),
                ParamSpec(
                    key=f"point.{point.code}.locked",
                    title_key="insp.locked",
                    help_key="insp.lock_hint",
                    owner=point,
                    attr="locked",
                    kind="bool",
                    merge_key=f"point:{id(point)}:lock",
                ),
            ],
        )
    ]


def link_specs(link: Link, axle: Axle, name_key: str) -> list[GroupSpec]:
    """Параметры рычага: длина числом (Р-3), режим смещения, шарнир."""
    return [
        GroupSpec(
            "insp.group.link",
            [
                ParamSpec(
                    key=f"link.{link.code}.length",
                    title_key="insp.link_length",
                    help_key="insp.link_length_hint",
                    owner=link,
                    attr="",
                    kind="readonly",
                    unit=UnitKind.LENGTH,
                    getter=lambda: axle.link_length(link.code),
                ),
                ParamSpec(
                    key=f"link.{link.code}.edit_mode",
                    title_key="insp.link_edit_mode",
                    help_key="insp.link_length_hint",
                    owner=link,
                    attr="edit_mode",
                    kind="enum",
                    options=tuple((mode, f"link_mode.{mode}") for mode in ("move_outer", "move_inner", "move_both")),
                    merge_key=f"link:{id(link)}:mode",
                ),
                ParamSpec(
                    key=f"link.{link.code}.joint",
                    title_key="insp.link_joint",
                    help_key="hp.ubj.help",
                    owner=link,
                    attr="joint",
                    kind="enum",
                    options=tuple((joint, f"joint.{joint}") for joint in ("ball", "bushing", "rod_end", "cv")),
                    merge_key=f"link:{id(link)}:joint",
                ),
                _num(link, "diameter_mm", "link.diameter", 5, 80, 0.5, UnitKind.LENGTH, title_key="param.diameter_link_mm.name", help_key="param.diameter_link_mm.help"),
                _num(link, "articulation_limit_deg", "link.articulation", 5, 60, 0.5, UnitKind.ANGLE, title_key="param.articulation_limit_deg.name", help_key="param.articulation_limit_deg.help"),
            ],
        )
    ]

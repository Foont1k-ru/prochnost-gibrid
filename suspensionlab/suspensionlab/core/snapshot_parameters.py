"""Сопоставление только скалярных полей, представленных в инспекторе."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..model import param_specs as specs
from ..model.entities import Project
from ..model.param_specs import ParamSpec
from ..model.units import UnitKind

Scalar = str | bool | int | float
ParameterStatus = Literal["changed", "unchanged", "incompatible", "invalid"]


@dataclass(frozen=True, slots=True)
class ParameterComparison:
    role: str  # vehicle, front, rear
    component: str
    code: str
    name_key: str
    kind: str
    unit: str  # internal unit, never the user's display units
    old_type: str
    new_type: str
    old: Scalar | None
    new: Scalar | None
    status: ParameterStatus
    delta: int | float | None
    selectable: bool


def _unit(param: ParamSpec) -> str:
    if param.kind not in ("int", "float"):
        return ""
    if param.attr.endswith("_pct"):
        return "%"
    if param.attr.endswith("_Ns_mm"):
        return "Н·с/мм"
    return {UnitKind.LENGTH: "мм", UnitKind.ANGLE: "°", UnitKind.MASS: "кг",
            UnitKind.RATE: "Н/мм", UnitKind.FORCE: "Н", UnitKind.MOMENT: "Н·м",
            UnitKind.FREQUENCY: "Гц", UnitKind.PLAIN: ""}[param.unit]


def _capture(project: Project) -> dict[tuple[str, str, str], tuple[ParamSpec, bool]]:
    rows: dict[tuple[str, str, str], tuple[ParamSpec, bool]] = {}

    def add(role: str, component: str, groups: list[specs.GroupSpec], selectable: bool = True) -> None:
        for group in groups:
            for param in group.params:
                # Вычисляемые, списки и данные вне инспектора не входят в область сравнения.
                if param.kind not in ("float", "int", "text", "enum", "bool") or not param.attr or param.getter:
                    continue
                key = (role, component, param.key)
                if key in rows:
                    raise ValueError("duplicate parameter key")
                rows[key] = (param, selectable)

    add("vehicle", "vehicle", specs.vehicle_specs(project.vehicle))
    for role in ("front", "rear"):
        axle = project.axle(role)
        add(role, "wheel", specs.wheel_specs(axle.wheel))
        for component, groups in (
            ("spring", specs.spring_specs(axle)), ("damper", specs.damper_specs(axle)),
            ("arb", specs.arb_specs(axle)), ("bump_stop", specs.bump_stop_specs(axle)),
            ("steering", specs.steering_specs(axle)), ("drivetrain", specs.drivetrain_specs(axle)),
            ("setup", specs.setup_specs(axle)), ("travel", specs.travel_specs(axle)),
        ):
            add(role, component, groups, component != "steering" or axle.spec.supports_steering)
    return rows


def _scalar(param: ParamSpec) -> Scalar | None:
    value = param.value()
    if param.kind == "bool":
        return value if isinstance(value, bool) else None
    if param.kind in ("enum", "text"):
        return value if isinstance(value, str) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if param.kind == "int" and not isinstance(value, int):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def compare_parameters(reference: Project, current: Project) -> tuple[ParameterComparison, ...]:
    """Сравнивает заданные поля без преобразования единиц и без изменения модели."""
    old, new = _capture(reference), _capture(current)
    # Неполное совпадение реестров не должно незаметно маскировать поля.
    if old.keys() != new.keys():
        raise ValueError("incompatible parameter registry")
    result = []
    for key, (new_spec, selectable) in new.items():
        role, component, code = key
        old_spec, _ = old[key]
        if (old_spec.attr, old_spec.kind, old_spec.unit) != (new_spec.attr, new_spec.kind, new_spec.unit):
            raise ValueError("incompatible parameter definition")
        old_value, new_value = _scalar(old_spec), _scalar(new_spec)
        old_type = reference.axle(role).type_code if role != "vehicle" else ""
        new_type = current.axle(role).type_code if role != "vehicle" else ""
        delta: int | float | None = None
        status: ParameterStatus
        if old_value is None or new_value is None:
            status = "invalid"
        elif old_type != new_type:
            status = "incompatible"
        else:
            status = "changed" if old_value != new_value else "unchanged"
            if new_spec.kind in ("int", "float"):
                assert isinstance(old_value, (int, float)) and isinstance(new_value, (int, float))
                try:
                    difference = new_value - old_value
                    if not math.isfinite(difference):
                        status = "invalid"
                    else:
                        delta = difference
                except OverflowError:
                    status = "invalid"
        result.append(ParameterComparison(role, component, code, new_spec.title_key, new_spec.kind,
                                          _unit(new_spec), old_type, new_type, old_value, new_value,
                                          status, delta, selectable))
    return tuple(result)

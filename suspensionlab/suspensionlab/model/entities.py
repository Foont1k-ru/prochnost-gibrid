"""Модель данных проекта: автомобиль, оси, точки, рычаги, пружины.

Модель — обычные dataclass-классы без зависимостей от Qt и от файловой
системы. Сериализация в JSON — методы ``to_dict``/``from_dict``; политика
версий схемы и миграции — в :mod:`suspensionlab.model.project_io`.

Внутренние единицы: мм, градусы, кг, Н, Н/мм, Гц.
Координаты точек хранятся для **левой** стороны; правая сторона
получается зеркальным отражением по Y (кроме моста, где точки заданы
явно для каждой стороны).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..core.geometry import (
    axis_length,
    link_plan_angle,
    link_side_angle,
    mirror_y,
)
from .suspension_types import REGISTRY, SuspensionTypeSpec, get_type

#: Текущая версия схемы файла проекта.
SCHEMA_VERSION = "1.0"

#: Допустимые режимы изменения длины рычага (Р-3).
LENGTH_EDIT_MODES = ("move_outer", "move_inner", "move_both")

#: Допустимые типы шарниров.
JOINT_TYPES = ("ball", "bushing", "rod_end", "cv")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

_TIRE_RE = re.compile(r"^\s*(?P<width>\d{3})\s*/\s*(?P<aspect>\d{2,3})\s*[Rr]\s*(?P<rim>\d{2}(?:[.,]5)?)\s*$")


def parse_tire_size(text: str) -> tuple[float, float, float] | None:
    """Разбирает обозначение шины ``225/45R17``.

    Возвращает ``(ширина, профиль, диаметр диска в дюймах)`` или ``None``.
    """
    match = _TIRE_RE.match(text or "")
    if not match:
        return None
    return (
        float(match.group("width")),
        float(match.group("aspect")),
        float(match.group("rim").replace(",", ".")),
    )


def tire_theoretical_radius_mm(text: str, default: float = 310.0) -> float:
    """Теоретический радиус шины по её обозначению (мм)."""
    parsed = parse_tire_size(text)
    if parsed is None:
        return default
    width, aspect, rim = parsed
    return rim * 25.4 / 2.0 + width * aspect / 100.0


def _round(value: float) -> float:
    """Округление при сериализации — чтобы файлы оставались читаемыми."""
    return round(float(value), 4)


def _as_dict(value: Any) -> dict[str, Any]:
    """Типизированный ``dict`` из произвольного значения."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Типизированный ``list`` из произвольного значения."""
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# Точка крепления
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Hardpoint:
    """Точка крепления: координаты, признак фиксации, зона компоновки."""

    code: str
    x: float
    y: float
    z: float
    locked: bool = False
    zone_min: tuple[float, float, float] | None = None
    zone_max: tuple[float, float, float] | None = None

    def as_tuple(self) -> tuple[float, float, float]:
        """Координаты кортежем (мм)."""
        return (self.x, self.y, self.z)

    def mirrored(self) -> tuple[float, float, float]:
        """Зеркальные координаты (правая сторона)."""
        return mirror_y(self.as_tuple())

    def in_zone(self) -> bool:
        """Лежит ли точка внутри своей зоны компоновки."""
        if self.zone_min is None or self.zone_max is None:
            return True
        return all(
            self.zone_min[index] - 1e-9 <= value <= self.zone_max[index] + 1e-9
            for index, value in enumerate(self.as_tuple())
        )

    def to_dict(self) -> dict[str, Any]:
        """Сериализация точки в JSON-совместимый словарь."""
        data: dict[str, Any] = {"x": _round(self.x), "y": _round(self.y), "z": _round(self.z)}
        if self.locked:
            data["locked"] = True
        if self.zone_min is not None and self.zone_max is not None:
            data["zone"] = {
                "min": [_round(v) for v in self.zone_min],
                "max": [_round(v) for v in self.zone_max],
            }
        return data

    @classmethod
    def from_dict(cls, code: str, data: dict[str, Any]) -> Hardpoint:
        """Восстанавливает точку из словаря; отсутствующие поля — по умолчанию."""
        zone = data.get("zone")
        zone_min = zone_max = None
        if isinstance(zone, dict) and "min" in zone and "max" in zone:
            zone_min = tuple(float(v) for v in zone["min"])  # type: ignore[assignment]
            zone_max = tuple(float(v) for v in zone["max"])  # type: ignore[assignment]
        return cls(
            code=code,
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            z=float(data.get("z", 0.0)),
            locked=bool(data.get("locked", False)),
            zone_min=zone_min,  # type: ignore[arg-type]
            zone_max=zone_max,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Колесо, пружина, амортизатор, стабилизатор
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Wheel:
    """Колесо и шина."""

    tire: str = "225/45R17"
    r_dynamic_mm: float = 310.0
    r_static_mm: float = 300.0
    width_mm: float = 225.0
    et_mm: float = 35.0
    spacer_mm: float = 0.0
    k_tire_N_mm: float = 220.0

    @property
    def theoretical_radius_mm(self) -> float:
        """Радиус, вычисленный по обозначению шины (для проверки)."""
        return tire_theoretical_radius_mm(self.tire, self.r_dynamic_mm)

    def sync_from_tire(self) -> None:
        """Обновляет ширину и динамический радиус по обозначению шины."""
        parsed = parse_tire_size(self.tire)
        if parsed is None:
            return
        width, _aspect, _rim = parsed
        self.width_mm = width
        self.r_dynamic_mm = tire_theoretical_radius_mm(self.tire, self.r_dynamic_mm)
        self.r_static_mm = self.r_dynamic_mm - 10.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация колеса."""
        return {
            "tire": self.tire,
            "r_dynamic_mm": _round(self.r_dynamic_mm),
            "r_static_mm": _round(self.r_static_mm),
            "width_mm": _round(self.width_mm),
            "et_mm": _round(self.et_mm),
            "spacer_mm": _round(self.spacer_mm),
            "k_tire_N_mm": _round(self.k_tire_N_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Wheel:
        """Восстанавливает колесо из словаря."""
        wheel = cls()
        wheel.tire = str(data.get("tire", wheel.tire))
        wheel.r_dynamic_mm = float(data.get("r_dynamic_mm", wheel.r_dynamic_mm))
        wheel.r_static_mm = float(data.get("r_static_mm", wheel.r_static_mm))
        wheel.width_mm = float(data.get("width_mm", wheel.width_mm))
        wheel.et_mm = float(data.get("et_mm", wheel.et_mm))
        wheel.spacer_mm = float(data.get("spacer_mm", wheel.spacer_mm))
        wheel.k_tire_N_mm = float(data.get("k_tire_N_mm", wheel.k_tire_N_mm))
        return wheel


@dataclass(slots=True)
class Spring:
    """Пружина с возможной прогрессивной характеристикой."""

    rate_N_mm: float = 90.0
    free_len_mm: float = 250.0
    preload_mm: float = 5.0
    progressive: list[tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация пружины."""
        return {
            "rate_N_mm": _round(self.rate_N_mm),
            "free_len_mm": _round(self.free_len_mm),
            "preload_mm": _round(self.preload_mm),
            "progressive": [[_round(a), _round(b)] for a, b in self.progressive],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Spring:
        """Восстанавливает пружину из словаря."""
        spring = cls()
        spring.rate_N_mm = float(data.get("rate_N_mm", spring.rate_N_mm))
        spring.free_len_mm = float(data.get("free_len_mm", spring.free_len_mm))
        spring.preload_mm = float(data.get("preload_mm", spring.preload_mm))
        spring.progressive = [(float(a), float(b)) for a, b in _as_list(data.get("progressive"))]
        return spring


@dataclass(slots=True)
class Damper:
    """Амортизатор: ходы и характеристики сопротивления."""

    len_extended_mm: float = 420.0
    len_compressed_mm: float = 280.0
    bump_rate_Ns_mm: float = 2.5
    rebound_rate_Ns_mm: float = 6.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация амортизатора."""
        return {
            "len_extended_mm": _round(self.len_extended_mm),
            "len_compressed_mm": _round(self.len_compressed_mm),
            "bump_rate_Ns_mm": _round(self.bump_rate_Ns_mm),
            "rebound_rate_Ns_mm": _round(self.rebound_rate_Ns_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Damper:
        """Восстанавливает амортизатор из словаря."""
        damper = cls()
        damper.len_extended_mm = float(data.get("len_extended_mm", damper.len_extended_mm))
        damper.len_compressed_mm = float(data.get("len_compressed_mm", damper.len_compressed_mm))
        damper.bump_rate_Ns_mm = float(data.get("bump_rate_Ns_mm", damper.bump_rate_Ns_mm))
        damper.rebound_rate_Ns_mm = float(data.get("rebound_rate_Ns_mm", damper.rebound_rate_Ns_mm))
        return damper


@dataclass(slots=True)
class AntiRollBar:
    """Стабилизатор поперечной устойчивости (ARB)."""

    wheel_rate_N_mm: float = 25.0
    diameter_mm: float = 22.0
    arm_length_mm: float = 250.0
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Сериализация стабилизатора."""
        return {
            "wheel_rate_N_mm": _round(self.wheel_rate_N_mm),
            "diameter_mm": _round(self.diameter_mm),
            "arm_length_mm": _round(self.arm_length_mm),
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AntiRollBar:
        """Восстанавливает стабилизатор из словаря."""
        arb = cls()
        arb.wheel_rate_N_mm = float(data.get("wheel_rate_N_mm", arb.wheel_rate_N_mm))
        arb.diameter_mm = float(data.get("diameter_mm", arb.diameter_mm))
        arb.arm_length_mm = float(data.get("arm_length_mm", arb.arm_length_mm))
        arb.enabled = bool(data.get("enabled", arb.enabled))
        return arb


@dataclass(slots=True)
class BumpStop:
    """Отбойник: момент вступления и жёсткость."""

    engage_travel_pct: float = 75.0
    rate_N_mm: float = 400.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация отбойника."""
        return {"engage_travel_pct": _round(self.engage_travel_pct), "rate_N_mm": _round(self.rate_N_mm)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BumpStop:
        """Восстанавливает отбойник из словаря."""
        stop = cls()
        stop.engage_travel_pct = float(data.get("engage_travel_pct", stop.engage_travel_pct))
        stop.rate_N_mm = float(data.get("rate_N_mm", stop.rate_N_mm))
        return stop


@dataclass(slots=True)
class Steering:
    """Рулевое управление (рейка и тяги задаются точками крепления)."""

    rack_travel_mm: float = 150.0
    max_steer_deg: float = 38.0
    ratio: float = 16.0
    rack_height_offset_mm: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация рулевого."""
        return {
            "rack_travel_mm": _round(self.rack_travel_mm),
            "max_steer_deg": _round(self.max_steer_deg),
            "ratio": _round(self.ratio),
            "rack_height_offset_mm": _round(self.rack_height_offset_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Steering:
        """Восстанавливает рулевое из словаря."""
        steering = cls()
        steering.rack_travel_mm = float(data.get("rack_travel_mm", steering.rack_travel_mm))
        steering.max_steer_deg = float(data.get("max_steer_deg", steering.max_steer_deg))
        steering.ratio = float(data.get("ratio", steering.ratio))
        steering.rack_height_offset_mm = float(
            data.get("rack_height_offset_mm", steering.rack_height_offset_mm)
        )
        return steering


@dataclass(slots=True)
class Drivetrain:
    """Привод: полуоси, ШРУСы, допустимые углы и запас плунжера."""

    driven: bool = False
    cv_inner_limit_deg: float = 22.0
    cv_outer_limit_deg: float = 45.0
    plunge_min_mm: float = 3.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация привода."""
        return {
            "driven": self.driven,
            "cv_inner_limit_deg": _round(self.cv_inner_limit_deg),
            "cv_outer_limit_deg": _round(self.cv_outer_limit_deg),
            "plunge_min_mm": _round(self.plunge_min_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Drivetrain:
        """Восстанавливает привод из словаря."""
        drivetrain = cls()
        drivetrain.driven = bool(data.get("driven", drivetrain.driven))
        drivetrain.cv_inner_limit_deg = float(data.get("cv_inner_limit_deg", drivetrain.cv_inner_limit_deg))
        drivetrain.cv_outer_limit_deg = float(data.get("cv_outer_limit_deg", drivetrain.cv_outer_limit_deg))
        drivetrain.plunge_min_mm = float(data.get("plunge_min_mm", drivetrain.plunge_min_mm))
        return drivetrain


@dataclass(slots=True)
class Setup:
    """Статическая настройка (setup) оси."""

    ride_height_mm: float = 120.0
    camber_deg: float = -2.5
    toe_deg_total: float = -0.1
    caster_deg: float = 6.0
    corner_weight_kg: float = 320.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация настройки."""
        return {
            "ride_height_mm": _round(self.ride_height_mm),
            "camber_deg": _round(self.camber_deg),
            "toe_deg_total": _round(self.toe_deg_total),
            "caster_deg": _round(self.caster_deg),
            "corner_weight_kg": _round(self.corner_weight_kg),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Setup:
        """Восстанавливает настройку из словаря."""
        setup = cls()
        setup.ride_height_mm = float(data.get("ride_height_mm", setup.ride_height_mm))
        setup.camber_deg = float(data.get("camber_deg", setup.camber_deg))
        setup.toe_deg_total = float(data.get("toe_deg_total", setup.toe_deg_total))
        setup.caster_deg = float(data.get("caster_deg", setup.caster_deg))
        setup.corner_weight_kg = float(data.get("corner_weight_kg", setup.corner_weight_kg))
        return setup


@dataclass(slots=True)
class Travel:
    """Ходы подвески и сетка свипа."""

    bump_mm: float = 40.0
    droop_mm: float = 35.0
    sweep_points: int = 201

    def to_dict(self) -> dict[str, Any]:
        """Сериализация ходов."""
        return {
            "bump_mm": _round(self.bump_mm),
            "droop_mm": _round(self.droop_mm),
            "sweep_points": int(self.sweep_points),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Travel:
        """Восстанавливает ходы из словаря."""
        travel = cls()
        travel.bump_mm = float(data.get("bump_mm", travel.bump_mm))
        travel.droop_mm = float(data.get("droop_mm", travel.droop_mm))
        travel.sweep_points = int(data.get("sweep_points", travel.sweep_points))
        return travel


# ---------------------------------------------------------------------------
# Рычаг/тяга
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Link:
    """Рычаг или тяга: параметры, которые не выводятся из координат.

    Длина **не хранится**: она всегда вычисляется по координатам точек
    (ось качания → наружная точка), поэтому не может «разойтись» с
    геометрией. Редактирование длины (Р-3) — это команда, смещающая
    выбранный конец рычага.
    """

    code: str
    edit_mode: str = "move_outer"
    joint: str = "ball"
    diameter_mm: float = 24.0
    articulation_limit_deg: float = 25.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация рычага."""
        return {
            "edit_mode": self.edit_mode,
            "joint": self.joint,
            "diameter_mm": _round(self.diameter_mm),
            "articulation_limit_deg": _round(self.articulation_limit_deg),
        }

    @classmethod
    def from_dict(cls, code: str, data: dict[str, Any]) -> Link:
        """Восстанавливает рычаг из словаря."""
        link = cls(code=code)
        link.edit_mode = str(data.get("edit_mode", link.edit_mode))
        if link.edit_mode not in LENGTH_EDIT_MODES:
            link.edit_mode = "move_outer"
        link.joint = str(data.get("joint", link.joint))
        if link.joint not in JOINT_TYPES:
            link.joint = "ball"
        link.diameter_mm = float(data.get("diameter_mm", link.diameter_mm))
        link.articulation_limit_deg = float(data.get("articulation_limit_deg", link.articulation_limit_deg))
        return link


# ---------------------------------------------------------------------------
# Ось
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Axle:
    """Одна ось автомобиля: тип подвески, точки, узлы, настройка."""

    role: str
    type_code: str
    layout: str = ""
    hardpoints: dict[str, Hardpoint] = field(default_factory=dict)
    links: dict[str, Link] = field(default_factory=dict)
    wheel: Wheel = field(default_factory=Wheel)
    spring: Spring = field(default_factory=Spring)
    damper: Damper = field(default_factory=Damper)
    arb: AntiRollBar = field(default_factory=AntiRollBar)
    bump_stop: BumpStop = field(default_factory=BumpStop)
    steering: Steering = field(default_factory=Steering)
    drivetrain: Drivetrain = field(default_factory=Drivetrain)
    setup: Setup = field(default_factory=Setup)
    travel: Travel = field(default_factory=Travel)

    # ------------------------------------------------------------------ тип
    @property
    def spec(self) -> SuspensionTypeSpec:
        """Описание типа подвески из реестра."""
        return get_type(self.type_code)

    @property
    def is_live_axle(self) -> bool:
        """Неразрезной мост?"""
        return self.type_code == "live_axle_coil"

    @property
    def has_explicit_sides(self) -> bool:
        """Обе стороны заданы отдельными точками, а не зеркалируются."""
        return self.type_code in ("live_axle_coil", "torsion_beam_rear")

    # ------------------------------------------------------------------ точки
    def ensure_points(self, overwrite: bool = False) -> None:
        """Добавляет недостающие точки типа; лишние не удаляет.

        При ``overwrite=True`` координаты всех точек сбрасываются к
        значениям из реестра (используется при смене типа подвески).
        """
        spec = self.spec
        for point_spec in spec.points:
            if overwrite or point_spec.code not in self.hardpoints:
                self.hardpoints[point_spec.code] = Hardpoint(
                    code=point_spec.code,
                    x=point_spec.x,
                    y=point_spec.y,
                    z=point_spec.z,
                )
        for link_spec in spec.links:
            if link_spec.code not in self.links:
                self.links[link_spec.code] = Link(code=link_spec.code, joint=link_spec.joint)

    def point(self, code: str) -> Hardpoint:
        """Точка по коду; при отсутствии — исключение с понятным текстом."""
        if code not in self.hardpoints:
            raise KeyError(code)
        return self.hardpoints[code]

    def point_codes(self) -> tuple[str, ...]:
        """Коды точек в порядке описания типа (без лишних)."""
        known = [spec.code for spec in self.spec.points]
        extra = [code for code in self.hardpoints if code not in known]
        return tuple(known + extra)

    def points_of_group(self, group: str) -> list[Hardpoint]:
        """Точки, относящиеся к группе (``upper_arm``, ``steering`` …)."""
        return [self.hardpoints[spec.code] for spec in self.spec.points if spec.group == group and spec.code in self.hardpoints]

    # ------------------------------------------------------------------ рычаги
    def link_spec(self, code: str):
        """Описание рычага из реестра типа."""
        return self.spec.link(code)

    def link_length(self, code: str) -> float:
        """Длина рычага по текущим координатам (мм)."""
        spec = self.link_spec(code)
        if spec is None:
            return 0.0
        points = [self.hardpoints[p].as_tuple() for p in (*spec.pivot, spec.end) if p in self.hardpoints]
        if len(points) != len(spec.pivot) + 1:
            return 0.0
        return axis_length(list(points))

    def link_angles(self, code: str) -> tuple[float, float]:
        """Углы рычага в плане и в боку (градусы)."""
        spec = self.link_spec(code)
        if spec is None or spec.end not in self.hardpoints:
            return (0.0, 0.0)
        end = self.hardpoints[spec.end].as_tuple()
        if not spec.pivot:
            return (0.0, 0.0)
        pivot_points = [self.hardpoints[p].as_tuple() for p in spec.pivot if p in self.hardpoints]
        if not pivot_points:
            return (0.0, 0.0)
        if len(pivot_points) >= 2:
            from ..core.geometry import midpoint

            base = midpoint(pivot_points[0], pivot_points[1])
        else:
            base = pivot_points[0]
        return (link_plan_angle(base, end), link_side_angle(base, end))

    def link_endpoints(self, code: str) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
        """Отрезки для отрисовки рычага: каждая внутренняя точка → наружная."""
        spec = self.link_spec(code)
        if spec is None or spec.end not in self.hardpoints:
            return []
        end = self.hardpoints[spec.end].as_tuple()
        return [
            (self.hardpoints[p].as_tuple(), end) for p in spec.pivot if p in self.hardpoints
        ]

    # ------------------------------------------------------------------ колесо
    def wheel_center_code(self) -> str | None:
        """Код точки центра колеса для текущего типа подвески."""
        if self.has_explicit_sides and "wheel_center_l" in self.hardpoints:
            return "wheel_center_l"
        if "wheel_center" in self.hardpoints:
            return "wheel_center"
        return None

    def track_mm(self) -> float:
        """Колея оси по координатам центров колёс (мм)."""
        if self.has_explicit_sides and "wheel_center_l" in self.hardpoints:
            right = self.hardpoints.get("wheel_center_r")
            if right is not None:
                return abs(self.hardpoints["wheel_center_l"].y - right.y)
            return 0.0
        code = self.wheel_center_code()
        if code is None:
            return 0.0
        return 2.0 * abs(self.hardpoints[code].y)

    # ------------------------------------------------------------------ сериализация
    def to_dict(self) -> dict[str, Any]:
        """Сериализация оси."""
        data: dict[str, Any] = {
            "type": self.type_code,
            "driven": self.drivetrain.driven,
            "wheel": self.wheel.to_dict(),
            "hardpoints": {code: self.hardpoints[code].to_dict() for code in self.point_codes() if code in self.hardpoints},
            "links": {code: link.to_dict() for code, link in self.links.items()},
            "spring": self.spring.to_dict(),
            "damper": self.damper.to_dict(),
            "arb": self.arb.to_dict(),
            "bump_stop": self.bump_stop.to_dict(),
            "steering": self.steering.to_dict(),
            "drivetrain": self.drivetrain.to_dict(),
            "setup": self.setup.to_dict(),
            "travel": self.travel.to_dict(),
        }
        if self.layout:
            data["layout"] = self.layout
        return data

    @classmethod
    def from_dict(cls, role: str, data: dict[str, Any]) -> Axle:
        """Восстанавливает ось из словаря, дополняя недостающие точки типа."""
        axle = cls(role=role, type_code=str(data.get("type", "double_wishbone")))
        if axle.type_code not in REGISTRY:
            axle.type_code = "double_wishbone" if role == "front" else "multilink_rear"
        axle.layout = str(data.get("layout", axle.spec.default_layout))
        for code, point_data in _as_dict(data.get("hardpoints")).items():
            axle.hardpoints[code] = Hardpoint.from_dict(code, _as_dict(point_data))
        for code, link_data in _as_dict(data.get("links")).items():
            axle.links[code] = Link.from_dict(code, _as_dict(link_data))
        axle.wheel = Wheel.from_dict(_as_dict(data.get("wheel")))
        axle.spring = Spring.from_dict(_as_dict(data.get("spring")))
        axle.damper = Damper.from_dict(_as_dict(data.get("damper")))
        axle.arb = AntiRollBar.from_dict(_as_dict(data.get("arb")))
        axle.bump_stop = BumpStop.from_dict(_as_dict(data.get("bump_stop")))
        axle.steering = Steering.from_dict(_as_dict(data.get("steering")))
        axle.drivetrain = Drivetrain.from_dict(_as_dict(data.get("drivetrain")))
        axle.drivetrain.driven = bool(data.get("driven", axle.drivetrain.driven))
        axle.setup = Setup.from_dict(_as_dict(data.get("setup")))
        axle.travel = Travel.from_dict(_as_dict(data.get("travel")))
        axle.ensure_points()
        return axle


# ---------------------------------------------------------------------------
# Автомобиль, снимки, вид, проект
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Vehicle:
    """Параметры автомобиля в целом."""

    name: str = ""
    mass_kg: float = 1420.0
    front_weight_pct: float = 58.0
    cg_height_mm: float = 520.0
    cg_x_from_front_mm: float = 1120.0
    wheelbase_mm: float = 2650.0
    track_front_mm: float = 1520.0
    track_rear_mm: float = 1540.0
    unsprung_front_kg: float = 42.0
    unsprung_rear_kg: float = 48.0
    profile: str = "ring_race"

    @property
    def front_mass_kg(self) -> float:
        """Масса, приходящаяся на переднюю ось."""
        return self.mass_kg * self.front_weight_pct / 100.0

    @property
    def rear_mass_kg(self) -> float:
        """Масса, приходящаяся на заднюю ось."""
        return self.mass_kg - self.front_mass_kg

    def to_dict(self) -> dict[str, Any]:
        """Сериализация автомобиля."""
        return {
            "name": self.name,
            "mass_kg": _round(self.mass_kg),
            "front_weight_pct": _round(self.front_weight_pct),
            "cg_height_mm": _round(self.cg_height_mm),
            "cg_x_from_front_mm": _round(self.cg_x_from_front_mm),
            "wheelbase_mm": _round(self.wheelbase_mm),
            "track_front_mm": _round(self.track_front_mm),
            "track_rear_mm": _round(self.track_rear_mm),
            "unsprung_front_kg": _round(self.unsprung_front_kg),
            "unsprung_rear_kg": _round(self.unsprung_rear_kg),
            "profile": self.profile,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vehicle:
        """Восстанавливает автомобиль из словаря."""
        vehicle = cls()
        for name in (
            "name",
            "mass_kg",
            "front_weight_pct",
            "cg_height_mm",
            "cg_x_from_front_mm",
            "wheelbase_mm",
            "track_front_mm",
            "track_rear_mm",
            "unsprung_front_kg",
            "unsprung_rear_kg",
            "profile",
        ):
            if name in data:
                if name == "name" or name == "profile":
                    setattr(vehicle, name, str(data[name]))
                else:
                    setattr(vehicle, name, float(data[name]))
        return vehicle


@dataclass(slots=True)
class ViewState:
    """Состояние отображения, сохраняемое вместе с проектом."""

    theme: str = "dark"
    view_mode: str = "front"
    zoom: float = 1.0
    layers: dict[str, bool] = field(default_factory=dict)
    active_tab: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация состояния вида."""
        return {
            "theme": self.theme,
            "view_mode": self.view_mode,
            "zoom": _round(self.zoom),
            "layers": dict(self.layers),
            "active_tab": int(self.active_tab),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ViewState:
        """Восстанавливает состояние вида из словаря."""
        view = cls()
        view.theme = str(data.get("theme", view.theme))
        view.view_mode = str(data.get("view_mode", view.view_mode))
        view.zoom = float(data.get("zoom", view.zoom))
        view.layers = {str(k): bool(v) for k, v in _as_dict(data.get("layers")).items()}
        view.active_tab = int(data.get("active_tab", view.active_tab))
        return view


@dataclass(slots=True)
class Snapshot:
    """Снимок настройки: полное состояние модели под именем."""

    name: str
    note: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация снимка."""
        return {"name": self.name, "note": self.note, "data": self.data}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        """Восстанавливает снимок из словаря."""
        return cls(
            name=str(data.get("name", "")),
            note=str(data.get("note", "")),
            data=_as_dict(data.get("data")),
        )


@dataclass(slots=True)
class ProjectMeta:
    """Метаданные проекта (титульные данные)."""

    name: str = ""
    author: str = ""
    created: str = field(default_factory=lambda: date.today().isoformat())
    revision: int = 1
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Сериализация метаданных."""
        return {
            "name": self.name,
            "author": self.author,
            "created": self.created,
            "revision": self.revision,
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectMeta:
        """Восстанавливает метаданные из словаря."""
        meta = cls()
        meta.name = str(data.get("name", ""))
        meta.author = str(data.get("author", ""))
        meta.created = str(data.get("created", meta.created))
        meta.revision = int(data.get("revision", meta.revision))
        meta.comment = str(data.get("comment", ""))
        return meta


@dataclass(slots=True)
class Project:
    """Проект целиком: автомобиль, передняя и задняя оси, модель B, снимки."""

    meta: ProjectMeta = field(default_factory=ProjectMeta)
    vehicle: Vehicle = field(default_factory=Vehicle)
    front: Axle = field(default_factory=lambda: Axle(role="front", type_code="double_wishbone"))
    rear: Axle = field(default_factory=lambda: Axle(role="rear", type_code="multilink_rear"))
    model_b: Project | None = None
    snapshots: list[Snapshot] = field(default_factory=list)
    view: ViewState = field(default_factory=ViewState)
    locks: dict[str, bool] = field(default_factory=dict)
    path: str | None = None

    # ------------------------------------------------------------------ создание
    def __post_init__(self) -> None:
        self.front.ensure_points()
        self.rear.ensure_points()

    @classmethod
    def create_default(cls) -> Project:
        """Пустой проект с типовой геометрией обеих осей."""
        project = cls()
        project.meta.name = ""
        return project

    # ------------------------------------------------------------------ доступ
    def axle(self, role: str) -> Axle:
        """Ось по роли: ``front`` или ``rear``."""
        if role == "front":
            return self.front
        if role == "rear":
            return self.rear
        raise ValueError(role)

    def axles(self) -> tuple[Axle, Axle]:
        """Обе оси проекта."""
        return (self.front, self.rear)

    def set_axle_type(self, role: str, type_code: str) -> None:
        """Меняет тип подвески оси, сохраняя общие точки."""
        if type_code not in REGISTRY:
            raise KeyError(type_code)
        axle = self.axle(role)
        axle.type_code = type_code
        axle.layout = axle.spec.default_layout
        axle.ensure_points()

    # ------------------------------------------------------------------ копии
    def clone(self) -> Project:
        """Глубокая копия проекта (без вложенной модели B)."""
        data = self.to_dict()
        data["model_b"] = None
        return Project.from_dict(data)

    def clone_as_model_b(self) -> Project:
        """Копия текущего состояния в качестве «модели B» для сравнения."""
        model_b = Project.from_dict(self._to_dict_without_b())
        model_b.model_b = None
        return model_b

    # ------------------------------------------------------------------ снимки
    def add_snapshot(self, name: str, note: str = "") -> None:
        """Сохраняет снимок настройки (полное состояние модели)."""
        self.snapshots.append(Snapshot(name=name.strip() or name, note=note, data=self._to_dict_without_b()))

    def restore_snapshot(self, index: int) -> None:
        """Возвращает модель к снимку с индексом ``index``."""
        if not 0 <= index < len(self.snapshots):
            raise IndexError(index)
        restored = Project.from_dict(copy.deepcopy(self.snapshots[index].data))
        self.meta = restored.meta
        self.vehicle = restored.vehicle
        self.front = restored.front
        self.rear = restored.rear
        self.view = restored.view

    # ------------------------------------------------------------------ JSON
    def _to_dict_without_b(self) -> dict[str, Any]:
        """Словарь проекта без вложенной модели B (для снимков)."""
        data = self.to_dict()
        data["model_b"] = None
        data["snapshots"] = []
        return data

    def to_dict(self) -> dict[str, Any]:
        """Полная сериализация проекта в JSON-совместимый словарь."""
        return {
            "schema_version": SCHEMA_VERSION,
            "meta": self.meta.to_dict(),
            "vehicle": self.vehicle.to_dict(),
            "front_axle": self.front.to_dict(),
            "rear_axle": self.rear.to_dict(),
            "model_b": self.model_b.to_dict() if self.model_b is not None else None,
            "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
            "view": self.view.to_dict(),
            "locks": {key: True for key, value in self.locks.items() if value},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        """Восстанавливает проект (с предварительной миграцией схемы)."""
        project = cls()
        project.meta = ProjectMeta.from_dict(_as_dict(data.get("meta")))
        project.vehicle = Vehicle.from_dict(_as_dict(data.get("vehicle")))
        project.front = Axle.from_dict("front", _as_dict(data.get("front_axle")))
        project.rear = Axle.from_dict("rear", _as_dict(data.get("rear_axle")))
        model_b_data = data.get("model_b")
        if isinstance(model_b_data, dict):
            project.model_b = Project.from_dict(model_b_data)
            project.model_b.model_b = None
        project.snapshots = [Snapshot.from_dict(_as_dict(item)) for item in _as_list(data.get("snapshots"))]
        project.view = ViewState.from_dict(_as_dict(data.get("view")))
        project.locks = {str(key): True for key in _as_dict(data.get("locks"))}
        project.front.ensure_points()
        project.rear.ensure_points()
        return project

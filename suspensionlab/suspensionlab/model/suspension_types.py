"""Реестр типов подвески.

Каждый тип подвески описывается декларативно: набор точек крепления,
набор рычагов/тяг, поддерживаемые опции (привод, рулевое, варианты
схемы моста). Панели интерфейса, схема и таблицы строятся по этому
описанию, поэтому добавление нового типа подвески не требует правок
интерфейса (требование ТЗ, §3 и §8).

Ядро расчёта (этапы M1/M4) обращается к реестру так же, как UI:
``REGISTRY[type_code]``. Сам реестр от Qt не зависит.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Описание точки и рычага
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PointSpec:
    """Описание точки крепления в реестре типа подвески."""

    code: str
    group: str
    role: str
    x: float
    y: float
    z: float
    mirrored: bool = True

    @property
    def name_key(self) -> str:
        """Ключ локализации названия точки."""
        return f"hp.{self.base_code}.name"

    @property
    def help_key(self) -> str:
        """Ключ локализации подсказки по точке."""
        return f"hp.{self.base_code}.help"

    @property
    def base_code(self) -> str:
        """Код без суффикса стороны (``ll_in_l`` → ``ll_in``)."""
        if self.code.endswith("_l") or self.code.endswith("_r"):
            return self.code[:-2]
        return self.code

    @property
    def side(self) -> str:
        """Сторона точки: ``left``/``right``/``center``."""
        if self.code.endswith("_l"):
            return "left"
        if self.code.endswith("_r"):
            return "right"
        return "center"


@dataclass(frozen=True, slots=True)
class LinkSpec:
    """Описание рычага или тяги.

    ``pivot`` — точки, задающие ось качания (одна — шарнир, две — ось).
    ``end`` — точка на кулаке/мосту, до которой измеряется длина.
    Длина редактируется пользователем (Р-3), режим смещения конца задаётся
    в самой модели (``Link.length_edit_mode``).
    """

    code: str
    pivot: tuple[str, ...]
    end: str
    group: str = "links"
    joint: str = "ball"
    movable_end: bool = True

    @property
    def name_key(self) -> str:
        """Ключ локализации названия рычага."""
        return f"link.{self.code}.name"

    @property
    def help_key(self) -> str:
        """Ключ локализации подсказки по рычагу."""
        return f"link.{self.code}.help"


@dataclass(frozen=True, slots=True)
class SuspensionTypeSpec:
    """Полное описание типа подвески."""

    code: str
    role: str  # "front" | "rear"
    points: tuple[PointSpec, ...]
    links: tuple[LinkSpec, ...]
    supports_driven: bool = True
    supports_steering: bool = False
    layouts: tuple[str, ...] = ()
    default_layout: str = ""
    point_groups: tuple[str, ...] = field(default_factory=tuple)

    @property
    def name_key(self) -> str:
        """Ключ локализации названия типа."""
        return f"type.{self.code}.name"

    @property
    def help_key(self) -> str:
        """Ключ локализации описания типа."""
        return f"type.{self.code}.help"

    def point(self, code: str) -> PointSpec | None:
        """Возвращает описание точки по коду."""
        for spec in self.points:
            if spec.code == code:
                return spec
        return None

    def point_codes(self) -> tuple[str, ...]:
        """Все коды точек типа в порядке описания."""
        return tuple(spec.code for spec in self.points)

    def link(self, code: str) -> LinkSpec | None:
        """Возвращает описание рычага по коду."""
        for spec in self.links:
            if spec.code == code:
                return spec
        return None


# ---------------------------------------------------------------------------
# Вспомогательные конструкторы точек
# ---------------------------------------------------------------------------


def _p(code: str, group: str, role: str, x: float, y: float, z: float, mirrored: bool = True) -> PointSpec:
    """Сокращённая запись описания точки."""
    return PointSpec(code=code, group=group, role=role, x=x, y=y, z=z, mirrored=mirrored)


#: Общие точки упруго-демпфирующих элементов для независимых подвесок.
_COMMON_ELASTIC = (
    _p("spring_lo", "spring", "arm", 0.0, 520.0, 150.0),
    _p("spring_up", "spring", "body", 0.0, 430.0, 560.0),
    _p("damper_lo", "damper", "arm", 0.0, 500.0, 160.0),
    _p("damper_up", "damper", "body", 0.0, 415.0, 545.0),
    _p("arb_lo", "arb", "arm", 0.0, 470.0, 155.0),
    _p("arb_up", "arb", "body", 0.0, 405.0, 320.0),
)

_COMMON_DRIVE = (
    _p("halfshaft_in", "drivetrain", "body", 0.0, 120.0, 300.0),
    _p("halfshaft_out", "drivetrain", "upright", 0.0, 700.0, 310.0),
)

_COMMON_WHEEL = (_p("wheel_center", "wheel", "upright", 0.0, 762.0, 310.0),)

_COMMON_LINK_TAIL = (
    LinkSpec(code="halfshaft", pivot=("halfshaft_in",), end="halfshaft_out", group="drivetrain"),
)


# ---------------------------------------------------------------------------
# Передняя двухрычажная
# ---------------------------------------------------------------------------

DOUBLE_WISHBONE = SuspensionTypeSpec(
    code="double_wishbone",
    role="front",
    points=(
        _p("uca_f_in", "upper_arm", "body", 90.0, 330.0, 395.0),
        _p("uca_r_in", "upper_arm", "body", -110.0, 340.0, 400.0),
        _p("ubj", "upper_arm", "upright", -5.0, 655.0, 430.0),
        _p("lca_f_in", "lower_arm", "body", 120.0, 250.0, 140.0),
        _p("lca_r_in", "lower_arm", "body", -140.0, 260.0, 150.0),
        _p("lbj", "lower_arm", "upright", 0.0, 690.0, 145.0),
        _p("tierod_in", "steering", "body", -120.0, 280.0, 170.0),
        _p("tierod_out", "steering", "upright", -150.0, 640.0, 175.0),
        *_COMMON_ELASTIC,
        *_COMMON_DRIVE,
        *_COMMON_WHEEL,
    ),
    links=(
        LinkSpec(code="upper_arm", pivot=("uca_f_in", "uca_r_in"), end="ubj", group="upper_arm"),
        LinkSpec(code="lower_arm", pivot=("lca_f_in", "lca_r_in"), end="lbj", group="lower_arm"),
        LinkSpec(code="tierod", pivot=("tierod_in",), end="tierod_out", group="steering", joint="rod_end"),
        *_COMMON_LINK_TAIL,
    ),
    supports_driven=True,
    supports_steering=True,
    point_groups=("upper_arm", "lower_arm", "steering", "spring", "damper", "arb", "drivetrain", "wheel"),
)

# ---------------------------------------------------------------------------
# Передняя многорычажная
# ---------------------------------------------------------------------------

MULTILINK_FRONT = SuspensionTypeSpec(
    code="multilink_front",
    role="front",
    points=(
        _p("l1_in", "upper_links", "body", 150.0, 320.0, 420.0),
        _p("l1_out", "upper_links", "upright", 120.0, 660.0, 425.0),
        _p("l2_in", "upper_links", "body", -160.0, 330.0, 415.0),
        _p("l2_out", "upper_links", "upright", -130.0, 665.0, 420.0),
        _p("l3_in", "lower_links", "body", 170.0, 280.0, 155.0),
        _p("l3_out", "lower_links", "upright", 140.0, 690.0, 160.0),
        _p("l4_in", "lower_links", "body", -180.0, 290.0, 150.0),
        _p("l4_out", "lower_links", "upright", -150.0, 695.0, 155.0),
        _p("tierod_in", "steering", "body", -120.0, 300.0, 185.0),
        _p("tierod_out", "steering", "upright", -170.0, 645.0, 190.0),
        *_COMMON_ELASTIC,
        *_COMMON_DRIVE,
        *_COMMON_WHEEL,
    ),
    links=(
        LinkSpec(code="link1", pivot=("l1_in",), end="l1_out", group="upper_links"),
        LinkSpec(code="link2", pivot=("l2_in",), end="l2_out", group="upper_links"),
        LinkSpec(code="link3", pivot=("l3_in",), end="l3_out", group="lower_links"),
        LinkSpec(code="link4", pivot=("l4_in",), end="l4_out", group="lower_links"),
        LinkSpec(code="tierod", pivot=("tierod_in",), end="tierod_out", group="steering", joint="rod_end"),
        *_COMMON_LINK_TAIL,
    ),
    supports_driven=True,
    supports_steering=True,
    point_groups=("upper_links", "lower_links", "steering", "spring", "damper", "arb", "drivetrain", "wheel"),
)

# ---------------------------------------------------------------------------
# Задняя независимая многорычажная (5-link)
# ---------------------------------------------------------------------------

MULTILINK_REAR = SuspensionTypeSpec(
    code="multilink_rear",
    role="rear",
    points=(
        _p("uf_in", "upper_links", "body", 180.0, 300.0, 430.0),
        _p("uf_out", "upper_links", "upright", 120.0, 680.0, 420.0),
        _p("ur_in", "upper_links", "body", -200.0, 320.0, 450.0),
        _p("ur_out", "upper_links", "upright", -140.0, 690.0, 430.0),
        _p("lf_in", "lower_links", "body", 160.0, 280.0, 150.0),
        _p("lf_out", "lower_links", "upright", 130.0, 700.0, 160.0),
        _p("lr_in", "lower_links", "body", -180.0, 290.0, 140.0),
        _p("lr_out", "lower_links", "upright", -160.0, 700.0, 150.0),
        _p("toe_in", "steering", "body", -260.0, 300.0, 300.0),
        _p("toe_out", "steering", "upright", -240.0, 690.0, 300.0),
        *_COMMON_ELASTIC,
        *_COMMON_DRIVE,
        *_COMMON_WHEEL,
    ),
    links=(
        LinkSpec(code="upper_front", pivot=("uf_in",), end="uf_out", group="upper_links"),
        LinkSpec(code="upper_rear", pivot=("ur_in",), end="ur_out", group="upper_links"),
        LinkSpec(code="lower_front", pivot=("lf_in",), end="lf_out", group="lower_links"),
        LinkSpec(code="lower_rear", pivot=("lr_in",), end="lr_out", group="lower_links"),
        LinkSpec(code="toe_link", pivot=("toe_in",), end="toe_out", group="steering", joint="rod_end"),
        *_COMMON_LINK_TAIL,
    ),
    supports_driven=True,
    supports_steering=False,
    point_groups=("upper_links", "lower_links", "steering", "spring", "damper", "arb", "drivetrain", "wheel"),
)

# ---------------------------------------------------------------------------
# Задний неразрезной мост на пружинах
# ---------------------------------------------------------------------------

LIVE_AXLE_POINTS = (
    _p("ll_in_l", "trailing_links", "body", 320.0, 430.0, 260.0, mirrored=False),
    _p("ll_out_l", "trailing_links", "axle", 300.0, 640.0, 180.0, mirrored=False),
    _p("ll_in_r", "trailing_links", "body", 320.0, -430.0, 260.0, mirrored=False),
    _p("ll_out_r", "trailing_links", "axle", 300.0, -640.0, 180.0, mirrored=False),
    _p("ul_in_l", "trailing_links", "body", -320.0, 400.0, 420.0, mirrored=False),
    _p("ul_out_l", "trailing_links", "axle", -300.0, 630.0, 330.0, mirrored=False),
    _p("ul_in_r", "trailing_links", "body", -320.0, -400.0, 420.0, mirrored=False),
    _p("ul_out_r", "trailing_links", "axle", -300.0, -630.0, 330.0, mirrored=False),
    _p("tri_in", "triangulated", "body", 0.0, 0.0, 440.0, mirrored=False),
    _p("tri_out_l", "triangulated", "axle", 0.0, 430.0, 320.0, mirrored=False),
    _p("tri_out_r", "triangulated", "axle", 0.0, -430.0, 320.0, mirrored=False),
    _p("panhard_body", "lateral", "body", -120.0, 400.0, 300.0, mirrored=False),
    _p("panhard_axle", "lateral", "axle", -120.0, -380.0, 200.0, mirrored=False),
    _p("watt_center", "lateral", "axle", 0.0, 0.0, 230.0, mirrored=False),
    _p("watt_l", "lateral", "body", 0.0, 300.0, 330.0, mirrored=False),
    _p("watt_r", "lateral", "body", 0.0, -300.0, 330.0, mirrored=False),
    _p("torquearm_in", "torque_arm", "body", 700.0, 0.0, 300.0, mirrored=False),
    _p("torquearm_out", "torque_arm", "axle", 120.0, 0.0, 240.0, mirrored=False),
    _p("spring_lo_l", "spring", "axle", 0.0, 430.0, 170.0, mirrored=False),
    _p("spring_up_l", "spring", "body", 0.0, 430.0, 520.0, mirrored=False),
    _p("spring_lo_r", "spring", "axle", 0.0, -430.0, 170.0, mirrored=False),
    _p("spring_up_r", "spring", "body", 0.0, -430.0, 520.0, mirrored=False),
    _p("damper_lo_l", "damper", "axle", 120.0, 470.0, 160.0, mirrored=False),
    _p("damper_up_l", "damper", "body", 120.0, 470.0, 500.0, mirrored=False),
    _p("damper_lo_r", "damper", "axle", 120.0, -470.0, 160.0, mirrored=False),
    _p("damper_up_r", "damper", "body", 120.0, -470.0, 500.0, mirrored=False),
    _p("pinion_center", "drivetrain", "axle", 0.0, 0.0, 300.0, mirrored=False),
    _p("driveshaft_front", "drivetrain", "body", 900.0, 0.0, 320.0, mirrored=False),
    _p("axle_center_l", "axle", "axle", 0.0, 640.0, 310.0, mirrored=False),
    _p("axle_center_r", "axle", "axle", 0.0, -640.0, 310.0, mirrored=False),
    _p("wheel_center_l", "wheel", "axle", 0.0, 720.0, 310.0, mirrored=False),
    _p("wheel_center_r", "wheel", "axle", 0.0, -720.0, 310.0, mirrored=False),
)

LIVE_AXLE_LINKS = (
    LinkSpec(code="lower_trailing_left", pivot=("ll_in_l",), end="ll_out_l", group="trailing_links"),
    LinkSpec(code="lower_trailing_right", pivot=("ll_in_r",), end="ll_out_r", group="trailing_links"),
    LinkSpec(code="upper_trailing_left", pivot=("ul_in_l",), end="ul_out_l", group="trailing_links"),
    LinkSpec(code="upper_trailing_right", pivot=("ul_in_r",), end="ul_out_r", group="trailing_links"),
    LinkSpec(code="panhard", pivot=("panhard_body",), end="panhard_axle", group="lateral", joint="rod_end"),
    LinkSpec(code="torque_arm", pivot=("torquearm_in",), end="torquearm_out", group="torque_arm", joint="bushing"),
    LinkSpec(code="driveshaft", pivot=("driveshaft_front",), end="pinion_center", group="drivetrain", joint="cv"),
)

LIVE_AXLE = SuspensionTypeSpec(
    code="live_axle_coil",
    role="rear",
    points=LIVE_AXLE_POINTS,
    links=LIVE_AXLE_LINKS,
    supports_driven=True,
    supports_steering=False,
    layouts=("4link_panhard", "4link_watt", "3link_panhard", "torquearm_panhard"),
    default_layout="4link_panhard",
    point_groups=(
        "trailing_links",
        "triangulated",
        "lateral",
        "torque_arm",
        "spring",
        "damper",
        "drivetrain",
        "axle",
        "wheel",
    ),
)

#: Все типы подвесок, доступные в приложении.
REGISTRY: dict[str, SuspensionTypeSpec] = {
    spec.code: spec for spec in (DOUBLE_WISHBONE, MULTILINK_FRONT, MULTILINK_REAR, LIVE_AXLE)
}


def types_for_role(role: str) -> tuple[str, ...]:
    """Коды типов подвески для передней или задней оси."""
    if role == "front":
        return ("double_wishbone", "multilink_front")
    if role == "rear":
        return ("multilink_rear", "live_axle_coil")
    return ()


def get_type(code: str) -> SuspensionTypeSpec:
    """Возвращает описание типа подвески по коду."""
    if code not in REGISTRY:
        raise KeyError(code)
    return REGISTRY[code]

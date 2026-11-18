"""Единицы измерения: внутренние величины и их отображение.

Внутри приложения все величины хранятся в системе, близкой к СИ:
мм, градусы, Н, Н/мм, кг, Н·м, Гц. Конвертация выполняется только на
границе интерфейса (инспектор, схемы, чертежи, отчёты) — это правило
из ТЗ (§8) и оно соблюдается во всём коде.

Пользователь может вводить значения:
* с десятичной запятой или точкой: ``12,5`` и ``12.5``;
* с разделителем тысяч пробелом: ``1 234,5``;
* с единицей измерения: ``340 мм``, ``12 см``, ``2.5in``, ``1"``;
* в виде арифметического выражения: ``120+15/2``, ``340*0.98``.

Модуль не зависит от Qt и полностью покрыт тестами.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Виды величин
# ---------------------------------------------------------------------------


class UnitKind(str, Enum):
    """Вид физической величины (влияет на разбор и форматирование)."""

    LENGTH = "length"
    ANGLE = "angle"
    RATE = "rate"
    MASS = "mass"
    FORCE = "force"
    MOMENT = "moment"
    FREQUENCY = "frequency"
    PLAIN = "plain"


#: Коэффициенты перевода в базовую единицу: код -> (коэффициент, точность).
LENGTH_UNITS: dict[str, float] = {"mm": 1.0, "cm": 10.0, "in": 25.4}
RATE_UNITS: dict[str, float] = {
    "N_mm": 1.0,
    "kgf_mm": 9.80665,
    "lb_in": 4.4482216152605 / 25.4,
}
ANGLE_UNITS: dict[str, float] = {"deg": 1.0, "degmin": 1.0, "rad": 180.0 / math.pi}
MASS_UNITS: dict[str, float] = {"kg": 1.0, "lb": 0.45359237}
FORCE_UNITS: dict[str, float] = {"N": 1.0, "kgf": 9.80665, "lbf": 4.4482216152605}

#: Текстовые обозначения единиц для суффикса в поле ввода.
UNIT_SUFFIXES: dict[str, float] = {
    "мм": 1.0,
    "mm": 1.0,
    "см": 10.0,
    "cm": 10.0,
    "in": 25.4,
    "inch": 25.4,
    "дюйм": 25.4,
    "дюйма": 25.4,
    "дюймов": 25.4,
    '"': 25.4,
    "″": 25.4,
}


class UnitConversionError(ValueError):
    """Ошибка разбора числового ввода.

    Текст сообщения — ключ локализации, а не готовая строка: интерфейс
    сам переведёт его и покажет пользователю по-русски.
    """

    def __init__(self, message_key: str, value: str = "") -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.value = value


# ---------------------------------------------------------------------------
# Нормализация и разбор
# ---------------------------------------------------------------------------

_THIN_SPACES = "\u00a0\u202f\u2009"
_UNIT_TAIL_RE = re.compile(r"^(?P<expr>.*?)\s*(?P<unit>мм|mm|см|cm|inch|in|дюймов|дюйма|дюйм|\"|″)\s*$")
_DMS_RE = re.compile(
    r"^(?P<deg>-?\d+(?:[.,]\d+)?)\s*°\s*(?:(?P<min>\d+(?:[.,]\d+)?)\s*[′']?)?\s*$"
)


def normalize_number_text(text: str) -> str:
    """Приводит пользовательскую запись числа к виду, понятному ``float``.

    Убирает разделители тысяч (пробелы), заменяет десятичную запятую
    точкой. Если в строке есть и точка, и запятая, точка считается
    десятичной (``1,234.5`` — западный стиль), запятая — разделителем
    тысяч.
    """
    cleaned = text.strip()
    for space in _THIN_SPACES:
        cleaned = cleaned.replace(space, " ")
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        raise UnitConversionError("error.number.empty", text)
    cleaned = cleaned.replace(",", "") if "," in cleaned and "." in cleaned else cleaned.replace(",", ".")
    return cleaned


_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)


def _eval_node(node: ast.AST) -> float:
    """Безопасное вычисление арифметического выражения из числа и операторов."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnitConversionError("error.number.format", str(node.value))
        return float(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise UnitConversionError("error.number.division_by_zero")
            return left / right
        return left**right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise UnitConversionError("error.number.format", ast.dump(node))


def eval_expression(text: str) -> float:
    """Вычисляет арифметическое выражение, записанное пользователем."""
    normalized = normalize_number_text(text)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as error:
        raise UnitConversionError("error.number.format", text) from error
    try:
        value = _eval_node(tree)
    except (OverflowError, ValueError, ZeroDivisionError, TypeError) as error:
        if isinstance(error, UnitConversionError):
            raise
        raise UnitConversionError("error.number.format", text) from error
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        raise UnitConversionError("error.number.format", text)
    return value


def parse_length_mm(text: str) -> float:
    """Разбирает длину и возвращает миллиметры."""
    raw = text.strip()
    match = _UNIT_TAIL_RE.match(raw) if raw else None
    if match and match.group("expr").strip():
        factor = UNIT_SUFFIXES[match.group("unit")]
        return eval_expression(match.group("expr")) * factor
    return eval_expression(raw)


def parse_angle_deg(text: str) -> float:
    """Разбирает угол (градусы или градусы-минуты) и возвращает градусы."""
    raw = text.strip()
    dms = _DMS_RE.match(raw)
    if dms:
        degrees = float(normalize_number_text(dms.group("deg")))
        minutes_text = dms.group("min")
        minutes = float(normalize_number_text(minutes_text)) if minutes_text else 0.0
        sign = -1.0 if dms.group("deg").startswith("-") else 1.0
        return degrees + sign * minutes / 60.0
    if raw.endswith("′") or raw.endswith("'"):
        raise UnitConversionError("error.number.format", text)
    return eval_expression(raw)


def parse_rate(text: str) -> float:
    """Разбирает жёсткость в Н/мм (допускает ``кгс/мм`` и ``lb/in``)."""
    raw = text.strip().lower()
    for suffix, factor in (("кгс/мм", 9.80665), ("kgf/mm", 9.80665), ("lb/in", 4.4482216152605 / 25.4)):
        if raw.endswith(suffix):
            base = eval_expression(raw[: -len(suffix)].strip())
            return base * factor
    return eval_expression(raw)


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------


def format_number(value: float, decimals: int = 1, group_thousands: bool = True) -> str:
    """Форматирует число по-русски: запятая в дроби, пробел в тысячах."""
    if not math.isfinite(value):
        return "—"
    text = f"{abs(value):.{decimals}f}"
    integer, _, fraction = text.partition(".")
    if group_thousands and len(integer) > 3:
        groups: list[str] = []
        while len(integer) > 3:
            groups.insert(0, integer[-3:])
            integer = integer[:-3]
        groups.insert(0, integer)
        integer = " ".join(groups)
    result = integer + ("," + fraction if fraction else "")
    return ("-" if value < 0 and float(result.replace(" ", "").replace(",", ".")) != 0 else "") + result


def format_angle_deg(value: float, decimals: int = 2) -> str:
    """Форматирует угол в градусах с символом ``°``."""
    return f"{format_number(value, decimals, group_thousands=False)}°"


def format_angle_deg_min(value: float) -> str:
    """Форматирует угол в градусах и минутах: ``12°30′``."""
    sign = "-" if value < 0 else ""
    total_minutes = round(abs(value) * 60.0)
    degrees, minutes = divmod(total_minutes, 60)
    return f"{sign}{degrees}°{minutes:02d}′"


# ---------------------------------------------------------------------------
# Настройки отображения единиц
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UnitSettings:
    """Выбранные пользователем единицы отображения (см. ТЗ, §6.3)."""

    length: str = "mm"
    angle: str = "deg"
    rate: str = "N_mm"

    #: Точность отображения по видам величин.
    decimals_length: int = 1
    decimals_angle: int = 2
    decimals_rate: int = 1

    def __post_init__(self) -> None:
        if self.length not in LENGTH_UNITS:
            self.length = "mm"
        if self.angle not in ANGLE_UNITS:
            self.angle = "deg"
        if self.rate not in RATE_UNITS:
            self.rate = "N_mm"

    # ------------------------------------------------------------------ единицы
    def factor(self, kind: UnitKind) -> float:
        """Коэффициент перевода внутренней величины в выбранную единицу."""
        if kind is UnitKind.LENGTH:
            return 1.0 / LENGTH_UNITS[self.length]
        if kind is UnitKind.ANGLE:
            return 1.0 / ANGLE_UNITS[self.angle]
        if kind is UnitKind.RATE:
            return 1.0 / RATE_UNITS[self.rate]
        return 1.0

    def suffix_key(self, kind: UnitKind) -> str:
        """Ключ локализации для обозначения единицы."""
        if kind is UnitKind.LENGTH:
            return f"unit.length.{self.length}"
        if kind is UnitKind.ANGLE:
            return f"unit.angle.{self.angle}"
        if kind is UnitKind.RATE:
            return f"unit.rate.{self.rate}"
        if kind is UnitKind.MASS:
            return "unit.mass.kg"
        if kind is UnitKind.FORCE:
            return "unit.force.N"
        if kind is UnitKind.MOMENT:
            return "unit.moment.Nm"
        if kind is UnitKind.FREQUENCY:
            return "unit.frequency.Hz"
        return "unit.plain.none"

    def decimals(self, kind: UnitKind) -> int:
        """Точность отображения для вида величины."""
        if kind is UnitKind.LENGTH:
            return self.decimals_length
        if kind is UnitKind.ANGLE:
            return 0 if self.angle == "degmin" else self.decimals_angle
        if kind is UnitKind.RATE:
            return self.decimals_rate
        if kind is UnitKind.PLAIN:
            return 3
        return 1

    # ------------------------------------------------------------------ вывод
    def display(self, value_internal: float, kind: UnitKind) -> str:
        """Преобразует внутреннее значение в строку без единицы измерения."""
        value = value_internal * self.factor(kind)
        decimals = self.decimals(kind)
        if kind is UnitKind.ANGLE:
            if self.angle == "degmin":
                return format_angle_deg_min(value)
            return format_number(value, decimals, group_thousands=False)
        return format_number(value, decimals)

    # ------------------------------------------------------------------ ввод
    def parse(self, text: str, kind: UnitKind) -> float:
        """Разбирает пользовательский ввод и возвращает внутреннее значение."""
        if kind is UnitKind.LENGTH:
            match = _UNIT_TAIL_RE.match(text.strip())
            if match and match.group("expr").strip():
                return parse_length_mm(text)
            return eval_expression(text) * LENGTH_UNITS[self.length]
        if kind is UnitKind.ANGLE:
            if "°" in text or "′" in text or "'" in text:
                return parse_angle_deg(text)
            return eval_expression(text) * ANGLE_UNITS[self.angle]
        if kind is UnitKind.RATE:
            if any(text.strip().lower().endswith(s) for s in ("кгс/мм", "kgf/mm", "lb/in")):
                return parse_rate(text)
            return eval_expression(text) * RATE_UNITS[self.rate]
        return eval_expression(text)

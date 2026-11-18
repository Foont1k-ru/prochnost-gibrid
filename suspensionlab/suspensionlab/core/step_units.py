"""Осторожный обзор единиц длины в выбранных контекстах STEP Part 21.

Читает только прямой GLOBAL_UNIT_ASSIGNED_CONTEXT и комплексные SI_UNIT длины.
Это не валидация STEP и не разрешение всех возможных единиц и вложенных контекстов.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .step_inventory import _COMPLEX, _args, _ref, _statements
from .step_placements import _complex_components

UnitStatus = Literal["known", "missing", "ambiguous", "unsupported", "limit"]


@dataclass(frozen=True)
class ContextLengthUnit:
    context: int
    status: UnitStatus
    unit_entity: int | None = None
    mm_per_unit: float | None = None


# ISO SI_PREFIX; коэффициент вычисляется в миллиметрах на одну указанную единицу.
_PREFIX = {"$": 0, ".EXA.": 18, ".PETA.": 15, ".TERA.": 12, ".GIGA.": 9,
           ".MEGA.": 6, ".KILO.": 3, ".HECTO.": 2, ".DECA.": 1, ".DECI.": -1,
           ".CENTI.": -2, ".MILLI.": -3, ".MICRO.": -6, ".NANO.": -9,
           ".PICO.": -12, ".FEMTO.": -15, ".ATTO.": -18}
_MAX_REFERENCES = 20_000
_MAX_TOTAL_REFERENCES = 100_000


def _components_by_id(text: str, identifiers: set[int]) -> dict[int, list[tuple[str, str]] | None]:
    """Только комплексные записи указанных идентификаторов; строки не анализируются как объекты."""
    result: dict[int, list[tuple[str, str]] | None] = {}
    for statement in _statements(text):
        match = _COMPLEX.match(statement)
        if match:
            number = int(match.group(1))
            if number in identifiers:
                result[number] = _complex_components(statement, match.end())
    return result


def _references(body: str) -> tuple[int, ...] | None:
    body = body.strip()
    if not body.startswith("(") or not body.endswith(")") or len(body) > 200_000:
        return None
    try:
        parts = _args(body[1:-1])
        if len(parts) > _MAX_REFERENCES:
            return None
        return tuple(_ref(part) for part in parts)
    except ValueError:
        return None


def _unit_kind(components: list[tuple[str, str]] | None) -> tuple[str, float | None]:
    """length/other/unsupported/unknown и масштаб, без предположений о пропущенных записях."""
    if components is None:
        return "unknown", None
    names = [name for name, _ in components]
    length_count = names.count("LENGTH_UNIT")
    angle_count = names.count("PLANE_ANGLE_UNIT") + names.count("SOLID_ANGLE_UNIT")
    if not length_count:
        # Другие единицы не считаются автоматически безвредными: распознаём только
        # обычные SI-единицы плоского и телесного угла.
        angle_name = "PLANE_ANGLE_UNIT" if "PLANE_ANGLE_UNIT" in names else "SOLID_ANGLE_UNIT"
        expected = ".RADIAN." if angle_name == "PLANE_ANGLE_UNIT" else ".STERADIAN."
        if (angle_count != 1 or len(names) != 3 or set(names) != {"NAMED_UNIT", "SI_UNIT", angle_name} or
                next((body for name, body in components if name == "NAMED_UNIT"), None) != "*" or
                next((body for name, body in components if name == angle_name), None) != ""):
            return "unknown", None
        try:
            angle = _args(next(body for name, body in components if name == "SI_UNIT"))
            return ("other", None) if len(angle) == 2 and angle[0] == "$" and angle[1].upper() == expected else ("unknown", None)
        except ValueError:
            return "unknown", None
    if length_count != 1 or angle_count or names.count("SI_UNIT") != 1 or names.count("NAMED_UNIT") != 1:
        return "unsupported", None
    if any(body for name, body in components if name == "LENGTH_UNIT"):
        return "unsupported", None
    if next(body for name, body in components if name == "NAMED_UNIT") != "*":
        return "unsupported", None
    # Неподдерживаемые дополнительные подтипы могут менять смысл объявления.
    if set(names) != {"LENGTH_UNIT", "NAMED_UNIT", "SI_UNIT"}:
        return "unsupported", None
    try:
        body = next(body for name, body in components if name == "SI_UNIT")
        values = _args(body)
        if len(values) != 2 or values[1].upper() != ".METRE.":
            return "unsupported", None
        exponent = _PREFIX.get(values[0].upper())
        if exponent is None:
            return "unsupported", None
        return "length", 10.0 ** (exponent + 3)
    except ValueError:
        return "unsupported", None


def inspect_context_units(text: str, contexts: set[int]) -> tuple[ContextLengthUnit, ...]:
    """Декларация масштаба длины в каждом контексте; никакой конвертации координат."""
    if not contexts:
        return ()
    context_entities = _components_by_id(text, contexts)
    candidates: dict[int, tuple[int, ...] | None] = {}
    ambiguous: set[int] = set()
    reference_count = 0
    for context in contexts:
        components = context_entities.get(context)
        if components is None:
            candidates[context] = None
            continue
        assignments = [body for name, body in components if name == "GLOBAL_UNIT_ASSIGNED_CONTEXT"]
        if len(assignments) > 1:
            ambiguous.add(context)
            continue
        refs = _references(assignments[0]) if assignments else None
        candidates[context] = refs
        reference_count += len(refs) if refs is not None else 0
        if reference_count > _MAX_TOTAL_REFERENCES:
            return tuple(ContextLengthUnit(number, "limit") for number in sorted(contexts))
    unit_ids = {number for refs in candidates.values() if refs is not None for number in refs}
    units = _components_by_id(text, unit_ids) if unit_ids else {}
    output = []
    for context in sorted(contexts):
        refs = candidates.get(context)
        if context in ambiguous:
            output.append(ContextLengthUnit(context, "ambiguous"))
        elif refs is None:
            output.append(ContextLengthUnit(context, "missing"))
        elif len(set(refs)) != len(refs):
            output.append(ContextLengthUnit(context, "ambiguous"))
        else:
            classified = [(number, *_unit_kind(units.get(number))) for number in refs]
            lengths = [(number, factor) for number, kind, factor in classified if kind in ("length", "unsupported")]
            if len(lengths) > 1:
                output.append(ContextLengthUnit(context, "ambiguous"))
            elif len(lengths) != 1 or any(kind in ("unknown", "unsupported") for _, kind, _ in classified):
                output.append(ContextLengthUnit(context, "unsupported"))
            else:
                unit, factor = lengths[0]
                output.append(ContextLengthUnit(context, "known", unit, factor))
    return tuple(output)

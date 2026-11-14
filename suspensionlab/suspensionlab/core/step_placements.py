"""Частичное чтение пар систем координат STEP, без вычисления поз деталей.

Поддерживается только явная цепочка NAUO → PRODUCT_DEFINITION_SHAPE →
CONTEXT_DEPENDENT_SHAPE_REPRESENTATION → комплексное отношение →
ITEM_DEFINED_TRANSFORMATION → два AXIS2_PLACEMENT_3D. Никакого разрешения
контекстов представлений, единиц, направления преобразования или дерева нет.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from math import hypot, isfinite
from typing import Literal

from .step_inventory import _COMPLEX, _RECORD, _args, _ref, _statements

Vector = tuple[float, float, float]
Issue = Literal["missing", "ambiguous", "unsupported", "invalid"]


@dataclass(frozen=True)
class Frame:
    entity: int
    origin: Vector
    x: Vector
    y: Vector
    z: Vector


@dataclass(frozen=True)
class PlacementFrames:
    occurrence: int
    relation: int | None
    transformation: int | None
    first: Frame | None
    second: Frame | None
    issue: Issue | None


class PlacementLimitError(ValueError):
    pass


_COMPONENT = re.compile(r"\s*([A-Z][A-Z0-9_]*)\s*\(", re.I)
_BRACKETS = re.compile(r"'(?:''|[^'])*'|[()]", re.DOTALL)
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?\Z")
_LIMIT = 20_000


def _unit(v: Vector) -> Vector:
    length = hypot(*v)
    if not isfinite(length) or length < 1e-12:
        raise ValueError("zero direction")
    return tuple(n / length for n in v)  # type: ignore[return-value]


def _cross(a: Vector, b: Vector) -> Vector:
    return a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]


def _frame(entity: int, origin: Vector, axis: Vector | None, reference: Vector | None) -> Frame:
    if axis is None and reference is None:
        axis, reference = (0., 0., 1.), (1., 0., 0.)
    elif axis is None or reference is None:
        # Частичные значения по умолчанию требуют полного алгоритма STEP; не угадываем.
        raise ValueError("partial defaults")
    z, ref = _unit(axis), _unit(reference)
    y_raw = _cross(z, ref)
    if hypot(*y_raw) < 1e-10:
        raise ValueError("parallel directions")
    y = _unit(y_raw)
    x = _unit(_cross(y, z))
    return Frame(entity, origin, x, y, z)


def _vector(value: str) -> Vector:
    value = value.strip()
    if not (value.startswith("(") and value.endswith(")")):
        raise ValueError("vector expected")
    parts = _args(value[1:-1])
    if len(parts) != 3 or not all(_NUMBER.fullmatch(n) for n in parts):
        raise ValueError("3D numeric vector expected")
    xyz = tuple(float(n) for n in parts)
    if not all(isfinite(n) and abs(n) <= 1e100 for n in xyz):
        raise ValueError("nonfinite or excessive vector")
    return xyz  # type: ignore[return-value]


def _record(statement: str):
    """Игнорируем другие записи; заголовок и уникальность уже проверены обзором."""
    return _RECORD.fullmatch(statement)


def _relationship_components(statement: str, start: int) -> list[int]:
    """Ищем только непосредственные компоненты комплексной записи, не имена внутри строк."""
    tail = statement[start:].strip()
    if not tail.endswith(")"):
        return []
    body = tail[:-1]
    pos = 0
    names: set[str] = set()
    refs: list[int] = []
    while pos < len(body):
        if not body[pos:].strip():
            break
        component = _COMPONENT.match(body, pos)
        if not component:
            return []
        name = component.group(1).upper()
        names.add(name)
        depth = 1
        end = None
        for bracket in _BRACKETS.finditer(body, component.end()):
            token = bracket.group()
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0:
                    end = bracket.start()
                    pos = bracket.end()
                    break
        if end is None:
            return []
        if name == "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION":
            try:
                refs.append(_ref(body[component.end():end].strip()))
            except ValueError:
                return []
    required = {"REPRESENTATION_RELATIONSHIP", "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION",
                "SHAPE_REPRESENTATION_RELATIONSHIP"}
    return refs if required <= names else []


def inspect_placement_frames(text: str, occurrences: tuple[int, ...]) -> tuple[PlacementFrames, ...]:
    """Вернуть две системы записи без предположения, как они переносят тело."""
    wanted = set(occurrences)
    shapes: dict[int, int] = {}
    contexts: list[tuple[int, int]] = []
    relations: dict[int, list[int]] = {}
    transforms: dict[int, tuple[int, int]] = {}
    for statement in _statements(text):
        match = _record(statement)
        if match:
            kind = match.group(2).upper()
            if kind not in {"PRODUCT_DEFINITION_SHAPE", "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION", "ITEM_DEFINED_TRANSFORMATION"}:
                continue
            try:
                number = int(match.group(1))
                args = _args(match.group(3))
                if kind == "PRODUCT_DEFINITION_SHAPE":
                    target = _ref(args[2])
                    if target in wanted:
                        shapes[number] = target
                elif kind == "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION":
                    contexts.append((_ref(args[0]), _ref(args[1])))
                else:
                    transforms[number] = (_ref(args[2]), _ref(args[3]))
            except (ValueError, IndexError):
                continue
        elif "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION" in statement.upper():
            cm = _COMPLEX.match(statement)
            if cm:
                relations[int(cm.group(1))] = _relationship_components(statement, cm.end())
        if max(len(shapes), len(contexts), len(relations), len(transforms)) > _LIMIT:
            raise PlacementLimitError("too many placement records")
    links: dict[int, list[int]] = defaultdict(list)
    for relation, shape in contexts:
        if shape in shapes:
            links[shapes[shape]].append(relation)
    axis_ids: set[int] = set()
    selection: dict[int, tuple[int | None, int | None, tuple[int, int] | None, Issue | None]] = {}
    for occurrence in occurrences:
        matches = links.get(occurrence, [])
        if len(matches) != 1:
            selection[occurrence] = (None, None, None, "ambiguous" if matches else "missing")
            continue
        relation = matches[0]
        refs = relations.get(relation, [])
        if len(refs) != 1:
            selection[occurrence] = (relation, None, None, "ambiguous" if len(refs) > 1 else "unsupported")
            continue
        transformation = refs[0]
        pair = transforms.get(transformation)
        if pair is None:
            selection[occurrence] = (relation, transformation, None, "unsupported")
            continue
        selection[occurrence] = (relation, transformation, pair, None)
        axis_ids.update(pair)

    axes: dict[int, tuple[int, int | None, int | None]] = {}
    for statement in _statements(text):
        match = _record(statement)
        if not match or match.group(2).upper() != "AXIS2_PLACEMENT_3D":
            continue
        number = int(match.group(1))
        if number not in axis_ids:
            continue
        try:
            args = _args(match.group(3))
            axes[number] = (_ref(args[1]), None if args[2] == "$" else _ref(args[2]),
                            None if args[3] == "$" else _ref(args[3]))
        except (ValueError, IndexError):
            continue
    vector_ids = {r for refs in axes.values() for r in refs if r is not None}
    vectors: dict[int, tuple[str, Vector]] = {}
    for statement in _statements(text):
        match = _record(statement)
        if not match or match.group(2).upper() not in ("CARTESIAN_POINT", "DIRECTION"):
            continue
        number = int(match.group(1))
        if number not in vector_ids:
            continue
        try:
            args = _args(match.group(3))
            vectors[number] = (match.group(2).upper(), _vector(args[1]))
        except (ValueError, IndexError):
            continue

    def make_frame(entity: int) -> Frame:
        origin_id, axis_id, ref_id = axes[entity]
        def vector(number: int, kind: str) -> Vector:
            actual, value = vectors[number]
            if actual != kind:
                raise ValueError("wrong entity type")
            return value
        origin = vector(origin_id, "CARTESIAN_POINT")
        axis = vector(axis_id, "DIRECTION") if axis_id is not None else None
        ref = vector(ref_id, "DIRECTION") if ref_id is not None else None
        return _frame(entity, origin, axis, ref)

    result = []
    for occurrence in occurrences:
        relation_id, transform_id, pair, issue = selection[occurrence]
        first = second = None
        if pair is not None:
            try:
                first, second = make_frame(pair[0]), make_frame(pair[1])
            except (KeyError, ValueError, ArithmeticError):
                first = second = None
                issue = "invalid"
        result.append(PlacementFrames(occurrence, relation_id, transform_id, first, second, issue))
    return tuple(result)

"""Частичное чтение пар систем координат STEP, без вычисления поз деталей.

Поддерживается только явная цепочка NAUO → PRODUCT_DEFINITION_SHAPE →
CONTEXT_DEPENDENT_SHAPE_REPRESENTATION → комплексное отношение →
ITEM_DEFINED_TRANSFORMATION → два AXIS2_PLACEMENT_3D. Частично сопоставляются
прямые ссылки представлений с определениями изделий. Единицы, направление
преобразования, геометрия и дерево глобальных положений не разрешаются.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
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
class RepresentationMatch:
    """Только прямые ссылки представлений; это не результат преобразования."""

    representation_1: int | None
    representation_2: int | None
    definition_1: int | None
    definition_2: int | None
    context_1: int | None
    context_2: int | None
    # Для каждой системы — наличие в списках rep1 и rep2; None = список не прочитан.
    frame_1_membership: tuple[bool | None, bool | None]
    frame_2_membership: tuple[bool | None, bool | None]
    status: Literal["child_parent", "parent_child", "mismatch", "ambiguous", "unresolved"]


@dataclass(frozen=True)
class PlacementFrames:
    occurrence: int
    relation: int | None
    transformation: int | None
    first: Frame | None
    second: Frame | None
    issue: Issue | None
    representation_match: RepresentationMatch | None


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


def _complex_components(statement: str, start: int) -> list[tuple[str, str]] | None:
    """Читает только непосредственные компоненты комплексного объекта."""
    tail = statement[start:].strip()
    if not tail.endswith(")"):
        return None
    body = tail[:-1]
    pos = 0
    result: list[tuple[str, str]] = []
    while pos < len(body):
        if not body[pos:].strip():
            break
        component = _COMPONENT.match(body, pos)
        if not component:
            return None
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
            return None
        result.append((component.group(1).upper(), body[component.end():end].strip()))
    return result


def _relationship_components(statement: str, start: int) -> tuple[list[int], list[tuple[int, int]]]:
    """Не извлекает ссылки из вложенных записей и строк."""
    components = _complex_components(statement, start)
    if components is None:
        return [], []
    names = {name for name, _body in components}
    required = {"REPRESENTATION_RELATIONSHIP", "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION",
                "SHAPE_REPRESENTATION_RELATIONSHIP"}
    if not required <= names:
        return [], []
    refs: list[int] = []
    representations: list[tuple[int, int]] = []
    invalid_representation = False
    for name, body in components:
        if name == "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION":
            try:
                refs.append(_ref(body))
            except ValueError:
                return [], []
        elif name == "REPRESENTATION_RELATIONSHIP":
            try:
                values = _args(body)
                representations.append((_ref(values[2]), _ref(values[3])))
            except (ValueError, IndexError):
                invalid_representation = True
    return refs, [] if invalid_representation else representations


def inspect_placement_frames(text: str, occurrences: Mapping[int, tuple[int, int]],
                             definitions: set[int]) -> tuple[PlacementFrames, ...]:
    """Вернуть две системы записи без предположения, как они переносят тело."""
    wanted = set(occurrences)
    shapes: dict[int, int] = {}
    contexts: list[tuple[int, int]] = []
    relations: dict[int, tuple[list[int], list[tuple[int, int]]]] = {}
    definition_shapes: dict[int, int] = {}
    shape_representations: list[tuple[int, int]] = []
    transforms: dict[int, tuple[int, int]] = {}
    for statement in _statements(text):
        match = _record(statement)
        if match:
            kind = match.group(2).upper()
            if kind not in {"PRODUCT_DEFINITION_SHAPE", "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION", "ITEM_DEFINED_TRANSFORMATION", "SHAPE_DEFINITION_REPRESENTATION"}:
                continue
            try:
                number = int(match.group(1))
                args = _args(match.group(3))
                if kind == "PRODUCT_DEFINITION_SHAPE":
                    target = _ref(args[2])
                    if target in wanted:
                        shapes[number] = target
                    if target in definitions:
                        definition_shapes[number] = target
                elif kind == "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION":
                    contexts.append((_ref(args[0]), _ref(args[1])))
                elif kind == "ITEM_DEFINED_TRANSFORMATION":
                    transforms[number] = (_ref(args[2]), _ref(args[3]))
                else:
                    shape_representations.append((_ref(args[0]), _ref(args[1])))
            except (ValueError, IndexError):
                continue
        elif "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION" in statement.upper():
            cm = _COMPLEX.match(statement)
            if cm:
                relations[int(cm.group(1))] = _relationship_components(statement, cm.end())
        if max(len(shapes), len(contexts), len(relations), len(transforms),
               len(definition_shapes), len(shape_representations)) > _LIMIT:
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
        refs, _rep_pairs = relations.get(relation, ([], []))
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
    rep_ids = {rep for relation, _, _, _ in selection.values() if relation is not None
               for pair in relations.get(relation, ([], []))[1] for rep in pair}
    rep_data: dict[int, tuple[frozenset[int], int]] = {}
    rep_types = {"SHAPE_REPRESENTATION", "ADVANCED_BREP_SHAPE_REPRESENTATION",
                 "MANIFOLD_SURFACE_SHAPE_REPRESENTATION", "FACETED_BREP_SHAPE_REPRESENTATION",
                 "GEOMETRICALLY_BOUNDED_SURFACE_SHAPE_REPRESENTATION"}
    for statement in _statements(text):
        match = _record(statement)
        if not match:
            continue
        kind, number = match.group(2).upper(), int(match.group(1))
        try:
            if kind == "AXIS2_PLACEMENT_3D" and number in axis_ids:
                args = _args(match.group(3))
                axes[number] = (_ref(args[1]), None if args[2] == "$" else _ref(args[2]),
                                None if args[3] == "$" else _ref(args[3]))
            elif kind in rep_types and number in rep_ids:
                args = _args(match.group(3))
                items = args[1]
                if not items.startswith("(") or not items.endswith(")") or len(items) > 200_000:
                    continue
                item_refs = _args(items[1:-1]) if items[1:-1].strip() else []
                if len(item_refs) > _LIMIT:
                    continue
                rep_data[number] = (frozenset(_ref(ref) for ref in item_refs), _ref(args[2]))
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

    rep_definitions: dict[int, list[int | None]] = defaultdict(list)
    for shape, representation in shape_representations:
        rep_definitions[representation].append(definition_shapes.get(shape))

    def match_representations(occurrence: int, relation_id: int, pair: tuple[int, int]) -> RepresentationMatch:
        rep_pairs = relations.get(relation_id, ([], []))[1]
        if len(rep_pairs) != 1:
            status: Literal["child_parent", "parent_child", "mismatch", "ambiguous", "unresolved"] = (
                "ambiguous" if len(rep_pairs) > 1 else "unresolved")
            return RepresentationMatch(None, None, None, None, None, None, (None, None), (None, None), status)
        rep1, rep2 = rep_pairs[0]
        def definition(rep: int) -> tuple[int | None, bool]:
            targets = rep_definitions.get(rep, [])
            concrete = {target for target in targets if target is not None}
            if len(concrete) > 1:
                return None, True
            if not targets or any(target is None for target in targets):
                return None, False
            return next(iter(concrete)), False
        def1, amb1 = definition(rep1)
        def2, amb2 = definition(rep2)
        parent, child = occurrences[occurrence]
        if amb1 or amb2 or parent == child:
            status = "ambiguous"
        elif def1 is None or def2 is None or rep1 not in rep_data or rep2 not in rep_data:
            status = "unresolved"
        elif (def1, def2) == (child, parent):
            status = "child_parent"
        elif (def1, def2) == (parent, child):
            status = "parent_child"
        else:
            status = "mismatch"
        def member(frame_id: int, rep_id: int) -> bool | None:
            data = rep_data.get(rep_id)
            return frame_id in data[0] if data is not None else None
        data1, data2 = rep_data.get(rep1), rep_data.get(rep2)
        return RepresentationMatch(rep1, rep2, def1, def2, data1[1] if data1 else None,
                                   data2[1] if data2 else None,
                                   (member(pair[0], rep1), member(pair[0], rep2)),
                                   (member(pair[1], rep1), member(pair[1], rep2)), status)

    result = []
    for occurrence in occurrences:
        relation_id, transform_id, pair, issue = selection[occurrence]
        first = second = None
        representation_match = None
        if pair is not None and relation_id is not None:
            representation_match = match_representations(occurrence, relation_id, pair)
            try:
                first, second = make_frame(pair[0]), make_frame(pair[1])
            except (KeyError, ValueError, ArithmeticError):
                first = second = None
                issue = "invalid"
        result.append(PlacementFrames(occurrence, relation_id, transform_id, first, second, issue, representation_match))
    return tuple(result)

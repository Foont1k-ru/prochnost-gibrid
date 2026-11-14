"""Ограниченный обзор текстового STEP Part 21, без CAD-импорта и проверки геометрии.

Только простые записи PRODUCT, PRODUCT_DEFINITION*, NEXT_ASSEMBLY_USAGE_OCCURRENCE.
Другие способы описать сборку не анализируются. Никакие положения не вычисляются.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
MAX_STATEMENT = 4 * 1024 * 1024
MAX_ENTITIES = 1_000_000
MAX_ITEMS = 10_000
_TOKEN = re.compile(r"'(?:''|[^'])*'|/\*.*?\*/|;|'|/\*", re.DOTALL)
_RECORD = re.compile(r"^\s*#([0-9]+)\s*=\s*([A-Z][A-Z0-9_]*)\s*\((.*)\)\s*$", re.DOTALL | re.IGNORECASE)
_COMPLEX = re.compile(r"^\s*#([0-9]+)\s*=\s*\(", re.DOTALL)
_REF = re.compile(r"#([0-9]+)\Z")
_ESCAPE = re.compile(r"\\X([24])\\([0-9A-Fa-f]+)\\X0\\", re.IGNORECASE)


class StepInventoryError(ValueError):
    """Файл не может быть безопасно прочитан этим ограниченным обзором."""


@dataclass(frozen=True)
class Product:
    entity: int
    identifier: str
    name: str


@dataclass(frozen=True)
class Occurrence:
    entity: int
    identifier: str
    name: str
    parent_definition: int
    child_definition: int
    parent: Product | None
    child: Product | None


@dataclass(frozen=True)
class StepInventory:
    schema: tuple[str, ...]
    products: tuple[Product, ...]
    occurrences: tuple[Occurrence, ...]
    definitions: int
    solid_records: int
    transformation_records: int
    unresolved_occurrences: int
    non_ascii_bytes: bool
    unsupported_string_escape: bool


def _statements(text: str):
    start = 0
    for match in _TOKEN.finditer(text):
        token = match.group()
        if match.end() - start > MAX_STATEMENT:
            raise StepInventoryError("Слишком большая запись STEP")
        if token in ("'", "/*"):
            raise StepInventoryError("Незакрытая строка или комментарий STEP")
        if token == ";":
            statement = text[start:match.start()]
            if "/*" in statement:
                statement = re.sub(r"'(?:''|[^'])*'|/\*.*?\*/", lambda m: " " if m.group().startswith("/*") else m.group(), statement, flags=re.DOTALL)
            yield statement.strip()
            start = match.end()
    if text[start:].strip():
        raise StepInventoryError("Незавершённая запись STEP")


def _args(body: str) -> list[str]:
    result = []
    start = depth = 0
    token = re.compile(r"'(?:''|[^'])*'|[(),]", re.DOTALL)
    for m in token.finditer(body):
        value = m.group()
        if value == "(":
            depth += 1
        elif value == ")":
            depth -= 1
            if depth < 0:
                raise StepInventoryError("Несогласованные скобки в записи STEP")
        elif value == "," and depth == 0:
            result.append(body[start:m.start()].strip())
            start = m.end()
    if depth:
        raise StepInventoryError("Несогласованные скобки в записи STEP")
    result.append(body[start:].strip())
    return result


def _string(value: str) -> tuple[str, bool]:
    if len(value) < 2 or value[0] != "'" or value[-1] != "'":
        raise StepInventoryError("Ожидалась строка в записи STEP")
    value = value[1:-1].replace("''", "'")
    if len(value) > 1024:
        raise StepInventoryError("Слишком длинная строка элемента STEP")
    def decode(match: re.Match[str]) -> str:
        try:
            raw = bytes.fromhex(match.group(2))
            return raw.decode("utf-16-be" if match.group(1) == "2" else "utf-32-be")
        except (ValueError, UnicodeError) as error:
            raise StepInventoryError("Некорректная Unicode-строка STEP") from error
    value = _ESCAPE.sub(decode, value)
    unsupported = "\\" in value
    # Управляющие символы не должны подменять строки отчёта.
    return "".join(c if c.isprintable() else " " for c in value), unsupported


def _ref(value: str) -> int:
    match = _REF.fullmatch(value)
    if not match or len(match.group(1)) > 9:
        raise StepInventoryError("Ожидалась ссылка на объект STEP")
    return int(match.group(1))


def read_step_inventory(path: Path) -> StepInventory:
    """Прочитать ограниченный обзор локального файла, не изменяя файл или проект."""
    try:
        with path.open("rb") as source:
            data = source.read(MAX_BYTES + 1)
    except OSError as error:
        raise StepInventoryError(f"Не удалось прочитать файл: {error}") from error
    if len(data) > MAX_BYTES:
        raise StepInventoryError("Файл превышает предел обзора 64 МиБ")
    text = data.decode("latin-1")
    products: dict[int, Product] = {}
    formations: dict[int, int] = {}
    definitions: dict[int, int] = {}
    links: list[tuple[int, str, str, int, int]] = []
    schema: list[str] = []
    seen: set[int] = set()
    counts: Counter[str] = Counter()
    state = "start"
    unsupported = False
    for statement in _statements(text):
        upper = statement.upper()
        if state == "start" and upper == "ISO-10303-21":
            state = "header_start"
        elif state == "header_start" and upper == "HEADER":
            state = "header"
        elif state == "header" and upper == "ENDSEC":
            state = "data_start"
        elif state == "header":
            if upper.startswith("FILE_SCHEMA"):
                schema.extend(_string(m.group())[0] for m in re.finditer(r"'(?:''|[^'])*'", statement))
        elif state == "data_start" and upper == "DATA":
            state = "data"
        elif state == "data" and upper == "ENDSEC":
            state = "end"
        elif state == "end" and upper == "END-ISO-10303-21":
            state = "done"
        elif state == "data":
            match = _RECORD.fullmatch(statement)
            complex_match = _COMPLEX.match(statement) if not match else None
            if not match and not complex_match:
                raise StepInventoryError("Неизвестный формат записи DATA")
            digits = (match or complex_match).group(1)  # type: ignore[union-attr]
            if len(digits) > 9:
                raise StepInventoryError("Слишком длинный номер объекта STEP")
            number = int(digits)
            if number in seen or number == 0:
                raise StepInventoryError("Повторяющийся или нулевой номер объекта STEP")
            seen.add(number)
            if len(seen) > MAX_ENTITIES:
                raise StepInventoryError("Слишком много записей STEP")
            if not match:
                continue
            kind = match.group(2).upper()
            if kind in ("MANIFOLD_SOLID_BREP", "ITEM_DEFINED_TRANSFORMATION"):
                counts[kind] += 1
            if kind not in ("PRODUCT", "PRODUCT_DEFINITION", "PRODUCT_DEFINITION_FORMATION", "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE", "NEXT_ASSEMBLY_USAGE_OCCURRENCE"):
                continue
            args = _args(match.group(3))
            try:
                if kind == "PRODUCT":
                    identifier, a = _string(args[0])
                    name, b = _string(args[1])
                    unsupported |= a or b
                    products[number] = Product(number, identifier, name)
                elif kind.startswith("PRODUCT_DEFINITION_FORMATION"):
                    formations[number] = _ref(args[2])
                elif kind == "PRODUCT_DEFINITION":
                    definitions[number] = _ref(args[2])
                else:
                    identifier, a = _string(args[0])
                    name, b = _string(args[1])
                    unsupported |= a or b
                    links.append((number, identifier, name, _ref(args[3]), _ref(args[4])))
            except IndexError as error:
                raise StepInventoryError(f"Неполная запись {kind}") from error
            if max(len(products), len(formations), len(definitions), len(links)) > MAX_ITEMS:
                raise StepInventoryError("Слишком много элементов сборки для обзора")
        else:
            raise StepInventoryError("Неподдерживаемая структура STEP Part 21")
    if state != "done":
        raise StepInventoryError("Файл STEP неполон или не содержит стандартного завершения")
    def product_for(definition: int) -> Product | None:
        return products.get(formations.get(definitions.get(definition, -1), -1))
    occurrences = tuple(Occurrence(i, ident, name, parent, child, product_for(parent), product_for(child))
                        for i, ident, name, parent, child in links)
    return StepInventory(tuple(schema), tuple(products.values()), occurrences, len(definitions),
                         counts["MANIFOLD_SOLID_BREP"], counts["ITEM_DEFINED_TRANSFORMATION"],
                         sum(o.parent is None or o.child is None for o in occurrences),
                         any(b > 127 for b in data), unsupported)

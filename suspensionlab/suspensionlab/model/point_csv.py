"""Строгий обмен сохранёнными координатами точек без изменения проекта."""
from __future__ import annotations

import csv
import io
import math
import os
import re
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ..export.csv_report import spreadsheet_safe
from .entities import Project

HEADERS = ("axle", "type", "code", "name", "representation", "x_mm", "y_mm", "z_mm",
           "point_locked", "x_locked", "y_locked", "z_locked")
MAX_BYTES = 4 * 1024 * 1024
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


@dataclass(frozen=True, slots=True)
class PointRecord:
    role: str
    code: str
    type_code: str
    name_key: str | None
    representation: str
    xyz: tuple[float, float, float]
    point_locked: bool
    axis_locks: tuple[bool, bool, bool]
    zone_min: tuple[float, float, float] | None
    zone_max: tuple[float, float, float] | None


@dataclass(frozen=True, slots=True)
class PointChange:
    point: PointRecord
    new: tuple[float, float, float]
    outside_zone: bool | None

    @property
    def axes(self) -> tuple[str, ...]:
        return tuple(axis for i, axis in enumerate("xyz") if self.point.xyz[i] != self.new[i])


class PointCSVError(ValueError):
    """Код и строка ошибки без содержимого файла и путей."""

    def __init__(self, code: str, row: int = 0, axis: str = "") -> None:
        super().__init__(code)
        self.code, self.row, self.axis = code, row, axis


def capture_points(project: Project) -> tuple[PointRecord, ...]:
    records = []
    for role in ("front", "rear"):
        axle = project.axle(role)
        for code in axle.point_codes():
            point = axle.hardpoints.get(code)
            if point is None:
                continue
            spec = axle.spec.point(code)
            representation = ("mirrored" if spec and spec.mirrored else
                              "explicit_side" if spec and spec.side != "center" else "single")
            locks = tuple(bool(project.locks.get(f"{role}.point.{code}.{axis}", False)) for axis in "xyz")
            records.append(PointRecord(role, code, axle.type_code, spec.name_key if spec else None,
                                       representation, point.as_tuple(), point.locked,
                                       (locks[0], locks[1], locks[2]), point.zone_min, point.zone_max))
    return tuple(records)


def write_points_csv(path: Path, records: tuple[PointRecord, ...], translate: Callable[[str], str]) -> None:
    """UTF-8 BOM, запятые, мм; текст экранируется, файл заменяется после записи."""
    temporary: str | None = None
    destination = path.resolve()
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=destination.parent,
                                         prefix=".suspensionlab-points-", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            writer = csv.writer(stream)
            writer.writerow(HEADERS)
            for r in records:
                name = translate(r.name_key) if r.name_key else r.code
                writer.writerow([spreadsheet_safe(r.role), spreadsheet_safe(r.type_code), spreadsheet_safe(r.code),
                                 spreadsheet_safe(name), spreadsheet_safe(r.representation), *r.xyz,
                                 r.point_locked, *r.axis_locks])
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)


def read_points_csv(path: Path, records: tuple[PointRecord, ...]) -> tuple[PointChange, ...]:
    """Проверяет полный файл и возвращает отличия без записи в модель.

    Имя и флаги в файле справочные: действуют только текущие фиксации проекта.
    """
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as error:
        raise PointCSVError("read") from error
    if len(raw) > MAX_BYTES:
        raise PointCSVError("size")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise PointCSVError("encoding") from error
    aliases: dict[tuple[str, str], PointRecord] = {}
    for record in records:
        for code in (record.code, spreadsheet_safe(record.code)):
            key = (record.role, code)
            if key in aliases and aliases[key] != record:
                raise PointCSVError("ambiguous")
            aliases[key] = record
    found: dict[tuple[str, str], tuple[float, float, float]] = {}
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        if tuple(next(reader, ())) != HEADERS:
            raise PointCSVError("header")
        for row_number, row in enumerate(reader, 2):
            if len(row) != len(HEADERS):
                raise PointCSVError("columns", row_number)
            key = (row[0], row[2])
            matched = aliases.get(key)
            if matched is None:
                raise PointCSVError("unknown", row_number)
            record = matched
            actual_key = (record.role, record.code)
            if actual_key in found:
                raise PointCSVError("duplicate", row_number)
            if row[1] != record.type_code or row[4] != record.representation:
                raise PointCSVError("mismatch", row_number)
            values: list[float] = []
            for i, axis in enumerate("xyz"):
                value = row[5 + i].strip()
                if len(value) > 100 or not _NUMBER.fullmatch(value):
                    raise PointCSVError("number", row_number, axis.upper())
                number = float(value)
                if not math.isfinite(number) or abs(number) > 1_000_000_000:
                    raise PointCSVError("number", row_number, axis.upper())
                if number != record.xyz[i] and (record.point_locked or record.axis_locks[i]):
                    raise PointCSVError("locked", row_number, axis.upper())
                values.append(number)
            found[actual_key] = (values[0], values[1], values[2])
        if len(found) != len(records):
            raise PointCSVError("missing")
    except csv.Error as error:
        raise PointCSVError("format") from error
    changes = []
    for record in records:
        new = found[(record.role, record.code)]
        if new == record.xyz:
            continue
        outside: bool | None = None
        if record.zone_min is not None and record.zone_max is not None:
            outside = not all(record.zone_min[i] - 1e-9 <= new[i] <= record.zone_max[i] + 1e-9 for i in range(3))
        changes.append(PointChange(record, new, outside))
    return tuple(changes)

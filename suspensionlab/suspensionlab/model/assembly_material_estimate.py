"""Справочные объёмы независимых неподрезанных деталей предварительной сборки."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .kim_format import KimFormatError
from .scheme_arm_assembly import validate_scheme_arm_assembly


@dataclass(frozen=True, slots=True)
class PartVolume:
    identifier: str
    name: str
    volume_mm3: float
    length_mm: float | None = None


def assembly_part_volumes(document: dict[str, Any]) -> tuple[PartVolume, ...]:
    """Аналитические объёмы каждого отдельного тела, не объединение сборки.

    Только поддерживаемые .kima 0.15/0.16: прямые полые трубы между точками,
    полые цилиндры и необязательная пластина с центральным отверстием.
    Пересечения, подрезки, сварка и отсутствующие детали не учитываются.
    """
    validate_scheme_arm_assembly(document)
    result: list[PartVolume] = []
    for index, part in enumerate(document['parts']):
        geometry = part['geometry']
        length = None
        if index < 2:
            points = geometry['source']['coordinates_mm']
            length = math.dist(points[index], points[2])
            radius, wall = float(geometry['radius_mm']), float(geometry['wall_mm'])
            volume = math.pi * wall * (2 * radius - wall) * length
        elif index < 4:
            outer, bore, length_housing = (float(geometry[key]) for key in
                                           ('outer_radius_mm', 'bore_radius_mm', 'length_mm'))
            volume = math.pi * (outer - bore) * (outer + bore) * length_housing
        else:
            width, height, thickness, radius = (float(geometry[key]) for key in
                                                ('width_mm', 'height_mm', 'thickness_mm', 'hole_radius_mm'))
            volume = (width * height - math.pi * radius * radius) * thickness
        if not math.isfinite(volume) or volume <= 0:
            raise KimFormatError('invalid estimated part volume')
        result.append(PartVolume(part['id'], part['name'], volume, length))
    return tuple(result)


def density_kg_m3(text: str) -> float | None:
    """Пустое поле означает отсутствие плотности, не плотность по умолчанию."""
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text.replace(',', '.'))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('invalid density') from error
    if not math.isfinite(value) or not 1e-6 <= value <= 1_000_000:
        raise ValueError('density outside computational bounds')
    return value

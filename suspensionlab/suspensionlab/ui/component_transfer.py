"""Проверка без потери точности перед явным переносом данных в окно."""
from __future__ import annotations

from math import isfinite

from ..i18n import tr


def transferable_damper_lengths(
    compressed: float, extended: float, *, minimum: float, maximum: float, decimals: int,
) -> tuple[float, float]:
    """Возвращает исходные длины только если поля вместят обе без изменения."""
    if not all(isfinite(value) for value in (compressed, extended, minimum, maximum)):
        raise ValueError(tr("analysis.copy_damper.invalid"))
    if minimum < 0 or maximum <= minimum or not 0 <= decimals <= 12:
        raise ValueError(tr("analysis.copy_damper.invalid"))
    if compressed <= 0 or extended <= compressed:
        raise ValueError(tr("analysis.copy_damper.invalid"))
    if compressed < minimum or extended > maximum:
        raise ValueError(tr("analysis.copy_damper.range", minimum=minimum, maximum=maximum))
    if any(float(f"{value:.{decimals}f}") != value for value in (compressed, extended)):
        raise ValueError(tr("analysis.copy_damper.precision", decimals=decimals))
    return compressed, extended

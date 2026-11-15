"""Дискретные экстремумы и состояние запасов, не прогноз между точками."""
import math

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.damper_range import summarize_damper_range
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.templates import load_template
from suspensionlab.ui.damper_range_text import damper_range_text


def test_range_extrema_conflicts_and_missing():
    points = [(-20, 405), (-10, None), (0, 400), (10, 350), (20, 350)]
    result = summarize_damper_range(points, StrokeLimits(350, 402))
    assert result.total == 5 and result.missing == 1 and result.conflicts == 3
    assert result.shortest is not None and (result.shortest.row, result.shortest.travel_mm) == (3, 10)
    assert result.longest is not None and (result.longest.row, result.longest.travel_mm) == (0, -20)
    assert result.compression_clearance_mm == 0 and result.extension_clearance_mm == -3
    text = damper_range_text(result)
    assert "4 из 5; недоступно: 1" in text and "Точек на упоре или за ним: 3" in text
    assert "Обнаружен упор" in text and "между точками" in text


def test_range_without_limits_empty_and_small_signed_clearance():
    no_limits = summarize_damper_range([(0, 400)], None)
    assert no_limits.conflicts is None and no_limits.extension_clearance_mm is None
    assert "Упоры не заданы" in damper_range_text(no_limits)
    empty = summarize_damper_range([(-1, None), (0, None)], StrokeLimits(300, 400))
    assert empty.shortest is None and empty.missing == 2
    assert "Нет доступных точек" in damper_range_text(empty)
    small = summarize_damper_range([(0, 300 - 0.0001)], StrokeLimits(300, 400))
    assert small.conflicts == 1 and small.compression_clearance_mm < 0
    assert "Обнаружен упор" in damper_range_text(small)
    clear = summarize_damper_range([(0, 350)], StrokeLimits(300, 400))
    assert clear.conflicts == 0 and "На доступных точках упоры не обнаружены" in damper_range_text(clear)


@pytest.mark.parametrize("points", [[(math.nan, 400)], [(0, math.inf)], [(0, -1)], [(0, 0)]])
def test_range_rejects_invalid_values(points):
    with pytest.raises(ValueError):
        summarize_damper_range(points)


def test_range_from_actual_sweep_keeps_conflicting_points():
    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [-30, 0, 30], damper_mount="lower_arm",
                            damper_limits=StrokeLimits(200, 325))
    points = [(p.travel_mm, s.damper.length_mm if s is not None and s.damper is not None else None)
              for p, s in zip(result.sweep.points, result.samples, strict=True)]
    summary = summarize_damper_range(points, StrokeLimits(200, 325))
    assert summary.missing == 0 and summary.conflicts == 3
    assert summary.shortest is not None and summary.longest is not None
    assert summary.shortest.length_mm == min(length for _, length in points if length is not None)
    assert summary.longest.length_mm == max(length for _, length in points if length is not None)
    assert summary.extension_clearance_mm is not None and summary.extension_clearance_mm < 0

"""Пояснение состояния не подменяет исходные результаты и пределы."""
from __future__ import annotations

from dataclasses import replace

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.templates import load_template
from suspensionlab.ui.analysis_explanation import explain_corner_sample


def test_user_case_slack_spring_and_damper_overextension():
    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [-16, 0], spring_mount="lower_arm",
                            static_spring_length_mm=320, coil_bind_length_mm=115,
                            damper_mount="lower_arm", damper_limits=StrokeLimits(205, 325))
    text = explain_corner_sample(result.samples[1], project.front.spring)
    assert "свободная длина пружины из проекта: 250.00 мм" in text.lower()
    assert "длина пружины 320.00 мм; сжатие 0.00 мм; сила 0.0 Н" in text
    assert "длина больше свободной" in text
    assert "опор амортизатора в этой точке: 394.27 мм" in text
    assert "до упора отбоя: -69.27 мм" in text and "превышен упор отбоя" in text
    assert "равновесия" in text and "Преднатяг из проекта отдельно не добавляется" in text
    assert "не вычисляется" in text
    assert "402.97 мм" in explain_corner_sample(result.samples[0], project.front.spring)
    assert "нет решения" in explain_corner_sample(None, project.front.spring).lower()


def test_no_parameters_and_all_spring_statuses_and_damper_boundaries():
    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm",
                            static_spring_length_mm=230, damper_mount="lower_arm",
                            damper_limits=StrokeLimits(350, 450))
    sample = result.samples[0]
    assert sample and sample.spring and sample.spring.state and sample.damper and sample.damper.stroke
    disabled = explain_corner_sample(replace(sample, spring=None, damper=None), project.front.spring)
    assert "Пружина не включена" in disabled and "Амортизатор не включён" in disabled
    original = sample.spring.state
    for status, message in (("slack", "длина больше свободной"), ("free_boundary", "Длина равна свободной"),
                            ("loaded", "Пружина сжата"), ("curve_knot", "в узле"),
                            ("outside_curve", "экстраполяция не выполняется"), ("coil_bind", "положение конфликтует")):
        changed = replace(sample.spring, state=replace(original, status=status))
        assert message in explain_corner_sample(replace(sample, spring=changed), project.front.spring)
    for status, message in (("inside", "между заданными пределами"), ("compressed_limit", "Достигнут заданный упор сжатия"),
                            ("extended_limit", "Достигнут заданный упор отбоя"),
                            ("below_compressed", "превышен упор сжатия"), ("above_extended", "превышен упор отбоя")):
        damper = replace(sample.damper, stroke=replace(sample.damper.stroke, status=status))
        assert message in explain_corner_sample(replace(sample, damper=damper), project.front.spring)
    unknown = replace(sample, spring=replace(sample.spring, state=replace(original, coil_clearance_mm=None, force_n=None)),
                      damper=replace(sample.damper, stroke=None))
    text = explain_corner_sample(unknown, project.front.spring)
    assert "смыкание не проверено" in text and "проверка не выполнена" in text and "сила не определена" in text
    bad = replace(sample, spring=replace(sample.spring, state=None, error="bad spring"),
                  damper=replace(sample.damper, error="bad damper"))
    text = explain_corner_sample(bad, project.front.spring)
    assert "bad spring" in text and "bad damper" in text
    assert "‹" not in text


def test_classification_uses_state_not_rounded_dimensions():
    project = load_template("ring")
    sample = analyze_corner(project.front, project.vehicle, [0], damper_mount="lower_arm").samples[0]
    assert sample and sample.damper
    length = sample.damper.length_mm
    result = analyze_corner(project.front, project.vehicle, [0], damper_mount="lower_arm",
                            damper_limits=StrokeLimits(100, length - 0.001)).samples[0]
    assert result
    text = explain_corner_sample(result, project.front.spring)
    assert "превышен упор отбоя" in text and "-0.00 мм" in text
    assert "состояние определяется до округления" in text
    assert pytest.approx(length, abs=0.005) == 394.27

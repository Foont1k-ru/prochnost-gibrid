"""Статические опоры и явно заданные пределы без принятия монтажных решений."""
from __future__ import annotations

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.templates import load_template
from suspensionlab.ui.analysis_explanation import explain_static_sample


def test_user_case_geometry_is_separate_from_installed_spring():
    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm",
                            static_spring_length_mm=320, coil_bind_length_mm=115,
                            damper_mount="lower_arm", damper_limits=StrokeLimits(205, 325))
    text = explain_static_sample(result.samples[0], project.front)
    assert "опор пружины в исходной геометрии: 419.76 мм" in text
    assert "точками: -99.76 мм" in text
    assert "Различие не считается автоматически ошибкой" in text
    assert "сжатый 205.00 мм, разжатый 325.00 мм" in text
    assert "394.27 мм" in text and "-69.27 мм" in text
    assert "не проверка равновесия" in text and "‹" not in text


def test_static_without_checks_and_invalid_nonzero_pose():
    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [0, 1])
    text = explain_static_sample(result.samples[0], project.front)
    assert "Пружина не включена" in text and "Амортизатор не включён" in text
    assert "опор пружины в исходной геометрии" not in text
    assert "нет решения" in explain_static_sample(None, project.front).lower()
    with pytest.raises(ValueError):
        explain_static_sample(result.samples[1], project.front)


def test_unknown_damper_limits_and_spring_coil_bind():
    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm",
                            static_spring_length_mm=230, coil_bind_length_mm=230, damper_mount="lower_arm")
    text = explain_static_sample(result.samples[0], project.front)
    assert "положение конфликтует с пружиной" in text
    assert "Упоры амортизатора не заданы" in text
    assert "Заданные полные длины амортизатора" not in text

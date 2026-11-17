"""Только эскиз по схеме; это не расчёт пригодности рычага."""
import math

import pytest

from suspensionlab.model.arm_concept import make_arm_concept
from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError


def set_points(project, points):
    for code, coordinates in zip(('lca_f_in', 'lca_r_in', 'lbj'), points, strict=True):
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = coordinates


def test_both_concepts_follow_same_current_points_without_mutating_project():
    project = Project.create_default()
    set_points(project, [(0, 0, 0), (100, 0, 0), (0, 100, 0)])
    before = project.to_dict()
    tube = make_arm_concept(project, 'tube', 10, 2, 3)
    sheet = make_arm_concept(project, 'sheet', 10, 2, 3)
    assert tube.points == sheet.points == ((0., 0., 0.), (100., 0., 0.), (0., 100., 0.))
    assert tube.lengths_mm == pytest.approx((100, math.sqrt(20000)))
    assert sheet.triangle_area_mm2 == pytest.approx(5000)
    assert project.to_dict() == before
    project.front.hardpoints['lbj'].y = 200
    updated = make_arm_concept(project, 'tube', 10, 2, 3)
    assert updated.points[2] == (0, 200, 0) and tube.points[2] == (0, 100, 0)
    assert updated.lengths_mm[0] == pytest.approx(200)


def test_collinear_sheet_is_refused_but_tube_concept_can_be_drawn():
    project = Project.create_default()
    set_points(project, [(0, 0, 0), (10, 0, 0), (20, 0, 0)])
    assert make_arm_concept(project, 'tube', 10, 2, 3).triangle_area_mm2 == 0
    with pytest.raises(KimFormatError):
        make_arm_concept(project, 'sheet', 10, 2, 3)


@pytest.mark.parametrize('radius,wall,sheet', [(0, 1, 3), (10, 10, 3), (10, 11, 3),
                                               (10, -1, 3), (10, 2, float('nan')),
                                               (10, True, 3), (float('inf'), 2, 3)])
def test_invalid_parameters_never_produce_a_concept(radius, wall, sheet):
    with pytest.raises(KimFormatError):
        make_arm_concept(Project.create_default(), 'tube', radius, wall, sheet)


def test_incompatible_or_missing_source_and_bad_style_rejected():
    project = Project.create_default()
    project.front.type_code = 'multilink_front'
    with pytest.raises(KimFormatError):
        make_arm_concept(project, 'tube', 10, 2, 3)
    project = Project.create_default()
    del project.front.hardpoints['lbj']
    with pytest.raises(KimFormatError):
        make_arm_concept(project, 'tube', 10, 2, 3)
    with pytest.raises(KimFormatError):
        make_arm_concept(Project.create_default(), 'not-a-style', 10, 2, 3)

"""Объёмы в общем виде — экранные символы существующих линий."""
from copy import deepcopy
from math import dist, isfinite

import pytest

from suspensionlab.core.scene3d import Scene3D, Segment3D
from suspensionlab.core.vehicle_schematic_scene import vehicle_schematic_scene
from suspensionlab.core.vehicle_schematic_visual import (
    TUBE_RADIUS_MM,
    TUBE_SIDES,
    make_schematic_visual,
)
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize('end', [(100., 0., 0.), (0., 0., 100.), (1., 2., 3.)])
def test_symbol_cylinder_ends_follow_given_segment(end):
    start = (0., 0., 0.)
    scene = Scene3D(0., (Segment3D(start, end, 'arm'),))
    visual = make_schematic_visual(scene)
    assert len(visual.faces) == 4 * TUBE_SIDES
    assert {joint.center for joint in visual.joints} == {start, end}
    # First face uses two ring vertices at start and one at end, perpendicular
    # to the given axis even when it is parallel to a world axis.
    a, b, c = visual.faces[0].vertices
    assert dist(a, start) == pytest.approx(TUBE_RADIUS_MM)
    assert dist(b, start) == pytest.approx(TUBE_RADIUS_MM)
    assert dist(c, end) == pytest.approx(TUBE_RADIUS_MM)
    assert sum((a[i] - start[i]) * (end[i] - start[i]) for i in range(3)) == pytest.approx(0, abs=1e-10)
    assert all(isfinite(coordinate) for face in visual.faces for point in face.vertices for coordinate in point)


def test_no_extra_members_and_deduplicated_joints():
    a, b, c = (0., 0., 0.), (100., 0., 0.), (100., 100., 0.)
    scene = Scene3D(0., (Segment3D(a, b, 'arm'), Segment3D(c, b, 'arm'),
                          Segment3D(a, c, 'wheel'), Segment3D(a, a, 'arm')))
    visual = make_schematic_visual(scene)
    assert len(visual.faces) == 2 * 4 * TUBE_SIDES
    assert {joint.center for joint in visual.joints} == {a, b, c}
    assert scene.segments[-1].start == scene.segments[-1].end


def test_template_and_geometry_remain_unchanged():
    project = load_template('live_axle')
    before = deepcopy(project.to_dict())
    scene = vehicle_schematic_scene(project).scene
    visual = make_schematic_visual(scene)
    expected = {p for seg in scene.segments if seg.kind in ('arm', 'steering') for p in (seg.start, seg.end)}
    assert {joint.center for joint in visual.joints} == expected
    assert project.to_dict() == before


def test_invalid_geometry_rejected():
    scene = Scene3D(0., (Segment3D((0., 0., 0.), (float('nan'), 1., 2.), 'arm'),))
    with pytest.raises(ValueError):
        make_schematic_visual(scene)

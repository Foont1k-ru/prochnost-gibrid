"""Выбор по 2D-проекции: все совпадения, а не предполагаемая 3D-видимость."""
import math

import pytest

from suspensionlab.core.scene3d import Segment3D
from suspensionlab.core.vehicle_schematic_pick import projected_link_hits
from suspensionlab.core.vehicle_schematic_scene import SelectableLink, vehicle_schematic_scene
from suspensionlab.model.templates import load_template


def link(role, code, a, b):
    return SelectableLink(role, code, Segment3D(a, b, 'arm'))


def hits(links, click, **overrides):
    args = {'center': (0., 0., 0.), 'yaw': 0., 'elevation': 0., 'scale': 1., 'origin': (0., 0.),
            'click': click, 'tolerance_px': 6.}
    args.update(overrides)
    return projected_link_hits(tuple(links), **args)


def test_ambiguous_projection_returns_all_distinct_links_not_assumed_visible():
    links = [link('front', 'a', (0., 0., 0.), (100., 0., 0.)),
             link('front', 'a', (0., 40., 0.), (100., 40., 0.)),
             link('rear', 'b', (50., 200., -30.), (50., 200., 30.))]
    found = hits(links, (50., 0.))
    assert {(hit.role, hit.code) for hit in found} == {('front', 'a'), ('rear', 'b')}
    assert len(found) == 2
    assert hits(links, (500., 500.)) == ()


def test_endpoints_collapsed_projection_pan_zoom_and_tolerance():
    target = link('front', 'a', (0., 0., 0.), (10., 0., 0.))
    assert hits([target], (26., 10.), origin=(5., 10.), scale=2.)[0].code == 'a'
    assert hits([target], (32., 10.), origin=(5., 10.), scale=2.) == ()
    collapsed = link('rear', 'b', (0., 1., 0.), (0., 3., 0.))
    assert hits([collapsed], (0., 0.))[0].code == 'b'


def test_template_targets_are_actual_scene_segments_and_track_axles_and_sides():
    project = load_template('live_axle')
    result = vehicle_schematic_scene(project)
    assert all(target.segment in result.scene.segments for target in result.links)
    front = [target for target in result.links if target.role == 'front' and target.code == 'lower_arm']
    assert len(front) == 4
    assert front[0].segment.start[1] == -front[2].segment.start[1]
    rear = [target for target in result.links if target.role == 'rear' and target.code == 'lower_trailing_right']
    assert len(rear) == 1
    point = project.rear.hardpoints['ll_in_r']
    assert rear[0].segment.start == (point.x - project.vehicle.wheelbase_mm, point.y, point.z)
    del project.rear.hardpoints['ll_in_r']
    incomplete = vehicle_schematic_scene(project)
    assert not any(t.code == 'lower_trailing_right' for t in incomplete.links)


@pytest.mark.parametrize('field,value', [('yaw', math.nan), ('scale', 0.), ('tolerance_px', -1.)])
def test_invalid_projection_fails_closed(field, value):
    with pytest.raises(ValueError):
        hits([], (0., 0.), **{field: value})

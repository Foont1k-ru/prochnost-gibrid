"""Проверка, что переданная заготовка строится реальным Open CASCADE."""
from math import dist, pi

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)

from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_part  # noqa: E402
from suspensionlab.model.cad_handoff import ClearanceSettings, prepare_cad_handoff  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import fixed_arm_tube_document  # noqa: E402
from suspensionlab.model.templates import load_template  # noqa: E402


def test_handoff_produces_two_valid_hollow_solids_on_frozen_anchors():
    project = load_template('ring')
    before = project.to_dict()
    settings = ClearanceSettings((('lower_arm', 10.), ('tierod', 5.)), 0., None, True, 5., .5)
    handoff = prepare_cad_handoff(project, -20, 20, 10, settings, 2.)
    document = fixed_arm_tube_document(handoff.snapshot, project, handoff.radius_mm, handoff.wall_mm)
    assert len(document['parts']) == 2 and project.to_dict() == before
    points = document['parts'][0]['geometry']['source']['coordinates_mm']
    for i, part in enumerate(document['parts']):
        shape = build_part(part)
        assert BRepCheck_Analyzer(shape).IsValid()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        assert props.Mass() == pytest.approx(pi * (10**2 - 8**2) * dist(points[i], points[2]), rel=1e-7)

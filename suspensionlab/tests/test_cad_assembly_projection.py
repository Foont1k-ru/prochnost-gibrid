"""Проверки протокола и CAD-геометрии без производственных допусков."""
from copy import deepcopy

import pytest

from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjectionJob, parse_projection
from suspensionlab.core.cad_transport import CadPreviewError
from suspensionlab.model.entities import Project
from suspensionlab.model.scheme_arm_assembly import make_plate, make_scheme_arm_assembly, set_assembly_plate


def make_document():
    return make_scheme_arm_assembly(Project.create_default(), 12, 2,
                                    {'axis': 'x', 'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 24})


def test_untrusted_projection_validation_and_cancellation():
    views = {plane: [[0, 0, 1, 1]] for plane in ('XY', 'XZ', 'YZ')}
    value = {'views': views, 'bounds_mm': [0, 0, 0, 1, 1, 1]}
    parsed = parse_projection(value)
    assert len(parsed.views) == 3 and parsed.bounds_mm == (0, 0, 0, 1, 1, 1)
    for bad in ({}, {**value, 'views': {**views, 'XY': []}},
                {**value, 'views': {**views, 'XY': [[0, 0, 1, float('nan')]]}},
                {**value, 'views': {**views, 'XY': [[0, 0, 1, True]]}},
                {**value, 'views': {**views, 'XY': [[0, 0, 1, 10**1000]]}},
                {**value, 'views': {**views, 'XY': [[0, 0, 1, 2, 3]]}},
                {**value, 'views': {**views, 'ZZ': []}},
                {**value, 'bounds_mm': [0, 0, 0, 1, 1]},
                {**value, 'bounds_mm': [0, 0, 0, 1, 1, float('nan')]},
                {**value, 'bounds_mm': [0, 0, 0, 1, 1, True]},
                {**value, 'bounds_mm': [0, 0, 0, 1, 1, 10**1000]},
                {**value, 'bounds_mm': [0, 0, 0, 1, 1, 0]},
                {**value, 'bounds_mm': [0, 0, 0, 1, 1, 0.5]},
                {**value, 'unexpected': 1}):
        with pytest.raises(CadPreviewError):
            parse_projection(bad)
    job = CadAssemblyProjectionJob()
    job.cancel()
    with pytest.raises(CadPreviewError, match='cancelled'):
        job.run(make_document())


def test_hlr_projection_orientation_visibility_and_curves():
    pytest.importorskip('OCP')
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    from suspensionlab.core.cad_assembly_projection import bounds_for_shape, project_shape

    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, 2), 10, 10, 2).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(-2, -2, -2), 4, 4, 2).Shape())
    views = project_shape(compound)
    # CAD bounds include hidden bodies, not just the visible outlines.
    assert bounds_for_shape(compound) == pytest.approx([-5, -5, -2, 5, 5, 4])
    # Looking along -Z, the larger front box completely hides the smaller one.
    assert len(views['XY']) == 4
    assert all(max(abs(x) for x in line) == pytest.approx(5) for line in views['XY'])
    assert any(min(line[1], line[3]) == pytest.approx(-2) for line in views['XZ'])
    assert any(min(line[1], line[3]) == pytest.approx(-2) for line in views['YZ'])
    shifted = project_shape(BRepPrimAPI_MakeBox(gp_Pnt(4, -3, 11), 2, 5, 7).Shape())
    for plane, expected in (('XY', (4, 6, -3, 2)), ('XZ', (4, 6, 11, 18)),
                            ('YZ', (-3, 2, 11, 18))):
        lines = shifted[plane]
        xs = [x for a, _, b, _ in lines for x in (a, b)]
        ys = [y for _, a, _, b in lines for y in (a, b)]
        assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx(expected)
    shape = BRepPrimAPI_MakeCylinder(3, 7).Shape()
    assert bounds_for_shape(shape) == pytest.approx([-3, -3, 0, 3, 3, 7], abs=1e-6)
    cylinder = project_shape(shape)
    assert len(cylinder['XY']) > 4  # circle approximated by segments
    assert any(abs(a + 3) < 1e-5 and abs(c + 3) < 1e-5 and abs(b-d) == pytest.approx(7)
               for a, b, c, d in cylinder['XZ'])


@pytest.mark.parametrize('plate', [False, True])
def test_isolated_job_builds_real_assembly_and_does_not_mutate_it(plate):
    pytest.importorskip('OCP')
    doc = make_document()
    if plate:
        doc = set_assembly_plate(doc, make_plate(40, 20, 3, 5), {'normal': 'y', 'offset_mm': [3, 4, 5]})
    original = deepcopy(doc)
    result = CadAssemblyProjectionJob().run(doc, timeout=45)
    assert len(result.views) == 3 and all(len(lines) > 4 for lines in result.views)
    assert all(result.bounds_mm[i] < result.bounds_mm[i + 3] for i in range(3))
    assert doc == original


def test_worker_timeout_kills_and_reaps_process(monkeypatch):
    import subprocess

    from suspensionlab.core import cad_assembly_projection_job

    class Process:
        killed = False
        waits = 0
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired('worker', timeout)
            return -1
        def kill(self):
            self.killed = True
        def poll(self):
            return None
    process = Process()
    monkeypatch.setattr(cad_assembly_projection_job.subprocess, 'Popen', lambda *args, **kwargs: process)
    with pytest.raises(CadPreviewError, match='timeout'):
        CadAssemblyProjectionJob().run(make_document(), timeout=0.01)
    assert process.killed and process.waits == 2


def test_invalid_or_crashed_worker_output_is_not_displayed(monkeypatch):
    from pathlib import Path

    from suspensionlab.core import cad_assembly_projection_job

    class Process:
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
    def start(command, **kwargs):
        report, output = Path(command[-1]), Path(command[-2])
        report.write_text('{"status":"ok"}', encoding='utf-8')
        output.write_text('{"XY":[],"XZ":[],"YZ":[]}', encoding='utf-8')
        return Process()
    monkeypatch.setattr(cad_assembly_projection_job.subprocess, 'Popen', start)
    with pytest.raises(CadPreviewError, match='output'):
        CadAssemblyProjectionJob().run(make_document())


def test_cad_bounds_follow_plate_placement_in_isolated_worker():
    pytest.importorskip('OCP')
    doc = make_document()
    first = CadAssemblyProjectionJob().run(doc)
    plate = set_assembly_plate(doc, make_plate(40, 20, 3, 5),
                               {'normal': 'z', 'offset_mm': [2000, 0, 0]})
    point_x = plate['parts'][0]['geometry']['source']['coordinates_mm'][2][0]
    second = CadAssemblyProjectionJob().run(plate)
    assert second.bounds_mm[3] == pytest.approx(point_x + 2000 + 20, abs=1e-5)
    assert second.bounds_mm[3] > first.bounds_mm[3] + 1000
    assert second.bounds_mm[0] == pytest.approx(first.bounds_mm[0], abs=1e-5)

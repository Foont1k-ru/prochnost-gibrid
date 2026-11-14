"""CAD CI: ограниченная и явно условная реконструкция поверхности вращения."""
from math import pi

import pytest

pytest.importorskip("OCP", reason="Опциональное CAD-ядро", exc_type=ImportError)
from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRep import BRep_Builder, BRep_Tool  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire  # noqa: E402
from OCP.GC import GC_MakeSegment  # noqa: E402
from OCP.Geom import Geom_SurfaceOfRevolution  # noqa: E402
from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec  # noqa: E402
from OCP.TopLoc import TopLoc_Location  # noqa: E402
from OCP.TopoDS import TopoDS, TopoDS_Face  # noqa: E402

from suspensionlab.core.cad_recovery import recover_revolution_face  # noqa: E402


def incomplete_cap(radius=2., circle_radius=None, apex_offset=0., second_wire=False):
    axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0))
    profile = GC_MakeSegment(gp_Pnt(apex_offset, 5, 0), gp_Pnt(radius, 0, 0)).Value()
    surface = Geom_SurfaceOfRevolution(profile, axis)
    circle = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), circle_radius or radius)
    wire = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire()
    face = TopoDS_Face()
    builder = BRep_Builder()
    builder.MakeFace(face, surface, 1e-7)
    builder.Add(face, wire)
    if second_wire:
        builder.Add(face, BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire())
    return face


def test_recovers_bounded_cap_at_original_and_transformed_location():
    for transformed in (False, True):
        face = incomplete_cap()
        if transformed:
            placement = gp_Trsf()
            placement.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), pi / 2)
            placement.SetTranslationPart(gp_Vec(10, 20, 30))
            face = TopoDS.Face(face.Moved(TopLoc_Location(placement)))
        restored = recover_revolution_face(face, 10.)
        assert restored is not None
        triangulation = BRep_Tool.Triangulation_s(restored, TopLoc_Location())
        assert triangulation is not None and triangulation.NbTriangles() > 0
        bounds = Bnd_Box()
        BRepBndLib.Add_s(restored, bounds, False)
        low, high = bounds.CornerMin(), bounds.CornerMax()
        if transformed:
            assert (low.X(), high.X(), low.Y(), high.Y(), low.Z(), high.Z()) == pytest.approx(
                (5, 10, 18, 22, 28, 32), abs=1e-5)
        else:
            assert (low.X(), high.X(), low.Y(), high.Y(), low.Z(), high.Z()) == pytest.approx(
                (-2, 2, 0, 5, -2, 2), abs=1e-5)


@pytest.mark.parametrize("parameters", [
    {"circle_radius": 3.},  # контур не соответствует концу профиля
    {"apex_offset": 0.5},  # профиль не достигает оси
    {"second_wire": True},  # возможны отверстия: реконструкция опасна
])
def test_ambiguous_face_is_not_recovered(parameters):
    assert recover_revolution_face(incomplete_cap(**parameters), 10.) is None


def test_worker_counts_and_draws_recovered_face(tmp_path, monkeypatch):
    from suspensionlab.core import cad_worker
    from tests.test_step_cad_assembly import write_cad_assembly

    path = tmp_path / "synthetic.step"
    write_cad_assembly(path)
    recovered_face = recover_revolution_face(incomplete_cap(), 10.)
    assert recovered_face is not None
    original = cad_worker._face_triangulation
    calls = 0

    def miss_first(face, location):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original(face, location)

    monkeypatch.setattr(cad_worker, "_face_triangulation", miss_first)
    monkeypatch.setattr(cad_worker, "_retry_face_triangulation", lambda face, location: None)
    monkeypatch.setattr(cad_worker, "recover_revolution_face", lambda face, deviation: recovered_face)
    triangles, faces, skipped, recovered, names, groups = cad_worker.create_mesh(path, 2.)
    assert (faces, skipped, recovered) == (12, 0, 1)
    assert len(triangles) > 22
    # The artificial cap is at the origin, while the STEP assembly is elsewhere.
    assert triangles.min(axis=(0, 1)) == pytest.approx((-2., 0., -2.), abs=1e-5)

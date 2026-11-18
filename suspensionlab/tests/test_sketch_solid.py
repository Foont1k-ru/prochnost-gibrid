"""CAD-тело из эскиза: аналитическая геометрия, STEP и изоляция процесса."""

import math

import pytest

from suspensionlab.core.sketch_solid_job import SketchSolidError, SketchSolidJob
from suspensionlab.core.sketch_solid_worker import ordered_contour
from suspensionlab.model.sketch_draft import make_entity, rectangle_entities
from suspensionlab.model.sketch_io import SketchDocument


def doc(entities, plane="XY", offset=0):
    return SketchDocument(plane, offset, tuple(entities))


def test_ordered_contour_reverses_unordered_segments_and_rejects_open_or_holes():
    lines = rectangle_entities((0, 0), (10, 20))
    reverse = lambda e: make_entity("line", e.end, e.start)  # noqa: E731
    result = ordered_contour((reverse(lines[2]), lines[0], reverse(lines[3]), lines[1]))
    assert len(result) == 4
    with pytest.raises(ValueError):
        ordered_contour((lines[0],))
    circles = (make_entity("circle", (0, 0), (10, 0)), make_entity("circle", (0, 0), (5, 0)))
    with pytest.raises(ValueError):
        ordered_contour(circles)


def test_missing_suffix_pre_cancel_and_no_overwrite(tmp_path):
    shape = doc(rectangle_entities((0, 0), (10, 20)))
    job = SketchSolidJob()
    with pytest.raises(SketchSolidError, match="расширение"):
        job.run(shape, 2, tmp_path / "bad.txt")
    job.cancel()
    with pytest.raises(SketchSolidError, match="отменено"):
        job.run(shape, 2, tmp_path / "cancel.step")
    assert not (tmp_path / "cancel.step").exists()


@pytest.fixture
def cad():
    pytest.importorskip("OCP", reason="CAD-ядро доступно только в CAD-сборке", exc_type=ImportError)
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    def read(path):
        # OCCT's narrow filename API is unreliable with Unicode on Windows.
        ascii_copy = path.parent / "readback-ascii.step"
        ascii_copy.write_bytes(path.read_bytes())
        reader = STEPControl_Reader()
        assert reader.ReadFile(str(ascii_copy)) == IFSelect_ReturnStatus.IFSelect_RetDone
        assert reader.TransferRoots() > 0
        shape = reader.OneShape()
        assert BRepCheck_Analyzer(shape).IsValid()
        solids = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
        assert solids.More()
        solids.Next()
        assert not solids.More()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, box, False, False)
        lower, upper = box.CornerMin(), box.CornerMax()
        return shape, props.Mass(), (lower.X(), lower.Y(), lower.Z(), upper.X(), upper.Y(), upper.Z())
    return read


@pytest.mark.parametrize("plane,bounds", [("XY", (0, 0, 12, 100, 50, 17)),
                                          ("XZ", (0, 12, 0, 100, 17, 50)),
                                          ("YZ", (12, 0, 0, 17, 100, 50))])
def test_export_reimport_real_solid_volume_bounds_and_atomic_no_overwrite(tmp_path, cad, plane, bounds):
    shape = doc(rectangle_entities((0, 0), (100, 50)), plane, 12)
    target = tmp_path / "тело.step"
    assert SketchSolidJob().run(shape, 5, target) == target
    raw = target.read_bytes()
    assert b"SI_UNIT(.MILLI.,.METRE.)" in raw
    _, volume, box = cad(target)
    assert volume == pytest.approx(25_000, rel=1e-9)
    assert box == pytest.approx(bounds, abs=1e-6)
    with pytest.raises(SketchSolidError, match="существует"):
        SketchSolidJob().run(shape, 5, target)
    assert target.read_bytes() == raw
    assert not list(tmp_path.glob(".sketch-solid-*"))


@pytest.mark.parametrize("plane", ["XY", "XZ", "YZ"])
def test_export_circle_retains_analytic_cylindrical_surface(tmp_path, cad, plane):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    circle = make_entity("circle", (2, 3), (12, 3))
    target = tmp_path / "круг.stp"
    SketchSolidJob().run(doc((circle,), plane, -7), 4, target)
    shape, volume, _ = cad(target)
    assert volume == pytest.approx(math.pi * 100 * 4, rel=1e-9)
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    surface_types = []
    while explorer.More():
        surface_types.append(BRepAdaptor_Surface(TopoDS.Face(explorer.Current())).GetType())
        explorer.Next()
    assert GeomAbs_SurfaceType.GeomAbs_Cylinder in surface_types


def test_long_analytic_arc_and_concave_contours(tmp_path, cad):
    arc = make_entity("arc", (0, 0), (10, 0), 270)
    chord = make_entity("line", (0, -10), (10, 0))
    target = tmp_path / "дуга.step"
    SketchSolidJob().run(doc((arc, chord)), 3, target)
    _, volume, _ = cad(target)
    assert volume == pytest.approx((75 * math.pi + 50) * 3, rel=1e-9)
    points = [(0, 0), (10, 0), (10, 3), (3, 3), (3, 10), (0, 10)]
    lines = [make_entity("line", points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    target2 = tmp_path / "concave.step"
    SketchSolidJob().run(doc(lines), 5, target2)
    _, volume, _ = cad(target2)
    assert volume == pytest.approx(255)


def test_invalid_contour_or_depth_never_publishes_file(tmp_path, cad):
    line = make_entity("line", (0, 0), (10, 0))
    for i, (entities, depth) in enumerate(((rectangle_entities((0, 0), (10, 10)), 0),
                                            ((line,), 3), (rectangle_entities((0, 0), (10, 10)), float("nan")))):
        target = tmp_path / f"bad{i}.step"
        with pytest.raises(SketchSolidError):
            SketchSolidJob().run(doc(entities), depth, target)
        assert not target.exists()
        assert not list(tmp_path.glob(".sketch-solid-*"))


def test_cancel_running_worker_never_publishes(tmp_path, monkeypatch):
    import subprocess
    import sys
    import threading

    from suspensionlab.core import sketch_solid_job

    original_popen = subprocess.Popen
    started = threading.Event()
    def slow_worker(_command, **kwargs):
        process = original_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        started.set()
        return process
    monkeypatch.setattr(sketch_solid_job.subprocess, "Popen", slow_worker)
    target = tmp_path / "cancel.step"
    job = SketchSolidJob()
    failures = []
    def run():
        try:
            job.run(doc(rectangle_entities((0, 0), (10, 10))), 5, target)
        except SketchSolidError as exc:
            failures.append(str(exc))
    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(5)
    job.cancel()
    worker.join(5)
    assert not worker.is_alive() and failures == ["Построение отменено"]
    assert not target.exists() and not list(tmp_path.glob(".sketch-solid-*"))


def test_clockwise_unordered_and_fillet_contour_build_real_solid(cad, tmp_path):
    from suspensionlab.model.sketch_construction import fillet_lines
    from suspensionlab.model.sketch_draft import SketchDraft

    rect = rectangle_entities((0, 0), (100, 50))
    reverse = lambda e: make_entity("line", e.end, e.start)  # noqa: E731
    unordered = (reverse(rect[2]), rect[0], reverse(rect[3]), rect[1])
    target = tmp_path / "reverse.step"
    SketchSolidJob().run(doc(unordered), 5, target)
    assert cad(target)[1] == pytest.approx(25_000)
    draft = SketchDraft(rect)
    draft.apply_fillet(0, 1, fillet_lines(draft.entities[0], draft.entities[1], 10))
    target2 = tmp_path / "fillet.step"
    SketchSolidJob().run(doc(draft.entities), 5, target2)
    assert cad(target2)[1] == pytest.approx((5000 - 100 + 25 * math.pi) * 5, rel=1e-9)


def test_invalid_worker_output_is_not_published(tmp_path, monkeypatch):
    import json

    from suspensionlab.core import sketch_solid_job

    class FakeProcess:
        def __init__(self, _command, *, cwd, **_kwargs):
            (cwd / "report.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
            (cwd / "result.step").write_bytes(b"ISO-10303-21;\nincomplete")
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
    monkeypatch.setattr(sketch_solid_job.subprocess, "Popen", FakeProcess)
    target = tmp_path / "result.step"
    with pytest.raises(SketchSolidError, match="неполный"):
        SketchSolidJob().run(doc(rectangle_entities((0, 0), (10, 10))), 5, target)
    assert not target.exists() and not list(tmp_path.glob(".sketch-solid-*"))


def test_destination_race_does_not_overwrite(tmp_path, monkeypatch):
    import json
    import os

    from suspensionlab.core import sketch_solid_job

    class FakeProcess:
        def __init__(self, _command, *, cwd, **_kwargs):
            (cwd / "report.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
            (cwd / "result.step").write_bytes(b"ISO-10303-21;\nEND-ISO-10303-21;\n")
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
    monkeypatch.setattr(sketch_solid_job.subprocess, "Popen", FakeProcess)
    original_link = os.link
    target = tmp_path / "race.step"
    def racing_link(src, dest):
        if str(dest) == str(target):
            target.write_bytes(b"other user data")
        return original_link(src, dest)
    monkeypatch.setattr(sketch_solid_job.os, "link", racing_link)
    with pytest.raises(SketchSolidError, match="существует"):
        SketchSolidJob().run(doc(rectangle_entities((0, 0), (10, 10))), 5, target)
    assert target.read_bytes() == b"other user data"
    assert not list(tmp_path.glob(".sketch-solid-*"))


@pytest.mark.parametrize("plane", ["XY", "XZ", "YZ"])
@pytest.mark.parametrize("reversed_order", [False, True])
def test_plate_two_analytic_holes_step_roundtrip_and_material(tmp_path, cad, plane, reversed_order):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_State
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    outer = list(rectangle_entities((0, 0), (100, 60)))
    circle = make_entity("circle", (25, 30), (35, 30))
    hole = list(rectangle_entities((60, 20), (80, 40)))
    if reversed_order:
        outer = [make_entity("line", e.end, e.start) for e in reversed(outer)]
        hole = [make_entity("line", e.end, e.start) for e in reversed(hole)]
    entities = [circle, *hole, *outer] if reversed_order else [*outer, circle, *hole]
    target = tmp_path / "holes.step"
    SketchSolidJob().run(doc(entities, plane, 12), 5, target)
    shape, volume, _ = cad(target)
    assert volume == pytest.approx((6000 - math.pi * 100 - 400) * 5, rel=1e-9)
    xyz = lambda x, y: ((x, y, 14) if plane == "XY" else (x, 14, y) if plane == "XZ" else (14, x, y))  # noqa: E731
    for pt, state in [((25, 30), TopAbs_State.TopAbs_OUT), ((70, 30), TopAbs_State.TopAbs_OUT),
                      ((50, 30), TopAbs_State.TopAbs_IN)]:
        assert BRepClass3d_SolidClassifier(shape, gp_Pnt(*xyz(*pt)), 1e-7).State() == state
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    types = []
    while explorer.More():
        types.append(BRepAdaptor_Surface(TopoDS.Face(explorer.Current())).GetType())
        explorer.Next()
    assert GeomAbs_SurfaceType.GeomAbs_Cylinder in types


def test_ring_and_arc_hole_roundtrip(tmp_path, cad):
    outer = make_entity("circle", (0, 0), (50, 0))
    inner = make_entity("circle", (0, 0), (10, 0))
    target = tmp_path / "ring.step"
    SketchSolidJob().run(doc((inner, outer)), 3, target)
    assert cad(target)[1] == pytest.approx(math.pi * (2500 - 100) * 3, rel=1e-9)
    arc = make_entity("arc", (0, 0), (10, 0), 270)
    chord = make_entity("line", (0, -10), (10, 0))
    target2 = tmp_path / "arc-hole.step"
    SketchSolidJob().run(doc((outer, arc, chord)), 3, target2)
    assert cad(target2)[1] == pytest.approx((2500 * math.pi - (75 * math.pi + 50)) * 3, rel=1e-9)


@pytest.mark.parametrize("case", ["separate", "nested", "touch", "cross", "outside-concave"])
def test_invalid_holes_never_publish(tmp_path, cad, case):
    outer = rectangle_entities((0, 0), (100, 100))
    circle = lambda p, r: make_entity("circle", p, (p[0] + r, p[1]))  # noqa: E731
    if case == "separate":
        entities = (*outer, circle((150, 50), 10))
    elif case == "nested":
        entities = (*outer, circle((50, 50), 20), circle((50, 50), 5))
    elif case == "touch":
        entities = (*outer, circle((10, 50), 10))
    elif case == "cross":
        entities = (*outer, circle((5, 50), 10))
    else:
        points = [(0, 0), (100, 0), (100, 30), (30, 30), (30, 100), (0, 100)]
        lines = [make_entity("line", points[i], points[(i+1) % len(points)]) for i in range(len(points))]
        entities = (*lines, circle((70, 70), 5))
    target = tmp_path / "bad.step"
    with pytest.raises(SketchSolidError):
        SketchSolidJob().run(doc(entities), 5, target)
    assert not target.exists() and not list(tmp_path.glob(".sketch-solid-*"))


def test_mesh_reader_for_hole_step(tmp_path, cad):
    from suspensionlab.core.cad_transport import CadJob

    circle = make_entity("circle", (25, 25), (35, 25))
    target = tmp_path / "деталь с отверстием.step"
    SketchSolidJob().run(doc((*rectangle_entities((0, 0), (100, 50)), circle), "XZ", 12), 5, target)
    mesh = CadJob().run(target, 0.2)
    assert mesh.face_count == 7 and mesh.skipped_faces == 0
    assert len(mesh.triangles) > 12
    assert cad(target)[1] == pytest.approx((5000 - 100 * math.pi) * 5)


def test_nested_and_disjoint_report_clear_reason(tmp_path, cad):
    outer = make_entity("circle", (0, 0), (50, 0))
    inner = make_entity("circle", (0, 0), (20, 0))
    island = make_entity("circle", (0, 0), (5, 0))
    with pytest.raises(SketchSolidError, match="вложенные острова"):
        SketchSolidJob().run(doc((outer, inner, island)), 2, tmp_path / "invalid.step")


@pytest.mark.parametrize("plane,axis", [("XY", 2), ("XZ", 1), ("YZ", 0)])
@pytest.mark.parametrize("direction,expected", [("positive", (12, 17)), ("negative", (7, 12)),
                                                 ("symmetric", (9.5, 14.5))])
@pytest.mark.parametrize("holes", [False, True])
def test_extrude_direction_step_roundtrip(tmp_path, cad, plane, axis, direction, expected, holes):
    entities = list(rectangle_entities((0, 0), (100, 50)))
    if holes:
        entities.append(make_entity("circle", (25, 25), (35, 25)))
    target = tmp_path / "direction.step"
    SketchSolidJob().run(doc(entities, plane, 12), 5, target, direction=direction)
    _, volume, box = cad(target)
    assert (box[axis], box[axis + 3]) == pytest.approx(expected, abs=1e-6)
    assert volume == pytest.approx((5000 - (100 * math.pi if holes else 0)) * 5, rel=1e-9)


def test_invalid_direction_is_rejected_without_output(tmp_path):
    target = tmp_path / "bad.step"
    with pytest.raises(SketchSolidError, match="направление"):
        SketchSolidJob().run(doc(rectangle_entities((0, 0), (10, 10))), 5, target, direction="bad")
    assert not target.exists()


@pytest.mark.parametrize("plane,axis", [("XY", 2), ("XZ", 1), ("YZ", 0)])
@pytest.mark.parametrize("direction,start,end", [("positive", 12, 22), ("negative", 2, 12),
                                                  ("symmetric", 7, 17)])
def test_blind_holes_step_volume_and_material_on_all_planes(tmp_path, cad, plane, axis, direction, start, end):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_State
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    circle = make_entity("circle", (25, 25), (35, 25))
    inner = rectangle_entities((60, 15), (80, 35))
    outer = rectangle_entities((0, 0), (100, 50))
    target = tmp_path / "blind.step"
    # Deliberately put the outer contour last to exercise classification.
    SketchSolidJob().run(doc((circle, *inner, *outer), plane, 12), 10, target,
                         direction=direction, hole_depth=4)
    shape, volume, box = cad(target)
    assert (box[axis], box[axis+3]) == pytest.approx((start, end), abs=1e-6)
    assert volume == pytest.approx(5000 * 10 - (100 * math.pi + 400) * 4, rel=1e-9)
    def xyz(u, v, z):
        return (u, v, z) if plane == "XY" else (u, z, v) if plane == "XZ" else (z, u, v)
    opening = end - 1 if direction == "negative" else start + 1
    back = start + 1 if direction == "negative" else end - 1
    for xy in ((25, 25), (70, 25)):
        assert BRepClass3d_SolidClassifier(shape, gp_Pnt(*xyz(*xy, opening)), 1e-7).State() == TopAbs_State.TopAbs_OUT
        assert BRepClass3d_SolidClassifier(shape, gp_Pnt(*xyz(*xy, back)), 1e-7).State() == TopAbs_State.TopAbs_IN
    assert BRepClass3d_SolidClassifier(shape, gp_Pnt(*xyz(50, 25, opening)), 1e-7).State() == TopAbs_State.TopAbs_IN
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    types = []
    while explorer.More():
        types.append(BRepAdaptor_Surface(TopoDS.Face(explorer.Current())).GetType())
        explorer.Next()
    assert GeomAbs_SurfaceType.GeomAbs_Cylinder in types


@pytest.mark.parametrize("hole_depth", [-1, 10, 11, float("nan"), float("inf")])
def test_invalid_blind_depth_never_publishes(tmp_path, hole_depth):
    target = tmp_path / "invalid.step"
    hole = make_entity("circle", (5, 5), (6, 5))
    with pytest.raises(SketchSolidError, match="Глубина"):
        SketchSolidJob().run(doc((*rectangle_entities((0, 0), (10, 10)), hole)), 10, target,
                             hole_depth=hole_depth)
    assert not target.exists()


def test_blind_depth_requires_internal_contour(tmp_path, cad):
    target = tmp_path / "no-holes.step"
    with pytest.raises(SketchSolidError):
        SketchSolidJob().run(doc(rectangle_entities((0, 0), (10, 10))), 10, target, hole_depth=4)
    assert not target.exists()


def test_blind_arc_pocket_and_cad_mesh(tmp_path, cad):
    from suspensionlab.core.cad_transport import CadJob

    outer = make_entity("circle", (0, 0), (50, 0))
    arc = make_entity("arc", (0, 0), (10, 0), 270)
    chord = make_entity("line", (0, -10), (10, 0))
    target = tmp_path / "blind-arc.step"
    SketchSolidJob().run(doc((chord, outer, arc)), 10, target, direction="negative", hole_depth=3)
    assert cad(target)[1] == pytest.approx(math.pi * 2500 * 10 - (75 * math.pi + 50) * 3, rel=1e-9)
    mesh = CadJob().run(target, 0.2)
    assert mesh.skipped_faces == 0 and mesh.face_count >= 5 and len(mesh.triangles) > 12


@pytest.mark.parametrize("plane,axis", [("XY", 2), ("XZ", 1), ("YZ", 0)])
@pytest.mark.parametrize("direction,start,end", [("positive", 12, 22), ("negative", 2, 12),
                                                  ("symmetric", 7, 17)])
@pytest.mark.parametrize("hole_side", ["negative", "positive"])
def test_blind_entry_side_override_is_real_after_step_roundtrip(tmp_path, cad, plane, axis, direction, start, end, hole_side):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_State

    hole = make_entity("circle", (25, 25), (35, 25))
    shape = doc((*rectangle_entities((0, 0), (100, 50)), hole), plane, 12)
    target = tmp_path / "выбранная сторона.step"
    SketchSolidJob().run(shape, 10, target, direction=direction, hole_depth=4, hole_side=hole_side)
    solid, volume, bounds = cad(target)
    assert (bounds[axis], bounds[axis + 3]) == pytest.approx((start, end), abs=1e-6)
    assert volume == pytest.approx(50000 - 400 * math.pi, rel=1e-9)
    def point(u, v, w):
        return gp_Pnt(*((u, v, w) if plane == "XY" else (u, w, v) if plane == "XZ" else (w, u, v)))
    for coordinate, expected in [(start + 1, TopAbs_State.TopAbs_OUT if hole_side == "negative" else TopAbs_State.TopAbs_IN),
                                 (end - 1, TopAbs_State.TopAbs_OUT if hole_side == "positive" else TopAbs_State.TopAbs_IN)]:
        assert BRepClass3d_SolidClassifier(solid, point(25, 25, coordinate), 1e-7).State() == expected
        assert BRepClass3d_SolidClassifier(solid, point(50, 25, coordinate), 1e-7).State() == TopAbs_State.TopAbs_IN


def test_blind_side_auto_and_invalid():
    from suspensionlab.model.sketch_extrude_settings import hole_entry_side

    assert hole_entry_side("positive") == "negative"
    assert hole_entry_side("negative") == "positive"
    assert hole_entry_side("symmetric") == "negative"
    assert hole_entry_side("positive", "positive") == "positive"
    with pytest.raises(ValueError, match="сторона"):
        hole_entry_side("positive", "invalid")
    with pytest.raises(ValueError, match="направление"):
        hole_entry_side("invalid")


def test_invalid_blind_side_does_not_create_step(tmp_path):
    target = tmp_path / "bad.step"
    with pytest.raises(SketchSolidError, match="сторона"):
        SketchSolidJob().run(doc(rectangle_entities((0, 0), (10, 10))), 5, target, hole_side="wrong")
    assert not target.exists()


@pytest.mark.parametrize("side", ["negative", "positive"])
def test_explicit_side_does_not_change_through_holes(tmp_path, cad, side):
    hole = make_entity("circle", (25, 25), (35, 25))
    shape = doc((*rectangle_entities((0, 0), (100, 50)), hole))
    path = tmp_path / "through.step"
    SketchSolidJob().run(shape, 10, path, hole_side=side)
    assert cad(path)[1] == pytest.approx((5000 - 100 * math.pi) * 10)


@pytest.mark.parametrize("plane,axis", [("XY", 2), ("XZ", 1), ("YZ", 0)])
@pytest.mark.parametrize("direction,start,end", [("positive", 12, 22), ("negative", 2, 12),
                                                  ("symmetric", 7, 17)])
def test_individual_holes_through_and_opposite_blind_sides(tmp_path, cad, plane, axis, direction, start, end):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_State

    rect = rectangle_entities((0, 0), (120, 60))
    through = make_entity("circle", (20, 30), (25, 30))
    bottom = make_entity("circle", (50, 30), (58, 30))
    pocket = rectangle_entities((80, 20), (100, 40))
    # Through default, explicit near hole and selected element inside a 4-edge loop.
    entities = (*rect, through, bottom, *pocket)
    overrides = ((5, 3., "negative"), (8, 4., "positive"))
    target = tmp_path / "multiple.step"
    SketchSolidJob().run(doc(entities, plane, 12), 10, target, direction=direction, hole_overrides=overrides)
    solid, volume, bounds = cad(target)
    assert (bounds[axis], bounds[axis + 3]) == pytest.approx((start, end), abs=1e-6)
    assert volume == pytest.approx(120*60*10 - math.pi*25*10 - math.pi*64*3 - 400*4, rel=1e-9)
    def state(x, y, coord):
        p = (x, y, coord) if plane == "XY" else (x, coord, y) if plane == "XZ" else (coord, x, y)
        return BRepClass3d_SolidClassifier(solid, gp_Pnt(*p), 1e-7).State()
    assert state(20, 30, start + 1) == state(20, 30, end - 1) == TopAbs_State.TopAbs_OUT
    assert state(50, 30, start + 1) == TopAbs_State.TopAbs_OUT
    assert state(50, 30, end - 1) == TopAbs_State.TopAbs_IN
    assert state(90, 30, start + 1) == TopAbs_State.TopAbs_IN
    assert state(90, 30, end - 1) == TopAbs_State.TopAbs_OUT
    assert state(70, 30, start + 1) == TopAbs_State.TopAbs_IN


@pytest.mark.parametrize("overrides", [((0, 3., "auto"),), ((4, 3., "auto"), (5, 4., "auto"))])
def test_external_or_repeated_loop_overrides_cannot_publish(tmp_path, cad, overrides):
    outer = rectangle_entities((0, 0), (100, 50))
    hole = rectangle_entities((30, 15), (50, 35))
    path = tmp_path / "invalid.step"
    with pytest.raises(SketchSolidError, match="внутренним контурам"):
        SketchSolidJob().run(doc((*outer, *hole)), 10, path, hole_overrides=overrides)
    assert not path.exists() and not list(tmp_path.glob(".sketch-solid-*"))


@pytest.mark.parametrize("overrides", [((99, 2., "auto"),), ((4, 10., "auto"),), ((4, -1., "auto"),),
                                       ((4, float("nan"), "auto"),), ((4, 2., "bad"),),
                                       ((4, 2., "auto"), (4, 3., "auto"))])
def test_invalid_individual_hole_settings_are_rejected_before_file(tmp_path, overrides):
    circle = make_entity("circle", (20, 20), (25, 20))
    target = tmp_path / "bad.step"
    with pytest.raises(SketchSolidError):
        SketchSolidJob().run(doc((*rectangle_entities((0, 0), (50, 50)), circle)), 10, target,
                             hole_overrides=overrides)
    assert not target.exists()


def test_individual_overrides_can_replace_blind_default_with_through(tmp_path, cad):
    outer = rectangle_entities((0, 0), (100, 50))
    a = make_entity("circle", (25, 25), (30, 25))
    b = make_entity("circle", (75, 25), (80, 25))
    target = tmp_path / "default-blind.step"
    SketchSolidJob().run(doc((*outer, a, b)), 10, target, hole_depth=3, hole_overrides=((4, 0, "auto"),))
    assert cad(target)[1] == pytest.approx(50_000 - math.pi*25*(10+3), rel=1e-9)

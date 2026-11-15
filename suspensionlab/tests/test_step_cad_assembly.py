"""STEP-файл создан Open CASCADE: сверка ограниченного парсера с эталонными позами.

Только CAD CI: искусственный образец, не пользовательская сборка и не подтверждение
всех вариантов STEP. Преобразования применяются только внутри теста.
"""
from math import pi

import numpy as np
import pytest

pytest.importorskip("OCP", reason="Опциональный CAD-эталон устанавливается отдельно", exc_type=ImportError)
from OCP.BinXCAFDrivers import BinXCAFDrivers  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec  # noqa: E402
from OCP.IFSelect import IFSelect_ReturnStatus  # noqa: E402
from OCP.STEPCAFControl import STEPCAFControl_Writer  # noqa: E402
from OCP.STEPControl import STEPControl_StepModelType  # noqa: E402
from OCP.TCollection import TCollection_ExtendedString  # noqa: E402
from OCP.TDocStd import TDocStd_Document  # noqa: E402
from OCP.TopLoc import TopLoc_Location  # noqa: E402
from OCP.XCAFApp import XCAFApp_Application  # noqa: E402
from OCP.XCAFDoc import XCAFDoc_DocumentTool  # noqa: E402

from suspensionlab.core import cad_worker  # noqa: E402
from suspensionlab.core.cad_transport import CadJob  # noqa: E402
from suspensionlab.core.cad_worker import create_mesh  # noqa: E402
from suspensionlab.core.step_candidate import candidate_transforms  # noqa: E402
from suspensionlab.core.step_inventory import read_step_inventory  # noqa: E402


def cad_placement(angle, translation, axis=(0, 0, 1)):
    placement = gp_Trsf()
    placement.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), angle)
    placement.SetTranslationPart(gp_Vec(*translation))
    return placement


def expected_point(placement, point):
    value = gp_Pnt(*point).Transformed(placement)
    return value.X(), value.Y(), value.Z()


def write_cad_assembly(path):
    app = XCAFApp_Application.GetApplication_s()
    BinXCAFDrivers.DefineFormat_s(app)
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    app.InitDocument(document)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    root = tool.NewShape()
    sub = tool.NewShape()
    part = tool.NewShape()
    tool.SetShape(part, BRepPrimAPI_MakeBox(2., 3., 5.).Shape())
    parent = cad_placement(pi / 2, (100, 30, 7))
    first = cad_placement(pi / 4, (11, -6, 4), (1, 0, 0))
    second = cad_placement(-pi / 3, (-4, 17, 8), (0, 1, 0))
    tool.AddComponent(sub, part, TopLoc_Location(first))
    tool.AddComponent(sub, part, TopLoc_Location(second))
    tool.AddComponent(root, sub, TopLoc_Location(parent))
    tool.UpdateAssemblies()
    writer = STEPCAFControl_Writer()
    assert writer.Transfer(document, STEPControl_StepModelType.STEPControl_AsIs)
    assert writer.Write(str(path)) == IFSelect_ReturnStatus.IFSelect_RetDone
    return parent, first, second


def test_generated_step_nested_and_repeated_occurrences_against_cad(tmp_path):
    path = tmp_path / "independent.step"
    parent, first, second = write_cad_assembly(path)
    unicode_path = tmp_path / "испытание сборки.step"
    path.rename(unicode_path)
    path = unicode_path
    create_mesh(path, 2.)  # Synthetic data: expose exceptions directly in CAD CI.
    mesh = CadJob().run(path, 2., timeout=90)
    assert mesh.face_count == 12 and mesh.skipped_faces == 0 and mesh.recovered_faces == 0 and len(mesh.triangles) >= 24
    # Both instances are grouped by the same product definition, without changing positions.
    assert mesh.triangle_parts is not None
    groups = np.unique(mesh.triangle_parts)
    assert len(groups) == 1 and groups[0] != 0
    assert len(mesh.isolated(int(groups[0])).triangles) == len(mesh.triangles)
    assert mesh.triangle_instances is not None
    instances = np.unique(mesh.triangle_instances)
    assert len(instances) == 2 and 0 not in instances
    assert all(mesh.instance_groups[int(i)] == int(groups[0]) for i in instances)
    measured_bounds = []
    for instance in instances:
        isolated = mesh.isolated_instance(int(instance)).triangles.reshape(-1, 3)
        measured_bounds.append((isolated.min(axis=0), isolated.max(axis=0)))
    for placement in (parent.Multiplied(first), parent.Multiplied(second)):
        corners = np.array([expected_point(placement, (x, y, z)) for x in (0., 2.)
                            for y in (0., 3.) for z in (0., 5.)])
        expected = (corners.min(axis=0), corners.max(axis=0))
        assert sum(np.allclose(low, expected[0], atol=1e-6, rtol=0) and
                   np.allclose(high, expected[1], atol=1e-6, rtol=0) for low, high in measured_bounds) == 1
    bounds_points = []
    for placement in (parent.Multiplied(first), parent.Multiplied(second)):
        for x in (0., 2.):
            for y in (0., 3.):
                for z in (0., 5.):
                    bounds_points.append(expected_point(placement, (x, y, z)))
    vertices = mesh.triangles.reshape(-1, 3)
    assert vertices.min(axis=0) == pytest.approx(np.min(bounds_points, axis=0), abs=1e-6)
    assert vertices.max(axis=0) == pytest.approx(np.max(bounds_points, axis=0), abs=1e-6)
    result = read_step_inventory(path)
    assert len(result.occurrences) == 3
    frames = {item.occurrence: item for item in result.placement_frames}
    assert all(frame.issue is None for frame in frames.values())
    assert all(frame.representation_match and frame.representation_match.status == "child_parent"
               for frame in frames.values())
    # Only equal, explicitly declared mm contexts are accepted by this experiment.
    units = {unit.context: unit for unit in result.context_units}
    assert all(unit.status == "known" and unit.mm_per_unit == pytest.approx(1) for unit in units.values())
    for frame in frames.values():
        info = frame.representation_match
        assert info and info.context_1 in units and info.context_2 in units
    parents = {occurrence.parent_definition for occurrence in result.occurrences}
    parent_occurrences = [occurrence for occurrence in result.occurrences if occurrence.child_definition in parents]
    assert len(parent_occurrences) == 1
    parent_occurrence = parent_occurrences[0]
    children = [occurrence for occurrence in result.occurrences
                if occurrence.parent_definition == parent_occurrence.child_definition]
    assert len(children) == 2 and children[0].child_definition == children[1].child_definition
    candidates = {item.occurrence: item for item in candidate_transforms(result)}
    assert all(item.status == "ready" and item.transform is not None for item in candidates.values()), (
        f"candidates={candidates}; occurrences={result.occurrences}; frames={result.placement_frames}; units={result.context_units}"
    )
    parent_candidate = candidates[parent_occurrence.entity].transform
    child_candidates = [candidates[occurrence.entity].transform for occurrence in children]
    assert parent_candidate is not None and all(c is not None for c in child_candidates)
    probe = (2., 3., 5.)
    for point in ((0., 0., 0.), probe, (-3., 7., 1.)):
        assert parent_candidate.apply_point(point) == pytest.approx(expected_point(parent, point), abs=1e-7)
    expected_children = [expected_point(first, probe), expected_point(second, probe)]
    for expected in expected_children:
        assert sum(c.apply_point(probe) == pytest.approx(expected, abs=1e-7) for c in child_candidates) == 1
    for reference in (first, second):
        child = next(c for c in child_candidates if c.apply_point(probe) == pytest.approx(expected_point(reference, probe), abs=1e-7))
        combined_reference = parent.Multiplied(reference)
        for point in ((0., 0., 0.), probe, (-3., 7., 1.)):
            assert parent_candidate.compose(child).apply_point(point) == pytest.approx(expected_point(combined_reference, point), abs=1e-7)


def test_missing_faces_are_counted_not_silently_accepted(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.step"
    write_cad_assembly(path)
    original = cad_worker._face_triangulation
    calls = 0

    def miss_first(face, location):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original(face, location)

    monkeypatch.setattr(cad_worker, "_face_triangulation", miss_first)
    monkeypatch.setattr(cad_worker, "_retry_face_triangulation", lambda face, location: None)
    triangles, faces, skipped, recovered, names, groups, instance_groups, instances = cad_worker.create_mesh(path, 2.)
    assert (faces, skipped, recovered, calls) == (12, 1, 0, 12)
    assert len(triangles) == 22
    monkeypatch.setattr(cad_worker, "_face_triangulation", lambda face, location: None)
    with pytest.raises(cad_worker.CadWorkerError, match="no_faces"):
        cad_worker.create_mesh(path, 2.)


def test_retry_can_recover_missing_face(tmp_path, monkeypatch):
    path = tmp_path / "retry.step"
    write_cad_assembly(path)
    original = cad_worker._face_triangulation
    calls = 0

    def miss_first(face, location):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original(face, location)

    monkeypatch.setattr(cad_worker, "_face_triangulation", miss_first)
    triangles, faces, skipped, recovered, names, groups, instance_groups, instances = cad_worker.create_mesh(path, 2.)
    assert (faces, skipped, recovered) == (12, 0, 0)
    assert len(triangles) >= 24 and calls == 13


def test_grouping_limits_fall_back_to_unidentified_without_losing_geometry(tmp_path, monkeypatch):
    from suspensionlab.core import cad_parts

    path = tmp_path / "limited.step"
    write_cad_assembly(path)
    monkeypatch.setattr(cad_parts, "MAX_GROUP_FACES", 2)
    triangles, faces, skipped, recovered, names, groups, instance_groups, instances = create_mesh(path, 2.)
    assert (faces, skipped, recovered) == (12, 0, 0)
    assert len(triangles) >= 24 and names == ("Без имени / прочие",)
    assert np.all(groups == 0)


def test_ambiguous_and_missing_faces_are_unidentified():
    from suspensionlab.core.cad_parts import face_group

    class Face:
        def __init__(self, key):
            self.key = key
        def __hash__(self):
            return 1
        def IsSame(self, other):  # noqa: N802
            return self.key == other.key
    face = Face(1)
    assert face_group(face, {}) == 0
    assert face_group(face, {1: [(Face(2), 3)]}) == 0
    assert face_group(face, {1: [(Face(1), 2), (Face(1), 3)]}) == 0
    assert face_group(face, {1: [(Face(1), 2), (Face(2), 3)]}) == 2


def test_distinct_solids_and_free_face_are_grouped_without_losing_geometry():
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pln
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound

    from suspensionlab.core.cad_parts import collect_part_groups, face_group

    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    first = BRepPrimAPI_MakeBox(2., 3., 5.).Shape()
    second = BRepPrimAPI_MakeBox(4., 6., 8.).Shape()
    tool.AddShape(first, False)
    tool.AddShape(second, False)
    loose = BRepBuilderAPI_MakeFace(gp_Pln(), 0., 1., 0., 1.).Face()
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for item in (first, second, loose):
        builder.Add(compound, item)
    names, mapping = collect_part_groups(tool, compound)
    explorer = TopExp_Explorer(compound, TopAbs_ShapeEnum.TopAbs_FACE)
    groups = []
    while explorer.More():
        groups.append(face_group(explorer.Current(), mapping))
        explorer.Next()
    assert len(names) == 3 and len(groups) == 13
    assert set(groups[:6]) == {1} and set(groups[6:12]) == {2} and groups[12] == 0


def test_coincident_instances_are_not_assigned_arbitrarily():
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    from suspensionlab.core.cad_instances import collect_instances
    from suspensionlab.core.cad_parts import face_group

    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    root = tool.NewShape()
    part = tool.NewShape()
    tool.SetShape(part, BRepPrimAPI_MakeBox(2., 3., 5.).Shape())
    tool.AddComponent(root, part, TopLoc_Location())
    tool.AddComponent(root, part, TopLoc_Location())
    tool.UpdateAssemblies()
    shape = tool.GetOneShape()
    # Избегаем чтения имён из недосериализованного тестового XCAF-документа.
    part_faces = {}
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        part_faces.setdefault(hash(face), []).append((face, 1))
        explorer.Next()
    parents, instance_faces = collect_instances(tool, part_faces)
    assert len(parents) == 3 and parents[1] == parents[2] != 0
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    seen = 0
    while explorer.More():
        assert face_group(explorer.Current(), part_faces) == parents[1]
        assert face_group(explorer.Current(), instance_faces) == 0
        seen += 1
        explorer.Next()
    assert seen == 12


def test_instance_limit_preserves_group_but_disables_instance_assignment(tmp_path, monkeypatch):
    from suspensionlab.core import cad_instances

    path = tmp_path / "instances.step"
    write_cad_assembly(path)
    monkeypatch.setattr(cad_instances, "MAX_INSTANCES", 2)
    triangles, faces, skipped, recovered, names, groups, parents, instances = create_mesh(path, 2.)
    assert (faces, skipped, recovered) == (12, 0, 0)
    assert len(triangles) >= 24 and np.all(groups > 0)
    assert parents == (0,) and np.all(instances == 0)

"""STEP-файл создан Open CASCADE: сверка ограниченного парсера с эталонными позами.

Только CAD CI: искусственный образец, не пользовательская сборка и не подтверждение
всех вариантов STEP. Преобразования применяются только внутри теста.
"""
from math import pi

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
    assert all(item.status == "ready" and item.transform is not None for item in candidates.values())
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

"""Open CASCADE: повторная сборка из параметров, не реальная деталь подвески."""
import math

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_assembly, build_part  # noqa: E402
from suspensionlab.model.kim_format import (  # noqa: E402
    make_assembly,
    make_test_cylinder,
    read_document,
    write_document,
)


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_cylinder_and_two_translated_instances_rebuild_after_reopening(tmp_path):
    part = make_test_cylinder('bar', 'Демонстрационный цилиндр', 10., 50.)
    assembly = make_assembly('Пример', [part], [
        {'id': 'one', 'part_id': 'bar', 'translation_mm': [100., 0., 0.]},
        {'id': 'two', 'part_id': 'bar', 'translation_mm': [-100., 0., 0.]},
    ])
    path = tmp_path / 'подвеска.kima'
    write_document(path, 'assembly', assembly)
    read = read_document(path, 'assembly')
    cylinder = build_part(read['parts'][0])
    compound = build_assembly(read)
    assert BRepCheck_Analyzer(cylinder).IsValid()
    assert volume(cylinder) == pytest.approx(math.pi * 10**2 * 50)
    assert volume(compound) == pytest.approx(2 * math.pi * 10**2 * 50)
    bounds = Bnd_Box()
    BRepBndLib.Add_s(compound, bounds)
    low, high = bounds.CornerMin(), bounds.CornerMax()
    xmin, ymin, zmin, xmax, ymax, zmax = low.X(), low.Y(), low.Z(), high.X(), high.Y(), high.Z()
    assert xmin == pytest.approx(-110., abs=1e-4)
    assert xmax == pytest.approx(110., abs=1e-4)
    assert ymin == pytest.approx(-10., abs=1e-4) and ymax == pytest.approx(10., abs=1e-4)
    assert zmin == pytest.approx(0., abs=1e-4) and zmax == pytest.approx(50., abs=1e-4)
    read['parts'][0]['geometry']['radius_mm'] = 20.
    assert volume(build_part(read['parts'][0])) == pytest.approx(math.pi * 20**2 * 50)
    assert volume(build_assembly(read)) == pytest.approx(2 * math.pi * 20**2 * 50)


def test_lower_arm_rods_rebuild_with_expected_volume_and_position(tmp_path):
    from suspensionlab.model.entities import Project
    from suspensionlab.model.kim_format import compare_lower_arm_source, make_lower_arm_prototype

    project = Project.create_default()
    for code, position in {
        'lca_f_in': (0., 0., 0.),
        'lca_r_in': (100., 0., 0.),
        'lbj': (0., 100., 0.),
    }.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = position
    part = make_lower_arm_prototype('arm', 'Черновик рычага', project, 2.)
    assembly = make_assembly('Черновик', [part], [
        {'id': 'instance', 'part_id': 'arm', 'translation_mm': [0, 0, 0]},
    ], project)
    path = tmp_path / 'подвеска.kima'
    write_document(path, 'assembly', assembly)
    saved = read_document(path, 'assembly')
    shape = build_part(saved['parts'][0])
    assert BRepCheck_Analyzer(shape).IsValid()
    expected = math.pi * 2**2 * (100. + math.sqrt(2) * 100.)
    assert volume(shape) == pytest.approx(expected)
    assert volume(build_assembly(saved)) == pytest.approx(expected)
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    center = props.CentreOfMass()
    assert center.X() == pytest.approx((50 * math.sqrt(2)) / (1 + math.sqrt(2)))
    assert center.Y() == pytest.approx(50.)
    assert center.Z() == pytest.approx(0., abs=1e-6)
    assert compare_lower_arm_source(saved['parts'][0], project)
    project.front.hardpoints['lbj'].y = 200.
    assert not compare_lower_arm_source(saved['parts'][0], project)
    updated = make_lower_arm_prototype('arm', 'Черновик рычага', project, 2.)
    assert volume(build_part(updated)) == pytest.approx(math.pi * 2**2 * (200 + math.sqrt(50000)))


def test_hollow_tubes_have_expected_volume_and_rebuild_from_changed_scheme(tmp_path):
    from suspensionlab.model.entities import Project
    from suspensionlab.model.kim_format import (
        compare_lower_arm_source,
        make_lower_arm_tube_prototype,
        rebuild_lower_arm_prototype,
    )

    project = Project.create_default()
    for code, position in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (100., 0., 0.), 'lbj': (0., 100., 0.),
    }.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = position
    part = make_lower_arm_tube_prototype('arm', 'Трубы', project, 10., 2.)
    path = tmp_path / 'рычаг.kim'
    write_document(path, 'part', part)
    saved = read_document(path, 'part')
    shape = build_part(saved)
    assert BRepCheck_Analyzer(shape).IsValid()
    area = math.pi * (10**2 - 8**2)
    assert volume(shape) == pytest.approx(area * (100 + math.sqrt(20000)), rel=1e-7)
    project.front.hardpoints['lbj'].y = 200
    assert not compare_lower_arm_source(saved, project)
    updated = rebuild_lower_arm_prototype(saved, project)
    assert compare_lower_arm_source(updated, project)
    assert BRepCheck_Analyzer(build_part(updated)).IsValid()
    assert volume(build_part(updated)) == pytest.approx(area * (200 + math.sqrt(50000)), rel=1e-7)
    assert read_document(path, 'part') == saved  # no silent file overwrite


def test_weldment_preview_contains_only_two_separate_tubes_and_rejects_stale_source(tmp_path):
    from suspensionlab.core.cad_kim_prototype import build_weldment_tubes_preview
    from suspensionlab.model.entities import Project
    from suspensionlab.model.welded_arm import make_welded_arm, rebuild_welded_arm

    project = Project.create_default()
    for code, position in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (100., 0., 0.), 'lbj': (0., 100., 0.),
    }.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = position
    doc = make_welded_arm(project, 10., 2., 'required')
    path = tmp_path / 'рычаг.kima'
    write_document(path, 'assembly', doc)
    saved = read_document(path, 'assembly')
    front, rear = (build_part(part) for part in saved['parts'])
    section = math.pi * (10**2 - 8**2)
    assert BRepCheck_Analyzer(front).IsValid() and BRepCheck_Analyzer(rear).IsValid()
    assert volume(front) == pytest.approx(section * 100, rel=1e-7)
    assert volume(rear) == pytest.approx(section * math.sqrt(20000), rel=1e-7)
    assert volume(build_weldment_tubes_preview(saved)) == pytest.approx(volume(front) + volume(rear))
    with pytest.raises(ValueError):
        build_assembly(saved)  # a partial preview must never masquerade as the full assembly
    saved['scheme']['front_axle']['hardpoints']['lbj']['y'] = 200
    with pytest.raises(ValueError):
        build_weldment_tubes_preview(saved)
    project.front.hardpoints['lbj'].y = 200
    updated = rebuild_welded_arm(saved, project)
    assert volume(build_weldment_tubes_preview(updated)) == pytest.approx(section * (200 + math.sqrt(50000)), rel=1e-7)
    assert read_document(path, 'assembly') == doc


def test_isolated_tube_mesh_rebuild_follows_scheme_and_rejects_stale(tmp_path):
    import numpy as np

    from suspensionlab.core.cad_transport import CadPreviewError
    from suspensionlab.core.cad_weldment_job import WeldmentCadJob
    from suspensionlab.core.cad_weldment_worker import MAX_TRIANGLES, create_mesh
    from suspensionlab.model.entities import Project
    from suspensionlab.model.welded_arm import make_welded_arm, rebuild_welded_arm

    project = Project.create_default()
    for code, position in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (100., 0., 0.), 'lbj': (0., 100., 0.),
    }.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = position
    doc = make_welded_arm(project, 10, 2, 'required')
    path = tmp_path / 'source.kima'
    write_document(path, 'assembly', doc)
    old = path.read_bytes()
    triangles, faces = create_mesh(path, 2.)
    assert 0 < len(triangles) <= MAX_TRIANGLES and faces >= 6
    mesh = WeldmentCadJob().run(doc)
    assert mesh.face_count == faces and len(mesh.triangles) == len(triangles)
    assert mesh.skipped_faces == mesh.recovered_faces == 0
    assert np.allclose(mesh.triangles, triangles)
    project.front.hardpoints['lbj'].y = 200.
    updated = rebuild_welded_arm(doc, project)
    changed = WeldmentCadJob().run(updated)
    assert changed.triangles[:, :, 1].max() > mesh.triangles[:, :, 1].max() + 90
    assert path.read_bytes() == old
    doc['scheme']['front_axle']['hardpoints']['lbj']['y'] += 1
    with pytest.raises(CadPreviewError):
        WeldmentCadJob().run(doc)
    cancelled = WeldmentCadJob()
    cancelled.cancel()
    with pytest.raises(CadPreviewError, match='cancelled'):
        cancelled.run(updated)


def test_bent_tube_is_hollow_valid_and_has_expected_centerline_volume():
    from suspensionlab.core.cad_weldment_job import WeldmentCadJob
    from suspensionlab.model.entities import Project
    from suspensionlab.model.welded_arm import make_welded_arm, rebuild_welded_arm

    project = Project.create_default()
    for code, position in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (0., -100., 0.), 'lbj': (100., 100., 0.),
    }.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = position
    doc = make_welded_arm(project, 10, 2, 'unknown', bends={
        'front': {'vertex_mm': [100., 0., 0.], 'radius_mm': 20.},
    })
    shape = build_part(doc['parts'][0])
    assert BRepCheck_Analyzer(shape).IsValid()
    expected = math.pi * (10**2 - 8**2) * (160 + 10 * math.pi)
    assert volume(shape) == pytest.approx(expected, rel=1e-7)
    mesh = WeldmentCadJob().run(doc)
    assert len(mesh.triangles) > 0 and mesh.skipped_faces == mesh.recovered_faces == 0
    project.front.hardpoints['lbj'].y = 150
    updated = rebuild_welded_arm(doc, project)
    assert volume(build_part(updated['parts'][0])) == pytest.approx(expected + math.pi * 36 * 50, rel=1e-7)
    assert WeldmentCadJob().run(updated).triangles[:, :, 1].max() > mesh.triangles[:, :, 1].max() + 40


def test_bent_tube_in_spatial_plane_is_valid_and_incomplete_assembly_refused():
    from suspensionlab.model.entities import Project
    from suspensionlab.model.welded_arm import make_welded_arm

    p = Project.create_default()
    for code, xyz in {
        'lca_f_in': (4., 5., 6.), 'lca_r_in': (0., -20., 0.), 'lbj': (4., 105., 106.),
    }.items():
        pt = p.front.hardpoints[code]
        pt.x, pt.y, pt.z = xyz
    doc = make_welded_arm(p, 10, 2, 'unknown', bends={
        'front': {'vertex_mm': [4, 105, 6], 'radius_mm': 20},
    })
    shape = build_part(doc['parts'][0])
    assert BRepCheck_Analyzer(shape).IsValid()
    assert volume(shape) == pytest.approx(math.pi * 36 * (160 + 10 * math.pi), rel=1e-7)
    with pytest.raises(ValueError):
        build_assembly(doc)


def test_scheme_part_roundtrip_rebuilds_same_cad_as_preview(tmp_path):
    from suspensionlab.core.cad_kim_prototype import build_weldment_tubes_preview
    from suspensionlab.model.entities import Project
    from suspensionlab.model.kim_format import make_scheme_arm_part
    from suspensionlab.model.welded_arm import make_welded_arm

    project = Project.create_default()
    part = make_scheme_arm_part('arm', 'Рычаг', project, 12, 2)
    path = tmp_path / 'схема-рычаг.kim'
    write_document(path, 'part', part, overwrite=False)
    saved = read_document(path, 'part')
    shape = build_part(saved)
    saved_project = Project.from_dict(saved['scheme'])
    preview = build_weldment_tubes_preview(make_welded_arm(saved_project, 12, 2, 'unknown'))
    assert BRepCheck_Analyzer(shape).IsValid() and BRepCheck_Analyzer(preview).IsValid()
    assert volume(shape) == pytest.approx(volume(preview), rel=1e-10)
    a, b = Bnd_Box(), Bnd_Box()
    BRepBndLib.Add_s(shape, a)
    BRepBndLib.Add_s(preview, b)
    for left, right in ((a.CornerMin(), b.CornerMin()), (a.CornerMax(), b.CornerMax())):
        assert (left.X(), left.Y(), left.Z()) == pytest.approx((right.X(), right.Y(), right.Z()), abs=1e-7)


def test_scheme_part_reopens_in_isolated_cad_preview_worker(tmp_path):
    from suspensionlab.core.cad_weldment_job import WeldmentCadJob
    from suspensionlab.model.entities import Project
    from suspensionlab.model.kim_format import make_scheme_arm_part
    from suspensionlab.model.welded_arm import make_welded_arm

    part = make_scheme_arm_part('arm', 'Рычаг', Project.create_default(), 12, 2)
    path = tmp_path / 'арм.kim'
    write_document(path, 'part', part, overwrite=False)
    loaded = read_document(path, 'part')
    geometry = loaded['geometry']
    preview = make_welded_arm(Project.from_dict(loaded['scheme']), geometry['radius_mm'], geometry['wall_mm'], 'unknown')
    mesh = WeldmentCadJob().run(preview, deviation=0.2)
    assert mesh.face_count >= 8 and mesh.skipped_faces == mesh.recovered_faces == 0
    assert len(mesh.triangles) > 20


@pytest.mark.parametrize('axis', ['x', 'y', 'z'])
def test_scheme_arm_bushing_housings_axis_center_volume_and_mesh_after_rebuild(tmp_path, axis):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from suspensionlab.core.cad_weldment_job import WeldmentCadJob
    from suspensionlab.model.entities import Project
    from suspensionlab.model.kim_format import make_scheme_arm_part, rebuild_scheme_arm_part, set_scheme_arm_bushings

    p = Project.create_default()
    for code, coords in {'lca_f_in': (10, 20, 30), 'lca_r_in': (110, 0, 40), 'lbj': (0, 100, 60)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = coords
    doc = set_scheme_arm_bushings(make_scheme_arm_part('arm', 'Рычаг', p, 10, 2),
                                  {'axis': axis, 'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 24})
    source = tmp_path / 'housing.kim'
    write_document(source, 'part', doc, overwrite=False)
    p.front.hardpoints['lca_f_in'].x += 50
    updated = rebuild_scheme_arm_part(read_document(source, 'part'), p)
    shape = build_part(updated)
    assert BRepCheck_Analyzer(shape).IsValid()
    explorer, solids = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID), []
    while explorer.More():
        solids.append(explorer.Current())
        explorer.Next()
    assert len(solids) == 4  # Two separate tubes and two separate housing solids, no boolean union.
    direction = {'x': (1, 0, 0), 'y': (0, 1, 0), 'z': (0, 0, 1)}[axis]
    for solid, point in zip(solids[2:], updated['geometry']['source']['coordinates_mm'][:2], strict=True):
        assert volume(solid) == pytest.approx(math.pi * (14**2 - 7**2) * 24, rel=1e-7)
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, props)
        center = props.CentreOfMass()
        assert (center.X(), center.Y(), center.Z()) == pytest.approx(point, abs=1e-6)
        faces = TopExp_Explorer(solid, TopAbs_ShapeEnum.TopAbs_FACE)
        found = 0
        while faces.More():
            surface = BRepAdaptor_Surface(TopoDS.Face(faces.Current()))
            if surface.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                d = surface.Cylinder().Axis().Direction()
                assert tuple(abs(v) for v in (d.X(), d.Y(), d.Z())) == pytest.approx(direction, abs=1e-7)
                found += 1
            faces.Next()
        assert found == 2
    mesh = WeldmentCadJob().run(updated)
    assert len(mesh.triangles) and mesh.skipped_faces == mesh.recovered_faces == 0
    assert read_document(source, 'part') == doc


@pytest.mark.parametrize('axis', ['x', 'y', 'z'])
def test_separate_parts_and_assembly_preview_are_consistent(tmp_path, axis):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from suspensionlab.core.cad_kim_prototype import build_scheme_arm_assembly_preview
    from suspensionlab.core.cad_weldment_job import WeldmentCadJob
    from suspensionlab.model.entities import Project
    from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly, rebuild_scheme_arm_assembly

    p = Project.create_default()
    for code, xyz in {'lca_f_in': (0, 0, 0), 'lca_r_in': (100, 0, 20), 'lbj': (0, 100, 40)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    doc = make_scheme_arm_assembly(p, 10, 2, {'axis': axis, 'outer_radius_mm': 14,
                                               'bore_radius_mm': 7, 'length_mm': 24})
    path = tmp_path / 'arm.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    p.front.hardpoints['lca_f_in'].x += 20
    updated = rebuild_scheme_arm_assembly(read_document(path, 'assembly'), p)
    shape = build_scheme_arm_assembly_preview(updated)
    assert BRepCheck_Analyzer(shape).IsValid()
    solids, exp = [], TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    assert len(solids) == 4
    expected = {'x': (1, 0, 0), 'y': (0, 1, 0), 'z': (0, 0, 1)}[axis]
    for i, solid in enumerate(solids):
        assert volume(solid) == pytest.approx(volume(build_part(updated['parts'][i])), rel=1e-7)
        if i < 2:
            continue
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, props)
        center = props.CentreOfMass()
        assert (center.X(), center.Y(), center.Z()) == pytest.approx(
            updated['parts'][0]['geometry']['source']['coordinates_mm'][i-2], abs=1e-6)
        faces, cylinders = TopExp_Explorer(solid, TopAbs_ShapeEnum.TopAbs_FACE), 0
        while faces.More():
            face = BRepAdaptor_Surface(TopoDS.Face(faces.Current()))
            if face.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                d = face.Cylinder().Axis().Direction()
                assert tuple(abs(v) for v in (d.X(), d.Y(), d.Z())) == pytest.approx(expected, abs=1e-7)
                cylinders += 1
            faces.Next()
        assert cylinders == 2
    mesh = WeldmentCadJob().run(updated)
    assert len(mesh.triangles) and mesh.skipped_faces == mesh.recovered_faces == 0
    assert read_document(path, 'assembly') == doc


def test_assembly_individual_dimension_edit_changes_only_corresponding_solid():
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    from suspensionlab.core.cad_kim_prototype import build_scheme_arm_assembly_preview
    from suspensionlab.model.entities import Project
    from suspensionlab.model.scheme_arm_assembly import edit_assembly_part, make_scheme_arm_assembly

    project = Project.create_default()
    doc = make_scheme_arm_assembly(project, 12, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                    'bore_radius_mm': 7, 'length_mm': 24})
    changed = edit_assembly_part(doc, 'housing_front', {'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 40})
    def volumes(document):
        explorer = TopExp_Explorer(build_scheme_arm_assembly_preview(document), TopAbs_ShapeEnum.TopAbs_SOLID)
        result = []
        while explorer.More():
            result.append(volume(explorer.Current()))
            explorer.Next()
        return result
    original_volumes, new_volumes = volumes(doc), volumes(changed)
    assert len(original_volumes) == len(new_volumes) == 4
    assert new_volumes[:2] == pytest.approx(original_volumes[:2])
    assert new_volumes[2] == pytest.approx(original_volumes[2] * 40 / 24)
    assert new_volumes[3] == pytest.approx(original_volumes[3])

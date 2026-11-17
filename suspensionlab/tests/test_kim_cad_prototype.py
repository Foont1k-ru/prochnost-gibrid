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

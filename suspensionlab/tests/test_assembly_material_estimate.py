"""Аналитическая оценка отдельных неподрезанных деталей предварительной сборки."""
import math
from copy import deepcopy

import pytest

from suspensionlab.model.assembly_material_estimate import assembly_part_volumes, density_kg_m3
from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.scheme_arm_assembly import (
    edit_assembly_part,
    make_plate,
    make_scheme_arm_assembly,
    set_assembly_axis,
    set_assembly_plate,
    set_plate_placement,
)


def document():
    project = Project.create_default()
    for code, xyz in {'lca_f_in': (0, 0, 0), 'lca_r_in': (30, 0, 0), 'lbj': (0, 40, 0)}.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    return make_scheme_arm_assembly(project, 10, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                       'bore_radius_mm': 7, 'length_mm': 24})


def test_volumes_of_separate_tubes_housings_and_optional_plate(tmp_path):
    doc = document()
    before = deepcopy(doc)
    values = assembly_part_volumes(doc)
    assert [part.identifier for part in values] == ['tube_front', 'tube_rear', 'housing_front', 'housing_rear']
    assert [part.length_mm for part in values] == [40., 50., None, None]
    assert [part.volume_mm3 for part in values] == pytest.approx([
        math.pi * (100 - 64) * 40, math.pi * (100 - 64) * 50,
        math.pi * (196 - 49) * 24, math.pi * (196 - 49) * 24,
    ])
    assert doc == before
    plate = set_assembly_plate(doc, make_plate(60, 50, 5, 10),
                               {'normal': 'z', 'offset_mm': [0, 0, 0]})
    estimate = assembly_part_volumes(plate)
    assert estimate[:4] == values
    assert estimate[4].volume_mm3 == pytest.approx((60 * 50 - math.pi * 10**2) * 5)
    assert estimate[4].length_mm is None
    path = tmp_path / 'сборка.kima'
    write_document(path, 'assembly', plate, overwrite=False)
    assert assembly_part_volumes(read_document(path, 'assembly')) == estimate
    assert plate == set_plate_placement(plate, {'normal': 'z', 'offset_mm': [0, 0, 0]})


def test_parameter_edits_and_orientation():
    doc = document()
    original = assembly_part_volumes(doc)
    for axis in ('x', 'y', 'z'):
        assert assembly_part_volumes(set_assembly_axis(doc, axis)) == original
    changed = edit_assembly_part(doc, 'housing_front',
                                 {'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 48})
    values = assembly_part_volumes(changed)
    assert values[2].volume_mm3 == pytest.approx(2 * original[2].volume_mm3)
    assert values[:2] == original[:2] and values[3:] == original[3:]
    bad = deepcopy(doc)
    bad['parts'][0]['geometry']['wall_mm'] = -1
    with pytest.raises(KimFormatError):
        assembly_part_volumes(bad)


@pytest.mark.parametrize(('text', 'expected'), [('', None), ('  ', None), ('7850', 7850.), ('7,85e3', 7850.),
                                               ('0,000001', 1e-6), ('1000000', 1000000.)])
def test_density_valid_or_absent(text, expected):
    assert density_kg_m3(text) == expected


@pytest.mark.parametrize('text', ['0', '-1', 'nan', 'inf', '1e309', '1e-7', '1000001', 'медь', '1,2,3'])
def test_invalid_density(text):
    with pytest.raises(ValueError):
        density_kg_m3(text)


def test_independent_cad_volume_oracle():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    from suspensionlab.core.cad_kim_prototype import build_part

    base = document()
    with_plate = set_assembly_plate(base, make_plate(60, 50, 5, 10),
                                    {'normal': 'y', 'offset_mm': [0, 0, 0]})
    for doc in (base, with_plate):
        for part, estimate in zip(doc['parts'], assembly_part_volumes(doc), strict=True):
            properties = GProp_GProps()
            BRepGProp.VolumeProperties_s(build_part(part), properties)
            assert properties.Mass() == pytest.approx(estimate.volume_mm3, rel=1e-7)

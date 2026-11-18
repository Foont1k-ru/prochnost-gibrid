from copy import deepcopy
from math import dist

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError
from suspensionlab.model.scheme_arm_assembly import make_plate, make_scheme_arm_assembly, set_assembly_plate
from suspensionlab.model.scheme_assembly_views import assembly_views


def document(axis='x'):
    return make_scheme_arm_assembly(Project.create_default(), 12, 2,
                                    {'axis': axis, 'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 24})


@pytest.mark.parametrize('axis,index', [('x', 0), ('y', 1), ('z', 2)])
def test_axes_dimensions_and_projections(axis, index):
    doc = document(axis)
    before = deepcopy(doc)
    views = assembly_views(doc)
    points = doc['parts'][0]['geometry']['source']['coordinates_mm']
    assert len(views.lines) == 4 and not views.has_plate
    assert views.lines[0].start == tuple(points[0]) and views.lines[0].end == tuple(points[2])
    assert views.dimensions[0].value_mm == pytest.approx(dist(points[0], points[2]))
    assert views.dimensions[1].value_mm == 24
    housing = views.lines[2]
    assert housing.end[index] - housing.start[index] == pytest.approx(24)
    assert all(housing.end[i] == housing.start[i] for i in range(3) if i != index)
    assert views.project('XY')[0][:2] == (tuple(points[0][:2]), tuple(points[2][:2]))
    with pytest.raises(ValueError):
        views.project('bad')
    assert doc == before


@pytest.mark.parametrize('normal,u,v', [('x', (0, 0, -1), (0, 1, 0)),
                                        ('y', (1, 0, 0), (0, 0, -1)),
                                        ('z', (1, 0, 0), (0, 1, 0))])
def test_plate_rotation_offset_and_hole(normal, u, v):
    doc = set_assembly_plate(document(), make_plate(40, 20, 3, 5),
                             {'normal': normal, 'offset_mm': [3, 4, 5]})
    views = assembly_views(doc)
    origin = [x + d for x, d in zip(doc['parts'][0]['geometry']['source']['coordinates_mm'][2], [3, 4, 5], strict=True)]
    first = views.lines[4]
    assert first.start == pytest.approx(tuple(origin[i] - 20*u[i] - 10*v[i] for i in range(3)))
    assert first.end == pytest.approx(tuple(origin[i] + 20*u[i] - 10*v[i] for i in range(3)))
    assert views.lines[8].start == pytest.approx(tuple(origin[i] + 5*u[i] for i in range(3)))
    assert len(views.lines) == 40 and views.has_plate
    assert [d.value_mm for d in views.dimensions[-4:]] == [40, 20, 3, 10]


def test_invalid_document_not_evaluated():
    doc = document()
    doc['parts'][0]['geometry']['radius_mm'] = -1
    with pytest.raises(KimFormatError):
        assembly_views(doc)

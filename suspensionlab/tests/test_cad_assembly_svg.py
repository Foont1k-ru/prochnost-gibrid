"""Безопасный отдельный SVG предварительных видов, не производственный чертёж."""
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
from suspensionlab.export.cad_assembly_svg import SvgProjectionError, projection_svg, write_new_projection_svg

NS = {'svg': 'http://www.w3.org/2000/svg'}


def sample():
    return CadAssemblyProjection((((0., 0., 2., 3.),), ((0., 0., 2., 4.),), ((0., 0., 3., 4.),)),
                                 (0., 0., 0., 2., 3., 4.))


def test_svg_views_dimensions_warning_and_no_external_content():
    data = projection_svg(sample(), '0.16', dimensions=True)
    root = ET.fromstring(data)
    assert root.tag == '{http://www.w3.org/2000/svg}svg'
    text = ' '.join(root.itertext())
    assert 'НЕ ПРОИЗВОДСТВЕННЫЙ ЧЕРТЁЖ' in text and 'НЕ ИСПОЛЬЗОВАТЬ ДЛЯ ИЗГОТОВЛЕНИЯ' in text
    assert '0.16, с условной пластиной' in text and 'может отличаться от файла и текущего проекта' in text
    assert all(plane in text for plane in ('XY:', 'XZ:', 'YZ:'))
    assert 'X ≈ 2.0 мм' in text and 'Y ≈ 3.0 мм' in text and 'Z ≈ 4.0 мм' in text
    assert len(root.findall('.//svg:path', NS)) == 6
    assert not root.findall('.//svg:script', NS) and not root.findall('.//svg:image', NS)
    assert all('href' not in key.lower() for element in root.iter() for key in element.attrib)
    plain = ET.fromstring(projection_svg(sample(), '0.15', dimensions=False))
    assert len(plain.findall('.//svg:path', NS)) == 3
    assert 'без пластины' in ' '.join(plain.itertext())
    assert 'X ≈ 2.0 мм' not in ' '.join(plain.itertext())


def test_svg_preserves_valid_small_dimensions_without_claiming_zero():
    result = CadAssemblyProjection((((0., 0., 0.02, 0.03),),) * 3, (0., 0., 0., 0.02, 0.03, 0.04))
    root = ET.fromstring(projection_svg(result, '0.15', dimensions=True))
    assert 'X <0.1 мм' in ' '.join(root.itertext())


def test_invalid_projection_and_parameters_are_rejected():
    invalid = CadAssemblyProjection((((0., 0., 2., 3.),),) * 3, (0., 0., 0., 1., 1., 1.))
    for value, version, dimensions in ((invalid, '0.15', True), (sample(), 'bad', True),
                                       (sample(), '0.15', 'yes')):
        with pytest.raises(SvgProjectionError):
            projection_svg(value, version, dimensions=dimensions)


def test_create_only_never_overwrites_existing_files_or_follows_link(tmp_path):
    target = tmp_path / 'виды.svg'
    result = write_new_projection_svg(target, sample(), '0.16', dimensions=True)
    assert result == target and ET.fromstring(target.read_bytes()).tag.endswith('svg')
    before = target.read_bytes()
    with pytest.raises(SvgProjectionError):
        write_new_projection_svg(target, sample(), '0.15', dimensions=False)
    assert target.read_bytes() == before
    with pytest.raises(SvgProjectionError):
        write_new_projection_svg(tmp_path / 'part.kim', sample(), '0.15', dimensions=True)
    assert not (tmp_path / 'part.kim').exists()
    link = tmp_path / 'alias.svg'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('symlinks not available')
    with pytest.raises(SvgProjectionError):
        write_new_projection_svg(link, sample(), '0.15', dimensions=True)
    assert target.read_bytes() == before and not list(tmp_path.glob('.projection-*.tmp'))


def test_file_created_during_export_is_never_replaced(tmp_path, monkeypatch):
    from suspensionlab.export import cad_assembly_svg

    target = tmp_path / 'race.svg'
    real_link = cad_assembly_svg.os.link
    def racing_link(source, destination):
        Path(destination).write_bytes(b'existing-user-file')
        real_link(source, destination)
    monkeypatch.setattr(cad_assembly_svg.os, 'link', racing_link)
    with pytest.raises(SvgProjectionError):
        write_new_projection_svg(target, sample(), '0.15', dimensions=True)
    assert target.read_bytes() == b'existing-user-file'
    assert not list(tmp_path.glob('.projection-*.tmp'))


def test_real_cad_assembly_produces_well_formed_vector_preview():
    pytest.importorskip('OCP')
    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjectionJob
    from suspensionlab.model.entities import Project
    from suspensionlab.model.scheme_arm_assembly import make_plate, make_scheme_arm_assembly, set_assembly_plate

    document = make_scheme_arm_assembly(Project.create_default(), 12, 2,
                                        {'axis': 'x', 'outer_radius_mm': 14,
                                         'bore_radius_mm': 7, 'length_mm': 24})
    document = set_assembly_plate(document, make_plate(40, 20, 3, 5),
                                  {'normal': 'z', 'offset_mm': [0, 0, 0]})
    projection = CadAssemblyProjectionJob().run(document, timeout=45)
    root = ET.fromstring(projection_svg(projection, document['version'], dimensions=True))
    path_data = [path.attrib['d'] for path in root.findall('.//svg:path', NS)]
    assert len(path_data) == 6
    assert all('M ' in data and ' L ' in data for data in path_data)
    text = ' '.join(root.itertext())
    for axis, i in zip('XYZ', range(3), strict=True):
        size = projection.bounds_mm[i + 3] - projection.bounds_mm[i]
        assert f'{axis} ≈ {size:.1f} мм' in text

"""Проверка DXF-копии и защиты чужих файлов."""

import pytest

from suspensionlab.model.sketch_draft import make_entity
from suspensionlab.model.sketch_dxf import SketchDxfError, write_new_dxf
from suspensionlab.model.sketch_io import SketchDocument


def document():
    return SketchDocument("YZ", 7.0, (make_entity("line", (1, 2), (3, 4)),
                                      make_entity("circle", (10, 20), (13, 24))))


def test_export_dxf_as_independent_xy_mm(tmp_path):
    import ezdxf

    path = tmp_path / "drawing.dxf"
    write_new_dxf(path, document())
    file = ezdxf.readfile(path)
    assert file.header["$INSUNITS"] == 4
    items = list(file.modelspace())
    assert [item.dxftype() for item in items] == ["LINE", "CIRCLE"]
    assert tuple(items[0].dxf.start) == (1, 2, 0)
    assert tuple(items[0].dxf.end) == (3, 4, 0)
    assert tuple(items[1].dxf.center) == (10, 20, 0)
    assert items[1].dxf.radius == 5


def test_export_never_overwrites_and_rejects_other_extension(tmp_path):
    target = tmp_path / "drawing.dxf"
    target.write_bytes(b"original")
    with pytest.raises(SketchDxfError):
        write_new_dxf(target, document())
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".sketch-dxf-*.tmp"))
    with pytest.raises(SketchDxfError):
        write_new_dxf(tmp_path / "project.json", document())


def test_export_does_not_follow_target_symlink(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("original")
    link = tmp_path / "link.dxf"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(SketchDxfError):
        write_new_dxf(link, document())
    assert target.read_text() == "original" and link.is_symlink()


def test_export_collision_during_link_does_not_clobber(tmp_path, monkeypatch):
    import suspensionlab.model.sketch_dxf as sketch_dxf

    path = tmp_path / "race.dxf"
    link = sketch_dxf.os.link

    def collide(source, destination):
        path.write_text("someone else")
        link(source, destination)

    monkeypatch.setattr(sketch_dxf.os, "link", collide)
    with pytest.raises(SketchDxfError):
        write_new_dxf(path, document())
    assert path.read_text() == "someone else"
    assert not list(tmp_path.glob(".sketch-dxf-*.tmp"))


@pytest.mark.parametrize("sweep,start,end", [(90, 0, 90), (-90, 270, 0)])
def test_export_analytic_arc(tmp_path, sweep, start, end):
    import ezdxf

    arc = make_entity("arc", (0, 0), (10, 0), sweep)
    path = tmp_path / "arc.dxf"
    write_new_dxf(path, SketchDocument("XY", 0, (arc,)))
    item = list(ezdxf.readfile(path).modelspace())[0]
    assert item.dxftype() == "ARC" and item.dxf.radius == 10
    assert item.dxf.start_angle == start and item.dxf.end_angle == end

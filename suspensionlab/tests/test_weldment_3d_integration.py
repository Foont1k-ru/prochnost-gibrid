"""Настоящие Qt и изолированный Open CASCADE: только в окружении с обоими пакетами."""
import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
pytest.importorskip('PySide6.QtWidgets', reason='Нужен Qt', exc_type=ImportError)

from PySide6.QtWidgets import QFileDialog  # noqa: E402

from suspensionlab.model.kim_format import write_document  # noqa: E402
from suspensionlab.model.welded_arm import make_welded_arm  # noqa: E402
from suspensionlab.ui.controller import AppController  # noqa: E402
from suspensionlab.ui.weldment_dialog import WeldmentDialog  # noqa: E402


def test_actual_cad_process_and_qt_follow_changes(qtbot, tmp_path, monkeypatch):
    c = AppController()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 12, 2, 'required'))
    original = source.read_bytes()
    dialog = WeldmentDialog(c)
    qtbot.addWidget(dialog)
    dialog.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    dialog._open_file()
    dialog._start_preview()
    panel = dialog._three_d
    panel._enable.setChecked(True)
    assert panel._view.mesh is None and not dialog._save.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    old = panel._view.mesh
    assert old is not None and old.skipped_faces == old.recovered_faces == 0
    assert dialog._save.isEnabled() and not panel._view.grab().isNull()
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y + 100, point.z))
    assert panel._view.mesh is None and not dialog._save.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    new = panel._view.mesh
    assert new is not None and new.triangles[:, :, 1].max() > old.triangles[:, :, 1].max() + 80
    assert dialog._save.isEnabled() and source.read_bytes() == original
    first = c.project.front.hardpoints['lca_f_in']
    c.move_point(first, point.as_tuple())
    assert panel._view.mesh is None and not dialog._save.isEnabled()
    dialog.close()


def test_editor_builds_live_3d_without_first_saving_file(qtbot, tmp_path, monkeypatch):
    import numpy as np

    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog

    c = AppController()
    for code, xyz in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (100., 0., 0.), 'lbj': (0., 100., 0.),
    }.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    before = c.project.to_dict()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    dialog.show()
    panel = dialog._three_d
    panel._enable.setChecked(True)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    old = panel._view.mesh
    assert old is not None and dialog._save_assembly.isEnabled()
    dialog._radius.setValue(20.)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    new = panel._view.mesh
    assert new is not None and np.ptp(new.triangles[:, :, 2]) > np.ptp(old.triangles[:, :, 2]) + 10
    assert c.project.to_dict() == before and not c.dirty and list(tmp_path.iterdir()) == []
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y + 100, point.z))
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    target = tmp_path / 'result.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    dialog._save_weldment_snapshot()
    doc = read_document(target, 'assembly')
    assert doc['parts'][0]['geometry']['radius_mm'] == 20
    assert doc['parts'][0]['geometry']['source']['coordinates_mm'][2][1] == 200
    dialog._wall.setValue(20.)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    dialog.close()


def test_bent_tube_editor_and_reopened_assembly_use_actual_cad(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog

    c = AppController()
    for code, xyz in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (0., -100., 0.), 'lbj': (100., 100., 0.),
    }.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = ArmConceptDialog(c)
    qtbot.addWidget(d)
    d.show()
    for field, value in zip(d._bend_fields['front'], ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    d._bend_checks['front'].setChecked(True)
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    old = d._three_d._view.mesh
    assert old is not None and d._save_assembly.isEnabled()
    path = tmp_path / 'bent.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_weldment_snapshot()
    doc = read_document(path, 'assembly')
    assert doc['version'] == '0.3' and doc['parts'][0]['geometry']['bend_radius_mm'] == 20
    viewer = WeldmentDialog(c)
    qtbot.addWidget(viewer)
    viewer.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    viewer._open_file()
    viewer._start_preview()
    viewer._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: viewer._three_d._view.mesh is not None, timeout=45000)
    outer = c.project.front.hardpoints['lbj']
    c.move_point(outer, (100, 150, 0))
    assert d._three_d._view.mesh is None and viewer._three_d._view.mesh is None
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None and viewer._three_d._view.mesh is not None,
                    timeout=45000)
    assert d._three_d._view.mesh.triangles[:, :, 1].max() > old.triangles[:, :, 1].max() + 40
    c.move_point(outer, (100, 10, 0))
    assert d._three_d._view.mesh is None and viewer._three_d._view.mesh is None
    assert not d._save_assembly.isEnabled() and not viewer._save.isEnabled()
    d.close()
    viewer.close()

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

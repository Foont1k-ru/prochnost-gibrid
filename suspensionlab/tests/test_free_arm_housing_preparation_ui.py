"""Invalid v2 isolation and real CAD infrastructure for the independent housing."""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from test_free_arm_housing_io import make_draft
from test_free_arm_ui import fill

from suspensionlab.model.free_arm_housing_io import to_data, write_free_arm_housing
from suspensionlab.ui.free_arm_dialog import FreeArmDialog
from suspensionlab.ui.weldment_3d import Weldment3D


def test_editor_refuses_malformed_v2_without_changing_current_draft(qtbot, tmp_path, monkeypatch):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    fill(dialog)
    dialog.apply_fields()
    before, form, document = dialog.draft, dialog._form(), deepcopy(dialog._cad._document)
    path = write_free_arm_housing(tmp_path / 'v2.slarm', make_draft())
    path.write_text(path.read_text(encoding='utf-8').replace('"version": "2"', '"version": "3"'), encoding='utf-8')
    contents = path.read_bytes()
    messages = []
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_args: (str(path), ''))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_args: messages.append(_args))
    dialog._open_file()
    assert messages and dialog.draft is before and dialog._form() == form
    assert dialog._cad._document == document and path.read_bytes() == contents
    dialog.close()


def test_v2_real_worker_display_cache_and_stale_invalidation(qtbot):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    document = to_data(make_draft(('front', 'rear')))
    accepted = [document]
    panel = Weldment3D(fixed_skeleton=True, is_current=lambda value: value == accepted[0])
    qtbot.addWidget(panel)
    panel.set_document(document)
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    assert panel._view.mesh.part_names == ('tube_front', 'tube_rear', 'ball_housing')
    assert panel._parts_tree.topLevelItem(0).childCount() == 3
    assert 'подрезаны' in panel._status.text()
    panel._enable.setChecked(False)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._active_cache_hit, timeout=30000)
    changed = deepcopy(document)
    changed['ball_housing']['offset_mm'][0] += 1
    accepted[0] = changed
    panel.set_document(changed)
    assert panel._view.mesh is None and not panel._active_cache_hit
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    assert panel._document == changed and not panel._active_cache_hit
    assert panel.shutdown()

"""Real isolated CAD and the independent editor's actual freshness predicate."""
import numpy as np
import pytest
from test_free_arm_ui import fill

from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def test_real_worker_reuses_restored_draft_and_force_rebuilds(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    fill(dialog)
    dialog.apply_fields()
    panel = dialog._cad
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    original = panel._view.mesh
    assert panel._mesh_cache._items and not panel._active_cache_hit
    dialog._fields['front_X'].setText('12')
    assert panel._view.mesh is None and not dialog._save.isEnabled()
    dialog._restore_draft()
    qtbot.waitUntil(lambda: panel._ready and panel._active_cache_hit, timeout=30000)
    assert panel._worker is None and np.array_equal(panel._view.mesh.triangles, original.triangles)
    assert panel._view.mesh.part_names == original.part_names and dialog._save.isEnabled()
    panel._retry.click()
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    assert not panel._active_cache_hit and np.array_equal(panel._view.mesh.triangles, original.triangles)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()
    assert not panel._mesh_cache._items

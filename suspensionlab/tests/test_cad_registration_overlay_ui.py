import copy
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QSettings

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_registration import evaluate_registration
from suspensionlab.core.cad_registration_overlay import overlay_pairs
from suspensionlab.ui.cad_registration_overlay_dialog import CadRegistrationOverlayDialog
from suspensionlab.ui.controller import AppController


def make_dialog(qtbot, tmp_path):
    controller = AppController()
    points = ((0., 0., 0.), (100., 0., 0.), (0., 100., 0.), (0., 0., 100.))
    target = (*points[:3], (0., 0., 110.))
    mask = (True, True, True, False)
    from suspensionlab.model.point_csv import capture_points
    records = tuple(replace(p, xyz=target[i]) for i, p in enumerate(capture_points(controller.project)[:4]))
    result = evaluate_registration(points, target, mask)
    dialog = CadRegistrationOverlayDialog(controller, result.fit.transform, overlay_pairs(records, mask, result),
                                          QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    dialog.show()
    return controller, dialog


def test_overlay_projects_same_coordinates_and_filters(qtbot, tmp_path):
    controller, dialog = make_dialog(qtbot, tmp_path)
    before = copy.deepcopy(controller.project.to_dict())
    mesh = CadMesh(np.array([[[0., 0, 0], [100, 0, 0], [0, 100, 0]]]), 1)
    dialog._confirm.setChecked(True)
    dialog._show_mesh(mesh)
    assert dialog._canvas.mesh is not None
    positions = dialog._canvas.positions()
    assert positions[0][1].x() == pytest.approx(positions[0][2].x())
    assert positions[0][1].y() == pytest.approx(positions[0][2].y())
    dialog._filter.setCurrentIndex(2)
    assert dialog._list.count() == 1
    assert [p[0] for p in dialog._canvas.positions()] == [3]
    dialog._list.setCurrentRow(0)
    assert '10 мм' in dialog._detail.text()
    assert dialog._canvas.selected == 3
    dialog._canvas.grab()
    assert controller.project.to_dict() == before and not controller.dirty and controller.undo.depth() == 0
    controller.modelChanged.emit()
    assert dialog._canvas.mesh is None and not dialog._choose.isEnabled()
    dialog._show_mesh(mesh)
    assert dialog._canvas.mesh is None


def test_withdraw_confirmation_discards_pending_result(qtbot, tmp_path):
    controller, dialog = make_dialog(qtbot, tmp_path)
    mesh = CadMesh(np.zeros((1, 3, 3)), 1)
    dialog._confirm.setChecked(True)
    dialog._confirm.setChecked(False)
    dialog._confirm.setChecked(True)
    dialog._show_mesh(mesh)
    assert dialog._canvas.mesh is None
    controller.projectReplaced.emit()
    assert dialog._stale and not dialog._confirm.isEnabled()


def test_pending_result_after_cancel_is_not_displayed(qtbot, tmp_path):
    _, dialog = make_dialog(qtbot, tmp_path)
    mesh = CadMesh(np.zeros((1, 3, 3)), 1)
    class Job:
        cancelled = False
        def cancel(self):
            self.cancelled = True
    class Reader:
        job = Job()
        def deleteLater(self):  # noqa: N802
            pass
    reader = Reader()
    dialog._confirm.setChecked(True)
    dialog._reader = reader
    dialog._cancel_read()
    assert reader.job.cancelled
    dialog._show_mesh(mesh)
    assert dialog._canvas.mesh is None
    dialog._finished()
    assert dialog._choose.isEnabled()


def test_overlay_matching_content_checked_before_cad_build(qtbot, tmp_path, monkeypatch):
    from hashlib import sha256

    from suspensionlab.core.cad_transport import CadJob
    _, dialog = make_dialog(qtbot, tmp_path)
    dialog._expected_digest = sha256(b'expected').digest()
    source = tmp_path / 'source.step'
    source.write_bytes(b'other')
    calls = []
    def build(self, path, deviation):
        calls.append(1)
        return CadMesh(np.array([[[0., 0, 0], [100, 0, 0], [0, 100, 0]]]), 1)
    monkeypatch.setattr(CadJob, 'run', build)
    dialog._confirm.setChecked(True)
    dialog.load_file(source)
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert not calls and dialog._canvas.mesh is None and 'отличается по содержимому' in dialog._status.text()
    source.write_bytes(b'expected')
    dialog.load_file(source)
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert len(calls) == 1 and dialog._canvas.mesh is not None

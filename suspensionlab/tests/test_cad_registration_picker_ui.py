"""Явный выбор точки по поверхностной сетке и защита во время чтения."""
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.ui.cad_registration_picker import CadRegistrationPicker


def test_picker_requires_valid_point_and_no_active_reader(qtbot, tmp_path):
    picker = CadRegistrationPicker(QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(picker)
    assert not picker._use_a.isEnabled() and not picker._use_b.isEnabled()
    picker._show_mesh(CadMesh(np.array([[[0., 0., 0.], [10., 0., 0.], [0., 10., 0.]]]), 1))
    assert picker._measure.isChecked()
    picker._add_measurement_point((1., 2., 3.))
    assert not picker._use_a.isEnabled() and picker._identity_note.text()
    picker._loaded_digest = b'a' * 32
    picker._sync_buttons()
    assert picker._use_a.isEnabled() and not picker._use_b.isEnabled()
    picker._add_measurement_point((4., 5., 6.))
    assert picker._use_b.isEnabled()
    picker._reader = object()
    picker._sync_buttons()
    assert not picker._use_a.isEnabled() and not picker._use_b.isEnabled()
    picker._use_point(0)
    assert picker.chosen is None
    picker._reader = None
    picker._sync_buttons()
    picker._use_b.click()
    assert picker.result() == QDialog.DialogCode.Accepted and picker.chosen == (4., 5., 6.)
    assert picker.chosen_digest == b'a' * 32
    picker._clear_measurement()
    assert not picker._use_a.isEnabled() and not picker._use_b.isEnabled()


def test_real_reader_transfers_only_digest_of_current_visible_mesh(qtbot, tmp_path, monkeypatch):
    from hashlib import sha256

    from suspensionlab.core.cad_transport import CadJob, CadPreviewError
    source = tmp_path / 'model.step'
    source.write_bytes(b'first')
    def build(self, path, deviation):
        if deviation == .2:
            raise CadPreviewError('mesh')
        return CadMesh(np.array([[[0., 0., 0.], [10., 0., 0.], [0., 10., 0.]]]), 1)
    monkeypatch.setattr(CadJob, 'run', build)
    picker = CadRegistrationPicker(QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(picker)
    picker.load_file(source)
    qtbot.waitUntil(lambda: picker._reader is None, timeout=10000)
    picker._add_measurement_point((1., 2., 3.))
    assert picker._use_a.isEnabled() and picker._loaded_digest == sha256(b'first').digest()
    # A failed attempt to load a changed file must not relabel the old mesh.
    source.write_bytes(b'second')
    picker._selected_deviation = .2
    picker.load_file(source)
    qtbot.waitUntil(lambda: picker._reader is None, timeout=10000)
    assert picker._loaded_digest == sha256(b'first').digest() and picker._use_a.isEnabled()
    picker._use_a.click()
    assert picker.chosen_digest == sha256(b'first').digest()
    picker._selected_deviation = 2.
    picker.load_file(source, force=True)
    qtbot.waitUntil(lambda: picker._reader is None, timeout=10000)
    assert picker._loaded_digest == sha256(b'second').digest()
    assert not picker._measurement_points and not picker._use_a.isEnabled()

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
    picker._clear_measurement()
    assert not picker._use_a.isEnabled() and not picker._use_b.isEnabled()

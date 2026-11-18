"""Сводка и явное копирование приблизительных замеров STEP."""
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.ui.cad_preview_dialog import CadPreviewDialog


def test_copy_measurement_summary_and_reset(qtbot, tmp_path):
    dialog = CadPreviewDialog(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    dialog._path = tmp_path / 'private-model.step'
    dialog._selected_deviation = .2
    dialog._show_mesh(CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]), 3, 1, 1))
    assert not dialog._copy_measure.isEnabled()
    dialog._add_measurement_point((1., 2., 3.))
    assert not dialog._copy_measure.isEnabled()
    dialog._add_measurement_point((4., -2., 15.))
    assert dialog._copy_measure.isEnabled()
    assert '+3.00, -4.00, +12.00' in dialog._measurement.text()
    assert 'XY ≈ 5.00' in dialog._measurement.text()
    dialog._swap_measure.click()
    assert '-3.00, +4.00, -12.00' in dialog._measurement.text()
    dialog._swap_measure.click()
    dialog._copy_measure.click()
    text = QApplication.clipboard().text()
    assert 'ОРИЕНТИРОВОЧНЫЙ ЗАМЕР' in text
    assert '0.2' in text
    assert 'пропущено: 1' in text and 'восстановлено: 1' in text
    assert 'B − A' in text and '(3.0, -4.0, 12.0)' in text and 'XY ≈ 5' in text
    assert 'private-model' not in text and str(tmp_path) not in text
    dialog._add_measurement_point((0., 0., 0.))
    assert not dialog._copy_measure.isEnabled() and not dialog._swap_measure.isEnabled()
    assert len(dialog._measurement_points) == 1
    dialog._add_measurement_point((1., 1., 1.))
    assert dialog._copy_measure.isEnabled()
    dialog._keep_previous = True
    dialog._show_mesh(CadMesh(np.array([[[0, 0, 0], [20, 0, 0], [0, 20, 0]]]), 1))
    assert not dialog._copy_measure.isEnabled() and not dialog._measurement_points
    assert QApplication.clipboard().text() == text  # замена не меняет системный буфер


def test_old_measurement_survives_failed_quality_reload(qtbot, tmp_path):
    dialog = CadPreviewDialog(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    dialog._selected_deviation = 2.
    dialog._show_mesh(CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]), 1))
    dialog._add_measurement_point((1., 2., 3.))
    dialog._add_measurement_point((4., 5., 6.))
    dialog._keep_previous = True
    dialog._selected_deviation = .2
    dialog._show_error('cancelled')
    assert dialog._copy_measure.isEnabled()
    dialog._copy_measure.click()
    assert 'сетки: 2.0 мм' in QApplication.clipboard().text()
    dialog._reset_loaded_view()
    assert not dialog._copy_measure.isEnabled()

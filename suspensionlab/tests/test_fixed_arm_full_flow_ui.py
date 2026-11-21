"""Сквозной эксперимент: изгиб, корпуса, общий стык, сохранение и актуальность."""
import json

import numpy as np
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from test_fixed_arm_context_ui import _select_part, _start_cut
from test_fixed_arm_tube_joint_ui import make_editor

from suspensionlab.model.bent_tube import make_bend_path
from suspensionlab.ui.fixed_arm_housings_dialog import FixedArmHousingsDialog


def test_bent_miter_housings_save_reopen_and_project_change(qtbot, monkeypatch, tmp_path):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_editor(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(2)  # XZ
    anchor, ball = dialog.preview.anchors[0], dialog.preview.anchors[2]
    midpoint = tuple((anchor[i] + ball[i]) / 2 for i in range(3))
    dialog._create_draft('front', midpoint)
    canvas = dialog._projections[1]
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (20., True))
    canvas._dimension_fields[1].setText(str(midpoint[2] - anchor[2] + 50))
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    bend = dialog._bend_editor.values()['front']
    assert dialog._draft is None
    assert make_bend_path(anchor, bend['vertex_mm'], ball, bend['radius_mm'], dialog._radius.value()).length > 0

    def fill_housings():
        editor = QApplication.activeModalWidget()
        if not isinstance(editor, FixedArmHousingsDialog):
            return
        for leg in ('front', 'rear'):
            for key, value in (('outer_diameter_mm', '40'), ('bore_diameter_mm', '25'), ('length_mm', '32')):
                editor.fields[leg][key].setText(value)
        editor.accept()
    QTimer.singleShot(50, fill_housings)
    dialog._edit_housings()
    assert dialog._housings is not None
    axis = np.asarray(dialog._housings['front']['axis'])
    expected_axis = np.asarray(dialog.preview.anchors[1]) - np.asarray(dialog.preview.anchors[0])
    assert axis == pytest.approx(expected_axis / np.linalg.norm(expected_axis))

    dialog._tabs.setCurrentIndex(4)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    _start_cut(dialog, qtbot, monkeypatch)
    _select_part(cad, 'tube_rear')
    assert dialog._tube_joint.currentData() == 'miter'
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert cad._view.mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    dialog._notch_checks['front'].setChecked(True)
    dialog._notch_clearances['front'].setText('0')
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    path = tmp_path / 'full.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['version'] == '6' and data['geometry']['tube_joint']['target'] == 'miter'
    assert data['geometry']['notches'] == {'front': 0.}
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog._bend_editor.values()['front'] == bend and dialog._tube_joint.currentData() == 'miter'
    assert dialog._notch_values() == {'front': 0.}
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    point = controller.project.front.hardpoints['lbj']
    controller.move_point(point, (point.x + 1, point.y, point.z))
    assert dialog.snapshot is None and cad._view.mesh is None and not dialog._save.isEnabled()
    assert dialog.shutdown()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()

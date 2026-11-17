"""Ввод, актуальность и сохранение только новой копии задней трубы."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.kim_format import read_document
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.rear_tube_dialog import RearTubeDialog


def controller():
    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0., 0., 0.), 'll_out_l': (100., 100., 0.)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    c.dirty = False
    return c


def test_rear_editor_live_bend_and_new_copy(qtbot, tmp_path, monkeypatch):
    c = controller()
    before = c.project.to_dict()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    assert d._candidate is not None and d._save.isEnabled()
    d._bend.setChecked(True)
    assert d._candidate is None and all(plan.view is None for plan in d._plans) and not d._save.isEnabled()
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    assert d._candidate is not None and len(d._plans[0].path) > 3
    path = tmp_path / 'new.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_copy()
    saved = read_document(path, 'assembly')
    assert saved['arm'] == 'rear_lower_left' and saved['bend']['radius_mm'] == 20
    assert c.project.to_dict() == before and not c.dirty
    original = path.read_bytes()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._save_copy()
    assert warnings and path.read_bytes() == original
    d._fields[3].setText('1000')
    assert d._candidate is None and d._three_d._document is None and not d._save.isEnabled()
    d._fields[3].setText('20')
    p = c.project.rear.hardpoints['ll_out_l']
    c.move_point(p, (100, 10, 0))
    assert d._candidate is None and path.read_bytes() == original
    d._baseline, d._saved_candidate = d._input_state(), None
    assert d.shutdown()
    d.close()


def test_input_changed_during_save_even_without_signal(qtbot, tmp_path, monkeypatch):
    c = controller()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    target = tmp_path / 'no-write.kima'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    def choose(*args):
        with QSignalBlocker(d._fields[3]):
            d._fields[3].setText('25')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    d._save_copy()
    assert warnings and not target.exists() and d._candidate['bend']['radius_mm'] == 25
    c.set_axle_type('rear', 'multilink_rear')
    assert d._candidate is None and d._three_d._document is None and not d._save.isEnabled()
    d._baseline, d._saved_candidate = d._input_state(), None
    assert d.shutdown()
    d.close()


def test_close_confirmation_and_project_replacement(qtbot, monkeypatch):
    c = controller()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    assert d._edit_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d.close()
    assert d.isVisible() and not d._three_d._closed
    c.set_axle_type('rear', 'multilink_rear')
    assert d._candidate is None and d._edit_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d.close()
    assert not d.isVisible()

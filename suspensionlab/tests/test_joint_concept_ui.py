"""Qt-редактор отдельного условного узла и защита сохранённых файлов."""
from PySide6.QtCore import QSettings, QSignalBlocker
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
from suspensionlab.model.kim_format import read_document, write_document
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.joint_concept_dialog import JointConceptDialog
from suspensionlab.ui.main_window import MainWindow


def test_menu_live_sections_invalid_and_type_switch_with_confirmation(qtbot, tmp_path, monkeypatch):
    c = AppController()
    project = c.project.to_dict()
    w = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(w)
    w._confirm_discard_changes = lambda: True
    w.show()
    w.action_joint_concept.trigger()
    d = w._joint_concept_dialog
    assert d is not None and d._candidate['joint_type'] == 'ball'
    assert d._section.document == d._candidate and not d._section.grab().isNull()
    field = d._fields['ball']['pin_radius_mm']
    field.setText('8')
    assert d._candidate is None and d._section.document is None and not d._save.isEnabled()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._kind.setCurrentIndex(d._kind.findData('bushing'))
    assert d._kind.currentData() == 'ball' and field.text() == '8' and d._has_unsaved()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._kind.setCurrentIndex(d._kind.findData('bushing'))
    assert d._candidate['joint_type'] == 'bushing' and not d._has_unsaved()
    assert d._section.document == d._candidate and not d._section.grab().isNull()
    assert c.project.to_dict() == project and not c.dirty
    assert d.shutdown()
    d.close()
    assert w._joint_concept_dialog is None
    w.close()


def test_saved_joint_open_edit_protect_and_new_copy(qtbot, tmp_path, monkeypatch):
    c = AppController()
    src = tmp_path / 'source.kima'
    doc = make_joint_concept('ball', DEFAULTS['ball'], name='Мой условный узел')
    doc['parameters']['pin_length_mm'] = 45.12345678901234
    write_document(src, 'assembly', doc)
    original = src.read_bytes()
    d = JointConceptDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(src), ''))
    d._open_file()
    assert d._candidate == doc and not d._has_unsaved()
    d._fields['ball']['outer_radius_mm'].setText('23')
    assert d._has_unsaved() and d._candidate is not None
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(src), ''))
    d._save_copy()
    assert warnings and src.read_bytes() == original
    target = tmp_path / 'copy.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    saved = read_document(target, 'assembly')
    assert saved['name'] == doc['name'] and saved['parameters']['outer_radius_mm'] == 23
    assert saved['parameters']['pin_length_mm'] == doc['parameters']['pin_length_mm']
    assert not d._has_unsaved() and src.read_bytes() == original and not c.dirty
    assert d.shutdown()
    d.close()


def test_open_and_save_races_do_not_write_stale_or_discard_work(qtbot, tmp_path, monkeypatch):
    c = AppController()
    doc = make_joint_concept('bushing', DEFAULTS['bushing'])
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', doc)
    d = JointConceptDialog(c)
    qtbot.addWidget(d)
    d._fields['ball']['outer_radius_mm'].setText('25')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._open_file()
    assert d._source is None and d._fields['ball']['outer_radius_mm'].text() == '25'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    target = tmp_path / 'stale.kima'
    def choose(*args):
        with QSignalBlocker(d._fields['ball']['outer_radius_mm']):
            d._fields['ball']['outer_radius_mm'].setText('26')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    d._save_copy()
    assert warnings and not target.exists() and d._has_unsaved()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._open_file()
    assert d._candidate == doc and d._kind.currentData() == 'bushing' and not d._has_unsaved()
    assert d.shutdown()
    d.close()

"""Явная работа с копией KIMA без замены проекта или исходного файла."""
from copy import deepcopy

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.kim_format import read_document, write_document
from suspensionlab.model.welded_arm import make_welded_arm
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow
from suspensionlab.ui.weldment_dialog import WeldmentDialog


def open_document(dialog, path, monkeypatch):
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()


def test_menu_nonmodal_live_update_and_new_copy(qtbot, tmp_path, monkeypatch):
    c = AppController()
    source = tmp_path / 'source.kima'
    doc = make_welded_arm(c.project, 12, 2, 'required')
    doc['parts'][0]['name'] = 'Особое имя'
    write_document(source, 'assembly', doc)
    before_bytes = source.read_bytes()
    before_project = deepcopy(c.project.to_dict())
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    window.action_weldment.trigger()
    dialog = window._weldment_dialog
    assert dialog is not None and dialog.windowModality() == Qt.WindowModality.NonModal
    open_document(dialog, source, monkeypatch)
    assert dialog._tree.topLevelItemCount() == 1 and dialog._canvas.concept is None
    assert dialog._activate.isEnabled() and not dialog._save.isEnabled()
    dialog._start_preview()
    assert dialog._candidate is not None and 'совпадают' in dialog._status.text()
    assert not dialog._canvas.grab().isNull()
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x + 10, point.y, point.z))
    assert dialog._candidate is not None and 'отличаются' in dialog._status.text()
    assert dialog._canvas.concept.points[2][0] == before_project['front_axle']['hardpoints']['lbj']['x'] + 10
    target = tmp_path / 'copy'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    dialog._save_copy()
    copied = read_document(tmp_path / 'copy.kima', 'assembly')
    assert copied['parts'][0]['name'] == 'Особое имя'
    assert copied['parts'][0]['geometry']['source']['coordinates_mm'][2][0] == point.x
    assert source.read_bytes() == before_bytes and c.dirty
    dialog.close()
    assert window._weldment_dialog is None
    c.dirty = False


def test_invalid_type_points_and_project_replacement_clear_preview(qtbot, tmp_path, monkeypatch):
    c = AppController()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 12, 2, 'unknown'))
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    open_document(d, source, monkeypatch)
    d._start_preview()
    first = c.project.front.hardpoints['lca_f_in']
    original = first.as_tuple()
    c.move_point(first, c.project.front.hardpoints['lbj'].as_tuple())
    assert d._candidate is None and d._canvas.concept is None and not d._save.isEnabled()
    c.move_point(first, original)
    assert d._candidate is not None
    c.set_axle_type('front', 'macpherson_front')
    assert d._candidate is None and not d._save.isEnabled()
    c.new_project()
    assert d._candidate is None and not d._active and 'заменён' in d._status.text()
    d._start_preview()
    assert d._candidate is not None


def test_stale_and_failed_open_cannot_show_old_preview(qtbot, tmp_path, monkeypatch):
    c = AppController()
    doc = make_welded_arm(c.project, 12, 2, 'unknown')
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', doc)
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    open_document(d, source, monkeypatch)
    d._start_preview()
    doc['scheme']['front_axle']['hardpoints']['lbj']['y'] += 10
    stale = tmp_path / 'stale.kima'
    write_document(stale, 'assembly', doc)
    open_document(d, stale, monkeypatch)
    assert d._canvas.concept is None and not d._activate.isEnabled() and 'не соответствуют' in d._status.text()
    open_document(d, tmp_path / 'missing.kima', monkeypatch)
    assert d._source is None and d._canvas.concept is None and not d._activate.isEnabled()
    assert d._tree.topLevelItemCount() == 0


def test_save_rejects_existing_and_changes_during_dialog(qtbot, tmp_path, monkeypatch):
    c = AppController()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 12, 2, 'unknown'))
    old = source.read_bytes()
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    open_document(d, source, monkeypatch)
    d._start_preview()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(source), ''))
    d._save_copy()
    assert len(warnings) == 1 and source.read_bytes() == old
    target = tmp_path / 'copy.kima'
    def choose(*args):
        p = c.project.front.hardpoints['lbj']
        c.move_point(p, (p.x + 5, p.y, p.z))
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    d._save_copy()
    assert len(warnings) == 2 and not target.exists() and source.read_bytes() == old
    def choose_without_signal(*args):
        c.project.front.hardpoints['lbj'].y += 1
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose_without_signal)
    d._save_copy()
    assert len(warnings) == 3 and not target.exists() and source.read_bytes() == old


def test_source_path_remains_protected_if_external_file_disappears(qtbot, tmp_path, monkeypatch):
    c = AppController()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 12, 2, 'unknown'))
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    open_document(d, source, monkeypatch)
    d._start_preview()
    source.unlink()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(source), ''))
    d._save_copy()
    assert warnings and not source.exists()

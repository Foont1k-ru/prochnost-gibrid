"""Динамический условный эскиз не сохраняет CAD и не изменяет исходный проект."""
from PySide6.QtCore import QSettings, Qt

from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


def test_open_live_nonmodal_and_follow_scheme_undo_redo(qtbot, tmp_path):
    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    before = c.project.to_dict()
    window.action_arm_concept.trigger()
    dialog = window._arm_concept_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert dialog.concept is not None and dialog.concept.style == 'tube'
    assert not c.dirty and c.project.to_dict() == before
    # Reopening does not duplicate the live window.
    window.action_arm_concept.trigger()
    assert window._arm_concept_dialog is dialog
    point = c.project.front.hardpoints['lbj']
    initial = point.as_tuple()
    old = dialog.concept.points[2]
    c.move_point(point, (initial[0] + 20, initial[1], initial[2]))
    assert dialog.concept is not None and dialog.concept.points[2][0] == old[0] + 20
    c.undo_last()
    assert dialog.concept is not None and dialog.concept.points[2] == old
    c.redo_last()
    assert dialog.concept is not None and dialog.concept.points[2][0] == old[0] + 20
    # Exercise paintEvent in the offscreen Qt backend.
    assert not dialog._canvas.grab().isNull()
    dialog.close()
    assert window._arm_concept_dialog is None
    c.dirty = False


def test_variant_and_dimension_edits_never_change_project(qtbot):
    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    dialog.show()
    before = c.project.to_dict()
    assert dialog.concept is not None and dialog.concept.style == 'tube'
    dialog._radius.setValue(15.)
    dialog._wall.setValue(15.)
    assert dialog.concept is None and dialog._canvas.concept is None
    assert 'недоступен' in dialog._status.text()
    dialog._style.setCurrentIndex(1)
    assert dialog.concept is not None and dialog.concept.style == 'sheet'
    assert not dialog._radius.isEnabled() and dialog._sheet.isEnabled()
    dialog._sheet.setValue(4.)
    assert dialog.concept is not None and dialog.concept.sheet_mm == 4.
    assert not dialog._canvas.grab().isNull()
    assert not c.dirty and c.project.to_dict() == before


def test_invalid_points_or_suspension_clear_old_result_and_recover(qtbot):
    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    old = dialog.concept
    assert old is not None
    first = c.project.front.hardpoints['lca_f_in']
    outer = c.project.front.hardpoints['lbj']
    original = first.as_tuple()
    c.move_point(first, outer.as_tuple())
    assert dialog.concept is None and dialog._canvas.concept is None and not dialog._summary.text()
    c.move_point(first, original)
    assert dialog.concept is not None and dialog.concept.points == old.points
    c.set_axle_type('front', 'multilink_front')
    assert dialog.concept is None and dialog._canvas.concept is None
    c.new_project()
    assert dialog.concept is not None
    assert not c.dirty

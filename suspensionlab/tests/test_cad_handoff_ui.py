"""Переход в существующий CAD-редактор только с явным подтверждением."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

from suspensionlab.model.cad_handoff import ClearanceSettings, prepare_cad_handoff
from suspensionlab.ui.cad_handoff_dialog import CadHandoffDialog
from suspensionlab.ui.clearance_dialog import ClearanceDialog
from suspensionlab.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / 'handoff.ini'), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
    qtbot.addWidget(win)
    win.controller.new_project('ring')
    win._tabs.setCurrentWidget(win._kinematics)
    win._show_workspace()
    win.show()
    qtbot.waitUntil(lambda: win._kinematics.result is not None, timeout=10000)
    yield win
    win.controller.dirty = False
    # Tests close any populated skeleton explicitly.
    win.close()


def _perform_check(view, monkeypatch, selection=('lower_arm', 'tierod'), radius=5):
    def exec_dialog(dialog):
        dialog.refine.setChecked(False)
        for code in selection:
            check, spin = dialog.links[code]
            check.setChecked(True)
            spin.setValue(radius)
        dialog.run_check()
        assert dialog.last_setup is not None
        dialog.reject()
    monkeypatch.setattr(ClearanceDialog, 'exec', exec_dialog)
    view.clearance_button.click()


def test_handoff_into_existing_cad_skeleton_without_changing_project(window, qtbot, monkeypatch):
    view, controller = window._kinematics, window.controller
    before = deepcopy(controller.project)
    assert not view.cad_handoff_button.isEnabled()
    _perform_check(view, monkeypatch)
    assert view.cad_handoff_button.isEnabled()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (1., True))
    prompts = []
    def confirm(dialog):
        prompts.append(dialog.summary.toPlainText())
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CadHandoffDialog, 'exec', confirm)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    view.cad_handoff_button.click()
    dialog = window._fixed_arm_skeleton_dialog
    assert dialog is not None and dialog.snapshot is not None and dialog.preview is not None
    assert dialog._radius.value() == 5 and dialog._wall.value() == 1
    assert dialog._from.value() == view.start.value() and dialog._spacing.value() == view.spacing.value()
    assert dialog._tabs.currentIndex() == dialog._tabs.count() - 1
    assert 'не переносится' in dialog._file_status.text()
    assert controller.project == before
    assert any('исключённых' in text and 'не подтверждение безопасности' in text for text in prompts)
    assert dialog.confirm_close()  # explicit user confirmation to discard the draft
    dialog.reject()
    qtbot.waitUntil(lambda: window._fixed_arm_skeleton_dialog is None, timeout=10000)


def test_conflict_is_shown_and_requires_explicit_confirmation(window, monkeypatch):
    view = window._kinematics
    _perform_check(view, monkeypatch, ('lower_arm', 'tierod', 'spring_capsule'), radius=1000)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (1., True))
    prompts = []
    def decline(dialog):
        prompts.append(dialog.summary.toPlainText())
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(CadHandoffDialog, 'exec', decline)
    view.cad_handoff_button.click()
    assert prompts and 'наложение' in prompts[0] and 'требующих внимания' in prompts[0]
    assert 'Не проверено (первые до трёх)' in prompts[0]
    assert prompts[0].index('Требуют внимания (первые до трёх)') < prompts[0].index('Не проверено (первые до трёх)')
    assert window._fixed_arm_skeleton_dialog is None


def test_only_unknown_lower_pair_cannot_be_transferred(window, monkeypatch):
    view = window._kinematics
    _perform_check(view, monkeypatch, ('lower_arm', 'spring_capsule'))
    assert view.cad_handoff_button.isEnabled()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (1., True))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    view.cad_handoff_button.click()
    assert warnings and 'Ни одна выбранная пара' in warnings[0]
    assert window._fixed_arm_skeleton_dialog is None


def test_changed_settings_after_calculation_are_not_reused(window, monkeypatch):
    view = window._kinematics
    _perform_check(view, monkeypatch)
    assert view.cad_handoff_button.isEnabled()
    def changed(dialog):
        for code in ('lower_arm', 'tierod'):
            check, spin = dialog.links[code]
            check.setChecked(True)
            spin.setValue(5)
        dialog.run_check()
        assert dialog.last_setup is not None
        dialog.margin.setValue(3)
        assert dialog.last_setup is None
        dialog.reject()
    monkeypatch.setattr(ClearanceDialog, 'exec', changed)
    view.clearance_button.click()
    assert not view.cad_handoff_button.isEnabled() and view._clearance_settings is None


def test_unrepresentable_checked_radius_cannot_silently_round(window, monkeypatch):
    view = window._kinematics
    _perform_check(view, monkeypatch, radius=5.001)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    view.cad_handoff_button.click()
    assert warnings and 'двух знаков' in warnings[0]
    assert window._fixed_arm_skeleton_dialog is None


def test_needs_lower_arm_and_forgets_settings_after_change(window, qtbot, monkeypatch):
    view = window._kinematics
    _perform_check(view, monkeypatch, ('upper_arm', 'tierod'))
    assert not view.cad_handoff_button.isEnabled()
    _perform_check(view, monkeypatch)
    assert view.cad_handoff_button.isEnabled()
    view.end.setValue(20)
    assert not view.cad_handoff_button.isEnabled() and view._clearance_settings is None
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert not view.cad_handoff_button.isEnabled()
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert not view.cad_handoff_button.isEnabled()


def test_stale_during_wall_input_or_confirmation_never_emits(window, monkeypatch):
    view = window._kinematics
    _perform_check(view, monkeypatch)
    emitted, warnings = [], []
    view.cadHandoffRequested.connect(emitted.append)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    def changed_input(*args):
        view.start.setValue(-20)
        return 1., True
    monkeypatch.setattr(QInputDialog, 'getDouble', changed_input)
    view.cad_handoff_button.click()
    assert not emitted and any('изменились' in text for text in warnings)


def test_exact_unrounded_change_during_confirmation_is_rejected(window, monkeypatch):
    view, project = window._kinematics, window.controller.project
    _perform_check(view, monkeypatch)
    emitted, warnings = [], []
    view.cadHandoffRequested.connect(emitted.append)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (1., True))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    def mutate(dialog):
        project.front.hardpoints['spring_lo'].x += .00001
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CadHandoffDialog, 'exec', mutate)
    view.cad_handoff_button.click()
    assert not emitted and any('изменился' in text for text in warnings)
    assert window._fixed_arm_skeleton_dialog is None


def test_already_open_editor_is_never_replaced(window, qtbot, monkeypatch):
    settings = ClearanceSettings((('lower_arm', 5.), ('tierod', 5.)), 0, None, False, 5, .5)
    handoff = prepare_cad_handoff(window.controller.project, -10, 10, 10, settings, 1.)
    window._open_fixed_arm_skeleton()
    existing = window._fixed_arm_skeleton_dialog
    assert existing is not None
    existing._radius.setValue(18)
    before = existing._state()
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window._open_fixed_arm_handoff(handoff)
    assert window._fixed_arm_skeleton_dialog is existing and existing._state() == before
    assert messages and 'не заменены' in messages[0]
    existing.reject()
    qtbot.waitUntil(lambda: window._fixed_arm_skeleton_dialog is None, timeout=10000)

"""Modal callbacks cannot use or mutate a closed/deleted joint editor."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QSignalBlocker, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox
from shiboken6 import isValid

from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
from suspensionlab.model.kim_format import write_document
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


def open_window(qtbot, tmp_path, monkeypatch):
    window = MainWindow(AppController(), QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.show()
    window.action_joint_concept.trigger()
    dialog = window._joint_concept_dialog
    assert dialog is not None
    return window, dialog


def close_during_prompt(window, dialog, flush, parent=False):
    # Avoid recursively opening the discard prompt in this adversarial callback.
    dialog._closing_confirmed = True
    try:
        assert (window if parent else dialog).close()
    finally:
        dialog._closing_confirmed = False
    if flush:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('operation', ['open', 'save'])
@pytest.mark.parametrize('flush', [False, True])
@pytest.mark.parametrize('parent', [False, True])
def test_file_choice_after_shutdown_or_deletion_is_ignored(qtbot, tmp_path, monkeypatch, operation, flush, parent):
    window, dialog = open_window(qtbot, tmp_path, monkeypatch)
    source, target = tmp_path / 'input.kima', tmp_path / 'output.kima'
    write_document(source, 'assembly', make_joint_concept('bushing', DEFAULTS['bushing']))
    initial = dialog._candidate

    def select(*_args):
        close_during_prompt(window, dialog, flush, parent)
        return str(source if operation == 'open' else target), ''

    name = 'getOpenFileName' if operation == 'open' else 'getSaveFileName'
    monkeypatch.setattr(QFileDialog, name, select)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_args: pytest.fail('warning after window shutdown'))
    (dialog._open_file if operation == 'open' else dialog._save_copy)()
    assert dialog._candidate is initial and not target.exists()
    if not parent:
        assert window._joint_concept_dialog is None
        if flush:
            assert not isValid(dialog)
    else:
        assert dialog._three_d._closed and window._joint_concept_dialog is dialog
    window.close()


@pytest.mark.parametrize('operation', ['open', 'save'])
@pytest.mark.parametrize('flush', [False, True])
def test_close_during_nested_qt_file_dialog(qtbot, tmp_path, monkeypatch, operation, flush):
    window, dialog = open_window(qtbot, tmp_path, monkeypatch)
    source, target = tmp_path / 'input.kima', tmp_path / 'output.kima'
    write_document(source, 'assembly', make_joint_concept('bushing', DEFAULTS['bushing']))
    initial, observed = dialog._candidate, []

    def select(*_args):
        file_dialog = QFileDialog(dialog)
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)

        def close():
            observed.append((file_dialog.isVisible(), dialog.close()))
            if isValid(file_dialog):
                file_dialog.reject()

        QTimer.singleShot(50, close)
        file_dialog.exec()
        if flush:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        # Force a late selected result even though this test dialog was rejected.
        return str(source if operation == 'open' else target), ''

    name = 'getOpenFileName' if operation == 'open' else 'getSaveFileName'
    monkeypatch.setattr(QFileDialog, name, select)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_args: pytest.fail('warning after shutdown'))
    (dialog._open_file if operation == 'open' else dialog._save_copy)()
    assert observed == [(True, True)] and dialog._candidate is initial and not target.exists()
    if flush:
        assert not isValid(dialog)
    window.close()


@pytest.mark.parametrize('flush', [False, True])
def test_close_during_discard_confirmation_does_not_load(qtbot, tmp_path, monkeypatch, flush):
    window, dialog = open_window(qtbot, tmp_path, monkeypatch)
    source = tmp_path / 'input.kima'
    write_document(source, 'assembly', make_joint_concept('bushing', DEFAULTS['bushing']))
    dialog._fields['ball']['outer_radius_mm'].setText('23')
    initial = dialog._candidate
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_args: (str(source), ''))

    def confirm(*_args):
        close_during_prompt(window, dialog, flush)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, 'question', confirm)
    dialog._open_file()
    assert dialog._candidate is initial and window._joint_concept_dialog is None
    if flush:
        assert not isValid(dialog)
    window.close()


@pytest.mark.parametrize('flush', [False, True])
def test_close_during_kind_confirmation_does_not_continue(qtbot, tmp_path, monkeypatch, flush):
    window, dialog = open_window(qtbot, tmp_path, monkeypatch)
    dialog._fields['ball']['outer_radius_mm'].setText('23')
    initial = dialog._candidate
    # Simulate the slot independently, so deferred deletion doesn't occur in the
    # middle of the QComboBox's native signal emission.
    with QSignalBlocker(dialog._kind):
        dialog._kind.setCurrentIndex(dialog._kind.findData('bushing'))

    def confirm(*_args):
        close_during_prompt(window, dialog, flush)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, 'question', confirm)
    dialog._kind_changed()
    assert dialog._candidate is initial and dialog._last_kind == 'ball'
    if flush:
        assert not isValid(dialog)
    window.close()


@pytest.mark.parametrize('flush', [False, True])
def test_close_during_save_error_does_not_refresh_deleted_window(qtbot, tmp_path, monkeypatch, flush):
    window, dialog = open_window(qtbot, tmp_path, monkeypatch)
    target = tmp_path / 'existing.kima'
    target.write_text('unchanged', encoding='utf-8')
    initial = dialog._candidate
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_args: (str(target), ''))

    def warning(*_args):
        close_during_prompt(window, dialog, flush)

    monkeypatch.setattr(QMessageBox, 'warning', warning)
    dialog._save_copy()
    assert target.read_text(encoding='utf-8') == 'unchanged' and dialog._candidate is initial
    if flush:
        assert not isValid(dialog)
    window.close()

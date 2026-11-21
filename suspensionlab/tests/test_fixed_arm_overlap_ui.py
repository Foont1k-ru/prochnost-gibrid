"""Результат анализа применяется только к актуальному снимку."""
import pytest
from PySide6.QtWidgets import QMessageBox

from suspensionlab.core.cad_fixed_arm_overlap_job import OverlapResult
from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def test_actual_overlap_and_invalidation(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    dialog._tabs.setCurrentIndex(4)
    view = dialog._overlap
    view._start()
    qtbot.waitUntil(lambda: view._worker is None, timeout=30000)
    assert 'Обнаружено объёмное пересечение' in view._status.text()
    assert 'не проверка касания' in view._status.text()
    old_token = view.generation
    dialog._radius.setValue(dialog._radius.value() + 1)
    assert 'не запускалась' in view._status.text()
    view._completed(old_token, OverlapResult(123, 1e-5))
    assert '123' not in view._status.text()
    token = view.generation
    controller.project.front.hardpoints['lbj'].x += 1
    view._completed(token, OverlapResult(123, 1e-5))
    assert 'устарел' in view._status.text() and '123' not in view._status.text()
    dialog._refresh()
    assert not view._button.isEnabled()
    assert dialog.shutdown()
    dialog.close()


def test_edit_during_check_discards_result_and_shutdown(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._capture_snapshot()
    view = dialog._overlap
    view._start()
    assert view._worker is not None
    dialog._radius.setValue(dialog._radius.value() + 1)
    qtbot.waitUntil(lambda: view._worker is None, timeout=30000)
    assert 'не запускалась' in view._status.text() and view._button.isEnabled()
    view._start()
    assert dialog.shutdown()
    assert not view._button.isEnabled()
    dialog.close()


def test_result_below_threshold_is_not_a_clearance_claim(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    view = dialog._overlap
    view._completed(view.generation, OverlapResult(0, 1e-6))
    assert 'не обнаружено' in view._status.text()
    assert 'не проверка касания, минимального зазора' in view._status.text()
    assert dialog.shutdown()
    dialog.close()

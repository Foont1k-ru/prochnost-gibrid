"""Диалог не выдаёт старые или неполные результаты за проверку."""
import pytest

from suspensionlab.ui.clearance_dialog import ClearanceDialog
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.kinematics_workspace import KinematicsWorkspace


def test_clearance_dialog_requires_explicit_radii_and_invalidates(qtbot, monkeypatch):
    controller = AppController()
    controller.new_project('ring')
    view = KinematicsWorkspace(controller)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert view.clearance_button.isEnabled()
    original = controller.project.to_dict()

    def interact(dialog):
        assert dialog is view._clearance_dialog
        assert dialog is not None
        dialog.run_check()
        assert 'Не рассчитано' in dialog.output.toPlainText()
        for code in ('lower_arm', 'tierod'):
            check, radius = dialog.links[code]
            check.setChecked(True)
            radius.setValue(5)
        dialog.run_check()
        text = dialog.output.toPlainText()
        assert 'зазор' in text and 'Невыбранные формы не проверены' in text
        assert 'Между точками сетки' in text and 'реальные детали не проверены' in text
        assert 'Уточнение: исходных поз' in text and '[дополнительная поза]' in text
        assert 'узкий контакт между позами может быть пропущен' in text
        dialog.alert_band.setValue(8)
        assert 'Не рассчитано' in dialog.output.toPlainText()
        dialog.refine.setChecked(False)
        assert not dialog.alert_band.isEnabled()
        dialog.run_check()
        assert 'уточнение отключено' in dialog.output.toPlainText()
        dialog.refine.setChecked(True)
        assert 'Не рассчитано' in dialog.output.toPlainText()
        dialog.margin.setValue(2)
        assert 'Не рассчитано' in dialog.output.toPlainText()
        dialog.run_check()
        assert 'зазор' in dialog.output.toPlainText()
        view.start.setValue(-20)
        assert not dialog.run_button.isEnabled()
        assert 'устарел' in dialog.output.toPlainText()
        dialog.margin.setValue(3)
        assert 'устарел' in dialog.output.toPlainText()
        dialog.run_check()
        assert 'устарел' in dialog.output.toPlainText()
        dialog.reject()

    monkeypatch.setattr(ClearanceDialog, "exec", interact)
    view.clearance_button.click()
    assert controller.project.to_dict() == original
    assert view.result is None and not view.clearance_button.isEnabled()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert view.clearance_button.isEnabled()


def test_rear_dialog_available_for_five_links(workspace_for_clearance, qtbot, monkeypatch):
    view = workspace_for_clearance
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    def interact(dialog):
        assert dialog is view._clearance_dialog
        assert dialog is not None and len(dialog.links) == 10
        for code in ('upper_front', 'toe_link'):
            check, radius = dialog.links[code]
            check.setChecked(True)
            radius.setValue(4)
        dialog.run_check()
        assert 'зазор' in dialog.output.toPlainText()
        wheel_check, wheel_radius = dialog.links['wheel_cylinder']
        wheel_check.setChecked(True)
        wheel_radius.setValue(300)
        dialog.run_check()
        assert 'ширину цилиндра' in dialog.output.toPlainText()
        dialog.wheel_width.setValue(200)
        dialog.run_check()
        assert 'Ширина цилиндра колеса: 200' in dialog.output.toPlainText()
        assert 'Отрицательный зазор с цилиндром' in dialog.output.toPlainText()
        dialog.wheel_width.setValue(210)
        assert 'Не рассчитано' in dialog.output.toPlainText()
        view.role.setCurrentIndex(0)
        assert 'устарел' in dialog.output.toPlainText()
        assert not dialog.run_button.isEnabled()
        dialog.reject()
    monkeypatch.setattr(ClearanceDialog, "exec", interact)
    view.clearance_button.click()


@pytest.fixture
def workspace_for_clearance(qtbot):
    controller = AppController()
    controller.new_project('ring')
    view = KinematicsWorkspace(controller)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    return view

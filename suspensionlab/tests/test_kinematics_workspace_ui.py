"""Рабочий сценарий: выбор, ввод, пересчёт, отмена и отсутствие ложного результата."""
import pytest

from suspensionlab.ui.controller import AppController, Selection
from suspensionlab.ui.kinematics_workspace import KinematicsWorkspace


def test_scheme_choice_describes_solver_support(qtbot):
    from suspensionlab.ui.dialogs import TemplateDialog

    dialog = TemplateDialog()
    qtbot.addWidget(dialog)
    assert 'не реализован' in dialog._kinematics_hint.text()
    dialog._front.setCurrentIndex(dialog._front.findData('double_wishbone'))
    assert 'доступен экспериментальный расчёт' in dialog._kinematics_hint.text()
    assert 'Задняя ось' in dialog._kinematics_hint.text()
    dialog._list.setCurrentRow(2)
    assert 'только для передней двухрычажной' in dialog._description.text()
    dialog.close()


@pytest.fixture
def workspace(qtbot):
    controller = AppController()
    controller.new_project('ring')
    view = KinematicsWorkspace(controller)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    return controller, view


def test_part_fields_edit_recalculate_undo_and_camera(workspace, qtbot):
    controller, view = workspace
    assert view.part.currentData() == ('link', 'lower_arm')
    assert {k[0] for k in view._rows} == {'lca_f_in', 'lca_r_in', 'lbj'}
    point = controller.project.front.hardpoints['lbj']
    old = point.z
    field = view._rows[('lbj', 'z')]
    field.set_value(old + 5, emit=True)
    assert point.z == old + 5 and view.result is None and not view.travel.isEnabled()
    assert 'ожидает' in view.status.text()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert view.preview.frame is not None and 'Решено положений' in view.status.text()
    controller.undo_last()
    assert point.z == old and view.result is None
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    before = controller.project.to_dict()
    view.preview.set_standard_view('top')
    assert controller.project.to_dict() == before
    controller.select(Selection('link', 'front', 'upper_arm'))
    assert view.part.currentData() == ('link', 'upper_arm')
    assert {k[0] for k in view._rows} == {'uca_f_in', 'uca_r_in', 'ubj'}


def test_length_respects_point_and_coordinate_locks(workspace, qtbot):
    controller, view = workspace
    point = controller.project.front.hardpoints['lbj']
    original = point.as_tuple()
    controller.set_lock('front.point.lbj.y', True)
    view._change_length('lower_arm', 500)
    assert point.as_tuple() == original
    assert 'зафиксирована' in view.sample.text()
    controller.set_lock('front.point.lbj.y', False)
    view._change_length('lower_arm', 500)
    assert controller.project.front.link_length('lower_arm') == pytest.approx(500)
    controller.undo_last()
    assert point.as_tuple() == pytest.approx(original)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)


def test_explicit_right_side_negative_coordinate_fits_slider(workspace, qtbot):
    controller, view = workspace
    controller.new_project('live_axle')
    view.role.setCurrentIndex(1)
    view.part.setCurrentIndex(view._part_index(('all', '')))
    negative = next((key, field) for key, field in view._rows.items()
                    if key[1] == 'y' and controller.project.rear.hardpoints[key[0]].y < 0)
    (code, _), field = negative
    value = controller.project.rear.hardpoints[code].y
    assert field._slider.value() == round(value / field._step)
    controller.move_points({('rear', code): (controller.project.rear.hardpoints[code].x, -2000,
                                           controller.project.rear.hardpoints[code].z)})
    assert field._slider.value() == round(-2000 / field._step)
    qtbot.waitUntil(lambda: 'не реализован' in view.status.text(), timeout=10000)


def test_pick_and_stale_click_cannot_select_new_revision(workspace, qtbot):
    controller, view = workspace
    token = view._revision
    view._apply_hit('upper_arm', token)
    assert view.part.currentData() == ('link', 'upper_arm')
    assert controller.selection == Selection('link', 'front', 'upper_arm')
    view.start.setValue(-40)
    view._apply_hit('lower_arm', token)
    assert view.part.currentData() == ('link', 'upper_arm')
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)


def test_partial_sweep_shows_failure_not_a_previous_pose(workspace, monkeypatch, qtbot):
    from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError

    initial = DoubleWishbone._step
    def fail(self, pose, travel):
        if travel > 11:
            raise KinematicsError(travel, 'тестовый отказ')
        return initial(self, pose, travel)
    monkeypatch.setattr(DoubleWishbone, '_step', fail)
    _, view = workspace
    view.end.setValue(40)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert 'Пример отказа' in view.status.text()
    view.travel.setValue(view.travel.maximum())
    assert view.preview.frame is None and 'нет решения' in view.sample.text()
    view.travel.setValue(0)
    assert view.preview.frame is not None


def test_save_and_reopen_preserves_coordinates(workspace, qtbot, tmp_path):
    controller, view = workspace
    view._change_point('lbj', 'z', 154.25)
    path = controller.save_project(tmp_path / 'example')
    view._change_point('lbj', 'z', 170)
    controller.open_project(path)
    assert controller.project.front.hardpoints['lbj'].z == pytest.approx(154.25)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert view._rows[('lbj', 'z')]._value == pytest.approx(154.25)


def test_unexpected_solver_error_has_no_previous_results(workspace, monkeypatch):
    from suspensionlab.ui import kinematics_workspace

    _, view = workspace
    monkeypatch.setattr(kinematics_workspace, 'calculate', lambda *a: (_ for _ in ()).throw(RuntimeError('oops')))
    view._invalidate()
    view._timer.stop()
    view._calculate()
    assert view.result is None and not view.travel.isEnabled()
    assert 'не выполнен' in view.status.text() and 'ошибки' in view.status.text()


def test_unsupported_and_invalid_geometry_do_not_claim_success(workspace, qtbot):
    controller, view = workspace
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: 'не реализован' in view.status.text(), timeout=10000)
    assert view.result is None and not view.travel.isEnabled() and view.preview.frame is not None
    view.role.setCurrentIndex(0)
    axle = controller.project.front
    a, b = axle.hardpoints['lca_f_in'], axle.hardpoints['lca_r_in']
    controller.move_points({('front', 'lca_r_in'): a.as_tuple()})
    qtbot.waitUntil(lambda: 'Расчёт не выполнен' in view.status.text(), timeout=10000)
    assert view.result is None and not view.travel.isEnabled()
    assert view.preview.frame is not None and b.as_tuple() == a.as_tuple()

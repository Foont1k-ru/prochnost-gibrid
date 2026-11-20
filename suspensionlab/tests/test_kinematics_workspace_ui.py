"""Рабочий сценарий: выбор, ввод, пересчёт, отмена и отсутствие ложного результата."""
import pytest

from suspensionlab.ui.controller import AppController, Selection
from suspensionlab.ui.kinematics_workspace import KinematicsWorkspace


def test_main_window_compact_layout_does_not_overlap(qtbot, tmp_path):
    from PySide6.QtCore import QSettings

    from suspensionlab.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.controller.new_project('ring')
    window._tabs.setCurrentWidget(window._kinematics)
    window._kinematics.role.setCurrentIndex(1)
    window._show_workspace()
    window.resize(1100, 700)
    window.show()
    view = window._kinematics
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    qtbot.waitUntil(lambda: view.preview.mapToGlobal(view.preview.rect().bottomLeft()).y() <
                    view.start.mapToGlobal(view.start.rect().topLeft()).y(), timeout=5000)
    assert {field._title.text() for field in view._rows.values()} == {'X', 'Y', 'Z'}
    window.controller.dirty = False
    window.close()


def test_scheme_choice_describes_solver_support(qtbot):
    from suspensionlab.ui.dialogs import TemplateDialog

    dialog = TemplateDialog()
    qtbot.addWidget(dialog)
    assert 'не реализован' in dialog._kinematics_hint.text()
    dialog._front.setCurrentIndex(dialog._front.findData('double_wishbone'))
    assert 'доступен экспериментальный расчёт' in dialog._kinematics_hint.text()
    assert 'задней пятирычажной' in dialog._kinematics_hint.text()
    dialog._rear.setCurrentIndex(dialog._rear.findData('torsion_beam_rear'))
    assert 'задней схемы расчёт хода пока не реализован' in dialog._kinematics_hint.text()
    dialog._list.setCurrentRow(2)
    assert 'задней пятирычажной' in dialog._description.text()
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


def test_rear_five_link_edit_changes_solution_and_failed_pose_is_hidden(workspace, qtbot, monkeypatch):
    from suspensionlab.core.double_wishbone import KinematicsError
    from suspensionlab.core.rear_five_link import RearFiveLink

    controller, view = workspace
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert 'пять тяг' in view.status.text() and view.travel.isEnabled()
    assert view.part.currentData() == ('link', 'upper_front')
    assert {key[0] for key in view._rows} == {'uf_in', 'uf_out'}
    assert len(view.preview.link_targets) == 5
    assert view.preview.frame.point('uf_out') is not None
    view.travel.setValue(view.travel.maximum())
    initial = view.preview.frame.point('uf_out')
    point = controller.project.rear.hardpoints['uf_out']
    original_z = point.z
    view._rows[('uf_out', 'z')].set_value(original_z + 5, emit=True)
    assert view.result is None and not view.travel.isEnabled()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    view.travel.setValue(view.travel.maximum())
    assert view.preview.frame.point('uf_out') != pytest.approx(initial)
    controller.undo_last()
    assert point.z == original_z
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    original = RearFiveLink._step
    def fail(self, pose, travel):
        if travel > 11:
            raise KinematicsError(travel, 'тестовый отказ')
        return original(self, pose, travel)
    monkeypatch.setattr(RearFiveLink, '_step', fail)
    view.end.setValue(40)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    view.travel.setValue(view.travel.maximum())
    assert view.preview.frame is None and 'нет решения' in view.sample.text()
    assert 'Пример отказа' in view.status.text()


def test_invalid_rear_geometry_clears_previous_result(workspace, qtbot):
    controller, view = workspace
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    axle = controller.project.rear
    controller.move_points({('rear', 'toe_out'): axle.hardpoints['toe_in'].as_tuple()})
    assert view.result is None and not view.travel.isEnabled()
    qtbot.waitUntil(lambda: 'Расчёт не выполнен' in view.status.text(), timeout=10000)
    assert view.result is None and not view.travel.isEnabled()
    assert 'совпадают' in view.status.text()
    controller.undo_last()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert 'пять тяг' in view.status.text()


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
    controller.new_project('live_axle')
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: 'не реализован' in view.status.text(), timeout=10000)
    assert view.result is None and not view.travel.isEnabled() and view.preview.frame is not None
    controller.new_project('ring')
    view.role.setCurrentIndex(0)
    axle = controller.project.front
    a, b = axle.hardpoints['lca_f_in'], axle.hardpoints['lca_r_in']
    controller.move_points({('front', 'lca_r_in'): a.as_tuple()})
    qtbot.waitUntil(lambda: 'Расчёт не выполнен' in view.status.text(), timeout=10000)
    assert view.result is None and not view.travel.isEnabled()
    assert view.preview.frame is not None and b.as_tuple() == a.as_tuple()


def test_element_setup_save_undo_scheme_change_and_recalculation(workspace, qtbot, tmp_path):
    controller, view = workspace
    view.part.setCurrentIndex(view._part_index(('group', 'spring')))
    assert 'Пружина: не проверено' in view.elements_sample.text()
    controls = view._element_controls
    controls['lower'].setCurrentIndex(controls['lower'].findData('lower_arm'))
    controls['upper'].setCurrentIndex(controls['upper'].findData('body'))
    controls['minimum_mm'].setValue(100)
    controls['maximum_mm'].setValue(500)
    assert view.result is None and 'ожидает' in view.summary.text()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert view.result.samples[0].spring.limits_complete
    assert 'Передняя:' in view.summary.text() and 'Задняя:' in view.summary.text()
    assert view.preview.frame.point('spring_lo') is not None
    path = controller.save_project(tmp_path / 'elements')
    controls['maximum_mm'].setValue(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert 'больше заданного максимума' in view.elements_sample.text() or 'минимум должен быть' in view.elements_sample.text()
    controller.undo_last()
    assert controller.project.front.kinematic_elements.spring.maximum_mm == 500
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    controller.set_axle_type('front', 'macpherson_front')
    assert controller.project.front.kinematic_elements is None
    qtbot.waitUntil(lambda: 'не реализован' in view.status.text(), timeout=10000)
    controller.undo_last()
    assert controller.project.front.kinematic_elements.spring.lower == 'lower_arm'
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    controller.open_project(path)
    assert controller.project.front.kinematic_elements.spring.maximum_mm == 500
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert 'Пружина:' in view.elements_sample.text()
    view.role.setCurrentIndex(1)
    view.part.setCurrentIndex(view._part_index(('group', 'damper')))
    assert view._element_controls['lower'].findData('lower_arm') == -1
    assert controller.project.rear.kinematic_elements is None


def test_summary_counts_failures_and_does_not_claim_limits_checked(workspace, monkeypatch, qtbot):
    from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError

    original = DoubleWishbone._step
    def fail(self, pose, travel):
        if travel > 11:
            raise KinematicsError(travel, 'тестовый отказ')
        return original(self, pose, travel)
    monkeypatch.setattr(DoubleWishbone, '_step', fail)
    _, view = workspace
    view.end.setValue(40)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    front_summary = view.summary.text().splitlines()[1]
    assert 'отказов 3' in front_summary
    assert 'не полностью проверено' in front_summary
    view.travel.setValue(view.travel.maximum())
    assert 'не рассчитано' in view.elements_sample.text()
    assert view.result.samples[-1].spring is None

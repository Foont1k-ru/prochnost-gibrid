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


def test_workspace_suspension_choice_confirm_cancel_and_undo(workspace, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, view = workspace
    assert view.suspension_type.currentData() == controller.project.front.type_code == 'double_wishbone'
    assert 'экспериментальная кинематика' in view.support_hint.text()
    assert 'только статическая схема' in view.suspension_type.itemText(
        view.suspension_type.findData('macpherson_front'))
    original = controller.project.front.to_dict()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    index = view.suspension_type.findData('macpherson_front')
    view.suspension_type.setCurrentIndex(index)
    view._choose_suspension_type(index)
    assert controller.project.front.to_dict() == original
    assert view.suspension_type.currentData() == 'double_wishbone'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    view.suspension_type.setCurrentIndex(index)
    view._choose_suspension_type(index)
    assert controller.project.front.type_code == 'macpherson_front'
    assert 'не реализован' in view.support_hint.text()
    qtbot.waitUntil(lambda: 'не реализован' in view.status.text(), timeout=10000)
    assert view.result is None and not view.travel.isEnabled()
    controller.undo_last()
    assert controller.project.front.to_dict() == original
    assert view.suspension_type.currentData() == 'double_wishbone'
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    controller.redo_last()
    assert view.suspension_type.currentData() == 'macpherson_front'
    view.role.setCurrentIndex(1)
    assert view.suspension_type.currentData() == controller.project.rear.type_code
    assert view.suspension_type.findData('double_wishbone') == -1


def test_workspace_collapsible_points_and_summary_preserve_editing(workspace, qtbot):
    controller, view = workspace
    assert len(view.point_toggles) == 3
    first, second = list(view.point_toggles)[:2]
    assert view.point_toggles[first].isChecked() and not view.point_toggles[second].isChecked()
    field = view._rows[(second, 'z')]
    assert not field.isVisible()
    view.point_toggles[second].click()
    assert field.isVisible()
    point = controller.project.front.hardpoints[second]
    previous = point.z
    field.set_value(previous + 1, emit=True)
    assert point.z == previous + 1 and view.result is None
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert not view.summary_toggle.isChecked() and not view.summary.isVisible()
    view.summary_toggle.click()
    assert view.summary.isVisible() and 'Передняя' in view.summary.text()


def test_workspace_graph_tracks_samples_gaps_and_invalidation(workspace, qtbot, monkeypatch):
    from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError
    from suspensionlab.core.sweep_plot import plot_segments

    controller, view = workspace
    assert view.results_tabs.currentIndex() == 0
    assert len(view.plot.points) == len(view.result.samples)
    assert view.plot.row == view.travel.value()
    view.results_tabs.setCurrentIndex(1)
    assert view.plot_panel.isVisible()
    view.plot.rowSelected.emit(0)
    assert view.travel.value() == 0 and view.plot.row == 0
    original = DoubleWishbone._step
    def fail(self, pose, travel):
        if travel > 11:
            raise KinematicsError(travel, 'тестовый отказ')
        return original(self, pose, travel)
    monkeypatch.setattr(DoubleWishbone, '_step', fail)
    view.end.setValue(40)
    assert view.result is None and view.plot.points == ()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    failed = [i for i, sample in enumerate(view.result.samples) if sample.scene is None]
    assert failed and all(view.plot.points[i].values == (None,) * 5 for i in failed)
    assert all(i not in (a, b) for a, b in plot_segments(view.plot.points, 0, 5) for i in failed)
    view.plot.rowSelected.emit(failed[0])
    assert view.preview.frame is None and 'нет решения' in view.sample.text()
    controller.new_project('live_axle')
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: 'не реализован' in view.status.text(), timeout=10000)
    assert view.plot.points == () and view.result is None


def test_workspace_type_confirmation_does_not_change_replaced_project(workspace, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, view = workspace
    def replace_during_question(*args):
        controller.new_project('ring')
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', replace_during_question)
    index = view.suspension_type.findData('macpherson_front')
    view.suspension_type.setCurrentIndex(index)
    view._choose_suspension_type(index)
    assert controller.project.front.type_code == 'double_wishbone'
    assert view.suspension_type.currentData() == 'double_wishbone'


def test_workspace_web_style_navigation_does_not_change_project(workspace, qtbot):
    controller, view = workspace
    assert view.front_button.isChecked() and not view.rear_button.isChecked()
    before = controller.project.to_dict()
    view.front_button.click()
    assert view.front_button.isChecked() and not view.rear_button.isChecked()
    view.rear_button.click()
    assert view.role.currentData() == 'rear' and view.rear_button.isChecked() and not view.front_button.isChecked()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert view.preview.volumetric and view.volume_button.isChecked()
    view.volume_button.click()
    assert not view.preview.volumetric
    view.volume_button.click()
    assert view.preview.volumetric
    point = list(view.point_toggles)[1]
    view.point_toggles[point].click()
    assert view.preview.selected_point == point
    view.point_toggles[point].click()
    assert view.preview.selected_point is None
    assert controller.project.to_dict() == before


def test_new_window_hides_advanced_docks_but_keeps_actions_and_layout_access(qtbot, tmp_path):
    from PySide6.QtCore import QSettings

    from suspensionlab.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.show()
    assert all(not dock.isVisible() for dock in (window._tree_dock, window._inspector_dock, window._diagnostics_dock))
    menu_file = window.menuBar().actions()[0].menu()
    experiments = next(a.menu() for a in menu_file.actions() if a.menu() is not None and
                       window.action_fixed_arm_skeleton in a.menu().actions())
    assert window.action_cad_registration in experiments.actions()
    assert window.action_cad_preview in menu_file.actions()
    window._tree_dock.toggleViewAction().trigger()
    assert window._tree_dock.isVisible()
    window._save_settings()
    window.controller.dirty = False
    window.close()
    reopened = MainWindow(settings=settings)
    qtbot.addWidget(reopened)
    reopened.show()
    assert reopened._tree_dock.isVisible()
    reopened.controller.dirty = False
    reopened.close()


def test_sidebar_is_not_horizontally_clipped_on_compact_window(qtbot, tmp_path):
    from PySide6.QtCore import QSettings

    from suspensionlab.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.controller.new_project('ring')
    window._tabs.setCurrentWidget(window._kinematics)
    window._show_workspace()
    window.resize(1100, 700)
    window.show()
    view = window._kinematics
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    assert view.editor_scroll.horizontalScrollBar().maximum() == 0
    assert view.front_button.isVisible() and view.rear_button.isVisible()
    assert view.front_button.geometry().right() < view.rear_button.geometry().left()
    window.controller.dirty = False
    window.close()


@pytest.mark.parametrize('control_width', [78, 100])
def test_sidebar_expands_for_larger_platform_controls(workspace, qtbot, control_width):
    _, view = workspace
    view.resize(1200, 800)
    qtbot.waitUntil(lambda: view.editor_scroll.horizontalScrollBar().maximum() == 0)
    initial_width = view.editor_scroll.minimumWidth()
    # Simulate platform/theme controls wider than the offscreen Linux defaults.
    view.editor.setStyleSheet(f'QToolButton {{ min-width: {control_width}px; }}')
    qtbot.waitUntil(lambda: view.editor_scroll.minimumWidth() > initial_width, timeout=5000)
    qtbot.waitUntil(lambda: view.editor_scroll.horizontalScrollBar().maximum() == 0, timeout=5000)
    assert view._rows[('lca_f_in', 'x')]._edit.isVisible()
    view.part.setCurrentIndex(view._part_index(('group', 'spring')))
    qtbot.waitUntil(lambda: view.editor_scroll.horizontalScrollBar().maximum() == 0, timeout=5000)
    qtbot.waitUntil(lambda: view._element_controls['lower'].isVisible(), timeout=5000)
    view.part.setCurrentIndex(view._part_index(('link', 'lower_arm')))
    view.editor.setStyleSheet('')
    # The minimum width can change before QSplitter/QScrollArea have processed
    # their resize/layout events (especially in the complete Windows suite).
    # Wait for both conditions, then check again after a further event-loop turn;
    # a persistent clipped layout still fails rather than being hidden.
    qtbot.waitUntil(lambda: view.editor_scroll.minimumWidth() == initial_width and
                    view.editor_scroll.horizontalScrollBar().maximum() == 0, timeout=5000)
    qtbot.wait(100)
    assert view.editor_scroll.minimumWidth() == initial_width
    assert view.editor_scroll.horizontalScrollBar().maximum() == 0
    assert view._rows[('lca_f_in', 'x')]._edit.isVisible()


def test_shift_click_point_opens_original_coordinates_without_edit(workspace, qtbot):
    from PySide6.QtCore import QPointF, Qt

    from suspensionlab.core.scene3d import project_orthographic

    controller, view = workspace
    view.resize(1200, 800)
    qtbot.waitUntil(lambda: view.preview.width() > 300, timeout=5000)
    preview = view.preview
    view.travel.setValue(view.travel.maximum())
    frame = preview.frame
    center, radius = preview.bounds
    scale = max(1.0, min(preview.width() - 36, preview.height() - 70)) / (2 * radius) * preview.zoom
    candidates = []
    for code, point in frame.points:
        if code not in preview.editable_point_codes or code in view.point_toggles:
            continue
        x, y = project_orthographic(point, center, preview.yaw, preview.elevation)
        pos = QPointF(preview.width() / 2 + preview.pan_x + x * scale,
                      preview.height() / 2 + 8 + preview.pan_y - y * scale).toPoint()
        if preview._point_hits(QPointF(pos)) == (code,) and preview.rect().contains(pos):
            candidates.append((code, pos))
    assert candidates
    code, pos = candidates[0]
    original = controller.project.to_dict()
    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos)
    assert controller.project.to_dict() == original
    assert preview.selected_point == code
    assert view.point_toggles[code].isChecked()
    qtbot.waitUntil(lambda: view._rows[(code, 'x')].isVisible(), timeout=5000)
    assert view._rows[(code, 'x')].value() == pytest.approx(controller.project.front.hardpoints[code].x)


def test_point_pick_disambiguation_and_stale_frame(workspace, qtbot):
    from PySide6.QtCore import QPoint

    controller, view = workspace
    original = controller.project.to_dict()
    frame, revision = view.preview.frame, view._revision
    view._select_point_hits(('lca_f_in', 'ubj'), QPoint(20, 20))
    assert view._menu is not None
    actions = view._menu.actions()
    assert len(actions) == 2
    actions[1].trigger()
    assert view.preview.selected_point == 'ubj'
    view._menu.close()
    qtbot.waitUntil(lambda: view._menu is None, timeout=3000)
    assert controller.project.to_dict() == original
    view.travel.setValue(view.travel.maximum())
    view._apply_point_hit('lca_f_in', revision, frame)
    assert view.preview.selected_point == 'ubj'
    view.start.setValue(-40)
    view._apply_point_hit('lca_f_in', revision, view.preview.frame)
    assert view.preview.selected_point == 'ubj'
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)


def test_point_selection_tracks_rear_and_unsupported_static_scheme(workspace, qtbot):
    controller, view = workspace
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    frame = view.preview.frame
    revision = view._revision
    assert frame.point('toe_out') is not None
    view._apply_point_hit('toe_out', revision, frame)
    assert view.preview.selected_point == 'toe_out'
    assert view.point_toggles['toe_out'].isChecked()
    view.role.setCurrentIndex(0)
    view._apply_point_hit('toe_out', revision, frame)
    assert view.preview.selected_point != 'toe_out'
    controller.new_project('live_axle')
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: 'не реализован' in view.status.text(), timeout=10000)
    frame = view.preview.frame
    code = next(code for code, _ in frame.points if code in view.preview.editable_point_codes)
    view._apply_point_hit(code, view._revision, frame)
    assert view.preview.selected_point == code
    assert view.point_toggles[code].isChecked()


def _drag_selected_point(qtbot, view, delta, *, escape=False):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from suspensionlab.core.scene3d import project_orthographic

    preview = view.preview
    center, radius = preview.bounds
    scale = max(1.0, min(preview.width() - 36, preview.height() - 70)) / (2 * radius) * preview.zoom
    x, y = project_orthographic(preview.frame.point(preview.selected_point), center, preview.yaw, preview.elevation)
    pos = QPointF(preview.width() / 2 + preview.pan_x + x * scale,
                  preview.height() / 2 + 8 + preview.pan_y - y * scale)
    target = pos + QPointF(*delta)
    QApplication.sendEvent(preview, QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos,
                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert preview._point_drag is not None
    QApplication.sendEvent(preview, QMouseEvent(QMouseEvent.Type.MouseMove, target,
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    if escape:
        qtbot.keyClick(preview, Qt.Key.Key_Escape)
    QApplication.sendEvent(preview, QMouseEvent(QMouseEvent.Type.MouseButtonRelease, target,
                           Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    return scale


def test_drag_point_top_view_is_single_undo_and_recalculates(workspace, qtbot):
    controller, view = workspace
    view.point_toggles['lbj'].setChecked(True)
    view.travel.setValue(view.travel.maximum())
    view.drag_point_button.setChecked(True)
    assert view.drag_point_button.isChecked()
    assert view.preview.frame.travel_mm == 0
    assert view.preview.point_drag_enabled
    point = controller.project.front.hardpoints['lbj']
    old = point.as_tuple()
    scale = _drag_selected_point(qtbot, view, (30., -20.))
    assert point.as_tuple() == pytest.approx((old[0] + 30 / scale, old[1] + 20 / scale, old[2]))
    assert view.result is None
    controller.undo_last()
    assert point.as_tuple() == pytest.approx(old)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)


def test_drag_locks_cancel_escape_and_nonzero_pose(workspace, qtbot):
    controller, view = workspace
    view.point_toggles['lbj'].setChecked(True)
    view.drag_point_button.setChecked(True)
    point = controller.project.front.hardpoints['lbj']
    original = point.as_tuple()
    _drag_selected_point(qtbot, view, (30., 20.), escape=True)
    assert point.as_tuple() == original
    controller.set_lock('front.point.lbj.x', True)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    _drag_selected_point(qtbot, view, (30., 20.))
    assert point.as_tuple() == original
    assert 'зафиксирована' in view.sample.text()
    view.travel.setValue(view.travel.maximum())
    assert not view.drag_point_button.isChecked()
    assert not view.preview.point_drag_enabled


def test_drag_mode_requires_selection_and_turns_off_with_camera_change(workspace):
    _, view = workspace
    assert view.preview.selected_point is None
    view.drag_point_button.setChecked(True)
    assert not view.drag_point_button.isChecked()
    assert 'Сначала выберите' in view.sample.text()
    view.point_toggles['lbj'].setChecked(True)
    view.drag_point_button.setChecked(True)
    assert view.preview.point_drag_enabled
    view.camera.viewSelected.emit('front')
    assert not view.drag_point_button.isChecked()
    assert not view.preview.point_drag_enabled


def test_drag_rear_and_ignore_stale_frame(workspace, qtbot):
    controller, view = workspace
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    code = 'uf_out'
    view.point_toggles[code].setChecked(True)
    view.drag_point_button.setChecked(True)
    assert view.drag_point_button.isChecked()
    point = controller.project.rear.hardpoints[code]
    old = point.as_tuple()
    old_frame = view.preview.frame
    scale = _drag_selected_point(qtbot, view, (-18., 25.))
    assert point.as_tuple() == pytest.approx((old[0] - 18 / scale, old[1] - 25 / scale, old[2]))
    after = point.as_tuple()
    view._commit_point_drag(code, old_frame, 100., 100.)
    assert point.as_tuple() == after
    controller.undo_last()
    assert point.as_tuple() == pytest.approx(old)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)


def test_drag_is_cancelled_when_geometry_or_frame_changes(workspace, qtbot):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from suspensionlab.core.scene3d import project_orthographic

    controller, view = workspace
    view.point_toggles['lbj'].setChecked(True)
    view.drag_point_button.setChecked(True)
    preview = view.preview
    center, radius = preview.bounds
    scale = max(1., min(preview.width() - 36, preview.height() - 70)) / (2 * radius) * preview.zoom
    x, y = project_orthographic(preview.frame.point('lbj'), center, preview.yaw, preview.elevation)
    pos = QPointF(preview.width() / 2 + preview.pan_x + x * scale,
                  preview.height() / 2 + 8 + preview.pan_y - y * scale)
    QApplication.sendEvent(preview, QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos,
                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert preview._point_drag is not None
    point = controller.project.front.hardpoints['lbj']
    old = point.as_tuple()
    view._change_point('lbj', 'z', old[2] + 2.)
    assert preview._point_drag is None
    target = pos + QPointF(50., 50.)
    QApplication.sendEvent(preview, QMouseEvent(QMouseEvent.Type.MouseButtonRelease, target,
                           Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert point.as_tuple() == pytest.approx((old[0], old[1], old[2] + 2.))
    controller.undo_last()
    assert point.as_tuple() == pytest.approx(old)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)


def _example_rocker(axle, code='lbj', mount='upright'):
    from suspensionlab.model.kinematic_elements import RockerSetup

    bx, by, bz = axle.hardpoints[code].as_tuple()
    x, y, z = bx + 30., by - 20., bz + 10.
    return RockerSetup(True, mount, (x + 100, y + 20, z + 100), (1, 0, 0),
                       (x + 100, y + 70, z + 100), (x, y, z),
                       (x + 100, y + 20, z + 130), (x + 100, y + 100, z + 160))


def test_rocker_dialog_requires_explicit_valid_geometry_and_keeps_disabled_setup(qtbot):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.model.templates import load_template
    from suspensionlab.ui.rocker_setup_dialog import RockerSetupDialog

    setup = _example_rocker(load_template('ring').front)
    dialog = RockerSetupDialog('double_wishbone', None)
    qtbot.addWidget(dialog)
    dialog.show()
    assert all(not edit.text() for edit in dialog.inputs.values())
    dialog.mode.setCurrentIndex(1)
    dialog._apply()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error.text()
    dialog.mount.setCurrentIndex(dialog.mount.findData('upright'))
    for (name, axis), edit in dialog.inputs.items():
        edit.setText(str(getattr(setup, name)[axis]).replace('.', ','))
    dialog.inputs[('axis', 0)].setText('0')
    dialog._apply()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.inputs[('axis', 0)].setText('1')
    dialog._apply()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.result_setup == setup
    direct = RockerSetupDialog('double_wishbone', setup)
    qtbot.addWidget(direct)
    direct.mode.setCurrentIndex(0)
    direct._apply()
    assert direct.result_setup == __import__('dataclasses').replace(setup, enabled=False)
    rear = RockerSetupDialog('multilink_rear', None)
    qtbot.addWidget(rear)
    assert rear.mount.findData('lower_arm') == -1
    rear.close()


def test_rocker_workspace_save_undo_direct_and_plot(workspace, qtbot, monkeypatch, tmp_path):
    from dataclasses import replace

    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui import kinematics_workspace

    controller, view = workspace
    view.part.setCurrentIndex(view._part_index(('group', 'damper')))
    setup = _example_rocker(controller.project.front, mount='lower_arm')
    result = [setup]
    class Dialog:
        def __init__(self, type_code, initial, parent):
            self.result_setup = result[0]
        def exec(self):
            return QDialog.DialogCode.Accepted
        def deleteLater(self):  # noqa: N802
            pass
    monkeypatch.setattr(kinematics_workspace, 'RockerSetupDialog', Dialog)
    view._edit_rocker()
    assert controller.project.front.kinematic_elements.rocker == setup
    assert not view._element_controls['lower'].isEnabled()
    assert all(toggle.parentWidget().isHidden() for toggle in view.point_toggles.values())
    assert view.result is None
    qtbot.waitUntil(lambda: view.result is not None, timeout=15000)
    zero = view.result.samples[view.travel.value()]
    assert zero.rocker is not None and zero.rocker.pose is not None
    assert zero.damper.length_mm == pytest.approx(zero.rocker.pose.damper_length_mm)
    assert 'Коромысло' in view.elements_sample.text()
    assert any(seg.kind == 'rocker' for seg in view.preview.frame.segments)
    view.plot_metric.setCurrentIndex(view.plot_metric.findData('rocker_ratio'))
    assert view.plot.points[view.travel.value()].values[-1] is not None
    path = controller.save_project(tmp_path / 'with-rocker')
    controller.undo_last()
    assert controller.project.front.kinematic_elements is None
    controller.redo_last()
    assert controller.project.front.kinematic_elements.rocker == setup
    controller.open_project(path)
    assert controller.project.front.kinematic_elements.rocker == setup
    qtbot.waitUntil(lambda: view.result is not None, timeout=15000)
    view.part.setCurrentIndex(view._part_index(('group', 'damper')))
    result[0] = replace(setup, enabled=False)
    view._edit_rocker()
    assert not controller.project.front.kinematic_elements.rocker.enabled
    assert view._element_controls['lower'].isEnabled()
    assert all(not toggle.parentWidget().isHidden() for toggle in view.point_toggles.values())
    qtbot.waitUntil(lambda: view.result is not None, timeout=15000)
    assert all(s.rocker is None for s in view.result.samples)


def test_rocker_dialog_does_not_apply_to_changed_project(workspace, monkeypatch, qtbot):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui import kinematics_workspace

    controller, view = workspace
    view.part.setCurrentIndex(view._part_index(('group', 'damper')))
    setup = _example_rocker(controller.project.front)
    class StaleDialog:
        def __init__(self, type_code, initial, parent):
            self.result_setup = setup
        def exec(self):
            view.role.setCurrentIndex(1)
            return QDialog.DialogCode.Accepted
        def deleteLater(self):  # noqa: N802
            pass
    monkeypatch.setattr(kinematics_workspace, 'RockerSetupDialog', StaleDialog)
    view._edit_rocker()
    assert controller.project.front.kinematic_elements is None
    assert controller.project.rear.kinematic_elements is None
    assert 'не применены' in view.sample.text()
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)


def test_rear_rocker_real_dialog_drives_calculation(workspace, qtbot):
    from PySide6.QtCore import QTimer

    from suspensionlab.ui.rocker_setup_dialog import RockerSetupDialog

    controller, view = workspace
    view.role.setCurrentIndex(1)
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    view.part.setCurrentIndex(view._part_index(('group', 'damper')))
    setup = _example_rocker(controller.project.rear, code='uf_out')
    def populate():
        dialog = view.findChild(RockerSetupDialog)
        assert dialog is not None
        dialog.mode.setCurrentIndex(1)
        dialog.mount.setCurrentIndex(dialog.mount.findData('upright'))
        for (name, axis), edit in dialog.inputs.items():
            edit.setText(str(getattr(setup, name)[axis]))
        dialog._apply()
    QTimer.singleShot(0, populate)
    view._edit_rocker()
    assert controller.project.rear.kinematic_elements.rocker == setup
    qtbot.waitUntil(lambda: view.result is not None, timeout=15000)
    assert view.result.samples[view.travel.value()].rocker.pose is not None
    assert 'Коромысло:' in view.elements_sample.text()
    assert not view._element_controls['upper'].isEnabled()
    assert controller.project.front.kinematic_elements is None

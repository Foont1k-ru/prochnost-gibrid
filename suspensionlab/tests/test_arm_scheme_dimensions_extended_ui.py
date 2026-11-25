"""Покрытие пользовательского ввода проекционных размеров."""
import pytest
from PySide6.QtCore import QSettings, Qt

from suspensionlab.model.arm_scheme_dimensions import arm_dimensions
from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


@pytest.mark.parametrize(('arm', 'codes'), [
    ('lower', ('lca_f_in', 'lca_r_in', 'lbj')),
    ('upper', ('uca_f_in', 'uca_r_in', 'ubj')),
])
@pytest.mark.parametrize(('key', 'moving', 'axis'), [('span_x', 1, 0), ('ball_x', 2, 0), ('ball_y', 2, 1)])
def test_each_dimension_changes_only_its_coordinate(qtbot, arm, codes, key, moving, axis):
    from suspensionlab.ui.canvas.axle_view import AxleCanvas

    controller = AppController()
    controller.project = load_template('ring')
    canvas = AxleCanvas(controller)
    qtbot.addWidget(canvas)
    canvas.resize(1100, 700)
    canvas.show()
    panel = canvas._arm_dimensions
    qtbot.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
    panel.arm.setCurrentIndex(panel.arm.findData(arm))
    axle = controller.project.front
    before = [axle.hardpoints[code].as_tuple() for code in codes]
    value = arm_dimensions(axle, arm)[key] + 10
    panel.fields[key].setValue(value)
    qtbot.mouseClick(panel.buttons[key], Qt.MouseButton.LeftButton)
    after = [axle.hardpoints[code].as_tuple() for code in codes]
    for i in range(3):
        for j in range(3):
            if (i, j) != (moving, axis):
                assert after[i][j] == before[i][j]
    assert abs(after[moving][axis] - after[0][axis]) == pytest.approx(value)
    controller.undo.undo()
    assert [axle.hardpoints[code].as_tuple() for code in codes] == before
    controller.undo.redo()
    assert [axle.hardpoints[code].as_tuple() for code in codes] == after


def test_dimensions_available_in_main_front_canvas_and_closed_on_view_change(qtbot, tmp_path):
    controller = AppController()
    controller.project = load_template('ring')
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window._show_workspace()
    window.show()
    canvas = window._canvases['front']
    window._tabs.setCurrentWidget(canvas)
    panel = canvas._arm_dimensions
    assert panel.toggle.isVisible()
    qtbot.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
    assert canvas.view_mode() == 'top'
    canvas.grab()
    assert set(canvas._dimension_hits) == {'span_x', 'ball_x', 'ball_y'}
    canvas.set_view_mode('side')
    assert not panel.toggle.isChecked() and not panel.body.isVisible() and not canvas._dimension_hits
    assert window.close()


def test_enter_in_dimension_input_applies_change(qtbot):
    from suspensionlab.ui.canvas.axle_view import AxleCanvas

    controller = AppController()
    controller.project = load_template('ring')
    canvas = AxleCanvas(controller)
    qtbot.addWidget(canvas)
    canvas.resize(1100, 700)
    canvas.show()
    panel = canvas._arm_dimensions
    qtbot.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
    field = panel.fields['ball_y']
    before = arm_dimensions(controller.project.front, 'lower')['ball_y']
    field.lineEdit().setFocus()
    field.lineEdit().selectAll()
    qtbot.keyClicks(field.lineEdit(), str(before + 25))
    qtbot.keyClick(field.lineEdit(), Qt.Key.Key_Return)
    assert arm_dimensions(controller.project.front, 'lower')['ball_y'] == pytest.approx(before + 25)


def test_longitudinal_position_uses_chosen_fixed_reference(qtbot):
    from suspensionlab.ui.canvas.axle_view import AxleCanvas

    controller = AppController()
    controller.project = load_template('ring')
    canvas = AxleCanvas(controller)
    qtbot.addWidget(canvas)
    canvas.show()
    panel = canvas._arm_dimensions
    qtbot.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
    axle = controller.project.front
    codes = ('lca_f_in', 'lca_r_in', 'lbj')
    assert all(panel.reference.findData(code) == -1 for code in codes)
    reference_index = panel.reference.findData('uca_f_in')
    assert reference_index > 0
    panel.reference.setCurrentIndex(reference_index)
    reference = axle.hardpoints['uca_f_in'].as_tuple()
    before = [axle.hardpoints[code].as_tuple() for code in codes]
    assert panel.fields['position_x'].value() == pytest.approx(before[0][0] - reference[0], abs=0.001)
    panel.fields['position_x'].setValue(before[0][0] - reference[0] + 30)
    qtbot.mouseClick(panel.buttons['position_x'], Qt.MouseButton.LeftButton)
    assert axle.hardpoints['uca_f_in'].as_tuple() == reference
    assert [axle.hardpoints[c].x for c in codes] == pytest.approx([p[0] + 30 for p in before])
    panel.arm.setCurrentIndex(panel.arm.findData('upper'))
    assert panel.reference.currentData() is None

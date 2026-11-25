"""Размеры на основной схеме — правки координат через историю проекта."""
import pytest
from PySide6.QtCore import Qt

from suspensionlab.model.arm_scheme_dimensions import arm_dimensions, dimension_edits
from suspensionlab.model.templates import load_template
from suspensionlab.ui.canvas.axle_view import AxleCanvas
from suspensionlab.ui.controller import AppController


def test_plan_dimensions_and_atomic_translation():
    axle = load_template('ring').front
    codes = ('lca_f_in', 'lca_r_in', 'lbj')
    old = [axle.hardpoints[code].as_tuple() for code in codes]
    values = arm_dimensions(axle, 'lower')
    edits = dimension_edits(axle, 'lower', 'span_x', values['span_x'] + 20)
    assert list(edits) == [('front', 'lca_r_in')]
    assert edits[('front', 'lca_r_in')][0] == old[0][0] + (old[1][0] - old[0][0]) / abs(old[1][0] - old[0][0]) * (values['span_x'] + 20)
    for key, index in [('ball_x', 0), ('ball_y', 1)]:
        changed = dimension_edits(axle, 'lower', key, values[key] + 10)[('front', 'lbj')]
        assert abs(changed[index] - old[0][index]) == pytest.approx(values[key] + 10)
        assert changed[2] == old[2][2]
    edits = dimension_edits(axle, 'lower', 'position_x', old[0][0] + 35)
    assert len(edits) == 3
    for code, before in zip(codes, old, strict=True):
        assert edits[('front', code)] == (before[0] + 35, before[1], before[2])
    axle.hardpoints['lbj'].x = old[0][0]
    with pytest.raises(ValueError, match='Направление'):
        dimension_edits(axle, 'lower', 'ball_x', 10)


def test_panel_in_main_scheme_updates_undo_and_locked_coordinates(qtbot):
    controller = AppController()
    controller.project = load_template('ring')
    canvas = AxleCanvas(controller)
    qtbot.addWidget(canvas)
    canvas.resize(1100, 700)
    canvas.show()
    panel = canvas._arm_dimensions
    qtbot.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
    assert canvas.view_mode() == 'top' and panel.body.isVisible()
    codes = ('lca_f_in', 'lca_r_in', 'lbj')
    before = [controller.project.front.hardpoints[code].as_tuple() for code in codes]
    panel.fields['position_x'].setValue(before[0][0] + 10)
    qtbot.mouseClick(panel.buttons['position_x'], Qt.MouseButton.LeftButton)
    assert [controller.project.front.hardpoints[c].x for c in codes] == [p[0] + 10 for p in before]
    controller.undo.undo()
    assert [controller.project.front.hardpoints[c].as_tuple() for c in codes] == before
    controller.project.front.hardpoints['lbj'].locked = True
    panel.fields['position_x'].setValue(before[0][0] + 20)
    panel._apply('position_x')
    assert 'не применён' in panel.status.text()
    assert [controller.project.front.hardpoints[c].as_tuple() for c in codes] == before
    controller.set_axle_type('front', 'macpherson_front')
    assert panel.isHidden()

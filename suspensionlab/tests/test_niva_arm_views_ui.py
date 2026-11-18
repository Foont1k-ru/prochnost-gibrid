"""Немодальные условные проекции и 3D отображают только актуальную схему."""
from PySide6.QtCore import QSettings

from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


def test_all_arm_views_follow_project_and_clear_on_incompatible_schema(qtbot, tmp_path):
    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    window.action_niva_arms.trigger()
    d = window._niva_arms_dialog
    assert d is not None
    assert d._arm.count() == 9
    for index in range(d._arm.count()):
        d._arm.setCurrentIndex(index)
        assert all(plan.view is not None and not plan.grab().isNull() for plan in d._plans)
        assert d._three_d.mesh is not None
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_right'))
    old = d._plans[0].view.points
    point = c.project.rear.hardpoints['ll_out_r']
    c.move_point(point, (point.x + 10, point.y, point.z))
    assert d._plans[0].view.points != old and d._three_d.mesh is not None
    c.set_axle_type('rear', 'multilink_rear')
    assert all(plan.view is None for plan in d._plans) and d._three_d.mesh is None
    c.set_axle_type('rear', 'live_axle_coil')
    assert d._three_d.mesh is not None
    d.close()
    assert window._niva_arms_dialog is None
    c.dirty = False
    window.close()

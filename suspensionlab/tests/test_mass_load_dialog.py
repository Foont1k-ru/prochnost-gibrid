"""Окно массы требует явные данные и не подставляет их при отмене."""
import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QDialog

from suspensionlab.core.mass_load import GRAVITY_M_S2
from suspensionlab.ui.mass_load_dialog import MassLoadDialog


@pytest.fixture
def window(qtbot, tmp_path):
    from suspensionlab.ui.main_window import MainWindow

    win = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(win)
    win.show()
    return win


def set_inputs(dialog, mass="1200", axle="55", unsprung="35"):
    for key, value in (("mass", mass), ("axle_percent", axle), ("unsprung", unsprung)):
        dialog._fields[key].setText(value)


def test_preview_explicit_inputs_rounding_and_invalidation(qtbot):
    dialog = MassLoadDialog("передняя", "левая", 100000)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._calculate_button.click()
    assert dialog.estimate is None and not dialog._apply.isEnabled()
    set_inputs(dialog)
    dialog._calculate_button.click()
    assert dialog.estimate is not None and dialog._apply.isEnabled()
    assert dialog.estimate.corner_sprung_kg == pytest.approx(295)
    assert dialog.applied_load == float(f"{295 * GRAVITY_M_S2:.1f}")
    assert "реакция шины" in dialog._result.text() and "не сила пружины" in dialog._result.text()
    dialog._fields["unsprung"].setText("0")
    assert dialog.estimate is None and dialog.applied_load is None and not dialog._apply.isEnabled()
    dialog._calculate_button.click()
    assert dialog.estimate is not None and dialog.estimate.corner_sprung_kg == pytest.approx(330)
    dialog._apply.click()
    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.mark.parametrize("mass,axle,unsprung", [
    ("", "50", "0"), ("nan", "50", "0"), ("1200", "100", "0"), ("1200", "50", "300"),
    ("1200", "50", "-1"), ("1e308", "50", "0"), ("0.000001", "50", "0"), ("1000000", "50", "0"),
])
def test_no_invalid_or_clamped_value_can_be_applied(qtbot, mass, axle, unsprung):
    dialog = MassLoadDialog("передняя", "левая", 100000)
    qtbot.addWidget(dialog)
    set_inputs(dialog, mass, axle, unsprung)
    dialog._calculate_button.click()
    assert dialog.estimate is None and dialog.applied_load is None and not dialog._apply.isEnabled()


def test_modal_apply_and_manual_change_clear_source(window, qtbot, monkeypatch):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.i18n import tr
    from suspensionlab.ui import equilibrium_dialog
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    window.controller.new_project("ring")
    before = window.controller.project.to_dict()
    dialog = EquilibriumDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    load = SpringEquilibrium(window.controller.project.front, 230).evaluate(12, 1).wheel_support_n
    mass = (load / GRAVITY_M_S2 + 40) * 4
    dialog._length.setValue(230)
    dialog._load.setValue(1000)

    def fill_and_apply():
        child = dialog.findChild(MassLoadDialog)
        assert child is not None
        set_inputs(child, repr(mass), "50", "40")
        child._calculate_button.click()
        child._apply.click()

    QTimer.singleShot(0, fill_and_apply)
    dialog._mass_load_button.click()
    assert dialog._load.value() == pytest.approx(load, abs=0.05)
    assert dialog._load_source is not None and "рассчитана по массе" in dialog._load_source_label.text()
    metadata = dict(dialog._report_parameters())
    assert "Оценка по массе" in metadata[tr("equilibrium_ui.load_source")]
    assert "40.0" in metadata[tr("equilibrium_ui.load_mass_inputs")]
    dialog._run.click()
    assert dialog._result is not None and dialog._result.estimate.travel_mm == pytest.approx(12, abs=0.1)
    captured = []
    monkeypatch.setattr(equilibrium_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    dialog._export_button.click()
    assert len(captured) == 1
    assert dict(captured[0].metadata)[tr("equilibrium_ui.load_mass_inputs")] == metadata[tr("equilibrium_ui.load_mass_inputs")]
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    path = dialog._path
    assert path is not None
    path_dialog = EquilibriumPathDialog(path, dialog)
    qtbot.addWidget(path_dialog)
    path_report = dialog._path_report(path, path_dialog._table)
    assert dict(path_report.metadata)[tr("equilibrium_ui.load_mass_inputs")] == metadata[tr("equilibrium_ui.load_mass_inputs")]
    # Та же нагрузка с новым источником всё равно снимает старый результат.
    estimate = dialog._load_source
    assert estimate is not None
    dialog._apply_mass_load(estimate, dialog._load.value())
    assert dialog._result is None and not dialog._export_button.isEnabled()
    dialog._load.setValue(dialog._load.value() + 1)
    assert dialog._result is None and dialog._load_source is None
    assert dict(dialog._report_parameters())[tr("equilibrium_ui.load_mass_inputs")] == "—"
    assert window.controller.project.to_dict() == before


def test_role_side_and_project_changes_clear_only_derived_load(window, qtbot):
    from suspensionlab.core.mass_load import symmetric_mass_load
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    window.controller.new_project("ring")
    dialog = EquilibriumDialog(window.controller, window)
    qtbot.addWidget(dialog)
    estimate = symmetric_mass_load(1200, 55, 35)
    load = float(f"{estimate.sprung_load_n:.1f}")
    dialog._apply_mass_load(estimate, load)
    dialog._side.setCurrentIndex(1)
    assert dialog._load.value() == 0 and dialog._load_source is None
    dialog._load.setValue(1000)
    dialog._role.setCurrentIndex(1)
    assert dialog._load.value() == 1000
    dialog._apply_mass_load(estimate, load)
    window.controller.new_project("ring")
    assert dialog._load.value() == 0 and dialog._load_source is None


def test_cancel_does_not_replace_manual_load(window, qtbot):
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    window.controller.new_project("ring")
    dialog = EquilibriumDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._load.setValue(500)

    def cancel():
        child = dialog.findChild(MassLoadDialog)
        assert child is not None
        set_inputs(child)
        child._calculate_button.click()
        child.reject()

    QTimer.singleShot(0, cancel)
    dialog._mass_load_button.click()
    assert dialog._load.value() == 500 and dialog._load_source is None


def test_context_change_during_modal_does_not_apply_stale_estimate(window, qtbot):
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    window.controller.new_project("ring")
    dialog = EquilibriumDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._load.setValue(500)

    def change_context_and_apply():
        child = dialog.findChild(MassLoadDialog)
        assert child is not None
        set_inputs(child)
        child._calculate_button.click()
        dialog._role.setCurrentIndex(1)
        child._apply.click()

    QTimer.singleShot(0, change_context_and_apply)
    dialog._mass_load_button.click()
    assert dialog._role.currentData() == "rear" and dialog._load.value() == 500 and dialog._load_source is None

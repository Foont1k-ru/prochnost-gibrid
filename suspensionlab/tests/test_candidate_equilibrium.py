"""Связь линейного кандидата и условного баланса без изменения проекта."""
import pytest

from suspensionlab.core.equilibrium import SpringEquilibrium
from suspensionlab.core.spring_candidate import SpringCandidate
from suspensionlab.core.spring_characteristics import SpringCharacteristic
from suspensionlab.model.templates import load_template


def test_override_characteristic_drives_candidate_force_and_balance():
    project = load_template("ring")
    original = project.to_dict()
    candidate = SpringCandidate(350, 230, 150, 10, 5, 12.5)
    characteristic = SpringCharacteristic(candidate.free_mm, candidate.linear_rate_n_mm, coil_bind_length_mm=150)
    model = SpringEquilibrium(project.front, candidate.installed_mm, coil_bind_length_mm=150,
                              spring_characteristic=characteristic)
    sample = model.evaluate(12, 1)
    assert sample.spring.force_n == pytest.approx(12.5 * max(350 - sample.spring.length_mm, 0))
    assert sample.wheel_support_n == pytest.approx(sample.spring.force_n * sample.motion_ratio)
    answer = model.find(sample.wheel_support_n, -30, 30)
    assert answer.estimate.travel_mm == pytest.approx(12, abs=0.1)
    default = SpringEquilibrium(project.front, candidate.installed_mm, coil_bind_length_mm=150)
    assert default.evaluate(12, 1).spring.force_n != sample.spring.force_n
    assert project.to_dict() == original


def test_override_requires_matching_bind_and_preserves_default():
    project = load_template("ring")
    characteristic = SpringCharacteristic(350, 12.5, coil_bind_length_mm=150)
    with pytest.raises(ValueError, match="смыкания"):
        SpringEquilibrium(project.front, 230, coil_bind_length_mm=151, spring_characteristic=characteristic)
    with pytest.raises(ValueError, match="смыкания"):
        SpringEquilibrium(project.front, 230, spring_characteristic=characteristic)
    default = SpringEquilibrium(project.front, 230)
    assert default.characteristic.free_length_mm == project.front.spring.free_len_mm
    assert default.characteristic.progressive == tuple(project.front.spring.progressive)


def test_candidate_context_cannot_silently_switch_axes(qtbot):
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    controller = AppController()
    controller.new_project("ring")
    dialog = EquilibriumDialog(controller, candidate=SpringCandidate(350, 230, 150, 10, 5, 12.5),
                               initial_role="front", initial_side="left")
    qtbot.addWidget(dialog)
    dialog._load.setValue(1000)
    dialog._side.setCurrentIndex(dialog._side.findData("right"))
    dialog._run.click()
    assert dialog._result is None and "заново" in dialog._status.text()


def test_only_estimate_reserve_evaluated_and_exported(qtbot, monkeypatch):
    from suspensionlab.i18n import tr
    from suspensionlab.ui import equilibrium_dialog
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    controller = AppController()
    controller.new_project("ring")
    before = controller.project.to_dict()
    candidate = SpringCandidate(350, 230, 150, 1000, 1000, 12.5)
    characteristic = SpringCharacteristic(350, 12.5, coil_bind_length_mm=150)
    target = SpringEquilibrium(controller.project.front, 230, coil_bind_length_mm=150,
                               spring_characteristic=characteristic).evaluate(12, 1).wheel_support_n
    dialog = EquilibriumDialog(controller, candidate=candidate)
    qtbot.addWidget(dialog)
    dialog._load.setValue(target)
    dialog._run.click()
    assert dialog._result is not None and dialog._display_values is not None
    values = dialog._display_values
    assert values["candidate_coil_condition"] == "не выполнено по численному критерию"
    assert values["candidate_compression_condition"] == "не выполнено по численному критерию"
    assert values["candidate_status"] == tr("spring_candidate.report.status.reserve_short")
    assert "Только в оценке середины" in dialog._output.text()
    assert "Путь по запасам" in dialog._output.text()
    captured = []
    monkeypatch.setattr(equilibrium_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    dialog._export_button.click()
    rows = dict(captured[0].rows)
    for key in ("candidate_coil", "candidate_compression", "candidate_coil_condition",
                "candidate_compression_condition", "candidate_status"):
        assert rows[tr(f"equilibrium_ui.field.{key}")] == values[key]
    assert controller.project.to_dict() == before
    dialog._load.setValue(dialog._load.value() + 10)
    assert dialog._display_values is None and not dialog._export_button.isEnabled()

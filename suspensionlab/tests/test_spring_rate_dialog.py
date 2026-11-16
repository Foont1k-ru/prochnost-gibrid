from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from suspensionlab.ui.spring_candidate_dialog import SpringCandidateDialog
from suspensionlab.ui.spring_rate_dialog import SpringRateDialog


def fill(dialog, values):
    for key, value in values.items():
        dialog._fields[key].setText(value)


def test_preview_cancel_and_validation(qtbot):
    dialog = SpringRateDialog("300", None)
    qtbot.addWidget(dialog)
    assert dialog.estimate is None and not dialog._apply.isEnabled()
    fill(dialog, {"length1": "280", "force1": "600", "length2": "240", "force2": "1400"})
    assert dialog._apply.isEnabled() and dialog.estimate is not None
    assert "жёсткость: 20.0 Н/мм" in dialog._result.text()
    assert "длина 310.0 мм" in dialog._result.text()
    assert "400.0 и 1200.0 Н" in dialog._result.text()
    assert "снимок точек для отчётов" in dialog._result.text()
    dialog._fields["force2"].setText("600")
    assert dialog.estimate is None and not dialog._apply.isEnabled()
    dialog._fields["force2"].setText("nan")
    assert dialog.estimate is None and not dialog._apply.isEnabled()
    dialog._fields["force2"].setText("10000000")
    assert dialog.estimate is None and not dialog._apply.isEnabled()
    dialog.reject()


def test_apply_rate_only_invalidates_prior_result_and_keeps_project_inputs(qtbot):
    candidate = SpringCandidateDialog(((0, 200),), 200, "")
    qtbot.addWidget(candidate)
    candidate.show()
    fill(candidate, {"free": "300", "installed": "200", "coil": "100", "coil_reserve": "0", "compression_reserve": "0"})
    candidate._compare.click()
    assert candidate.comparison is not None and candidate.comparison.candidate.linear_rate_n_mm is None
    def accept_rate():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SpringRateDialog)
        fill(dialog, {"length1": "280", "force1": "600", "length2": "240", "force2": "1400"})
        dialog._apply.click()
    QTimer.singleShot(0, accept_rate)
    candidate._estimate_rate.click()
    assert candidate._force_enable.isChecked() and candidate._force_rate.text() == "20.0"
    assert candidate._fields["free"].text() == "300" and candidate._fields["installed"].text() == "200"
    assert candidate.comparison is None
    candidate._compare.click()
    assert candidate.comparison is not None and candidate.comparison.candidate.linear_rate_n_mm == 20
    assert candidate.comparison.points[0].force_n == 2000
    assert candidate.comparison.candidate.rate_points is not None
    assert candidate.comparison.candidate.rate_points.force_1_n == 600
    assert "двух введённых точек" in candidate._rate_source_label.text()


def test_cancel_and_changed_free_length_do_not_apply(qtbot):
    candidate = SpringCandidateDialog(((0, 200),), 200, "")
    qtbot.addWidget(candidate)
    candidate.show()
    candidate._fields["free"].setText("300")
    def cancel():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SpringRateDialog)
        fill(dialog, {"length1": "280", "force1": "600", "length2": "240", "force2": "1400"})
        dialog.reject()
    QTimer.singleShot(0, cancel)
    candidate._estimate_rate.click()
    assert not candidate._force_enable.isChecked() and not candidate._force_rate.text()
    def change_free():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SpringRateDialog)
        fill(dialog, {"length1": "280", "force1": "600", "length2": "240", "force2": "1400"})
        candidate._fields["free"].setText("320")
        dialog._apply.click()
    QTimer.singleShot(0, change_free)
    candidate._estimate_rate.click()
    assert not candidate._force_enable.isChecked() and not candidate._force_rate.text()


def apply_points(candidate, values=None):
    values = values or {"length1": "280", "force1": "600", "length2": "240", "force2": "1400"}
    def apply():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SpringRateDialog)
        fill(dialog, values)
        dialog._apply.click()
    QTimer.singleShot(0, apply)
    candidate._estimate_rate.click()


def test_provenance_cleared_by_manual_rate_free_length_or_toggle(qtbot):
    candidate = SpringCandidateDialog(((0, 200),), 200, "")
    qtbot.addWidget(candidate)
    candidate.show()
    fill(candidate, {"free": "300", "installed": "200", "coil": "100", "coil_reserve": "0", "compression_reserve": "0"})
    for action in (lambda: candidate._force_rate.setText("21"),
                   lambda: candidate._fields["free"].setText("301"),
                   lambda: candidate._force_enable.setChecked(False)):
        candidate._fields["free"].setText("300")
        apply_points(candidate)
        candidate._compare.click()
        assert candidate.comparison is not None and candidate.comparison.candidate.rate_points is not None
        action()
        assert candidate.comparison is None and candidate._rate_points is None
        assert "вручную" in candidate._rate_source_label.text() or "не включена" in candidate._rate_source_label.text()
        candidate._force_enable.setChecked(True)
        candidate._compare.click()
        assert candidate.comparison is not None and candidate.comparison.candidate.rate_points is None


def test_reapply_equal_rate_with_new_points_invalidates_existing_snapshot(qtbot):
    candidate = SpringCandidateDialog(((0, 200),), 200, "")
    qtbot.addWidget(candidate)
    candidate.show()
    fill(candidate, {"free": "300", "installed": "200", "coil": "100", "coil_reserve": "0", "compression_reserve": "0"})
    apply_points(candidate)
    candidate._compare.click()
    assert candidate.comparison is not None
    seen = []
    candidate.snapshotInvalidated.connect(lambda: seen.append(True))
    apply_points(candidate, {"length1": "270", "force1": "800", "length2": "250", "force2": "1200"})
    assert candidate.comparison is None and seen == [True]
    assert candidate._rate_points is not None and candidate._rate_points.length_1_mm == 270
    candidate._compare.click()
    assert candidate.comparison is not None and candidate.comparison.candidate.rate_points == candidate._rate_points

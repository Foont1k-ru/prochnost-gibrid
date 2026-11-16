import csv

from PySide6.QtCore import QTimer

from suspensionlab.core.equilibrium import SpringEquilibrium
from suspensionlab.core.spring_characteristics import SpringCharacteristic
from suspensionlab.export.csv_report import write_csv_report
from suspensionlab.i18n import tr
from suspensionlab.ui.analysis_dialog import AnalysisDialog
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog
from suspensionlab.ui.spring_rate_dialog import SpringRateDialog


def test_provenance_survives_real_comparison_balance_and_path_reports(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import equilibrium_dialog

    controller = AppController()
    controller.new_project("ring")
    original = controller.project.to_dict()
    analysis = AnalysisDialog(controller)
    qtbot.addWidget(analysis)
    analysis.show()
    analysis._spring.setChecked(True)
    analysis._spring_length.setValue(320)
    analysis._from.setValue(0)
    analysis._to.setValue(2)
    analysis._run.click()
    analysis._spring_compare_button.click()
    candidate = analysis._spring_candidate_dialog
    assert candidate is not None
    for key, value in (("free", "350"), ("installed", "230"), ("coil", "150"),
                       ("coil_reserve", "10"), ("compression_reserve", "5")):
        candidate._fields[key].setText(value)
    def enter_points():
        helper = candidate.findChild(SpringRateDialog)
        assert helper is not None
        for key, value in (("length1", "300.123456789"), ("force1", "625"),
                           ("length2", "280.123456789"), ("force2", "875")):
            helper._fields[key].setText(value)
        helper._apply.click()
    QTimer.singleShot(0, enter_points)
    candidate._estimate_rate.click()
    candidate._compare.click()
    assert candidate.comparison is not None and candidate.report is not None
    snapshot = candidate.comparison.candidate
    assert snapshot.rate_points is not None
    expected = dict(candidate.report.metadata)
    assert expected[tr("spring_rate.source_label")] == tr("spring_rate.source_two_points")
    assert float(expected[tr("spring_rate.length1")]) == 300.123456789
    assert float(expected[tr("spring_rate.force1")]) == 625
    assert float(expected[tr("spring_rate.length2")]) == 280.123456789
    assert float(expected[tr("spring_rate.force2")]) == 875
    keys = ("source_label", "length1", "force1", "length2", "force2", "zero_label", "model1_label", "model2_label")
    captured = []
    monkeypatch.setattr(equilibrium_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    def inspect_balance():
        balance = candidate.findChild(EquilibriumDialog)
        assert balance is not None
        try:
            model = SpringEquilibrium(controller.project.front, snapshot.installed_mm,
                                      coil_bind_length_mm=snapshot.coil_bind_mm,
                                      spring_characteristic=SpringCharacteristic(snapshot.free_mm, snapshot.linear_rate_n_mm,
                                                                                 coil_bind_length_mm=snapshot.coil_bind_mm))
            balance._load.setValue(model.evaluate(12, 1).wheel_support_n)
            balance._run.click()
            assert balance._result is not None and balance._path is not None
            balance._export_button.click()
            view = EquilibriumPathDialog(balance._path, balance, candidate=snapshot)
            qtbot.addWidget(view)
            reports = [captured[0], balance._path_report(balance._path, view._table),
                       balance._path_graph_report(balance._path, view._table, view._plot.points, "graph")]
            for report in reports:
                metadata = dict(report.metadata)
                for key in keys:
                    assert metadata[tr(f"spring_rate.{key}")] == expected[tr(f"spring_rate.{key}")]
        finally:
            balance.reject()
    QTimer.singleShot(0, inspect_balance)
    candidate._balance.click()
    assert captured and controller.project.to_dict() == original
    path = write_csv_report(candidate.report, tmp_path / "result.csv")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream, delimiter=";"))
    assert [tr("spring_rate.length1"), "300.123456789"] in rows
    assert [tr("spring_rate.source_label"), tr("spring_rate.source_two_points")] in rows


def test_manual_disabled_and_source_precision_metadata():
    from suspensionlab.core.spring_candidate import SpringCandidate
    from suspensionlab.core.spring_rate_estimate import SpringRatePoints
    from suspensionlab.export.spring_rate_provenance import spring_rate_metadata

    disabled = SpringCandidate(300, 200, 100, 0, 0)
    manual = SpringCandidate(300, 200, 100, 0, 0, 20)
    points = SpringRatePoints(280.1234567890123, 600, 240.1234567890123, 1400)
    estimated = SpringCandidate(300, 200, 100, 0, 0, points.estimate(300).rate_n_mm, rate_points=points)
    assert dict(spring_rate_metadata(disabled)) == {tr("spring_rate.source_label"): tr("spring_rate.source_disabled")}
    assert dict(spring_rate_metadata(manual)) == {tr("spring_rate.source_label"): tr("spring_rate.source_manual")}
    metadata = dict(spring_rate_metadata(estimated))
    assert float(metadata[tr("spring_rate.length1")]) == points.length_1_mm
    assert float(metadata[tr("spring_rate.zero_label")]) == points.estimate(300).extrapolated_zero_length_mm
    assert float(metadata[tr("spring_rate.model1_label")]) == points.estimate(300).model_force_1_n

"""Переходы к дискретным экстремумам силы не сохраняют устаревший снимок."""
from suspensionlab.ui.spring_candidate_dialog import SpringCandidateDialog


def make_dialog(qtbot):
    dialog = SpringCandidateDialog(((0, None), (1, 100), (2, 250), (3, 300), (4, 250)), 200, "")
    qtbot.addWidget(dialog)
    dialog.show()
    for key, value in (("free", "300"), ("installed", "200"), ("coil", "100"),
                       ("coil_reserve", "0"), ("compression_reserve", "0")):
        dialog._fields[key].setText(value)
    return dialog


def test_force_summary_buttons_and_invalidation(qtbot):
    dialog = make_dialog(qtbot)
    dialog._compare.click()
    assert not dialog._force_min_button.isEnabled() and not dialog._force_max_button.isEnabled()
    dialog._force_enable.setChecked(True)
    dialog._force_rate.setText("10")
    dialog._compare.click()
    assert dialog._force_min_button.isEnabled() and dialog._force_max_button.isEnabled()
    text = dialog._result.toPlainText()
    assert "Наименьшая" in text and "Наибольшая" in text and "нет исходной длины — 1" in text
    assert dialog._force_min_row == 3 and dialog._force_max_row == 2
    dialog._force_rate.setText("20")
    assert dialog.comparison is None and not dialog._force_max_button.isEnabled()
    dialog._compare.click()
    selected = []
    dialog.rowSelected.connect(selected.append)
    dialog._force_max_button.click()
    assert selected == [2]


def test_force_summary_no_available_values_and_min_navigation(qtbot):
    dialog = make_dialog(qtbot)
    dialog._points = ((0, None), (1, 100))
    dialog._force_enable.setChecked(True)
    dialog._force_rate.setText("10")
    dialog._compare.click()
    assert "Нет строк" in dialog._result.toPlainText()
    assert not dialog._force_min_button.isEnabled() and not dialog._force_max_button.isEnabled()
    dialog._points = ((-1, 250), (1, 300))
    dialog._compare.click()
    selected = []
    dialog.rowSelected.connect(selected.append)
    dialog._force_min_button.click()
    assert selected == [1]

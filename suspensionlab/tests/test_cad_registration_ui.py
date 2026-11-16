import copy

from PySide6.QtWidgets import QComboBox, QLineEdit

from suspensionlab.ui.cad_registration_dialog import CadRegistrationDialog
from suspensionlab.ui.controller import AppController


def fill_identity(dialog):
    # Independent points are specified explicitly, rather than relying on a template.
    indices = [next(i for i, p in enumerate(dialog._records) if p.role == 'front' and p.code == code)
               for code in ('ubj', 'lbj', 'lca_f_in')]
    for row, index in enumerate(indices):
        combo = dialog._table.cellWidget(row, 0)
        assert isinstance(combo, QComboBox)
        combo.setCurrentIndex(combo.findData(index))
        for column, value in enumerate(dialog._records[index].xyz, 1):
            widget = dialog._table.cellWidget(row, column)
            assert isinstance(widget, QLineEdit)
            widget.setText(str(value))


def test_registration_preview_no_model_mutation_and_invalidation(qtbot):
    controller = AppController()
    # Known noncollinear points.
    for code, xyz in zip(('ubj', 'lbj', 'lca_f_in'), ((0, 0, 0), (100, 0, 0), (0, 100, 0)), strict=True):
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    before = copy.deepcopy(controller.project.to_dict())
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    fill_identity(dialog)
    dialog._run()
    assert 'Подтвердите' in dialog._result.toPlainText()
    dialog._confirmed.setChecked(True)
    dialog._run()
    assert 'R (строки)' in dialog._result.toPlainText()
    assert '0 мм' in dialog._result.toPlainText() or 'e-' in dialog._result.toPlainText()
    assert controller.project.to_dict() == before
    assert controller.undo.depth() == 0 and not controller.dirty
    cell = dialog._table.cellWidget(0, 1)
    assert isinstance(cell, QLineEdit)
    cell.setText('10')
    assert not dialog._result.toPlainText()
    dialog._run()
    assert dialog._result.toPlainText()
    controller.modelChanged.emit()
    assert 'устарели' in dialog._result.toPlainText()
    assert not dialog._calculate.isEnabled() and not dialog._table.isEnabled()
    dialog._run()
    assert 'устарели' in dialog._result.toPlainText()


def test_duplicate_incomplete_rows_and_limits(qtbot):
    dialog = CadRegistrationDialog(AppController())
    qtbot.addWidget(dialog)
    dialog._confirmed.setChecked(True)
    dialog._run()
    assert 'Выберите разные' in dialog._result.toPlainText()
    for row in range(3):
        combo = dialog._table.cellWidget(row, 0)
        assert isinstance(combo, QComboBox)
        combo.setCurrentIndex(1)
        for col in range(1, 4):
            edit = dialog._table.cellWidget(row, col)
            assert isinstance(edit, QLineEdit)
            edit.setText('0')
    dialog._run()
    assert 'Выберите разные' in dialog._result.toPlainText()
    for _ in range(30):
        dialog._add_row()
    assert dialog._table.rowCount() == 20 and not dialog._add.isEnabled()
    for _ in range(30):
        dialog._remove_row()
    assert dialog._table.rowCount() == 3

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


def test_control_pairs_are_excluded_and_export_invalidates(qtbot, tmp_path, monkeypatch):
    import csv

    from suspensionlab.ui import cad_registration_dialog as module

    controller = AppController()
    for code, xyz in zip(('ubj', 'lbj', 'lca_f_in', 'lca_r_in'),
                         ((0, 0, 0), (100, 0, 0), (0, 100, 0), (0, 0, 50)), strict=True):
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    fill_identity(dialog)
    dialog._confirmed.setChecked(True)
    dialog._run()
    assert 'Контрольные пары не заданы' in dialog._result.toPlainText()
    assert 'Только подбор: 3 отрезков' in dialog._result.toPlainText()
    assert 'С участием контроля: отрезков нет' in dialog._result.toPlainText()
    assert dialog._export.isEnabled()
    dialog._add_row()
    assert not dialog._export.isEnabled()
    combo = dialog._table.cellWidget(3, 0)
    purpose = dialog._table.cellWidget(3, 4)
    assert isinstance(combo, QComboBox) and isinstance(purpose, QComboBox)
    index = next(i for i, p in enumerate(dialog._records) if p.role == 'front' and p.code == 'lca_r_in')
    combo.setCurrentIndex(combo.findData(index))
    purpose.setCurrentIndex(1)
    for column, value in enumerate((0, 0, 60), 1):
        edit = dialog._table.cellWidget(3, column)
        assert isinstance(edit, QLineEdit)
        edit.setText(str(value))
    dialog._run()
    assert 'Контроль (не участвовал в подборе): 1 пар' in dialog._result.toPlainText()
    assert 'С участием контроля: 3 отрезков' in dialog._result.toPlainText()
    assert '10 мм' in dialog._result.toPlainText()
    target = tmp_path / 'report.csv'
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(target), 'CSV'))
    dialog._save_report()
    with target.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream, delimiter=';'))
    assert ['control_count', '1'] in rows
    assert any(row and len(row) > 1 and row[0:2] == ['4', 'control'] for row in rows)
    purpose.setCurrentIndex(0)
    assert not dialog._export.isEnabled() and not dialog._result.toPlainText()


def test_export_rechecks_revision_and_protects_project(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import cad_registration_dialog as module

    controller = AppController()
    for code, xyz in zip(('ubj', 'lbj', 'lca_f_in'), ((0, 0, 0), (100, 0, 0), (0, 100, 0)), strict=True):
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    fill_identity(dialog)
    dialog._confirmed.setChecked(True)
    dialog._run()
    warnings = []
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *args: warnings.append(args))
    project_file = tmp_path / 'project.csv'
    project_file.write_text('original', encoding='utf8')
    controller.project.path = str(project_file)
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(project_file), 'CSV'))
    dialog._save_report()
    assert warnings and project_file.read_text(encoding='utf8') == 'original'
    output = tmp_path / 'stale.csv'
    def change_during_dialog(*args):
        controller.modelChanged.emit()
        return str(output), 'CSV'
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', change_during_dialog)
    dialog._save_report()
    assert not output.exists() and not dialog._export.isEnabled()
    assert len(warnings) == 2


def test_replacing_project_invalidates_open_registration(qtbot):
    controller = AppController()
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    controller.new_project()
    assert dialog._stale and not dialog._calculate.isEnabled() and not dialog._export.isEnabled()


def test_explicit_surface_transfer_reuses_picker_and_tracks_manual_edit(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLabel

    from suspensionlab.ui import cad_registration_dialog as module
    created = []
    class FakePicker:
        def __init__(self, settings, parent):
            self.chosen = None
            created.append(self)
        def exec(self):
            self.chosen = (1.234567890123, -2., 3.)
            self.chosen_digest = b'a' * 32
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr(module, 'CadRegistrationPicker', FakePicker)
    dialog = CadRegistrationDialog(AppController())
    qtbot.addWidget(dialog)
    dialog._table.setCurrentCell(0, 1)
    dialog._pick_for_row()
    label = dialog._table.cellWidget(0, 5)
    assert isinstance(label, QLabel) and label.property('cad_source') == 'surface_preview'
    assert [float(dialog._table.cellWidget(0, c).text()) for c in range(1, 4)] == [1.234567890123, -2., 3.]
    dialog._table.setCurrentCell(1, 1)
    dialog._pick_for_row()
    assert len(created) == 1
    second = dialog._table.cellWidget(1, 5)
    assert second.property('cad_source') == 'surface_preview'
    dialog._table.cellWidget(1, 2).setText('42')
    assert second.property('cad_source') == 'manual_or_edited'
    assert label.property('cad_source') == 'surface_preview'


def test_picker_rejection_and_changes_during_modal_never_apply(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui import cad_registration_dialog as module
    controller = AppController()
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    dialog._table.setCurrentCell(0, 1)
    class FakePicker:
        def __init__(self, settings, parent):
            self.chosen = None
            self.action = lambda: None
            self.result = QDialog.DialogCode.Rejected
        def exec(self):
            self.chosen = (10., 20., 30.)
            self.chosen_digest = b'a' * 32
            self.action()
            return self.result
    monkeypatch.setattr(module, 'CadRegistrationPicker', FakePicker)
    dialog._pick_for_row()
    assert dialog._table.cellWidget(0, 1).text() == ''
    picker = dialog._picker
    picker.result = QDialog.DialogCode.Accepted
    picker.action = lambda: dialog._table.cellWidget(0, 1).setText('123')
    dialog._pick_for_row()
    assert dialog._table.cellWidget(0, 1).text() == '123'
    assert dialog._table.cellWidget(0, 2).text() == ''
    picker.action = controller.modelChanged.emit
    dialog._pick_for_row()
    assert dialog._stale and not dialog._pick.isEnabled()
    assert dialog._table.cellWidget(0, 1).text() == '123'
    assert dialog._table.cellWidget(0, 2).text() == ''


def test_picked_rows_marked_in_csv_and_invalidate_old_result(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui import cad_registration_dialog as module
    controller = AppController()
    for code, xyz in zip(('ubj', 'lbj', 'lca_f_in'), ((0, 0, 0), (100, 0, 0), (0, 100, 0)), strict=True):
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    fill_identity(dialog)
    dialog._confirmed.setChecked(True)
    dialog._run()
    assert dialog._report is not None
    class FakePicker:
        def __init__(self, settings, parent):
            self.chosen = None
        def exec(self):
            self.chosen = (0., 0., 0.)
            self.chosen_digest = b'a' * 32
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr(module, 'CadRegistrationPicker', FakePicker)
    dialog._table.setCurrentCell(0, 1)
    dialog._pick_for_row()
    assert dialog._report is None and not dialog._export.isEnabled()
    dialog._run()
    assert dialog._report is not None
    source_col = dialog._report.columns.index('cad_input')
    assert [r[source_col] for r in dialog._report.rows] == ['surface_preview', 'manual_or_edited', 'manual_or_edited']


def test_mixed_picked_sources_block_registration_until_fixed(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui import cad_registration_dialog as module
    controller = AppController()
    for code, xyz in zip(('ubj', 'lbj', 'lca_f_in'), ((0, 0, 0), (100, 0, 0), (0, 100, 0)), strict=True):
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    fill_identity(dialog)
    dialog._confirmed.setChecked(True)
    class FakePicker:
        def __init__(self, settings, parent):
            self.chosen = None
            self.point = (0., 0., 0.)
            self.digest = b'a' * 32
        def exec(self):
            self.chosen = self.point
            self.chosen_digest = self.digest
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr(module, 'CadRegistrationPicker', FakePicker)
    dialog._table.setCurrentCell(0, 1)
    dialog._pick_for_row()
    picker = dialog._picker
    picker.point, picker.digest = (100., 0., 0.), b'b' * 32
    dialog._table.setCurrentCell(1, 1)
    dialog._pick_for_row()
    assert 'разным содержимым STEP' in dialog._source_status.text()
    dialog._run()
    assert dialog._report is None and 'Нельзя совместить' in dialog._result.toPlainText()
    # Editing a coordinate drops its provenance; it is now explicitly unverified.
    dialog._table.cellWidget(1, 1).setText('100.00')
    assert 'неизвестный или изменённый ввод: 2' in dialog._source_status.text()
    dialog._run()
    assert dialog._report is not None
    assert ('surface_points_with_digest', '1') in dialog._report.metadata
    assert ('manual_or_edited_unverified', '2') in dialog._report.metadata
    assert dialog._snapshot_digest == b'a' * 32
    assert b'a'.decode() * 32 not in repr(dialog._report)


def test_distance_list_export_and_stale_protection(qtbot, tmp_path, monkeypatch):
    import csv

    from suspensionlab.ui import cad_registration_dialog as module

    controller = AppController()
    for code, xyz in zip(('ubj', 'lbj', 'lca_f_in'), ((0, 0, 0), (100, 0, 0), (0, 100, 0)), strict=True):
        point = controller.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    dialog = CadRegistrationDialog(controller)
    qtbot.addWidget(dialog)
    assert not dialog._export_distances.isEnabled()
    fill_identity(dialog)
    dialog._table.cellWidget(1, 1).setText('90')
    dialog._confirmed.setChecked(True)
    dialog._run()
    assert dialog._export_distances.isEnabled()
    text = dialog._result.toPlainText()
    assert text.index('Строки 1–2 / Только подбор') < text.index('Строки 2–3 / Только подбор')
    path = tmp_path / 'distances.csv'
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(path), 'CSV'))
    dialog._save_distances()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream, delimiter=';'))
    header = next(i for i, row in enumerate(rows) if row and row[0] == 'row_1')
    assert len(rows[header + 1:]) == 3
    warnings = []
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *args: warnings.append(args))
    controller.project.path = str(path)
    old = path.read_bytes()
    dialog._save_distances()
    assert warnings and path.read_bytes() == old
    def mutate_during_save(*args):
        dialog._table.cellWidget(0, 1).setText('2')
        return str(tmp_path / 'stale.csv'), 'CSV'
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', mutate_during_save)
    dialog._save_distances()
    assert not (tmp_path / 'stale.csv').exists() and len(warnings) == 2
    assert not dialog._export_distances.isEnabled() and dialog._distance_report is None

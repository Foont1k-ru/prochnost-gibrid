"""Сохранение и открытие схемы и заготовки в экспериментальном KIM."""

import threading

import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_transport import CadPreviewError
from suspensionlab.model.kim_format import make_scheme_arm_part, read_document, write_document
from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.kim_scheme_arm_dialog import KimSchemeArmDialog
from suspensionlab.ui.main_window import MainWindow


def test_save_new_scheme_part_from_live_editor_and_guard_unsignalled_changes(qtbot, tmp_path, monkeypatch):
    controller = AppController()
    dialog = ArmConceptDialog(controller)
    qtbot.addWidget(dialog)
    before = controller.project.to_dict()
    path = tmp_path / "arm.kim"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    assert dialog._save_linked_part.isEnabled()
    dialog._save_scheme_part()
    doc = read_document(path, "part")
    assert doc["version"] == "0.3" and doc["scheme"] == before
    assert doc["geometry"]["radius_mm"] == dialog._radius.value()
    assert not controller.dirty and controller.project.to_dict() == before
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog._save_scheme_part()
    assert warnings and read_document(path, "part") == doc
    target = tmp_path / "changed.kim"
    def change_during_selection(*args):
        controller.project.meta.name = "Без сигнала"
        return str(target), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", change_during_selection)
    dialog._save_scheme_part()
    assert not target.exists() and len(warnings) == 2
    dialog._bend_checks["front"].setChecked(True)
    assert not dialog._save_linked_part.isEnabled()
    assert dialog.shutdown()


def test_open_snapshot_explicit_rebuild_and_save_copy(qtbot, tmp_path, monkeypatch):
    controller = AppController()
    doc = make_scheme_arm_part("arm", "Рычаг", controller.project, 12, 2)
    path = tmp_path / "original.kim"
    write_document(path, "part", doc, overwrite=False)
    old = path.read_bytes()
    dialog = KimSchemeArmDialog(controller, read_document(path, "part"), path)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.canvas.concept is not None and not dialog.canvas.grab().isNull()
    assert "совпадают" in dialog.source_status.text()
    outer = controller.project.front.hardpoints["lbj"]
    controller.move_point(outer, (outer.x, outer.y + 20, outer.z))
    assert "различаются" in dialog.source_status.text()
    assert dialog.document == doc
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    dialog._apply_current_scheme()
    assert dialog.document == doc
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog._apply_current_scheme()
    assert dialog.document != doc and path.read_bytes() == old
    assert dialog.document["geometry"]["radius_mm"] == 12
    target = tmp_path / "updated.kim"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    dialog._save_copy()
    assert read_document(target, "part") == dialog.document and path.read_bytes() == old
    assert dialog.document == dialog._saved
    dialog.close()


def test_rebuild_confirmation_race_and_reject_unsaved_close(qtbot, tmp_path, monkeypatch):
    controller = AppController()
    doc = make_scheme_arm_part("arm", "Рычаг", controller.project, 12, 2)
    dialog = KimSchemeArmDialog(controller, doc, tmp_path / "original.kim")
    qtbot.addWidget(dialog)
    dialog.show()
    outer = controller.project.front.hardpoints["lbj"]
    controller.move_point(outer, (outer.x, outer.y + 10, outer.z))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    def race(*args):
        outer.y += 1
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", race)
    dialog._apply_current_scheme()
    assert warnings and dialog.document == doc
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog._apply_current_scheme()
    assert dialog.document != doc
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert not dialog.close() and dialog.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    assert dialog.close()


def test_saved_snapshot_3d_cancels_old_work_when_rebuilt(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    jobs = []
    class Job:
        def __init__(self):
            self.release, self.started = threading.Event(), threading.Event()
            self.cancelled = False
            jobs.append(self)
        def cancel(self):
            self.cancelled = True
        def run(self, document, *, deviation=2.):
            self.started.set()
            assert self.release.wait(10)
            x = document["parts"][0]["geometry"]["source"]["coordinates_mm"][2][0]
            return CadMesh(np.array([[[x, 0, 0], [x, 1, 0], [x, 0, 1]]]), 1)
    monkeypatch.setattr(module, "WeldmentCadJob", Job)
    controller = AppController()
    doc = make_scheme_arm_part("arm", "Рычаг", controller.project, 12, 2)
    dialog = KimSchemeArmDialog(controller, doc, tmp_path / "part.kim")
    qtbot.addWidget(dialog)
    dialog.three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: len(jobs) == 1 and jobs[0].started.is_set(), timeout=5000)
    assert not dialog.save_copy.isEnabled()
    point = controller.project.front.hardpoints["lbj"]
    controller.move_point(point, (point.x + 20, point.y, point.z))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog._apply_current_scheme()
    assert jobs[0].cancelled and dialog.three_d._view.mesh is None
    jobs[0].release.set()
    qtbot.waitUntil(lambda: len(jobs) == 2 and jobs[1].started.is_set(), timeout=5000)
    jobs[1].release.set()
    qtbot.waitUntil(lambda: dialog.three_d._view.mesh is not None, timeout=5000)
    assert dialog.three_d._view.mesh.triangles[0, 0, 0] == point.x
    assert dialog.save_copy.isEnabled()
    assert dialog.three_d.shutdown()
    dialog._saved = dialog.document


def test_menu_rejects_old_or_corrupt_file_without_changing_project(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import make_lower_arm_tube_prototype

    controller = AppController()
    window = MainWindow(controller, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    before = controller.project.to_dict()
    path = tmp_path / "old.kim"
    write_document(path, "part", make_lower_arm_tube_prototype("old", "Старый", controller.project, 12, 2))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window.action_scheme_arm_part.trigger()
    assert warnings and controller.project.to_dict() == before and not controller.dirty
    window.close()


def test_menu_opens_new_scheme_part_without_modifying_project(qtbot, tmp_path, monkeypatch):
    controller = AppController()
    window = MainWindow(controller, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    before = controller.project.to_dict()
    path = tmp_path / "arm.kim"
    expected = make_scheme_arm_part("arm", "Рычаг", controller.project, 12, 2)
    write_document(path, "part", expected, overwrite=False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    opened = []
    def exec_(dialog):
        opened.append((dialog.document, dialog.canvas.concept.points))
        assert dialog.three_d.shutdown()
        return 0
    monkeypatch.setattr(KimSchemeArmDialog, "exec", exec_)
    window.action_scheme_arm_part.trigger()
    assert len(opened) == 1 and opened[0][0] == expected
    assert controller.project.to_dict() == before and not controller.dirty
    window.close()


def test_failed_3d_blocks_saving_until_explicitly_disabled(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    class Job:
        def cancel(self):
            pass
        def run(self, document, *, deviation=2.):
            raise CadPreviewError("missing_cad")
    monkeypatch.setattr(module, "WeldmentCadJob", Job)
    controller = AppController()
    doc = make_scheme_arm_part("arm", "Рычаг", controller.project, 12, 2)
    dialog = KimSchemeArmDialog(controller, doc, tmp_path / "source.kim")
    qtbot.addWidget(dialog)
    dialog.three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: "CAD-ядро отсутствует" in dialog.three_d._status.text(), timeout=5000)
    assert dialog.three_d._view.mesh is None and not dialog.save_copy.isEnabled()
    dialog.three_d._enable.setChecked(False)
    assert dialog.save_copy.isEnabled()  # without CAD validation, as explicitly indicated
    assert dialog.three_d.shutdown()


def test_bushing_parameter_validation_keeps_dialog_open(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from suspensionlab.ui.kim_scheme_arm_dialog import BushingParametersDialog

    parent = QWidget()
    qtbot.addWidget(parent)
    d = BushingParametersDialog(None, parent)
    qtbot.addWidget(d)
    d.show()
    assert d.axis.currentData() == 'x'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d.fields['bore_radius_mm'].setText('15')
    d.accept()
    assert warnings and d.isVisible()
    d.fields['bore_radius_mm'].setText('7,5')
    d.accept()
    assert not d.isVisible() and d.values()['bore_radius_mm'] == 7.5


def test_add_edit_remove_bushings_and_reopen_without_changing_source(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui.kim_scheme_arm_dialog import BushingParametersDialog

    c = AppController()
    doc = make_scheme_arm_part('arm', 'Рычаг', c.project, 12, 2)
    source, target = tmp_path / 'source.kim', tmp_path / 'copy.kim'
    write_document(source, 'part', doc, overwrite=False)
    initial_bytes = source.read_bytes()
    d = KimSchemeArmDialog(c, doc, source)
    qtbot.addWidget(d)
    def accept(dialog):
        assert dialog.axis.currentData() == 'x'
        dialog.fields['length_mm'].setText('31.123456789')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BushingParametersDialog, 'exec', accept)
    d._edit_bushings()
    assert d.document['version'] == '0.4' and d.document['bushings']['axis'] == 'x'
    assert d.document['bushings']['length_mm'] == 31.123456789 and d.document != d._saved
    assert d.three_d._document == d.document and source.read_bytes() == initial_bytes
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    assert not d._confirm_close()
    changed = c.project.front.hardpoints['lca_f_in']
    c.move_point(changed, (changed.x + 20, changed.y, changed.z))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._apply_current_scheme()
    assert d.document['bushings']['length_mm'] == 31.123456789
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    saved = read_document(target, 'part')
    assert saved == d.document and source.read_bytes() == initial_bytes
    assert d.three_d.shutdown()
    d.close()
    d = KimSchemeArmDialog(c, saved, target)
    qtbot.addWidget(d)
    assert d.three_d._document == saved and d.remove_bushings.isEnabled()
    d._remove_bushings()
    assert d.document['version'] == '0.3' and 'bushings' not in d.document
    assert read_document(target, 'part') == saved and d.document != d._saved
    assert d.three_d.shutdown()
    d.close()


def test_bushing_dialog_rejects_races_and_invalid_inputs(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui.kim_scheme_arm_dialog import BushingParametersDialog

    c = AppController()
    doc = make_scheme_arm_part('arm', 'Рычаг', c.project, 12, 2)
    d = KimSchemeArmDialog(c, doc, tmp_path / 'source.kim')
    qtbot.addWidget(d)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    def invalid(dialog):
        dialog.fields['length_mm'].setText('0')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BushingParametersDialog, 'exec', invalid)
    d._edit_bushings()
    assert warnings and d.document == doc
    def race(dialog):
        d.document['name'] = 'Изменено во время диалога'
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BushingParametersDialog, 'exec', race)
    d._edit_bushings()
    assert len(warnings) == 2 and d.document['version'] == '0.3'
    d._saved = d.document
    assert d.three_d.shutdown()
    d.close()


def test_menu_opens_scheme_part_with_bushings(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import set_scheme_arm_bushings

    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    path = tmp_path / 'new.kim'
    doc = set_scheme_arm_bushings(make_scheme_arm_part('arm', 'Рычаг', c.project, 12, 2),
                                   {'axis': 'x', 'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 24})
    write_document(path, 'part', doc, overwrite=False)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    opened = []
    def open_dialog(dialog):
        opened.append(dialog.document)
        assert dialog.three_d.shutdown()
        return 0
    monkeypatch.setattr(KimSchemeArmDialog, 'exec', open_dialog)
    window.action_scheme_arm_part.trigger()
    assert opened == [doc] and not c.dirty
    window.close()

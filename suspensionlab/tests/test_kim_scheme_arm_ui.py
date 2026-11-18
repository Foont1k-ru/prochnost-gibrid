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

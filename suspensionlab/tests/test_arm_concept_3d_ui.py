"""3D черновик в редакторе живёт в памяти и безопасно реагирует на изменения."""
import threading

import numpy as np
from PySide6.QtWidgets import QFileDialog

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_transport import CadPreviewError
from suspensionlab.model.kim_format import read_document
from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog
from suspensionlab.ui.controller import AppController


def test_live_editor_3d_cancels_obsolete_work_and_saves_only_current(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    jobs = []
    class Job:
        def __init__(self):
            self.release = threading.Event()
            self.started = threading.Event()
            self.cancelled = False
            jobs.append(self)
        def cancel(self):
            self.cancelled = True  # emulate a result arriving despite cancellation
        def run(self, document, *, deviation=2.):
            self.started.set()
            assert self.release.wait(10)
            radius = document['parts'][0]['geometry']['radius_mm']
            return CadMesh(np.array([[[radius, 0, 0], [radius, 1, 0], [radius, 0, 1]],
                                     [[radius, 2, 0], [radius, 3, 0], [radius, 2, 1]]]), 2,
                           part_names=('tube_front', 'tube_rear'), triangle_parts=np.array([0, 1]))
    monkeypatch.setattr(module, 'WeldmentCadJob', Job)
    c = AppController()
    before = c.project.to_dict()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    panel = dialog._three_d
    assert dialog._candidate is not None and not panel._enable.isChecked()
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: len(jobs) == 1 and jobs[0].started.is_set(), timeout=5000)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    dialog._radius.setValue(20.)
    assert jobs[0].cancelled and panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    jobs[0].release.set()
    qtbot.waitUntil(lambda: len(jobs) == 2 and jobs[1].started.is_set(), timeout=5000)
    assert panel._view.mesh is None
    jobs[1].release.set()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=5000)
    assert panel._view.mesh.triangles[0, 0, 0] == 20
    assert dialog._save_assembly.isEnabled() and c.project.to_dict() == before and not c.dirty
    target = tmp_path / 'new.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    dialog._save_weldment_snapshot()
    assert read_document(target, 'assembly')['parts'][0]['geometry']['radius_mm'] == 20
    dialog._style.setCurrentIndex(1)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    assert dialog.shutdown()


def test_live_editor_clears_3d_on_invalid_data_and_missing_kernel(qtbot, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    class Job:
        def cancel(self):
            pass
        def run(self, document, *, deviation=2.):
            raise CadPreviewError('missing_cad')
    monkeypatch.setattr(module, 'WeldmentCadJob', Job)
    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    panel = dialog._three_d
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: 'CAD-ядро отсутствует' in panel._status.text(), timeout=5000)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    panel._enable.setChecked(False)
    assert dialog._save_assembly.isEnabled()
    dialog._wall.setValue(dialog._radius.value())
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    assert dialog.concept is None and dialog.shutdown()


def test_closing_main_window_cancels_editor_process(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from suspensionlab.ui import weldment_3d as module
    from suspensionlab.ui.main_window import MainWindow

    jobs = []
    class Job:
        def __init__(self):
            self.cancelled = threading.Event()
            jobs.append(self)
        def cancel(self):
            self.cancelled.set()
        def run(self, document, *, deviation=2.):
            assert self.cancelled.wait(10)
            raise CadPreviewError('cancelled')
    monkeypatch.setattr(module, 'WeldmentCadJob', Job)
    controller = AppController()
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    window.action_arm_concept.trigger()
    dialog = window._arm_concept_dialog
    assert dialog is not None
    dialog._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: len(jobs) == 1, timeout=5000)
    worker = dialog._three_d._worker
    assert worker is not None
    window.close()
    assert jobs[0].cancelled.is_set() and not worker.isRunning()

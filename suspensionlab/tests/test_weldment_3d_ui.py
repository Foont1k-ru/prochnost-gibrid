"""Очередь CAD-просмотра: старые, ошибочные и отменённые результаты не показываются."""
import threading

import numpy as np
from PySide6.QtWidgets import QFileDialog

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_transport import CadPreviewError
from suspensionlab.model.kim_format import write_document
from suspensionlab.model.welded_arm import make_welded_arm
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.weldment_dialog import WeldmentDialog


def setup_dialog(qtbot, tmp_path, monkeypatch):
    c = AppController()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 12, 2, 'unknown'))
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    return c, d


def test_old_job_result_discarded_and_latest_appears(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    jobs = []
    class Job:
        def __init__(self):
            self.release = threading.Event()
            self.started = threading.Event()
            self.cancelled = False
            jobs.append(self)
        def cancel(self):
            self.cancelled = True  # simulate a late result even after cancellation
        def run(self, document):
            self.started.set()
            assert self.release.wait(10)
            x = document['parts'][0]['geometry']['source']['coordinates_mm'][2][0]
            return CadMesh(np.array([[[x, 0, 0], [x, 1, 0], [x, 0, 1]]]), 1)
    monkeypatch.setattr(module, 'WeldmentCadJob', Job)
    c, d = setup_dialog(qtbot, tmp_path, monkeypatch)
    panel = d._three_d
    panel._enable.setChecked(True)
    assert panel._view.mesh is None and not d._save.isEnabled()
    qtbot.waitUntil(lambda: len(jobs) == 1 and jobs[0].started.is_set(), timeout=5000)
    p = c.project.front.hardpoints['lbj']
    c.move_point(p, (p.x + 25, p.y, p.z))
    assert jobs[0].cancelled and panel._view.mesh is None and not d._save.isEnabled()
    jobs[0].release.set()
    qtbot.waitUntil(lambda: len(jobs) == 2 and jobs[1].started.is_set(), timeout=5000)
    assert panel._view.mesh is None
    jobs[1].release.set()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=5000)
    assert panel._view.mesh.triangles[0, 0, 0] == p.x
    assert d._save.isEnabled() and 'Только две' in panel._status.text()
    c.new_project()
    assert panel._view.mesh is None and not d._save.isEnabled()
    assert d.shutdown()


def test_failure_and_unsignalled_change_never_show_old_3d(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    jobs = []
    class Job:
        def __init__(self):
            self.release = threading.Event()
            jobs.append(self)
        def cancel(self):
            self.release.set()
        def run(self, document):
            self.release.wait(10)
            if len(jobs) == 1:
                raise CadPreviewError('missing_cad')
            return CadMesh(np.array([[[0, 0, 0], [0, 1, 0], [0, 0, 1]]]), 1)
    monkeypatch.setattr(module, 'WeldmentCadJob', Job)
    c, d = setup_dialog(qtbot, tmp_path, monkeypatch)
    panel = d._three_d
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: len(jobs) == 1, timeout=5000)
    jobs[0].release.set()
    qtbot.waitUntil(lambda: 'CAD-ядро отсутствует' in panel._status.text(), timeout=5000)
    assert panel._view.mesh is None and not d._save.isEnabled()
    panel._retry.click()
    qtbot.waitUntil(lambda: len(jobs) == 2, timeout=5000)
    c.project.front.hardpoints['lbj'].x += 10  # no controller signal
    jobs[1].release.set()
    qtbot.waitUntil(lambda: 'без обновления окна' in panel._status.text(), timeout=5000)
    assert panel._view.mesh is None and not d._save.isEnabled()
    panel._enable.setChecked(False)
    assert panel._view.mesh is None and d._save.isEnabled()  # parameter-only copy remains explicitly available
    assert d.shutdown()


def test_close_cancels_inflight_job(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    jobs = []
    class Job:
        def __init__(self):
            self.done = threading.Event()
            jobs.append(self)
        def cancel(self):
            self.done.set()
        def run(self, document):
            assert self.done.wait(10)
            raise CadPreviewError('cancelled')
    monkeypatch.setattr(module, 'WeldmentCadJob', Job)
    _, d = setup_dialog(qtbot, tmp_path, monkeypatch)
    d.show()
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: len(jobs) == 1, timeout=5000)
    worker = d._three_d._worker
    assert worker is not None
    d.close()
    assert jobs[0].done.is_set() and not worker.isRunning()

"""Cache hit, forced rebuild, mutable documents and late worker results."""
from copy import deepcopy
from threading import Event

import numpy as np
import pytest

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.model.free_arm import FreeArmDraft
from suspensionlab.model.free_arm_io import to_data
from suspensionlab.ui import weldment_3d


def draft():
    return to_data(FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2))


def fake_mesh(x):
    triangles = np.array([[[x, 0, 0], [x, 1, 0], [x, 0, 1]],
                          [[x, 2, 0], [x, 3, 0], [x, 2, 1]]])
    return CadMesh(triangles, 2, part_names=('tube_front', 'tube_rear'), triangle_parts=np.array([0, 1]),
                   instance_groups=(0,), triangle_instances=np.array([0, 0]))


def install_instant_job(monkeypatch):
    calls = []

    class Job:
        def cancel(self):
            pass

        def run(self, document, *, deviation):
            calls.append((deepcopy(document), deviation))
            return fake_mesh(document['anchors_mm']['front'][0] + deviation)

    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    return calls


def new_panel(qtbot, doc, *, current=None):
    panel = weldment_3d.Weldment3D(fixed_skeleton=True, is_current=current)
    qtbot.addWidget(panel)
    panel.set_document(doc)
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    panel._timer.stop()
    panel._start()
    return panel


def ready(qtbot, panel):
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=5000)


def start_pending(panel):
    panel._timer.stop()
    panel._start()


def test_reuse_quality_toggle_force_and_shutdown(qtbot, monkeypatch):
    calls = install_instant_job(monkeypatch)
    doc = draft()
    panel = new_panel(qtbot, doc, current=lambda current: current == doc)
    ready(qtbot, panel)
    first = panel._view.mesh
    assert len(calls) == 1 and not panel._active_cache_hit and panel._mesh_cache._items
    panel._enable.setChecked(False)
    assert panel._view.mesh is None
    panel._enable.setChecked(True)
    start_pending(panel)
    assert panel._ready and panel._worker is None and len(calls) == 1
    assert panel._active_cache_hit and panel._view.mesh is not first
    assert np.array_equal(panel._view.mesh.triangles, first.triangles)
    assert 'кеша' in panel._status.text() and panel.can_save()
    panel._quality.setCurrentIndex(0)
    start_pending(panel)
    ready(qtbot, panel)
    assert len(calls) == 2 and calls[-1][1] == .2
    panel._quality.setCurrentIndex(1)
    start_pending(panel)
    assert panel._ready and len(calls) == 2 and panel._active_cache_hit
    panel._retry.click()
    start_pending(panel)
    ready(qtbot, panel)
    assert len(calls) == 3 and calls[-1][1] == 2. and not panel._active_cache_hit
    assert panel.shutdown() and not panel._mesh_cache._items and panel._mesh_cache._bytes == 0


def test_changes_and_old_result_do_not_hit_or_pollute_cache(qtbot, monkeypatch):
    jobs = []

    class Job:
        def __init__(self):
            self.entered, self.release = Event(), Event()
            self.cancelled = False
            jobs.append(self)

        def run(self, document, *, deviation):
            self.entered.set()
            assert self.release.wait(10)
            return fake_mesh(document['anchors_mm']['front'][0])

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    doc = draft()
    panel = new_panel(qtbot, doc)
    qtbot.waitUntil(lambda: jobs and jobs[0].entered.is_set(), timeout=5000)
    second = deepcopy(doc)
    second['anchors_mm']['front'][0] = 10.
    panel.set_document(second)
    assert jobs[0].cancelled and panel._view.mesh is None
    jobs[0].release.set()
    qtbot.waitUntil(lambda: len(jobs) == 2 and jobs[1].entered.is_set(), timeout=5000)
    assert panel._view.mesh is None and not panel._mesh_cache._items
    jobs[1].release.set()
    ready(qtbot, panel)
    assert panel._view.mesh.triangles[0, 0, 0] == 10
    assert len(panel._mesh_cache._items) == 1
    panel.set_document(doc)
    start_pending(panel)
    qtbot.waitUntil(lambda: len(jobs) == 3 and jobs[2].entered.is_set(), timeout=5000)
    jobs[2].release.set()
    ready(qtbot, panel)
    assert panel._view.mesh.triangles[0, 0, 0] == 0
    assert panel.shutdown()


def test_mutable_document_changed_without_signal_is_rejected(qtbot, monkeypatch):
    jobs = []

    class Job:
        def __init__(self):
            self.entered, self.release = Event(), Event()
            jobs.append(self)

        def run(self, document, *, deviation):
            self.entered.set()
            assert self.release.wait(10)
            return fake_mesh(document['anchors_mm']['front'][0])

        def cancel(self):
            self.release.set()

    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    doc = draft()
    panel = new_panel(qtbot, doc)
    qtbot.waitUntil(lambda: jobs and jobs[0].entered.is_set(), timeout=5000)
    doc['anchors_mm']['front'][0] = 10.
    jobs[0].release.set()
    qtbot.waitUntil(lambda: panel._worker is None, timeout=5000)
    assert not panel._ready and panel._view.mesh is None and not panel._mesh_cache._items
    assert 'изменился' in panel._status.text()
    assert panel.shutdown()


def test_stale_external_state_blocks_cache_hit(qtbot, monkeypatch):
    calls = install_instant_job(monkeypatch)
    doc = draft()
    is_current = [True]
    panel = new_panel(qtbot, doc, current=lambda _doc: is_current[0])
    ready(qtbot, panel)
    panel._enable.setChecked(False)
    is_current[0] = False
    panel._enable.setChecked(True)
    start_pending(panel)
    assert not panel._ready and panel._view.mesh is None and len(calls) == 1
    assert 'изменился' in panel._status.text()
    assert panel.shutdown()


def test_failed_worker_does_not_cache_and_retry_forces_new_process(qtbot, monkeypatch):
    from suspensionlab.core.cad_transport import CadPreviewError

    calls = []

    class Job:
        def cancel(self):
            pass

        def run(self, document, *, deviation):
            calls.append(deviation)
            if len(calls) == 1:
                raise CadPreviewError('missing_cad')
            return fake_mesh(5)

    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    panel = new_panel(qtbot, draft())
    qtbot.waitUntil(lambda: panel._worker is None and panel._retry.isEnabled(), timeout=5000)
    assert not panel._mesh_cache._items and panel._view.mesh is None
    panel._retry.click()
    start_pending(panel)
    ready(qtbot, panel)
    assert len(calls) == 2 and panel._mesh_cache._items
    assert panel.shutdown()


@pytest.mark.parametrize('index', [0, 1])
def test_uncacheable_document_uses_ordinary_worker(qtbot, monkeypatch, index):
    calls = install_instant_job(monkeypatch)
    doc = draft()
    doc['extra'] = (1, 2) if index == 0 else [0] * 100001
    panel = new_panel(qtbot, doc)
    ready(qtbot, panel)
    assert not panel._mesh_cache._items
    panel._enable.setChecked(False)
    panel._enable.setChecked(True)
    start_pending(panel)
    ready(qtbot, panel)
    assert len(calls) == 2
    assert panel.shutdown()


def test_forced_failure_invalidates_cached_entry(qtbot, monkeypatch):
    from suspensionlab.core.cad_transport import CadPreviewError

    calls = []

    class Job:
        def cancel(self):
            pass

        def run(self, document, *, deviation):
            calls.append(deviation)
            if len(calls) == 2:
                raise CadPreviewError('missing_cad')
            return fake_mesh(5)

    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    panel = new_panel(qtbot, draft())
    ready(qtbot, panel)
    assert panel._mesh_cache._items
    panel.set_workspace_compact(True)
    assert not panel._retry.isHidden()
    panel._retry.click()
    start_pending(panel)
    qtbot.waitUntil(lambda: panel._worker is None and panel._retry.isEnabled(), timeout=5000)
    assert panel._view.mesh is None and not panel._mesh_cache._items
    panel._enable.setChecked(False)
    panel._enable.setChecked(True)
    start_pending(panel)
    ready(qtbot, panel)
    assert len(calls) == 3 and not panel._active_cache_hit
    assert panel.shutdown()


def test_shutdown_discards_late_result_and_cache(qtbot, monkeypatch):
    jobs = []

    class Job:
        def __init__(self):
            self.entered, self.release = Event(), Event()
            jobs.append(self)

        def run(self, document, *, deviation):
            self.entered.set()
            assert self.release.wait(10)
            return fake_mesh(0)

        def cancel(self):
            self.release.set()

    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    panel = new_panel(qtbot, draft())
    qtbot.waitUntil(lambda: jobs and jobs[0].entered.is_set(), timeout=5000)
    assert panel.shutdown()
    qtbot.waitUntil(lambda: panel._worker is None, timeout=5000)
    assert not panel._ready and panel._view.mesh is None and not panel._mesh_cache._items

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
        def run(self, document, *, deviation=2.):
            self.started.set()
            assert self.release.wait(10)
            x = document['parts'][0]['geometry']['source']['coordinates_mm'][2][0]
            return CadMesh(np.array([[[x, 0, 0], [x, 1, 0], [x, 0, 1]],
                                     [[x, 2, 0], [x, 3, 0], [x, 2, 1]]]), 2,
                           part_names=('tube_front', 'tube_rear'), triangle_parts=np.array([0, 1]))
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
        def run(self, document, *, deviation=2.):
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
        def run(self, document, *, deviation=2.):
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


def test_quality_change_cancels_old_job_and_rebuilds(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import weldment_3d as module

    jobs = []
    class Job:
        def __init__(self):
            self.release = threading.Event()
            self.started = threading.Event()
            self.cancelled = False
            self.deviation = None
            jobs.append(self)
        def cancel(self):
            self.cancelled = True
        def run(self, document, *, deviation=2.):
            self.deviation = deviation
            self.started.set()
            assert self.release.wait(10)
            x = deviation
            return CadMesh(np.array([[[x, 0, 0], [x, 1, 0], [x, 0, 1]],
                                     [[x, 2, 0], [x, 3, 0], [x, 2, 1]]]), 2,
                           part_names=('tube_front', 'tube_rear'), triangle_parts=np.array([0, 1]))
    monkeypatch.setattr(module, 'WeldmentCadJob', Job)
    _, d = setup_dialog(qtbot, tmp_path, monkeypatch)
    panel = d._three_d
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: len(jobs) == 1 and jobs[0].started.is_set(), timeout=5000)
    assert jobs[0].deviation == 0.2 and not d._save.isEnabled()
    panel._quality.setCurrentIndex(1)
    assert jobs[0].cancelled and panel._view.mesh is None and not d._save.isEnabled()
    jobs[0].release.set()
    qtbot.waitUntil(lambda: len(jobs) == 2 and jobs[1].started.is_set(), timeout=5000)
    assert jobs[1].deviation == 2.0 and panel._view.mesh is None
    jobs[1].release.set()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=5000)
    assert panel._view.mesh.triangles[0, 0, 0] == 2.0 and d._save.isEnabled()
    assert d.shutdown()


def test_scheme_assembly_tree_search_highlight_and_stale_clear(qtbot):
    from copy import deepcopy

    from suspensionlab.model.entities import Project
    from suspensionlab.model.scheme_arm_assembly import make_plate, make_scheme_arm_assembly, set_assembly_plate
    from suspensionlab.ui.weldment_3d import Weldment3D

    doc = make_scheme_arm_assembly(Project.create_default(), 12, 2,
                                   {'axis': 'x', 'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 24})
    doc = set_assembly_plate(doc, make_plate(50, 40, 4, 7), {'normal': 'z', 'offset_mm': [0, 0, 0]})
    doc['parts'][0]['name'] = doc['parts'][1]['name'] = 'Повтор'
    snapshot = deepcopy(doc)
    triangles = np.array([[[i, 0, 0], [i, 1, 0], [i, 0, 1]] for i in range(5)], dtype=float)
    mesh = CadMesh(triangles, 5, part_names=tuple(p['id'] for p in doc['parts']),
                   triangle_parts=np.arange(5, dtype=np.int32))
    panel = Weldment3D(scheme_part=True, is_current=lambda candidate: candidate == doc)
    qtbot.addWidget(panel)
    panel.set_document(snapshot)
    panel._enable.setChecked(True)
    panel._timer.stop()
    generation = panel.generation
    panel._completed(generation, mesh)
    root = panel._parts_tree.topLevelItem(0)
    assert root is not None and root.childCount() == 5 and not panel._parts_panel.isHidden()
    assert root.child(0).text(0) == 'Повтор · tube_front'
    assert root.child(1).text(0) == 'Повтор · tube_rear'
    assert panel._view._highlight is None
    panel._view.yaw, panel._view.zoom = 1.25, 2
    panel._parts_tree.setCurrentItem(root.child(2))
    assert panel._view._highlight.tolist() == [False, False, True, False, False]
    assert panel._view.yaw == 1.25 and panel._view.zoom == 2 and panel.generation == generation
    panel._parts_filter.setText('TUBE_REAR')
    assert root.child(0).isHidden() and not root.child(1).isHidden() and panel._view._highlight is None
    panel._view.triangle_picked.emit(4)
    assert not panel._parts_filter.text() and panel._parts_tree.currentItem() is root.child(4)
    assert panel._view._highlight.tolist() == [False, False, False, False, True]
    panel._parts_tree.setCurrentItem(root)
    assert panel._view._highlight is None and panel.generation == generation
    panel._parts_tree.setCurrentItem(root.child(0))
    doc['parts'][0]['name'] = 'Изменено без обновления'
    panel._view.triangle_picked.emit(0)  # same selected group must still check freshness
    assert panel._view.mesh is None and panel._parts_tree.topLevelItemCount() == 0
    assert panel._parts_panel.isHidden() and not panel.can_save()
    panel._completed(generation - 1, mesh)
    assert panel._view.mesh is None
    assert panel.shutdown()


def test_scheme_assembly_tree_rejects_missing_or_misidentified_groups(qtbot):
    from suspensionlab.model.entities import Project
    from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly
    from suspensionlab.ui.weldment_3d import Weldment3D

    doc = make_scheme_arm_assembly(Project.create_default(), 12, 2,
                                   {'axis': 'x', 'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 24})
    triangles = np.array([[[i, 0, 0], [i, 1, 0], [i, 0, 1]] for i in range(4)], dtype=float)
    names = tuple(p['id'] for p in doc['parts'])
    panel = Weldment3D(scheme_part=True)
    qtbot.addWidget(panel)
    panel.set_document(doc)
    panel._enable.setChecked(True)
    panel._timer.stop()
    for mesh in (CadMesh(triangles, 4),
                 CadMesh(triangles, 4, part_names=tuple(reversed(names)), triangle_parts=np.arange(4)),
                 CadMesh(triangles, 4, part_names=names, triangle_parts=np.zeros(4, dtype=int))):
        panel._completed(panel.generation, mesh)
        assert panel._view.mesh is None and panel._parts_tree.topLevelItemCount() == 0 and not panel.can_save()
    assert panel.shutdown()


def test_front_pair_tree_has_four_independent_selectable_tubes(qtbot):
    from suspensionlab.model.entities import Project
    from suspensionlab.model.front_pair_snapshot import make_front_pair_snapshot
    from suspensionlab.model.front_tube_arm import make_front_tube_arm
    from suspensionlab.ui.weldment_3d import Weldment3D

    doc = make_front_pair_snapshot(make_front_tube_arm(Project.create_default(), 'front_upper_right', 10, 2))
    names = ('source_tube_front', 'source_tube_rear', 'paired_tube_front', 'paired_tube_rear')
    triangles = np.array([[[i, 0, 0], [i, 1, 0], [i, 0, 1]] for i in range(4)], dtype=float)
    mesh = CadMesh(triangles, 4, part_names=names, triangle_parts=np.arange(4))
    panel = Weldment3D(four_tubes=True, is_current=lambda candidate: candidate == doc)
    qtbot.addWidget(panel)
    panel.set_document(doc)
    panel._enable.setChecked(True)
    panel._timer.stop()
    token = panel.generation
    panel._completed(token, mesh)
    root = panel._parts_tree.topLevelItem(0)
    assert root is not None and root.childCount() == 4
    assert 'Исходный рычаг' in root.child(0).text(0) and 'Второй рычаг' in root.child(2).text(0)
    for i in range(4):
        panel._parts_tree.setCurrentItem(root.child(i))
        assert panel._view._highlight.tolist() == [j == i for j in range(4)]
    panel._view.triangle_picked.emit(1)
    assert panel._parts_tree.currentItem() is root.child(1)
    assert panel.generation == token
    panel._enable.setChecked(False)
    assert panel._view.mesh is None and panel._parts_tree.topLevelItemCount() == 0
    assert panel.shutdown()


def test_repeated_3d_widget_shutdown_during_worker(qtbot, monkeypatch):
    """Ограниченная проверка жизненного цикла, не доказательство отсутствия нативных сбоев."""
    from suspensionlab.model.entities import Project
    from suspensionlab.ui import weldment_3d

    jobs = []
    class Job:
        def __init__(self):
            self.started, self.stopped = threading.Event(), threading.Event()
            jobs.append(self)
        def run(self, document, *, deviation=2.):
            self.started.set()
            assert self.stopped.wait(5)
            raise CadPreviewError('cancelled')
        def cancel(self):
            self.stopped.set()
    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    doc = make_welded_arm(Project.create_default(), 12, 2, 'unknown')
    for _ in range(12):
        panel = weldment_3d.Weldment3D()
        panel.set_document(doc)
        panel._enable.setChecked(True)
        panel._timer.stop()
        panel._start()
        qtbot.waitUntil(lambda: jobs[-1].started.is_set(), timeout=5000)
        worker = panel._worker
        assert worker is not None and panel.shutdown() and not worker.isRunning()
        panel.close()
        panel.deleteLater()
        del panel, worker
        qtbot.wait(5)

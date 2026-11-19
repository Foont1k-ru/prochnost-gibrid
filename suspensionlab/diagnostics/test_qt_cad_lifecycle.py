"""Диагностика Qt с настоящими дочерними CAD-процессами, не часть обычного pytest."""
from copy import deepcopy

from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly
from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.scheme_arm_assembly_dialog import SchemeArmAssemblyDialog


def _running_process(panel):
    worker = panel._worker
    if worker is None:
        return False
    job = worker.job._job
    with job._lock:
        return job._process is not None and job._process.poll() is None


def _start_now(panel):
    panel._timer.stop()
    panel._start()


def test_two_real_cad_workers_rebuild_then_close(qtbot):
    # Два окна и два реальных процесса, как в зафиксированном Linux trace.
    controller = AppController()
    controller.new_project(project=load_template('ring'))
    doc = make_scheme_arm_assembly(controller.project, 12., 2., {'axis': 'x', 'outer_radius_mm': 14.,
                                                                   'bore_radius_mm': 7., 'length_mm': 24.})
    initial = deepcopy(doc)
    dialogs = [SchemeArmAssemblyDialog(controller, doc) for _ in range(2)]
    for dialog in dialogs:
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.three_d._enable.setChecked(True)
        _start_now(dialog.three_d)
    try:
        qtbot.waitUntil(lambda: all(_running_process(d.three_d) for d in dialogs), timeout=20000, interval=10)
        print('PHASE: both real CAD subprocesses active; invalidate', flush=True)
        previous = [d.three_d.generation for d in dialogs]
        for dialog in dialogs:
            dialog.axis.setCurrentIndex(dialog.axis.findData('y'))
            dialog.axis.setCurrentIndex(dialog.axis.findData('z'))
            assert dialog.three_d._view.mesh is None and dialog.three_d.generation > previous.pop(0)
        qtbot.waitUntil(lambda: all(d.three_d._view.mesh is not None and d.three_d.can_save() and d.three_d._worker is None
                                   for d in dialogs),
                        timeout=90000, interval=25)
        for dialog in dialogs:
            panel = dialog.three_d
            assert dialog.document['axis'] == panel._document['axis'] == 'z'
            assert panel._parts_tree.topLevelItem(0).childCount() == 4
            assert panel._view.mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
        print('PHASE: latest meshes accepted; start close-in-flight', flush=True)
        for dialog in dialogs:
            dialog.axis.setCurrentIndex(dialog.axis.findData('x'))
            _start_now(dialog.three_d)
        qtbot.waitUntil(lambda: all(_running_process(d.three_d) for d in dialogs), timeout=20000, interval=10)
        print('PHASE: close both windows while real CAD subprocesses active', flush=True)
        for dialog in dialogs:
            dialog._saved = deepcopy(dialog.document)  # avoid a modal confirmation in the diagnostic
            assert dialog.close()
            assert dialog.three_d._closed
            worker = dialog.three_d._worker
            assert worker is None or not worker.isRunning()
        qtbot.wait(100)
        assert doc == initial
        print('PHASE: close completed', flush=True)
    finally:
        for dialog in dialogs:
            dialog._saved = deepcopy(dialog.document)
            dialog.close()

"""Opt-in timing of real isolated weldment jobs and instrumented equivalents.

Run from suspensionlab: python diagnostics/weldment_job_stages.py --repeat 5
Measurements use the actual CadJob transport and worker, with diagnostics-only
wrappers for child stages. Synthetic example documents; not engineering checks.
"""
from __future__ import annotations

import argparse
import builtins
import json
import os
import platform
import statistics
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any


def child(args: list[str]) -> int:
    """Wrap only for the diagnostic process, not the shipping worker."""
    entry = perf_counter()
    import numpy as np

    from suspensionlab.core import cad_free_arm
    from suspensionlab.core import cad_weldment_worker as worker

    imported = perf_counter()
    timings: dict[str, float] = {}

    def record(name, fn):
        def wrapped(*a, **kw):
            start = perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                timings[name] = timings.get(name, 0.) + (perf_counter() - start) * 1000
        return wrapped

    original_import = builtins.__import__

    def timed_import(name, *a, **kw):
        if name == 'OCP.BRepCheck':
            return record('ocp_check_import_ms', original_import)(name, *a, **kw)
        return original_import(name, *a, **kw)

    for name in ('build_fixed_arm_housing_preview', 'build_weldment_tubes_preview', '_mesh_shape_grouped',
                 'create_grouped_mesh'):
        setattr(worker, name, record(name + '_ms', getattr(worker, name)))
    cad_free_arm.build_free_arm_tubes = record('build_free_arm_tubes_ms', cad_free_arm.build_free_arm_tubes)
    np.savez = record('save_npz_ms', np.savez)
    builtins.__import__ = timed_import
    try:
        before_main = perf_counter()
        result = worker.main(args)
        after_main = perf_counter()
    finally:
        builtins.__import__ = original_import
    output = Path(args[1])
    payload_bytes = output.stat().st_size if output.is_file() else 0
    trace = {'entry_s': entry, 'imported_s': imported, 'before_main_s': before_main, 'after_main_s': after_main,
             'timings_ms': timings, 'output_bytes': payload_bytes, 'status': result}
    Path(os.environ['SUSPENSIONLAB_BENCH_TRACE']).write_text(json.dumps(trace), encoding='utf-8')
    return result


def documents() -> dict[str, dict[str, Any]]:
    from suspensionlab.model.fixed_arm_housings import make_housing_preview
    from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document, preview_fixed_arm
    from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft
    from suspensionlab.model.free_arm_io import to_data
    from suspensionlab.model.templates import load_template

    straight = FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2)
    bent = FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2,
                        FreeArmBend((150, 20, 50), 20))
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    vertex = [(anchors[0][i] + anchors[2][i]) / 2 for i in range(3)]
    vertex[2] += 50
    arm = fixed_arm_tube_document(snapshot, project, 10, 2, {'front': {'vertex_mm': vertex, 'radius_mm': 20}})
    housing = {'outer_diameter_mm': 120, 'bore_diameter_mm': 30, 'length_mm': 200,
               'axis': [0, 0, 1], 'offset_mm': [10, -30, 12]}
    return {'free_straight': to_data(straight), 'free_bent': to_data(bent), 'snapshot_bent': arm,
            'snapshot_bent_housing': make_housing_preview(arm, None, ball_housing=housing)}


def measured_job(doc: dict[str, Any], *, instrumented: bool) -> tuple[Any, dict[str, Any]]:
    from suspensionlab.core import cad_transport as transport
    from suspensionlab.core.cad_weldment_job import WeldmentCadJob

    original_popen, original_mesh = transport.subprocess.Popen, transport.CadMesh
    trace_path = None
    info: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix='cad-stage-diagnostic-') as directory:
        trace_path = Path(directory) / 'trace.json'

        def popen(command, *args, **kwargs):
            info['launch_begin_s'] = perf_counter()
            if instrumented:
                assert command[1:3] == ['-m', 'suspensionlab.core.cad_weldment_worker']
                command = [sys.executable, str(Path(__file__).resolve()), '--worker', *command[3:]]
                kwargs['env'] = {**kwargs['env'], 'SUSPENSIONLAB_BENCH_TRACE': str(trace_path)}
            process = original_popen(command, *args, **kwargs)
            info['launch_return_s'] = perf_counter()

            class ProcessProxy:
                def __getattr__(self, key):
                    return getattr(process, key)

                def wait(self, *a, **kw):
                    code = process.wait(*a, **kw)
                    info['wait_return_s'] = perf_counter()
                    return code

            return ProcessProxy()

        def mesh(*args, **kwargs):
            start = perf_counter()
            try:
                return original_mesh(*args, **kwargs)
            finally:
                info['cadmesh_validate_ms'] = (perf_counter() - start) * 1000

        try:
            transport.subprocess.Popen = popen
            transport.CadMesh = mesh
            begin = perf_counter()
            result = WeldmentCadJob().run(doc, deviation=2.)
            end = perf_counter()
        finally:
            transport.subprocess.Popen = original_popen
            transport.CadMesh = original_mesh
        info['job_total_ms'] = (end - begin) * 1000
        info['input_before_launch_ms'] = (info['launch_begin_s'] - begin) * 1000
        info['popen_ms'] = (info['launch_return_s'] - info['launch_begin_s']) * 1000
        info['launch_to_wait_ms'] = (info['wait_return_s'] - info['launch_begin_s']) * 1000
        info['post_wait_ms'] = (end - info['wait_return_s']) * 1000
        if instrumented:
            trace = json.loads(trace_path.read_text(encoding='utf-8'))
            info.update(trace['timings_ms'])
            info['process_start_to_entry_ms'] = (trace['entry_s'] - info['launch_begin_s']) * 1000
            info['worker_module_import_ms'] = (trace['imported_s'] - trace['entry_s']) * 1000
            info['worker_main_ms'] = (trace['after_main_s'] - trace['before_main_s']) * 1000
            info['after_main_to_wait_ms'] = (info['wait_return_s'] - trace['after_main_s']) * 1000
            info['output_bytes'] = trace['output_bytes']
        for name in ('launch_begin_s', 'launch_return_s', 'wait_return_s'):
            info.pop(name)
        return result, info


def same_mesh(first, second) -> bool:
    import numpy as np

    return (first.face_count == second.face_count and first.skipped_faces == second.skipped_faces and
            first.recovered_faces == second.recovered_faces and first.part_names == second.part_names and
            first.instance_groups == second.instance_groups and
            np.array_equal(first.triangles, second.triangles) and
            np.array_equal(first.triangle_parts, second.triangle_parts) and
            np.array_equal(first.triangle_instances, second.triangle_instances))


def describe(values: list[float]) -> dict[str, float]:
    return {'median': round(statistics.median(values), 3), 'min': round(min(values), 3),
            'max': round(max(values), 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error('repeat must be 1..20')
    output: dict[str, Any] = {'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                                            'numpy': version('numpy'), 'ocp': version('cadquery-ocp-novtk'),
                                            'repeat': args.repeat, 'deviation_mm': 2.,
                                            'method': 'fresh subprocess; alternating instrumented and production; '
                                                      'compare exact outputs; overlapping stage durations'},
                              'cases': {}}
    for name, doc in documents().items():
        runs: dict[str, list[dict[str, Any]]] = {'instrumented': [], 'production': []}
        for i in range(args.repeat):
            measurements = {}
            order = (False, True) if i % 2 == 0 else (True, False)
            for instrumented in order:
                value, timing = measured_job(doc, instrumented=instrumented)
                measurements[instrumented] = value
                runs['instrumented' if instrumented else 'production'].append(timing)
            if not same_mesh(measurements[False], measurements[True]):
                raise RuntimeError(f'{name}: instrumented and production meshes differ')
        case: dict[str, Any] = {'triangles': len(value.triangles), 'groups': len(value.part_names),
                                'samples': runs, 'summary': {}}
        for variant, samples in runs.items():
            keys = set.intersection(*(set(sample) for sample in samples))
            case['summary'][variant] = {key: describe([sample[key] for sample in samples])
                                        for key in sorted(keys)}
        output['cases'][name] = case
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        raise SystemExit(child(sys.argv[2:]))
    main()

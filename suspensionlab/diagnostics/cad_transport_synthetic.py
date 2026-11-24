"""Time synthetic mesh transfer through real CadJob reader; no CAD or rendering.

Run from suspensionlab: python diagnostics/cad_transport_synthetic.py --repeat 7
The subprocess deliberately substitutes deterministic mesh output for the CAD
worker; it is not a CAD job, production load-time measurement or strength test.
"""
from __future__ import annotations

import argparse
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


def arrays(count: int) -> tuple[Any, Any]:
    import numpy as np

    triangles = np.arange(count * 9, dtype=np.float64).reshape(count, 3, 3) / 1000.
    groups = np.arange(count, dtype=np.int32) % 100
    return triangles, groups


def child(args: list[str]) -> int:
    import numpy as np

    _source, output, report, _deviation = args
    triangles, groups = arrays(int(os.environ['CAD_BENCH_SIZE']))
    start = perf_counter()
    np.savez(output, triangles=triangles, faces=np.array([len(triangles)], dtype=np.int64),
             skipped=np.array([0], dtype=np.int64), recovered=np.array([0], dtype=np.int64),
             names=np.array([f'group_{i}' for i in range(100)], dtype='U128'), groups=groups,
             instance_groups=np.array([0], dtype=np.int32), instances=np.zeros(len(triangles), dtype=np.int32))
    saved = perf_counter()
    Path(report).write_text(json.dumps({'status': 'ok'}), encoding='utf-8')
    Path(os.environ['CAD_BENCH_TRACE']).write_text(json.dumps({'save_ms': (saved - start) * 1000,
                                                              'archive_bytes': Path(output).stat().st_size}),
                                                  encoding='utf-8')
    return 0


def run(count: int) -> tuple[Any, dict[str, float]]:
    from suspensionlab.core import cad_transport as transport

    original_popen, original_mesh = transport.subprocess.Popen, transport.CadMesh
    info: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix='cad-transport-diagnostic-') as directory:
        trace = Path(directory) / 'trace.json'

        def popen(command, *args, **kwargs):
            assert command[1:3] == ['-m', 'suspensionlab.core.cad_weldment_worker']
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', *command[3:]]
            kwargs['env'] = {**kwargs['env'], 'CAD_BENCH_TRACE': str(trace), 'CAD_BENCH_SIZE': str(count)}
            process = original_popen(command, *args, **kwargs)

            class ProcessProxy:
                def __getattr__(self, key):
                    return getattr(process, key)

                def wait(self, *a, **kw):
                    result = process.wait(*a, **kw)
                    info['wait_return_s'] = perf_counter()
                    return result

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
            start = perf_counter()
            result = transport.CadJob().run(Path(directory) / 'unused.kima', 2., timeout=60, mode='weldment')
            end = perf_counter()
        finally:
            transport.subprocess.Popen = original_popen
            transport.CadMesh = original_mesh
        info['total_ms'] = (end - start) * 1000
        info['process_and_wait_ms'] = (info['wait_return_s'] - start) * 1000
        info['post_wait_ms'] = (end - info.pop('wait_return_s')) * 1000
        info.update(json.loads(trace.read_text(encoding='utf-8')))
        return result, info


def describe(values: list[float]) -> dict[str, float]:
    return {'median': round(statistics.median(values), 3), 'min': round(min(values), 3),
            'max': round(max(values), 3)}


def main() -> None:
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error('repeat must be 1..20')
    out: dict[str, Any] = {'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                                           'numpy': version('numpy'), 'repeat': args.repeat,
                                           'groups': 100, 'producer': 'synthetic, not CAD',
                                           'method': 'fresh subprocess; real CadJob output reader'}, 'cases': {}}
    for count in (12000, 50000, 200000):
        expected, groups = arrays(count)
        runs = []
        for _ in range(args.repeat):
            mesh, timing = run(count)
            if (not np.array_equal(mesh.triangles, expected) or not np.array_equal(mesh.triangle_parts, groups) or
                    mesh.part_names != tuple(f'group_{i}' for i in range(100)) or
                    mesh.instance_groups != (0,) or np.any(mesh.triangle_instances != 0)):
                raise RuntimeError('incorrect synthetic transport')
            runs.append(timing)
        keys = set.intersection(*(set(sample) for sample in runs))
        out['cases'][str(count)] = {'samples': runs,
                                    'summary': {key: describe([sample[key] for sample in runs])
                                                for key in sorted(keys)}}
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        raise SystemExit(child(sys.argv[2:]))
    main()

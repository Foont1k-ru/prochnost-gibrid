"""Time fresh Python subprocess startup/import/exit; not an isolated CAD job benchmark."""
from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
from importlib.metadata import version
from time import perf_counter

CASES = {
    'empty_python': 'pass',
    'numpy': 'import numpy',
    'weldment_module': 'import suspensionlab.core.cad_weldment_worker',
    'weldment_and_ocp_check': ('import suspensionlab.core.cad_weldment_worker; '
                               'from OCP.BRepCheck import BRepCheck_Analyzer'),
}


def main():
    samples = {name: [] for name in CASES}
    # Alternate order to reduce (not eliminate) effects of changing load or filesystem cache.
    for i in range(10):
        items = list(CASES.items())
        if i % 2:
            items.reverse()
        for name, statement in items:
            start = perf_counter()
            subprocess.run([sys.executable, '-c', statement], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           check=True, timeout=30)
            samples[name].append((perf_counter() - start) * 1000)
    summary = {name: {'median_ms': round(statistics.median(values), 2), 'min_ms': round(min(values), 2),
                      'max_ms': round(max(values), 2)} for name, values in samples.items()}
    print(json.dumps({'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                                      'numpy': version('numpy'), 'ocp': version('cadquery-ocp-novtk'),
                                      'repeats': 10, 'order': 'alternating; includes process exit'},
                      'cases': summary}, indent=2))


if __name__ == '__main__':
    main()

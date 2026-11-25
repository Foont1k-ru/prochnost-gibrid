"""Opt-in benchmark of synthetic CPU preview preparation, not CAD construction."""
from __future__ import annotations

import json
import platform
import statistics
import sys
from time import perf_counter

import numpy as np
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication

from suspensionlab.core.cad_interaction import interaction_geometry, interaction_geometry_by_part
from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.ui.canvas.cad_preview import CadPreview


def timing(fn, repeats=5):
    samples = []
    result = None
    for _ in range(repeats):
        start = perf_counter()
        result = fn()
        samples.append((perf_counter() - start) * 1000)
    return result, {"median_ms": round(statistics.median(samples), 2), "min_ms": round(min(samples), 2),
                    "max_ms": round(max(samples), 2)}


def run(count, parts):
    rng = np.random.default_rng(20261112)
    centers = rng.uniform(-100, 100, (count, 1, 3))
    triangles = centers + rng.normal(0, 1, (count, 3, 3))
    groups = np.arange(count, dtype=np.int32) % parts
    mesh = CadMesh(triangles, parts, part_names=tuple(f'part_{i}' for i in range(parts)), triangle_parts=groups)
    selected = (np.arange(count) % 7 == 0)
    fast, grouped = timing(lambda: interaction_geometry_by_part(mesh))
    _, partial = timing(lambda: interaction_geometry(mesh, selected))
    view = CadPreview()

    def setup():
        view.set_mesh(None)
        view.set_mesh(mesh)

    try:
        _, setup_time = timing(setup)
    finally:
        view.close()
    return {'triangles': count, 'groups': parts, 'fast_triangles': len(fast[0]),
            'group_simplification': grouped, 'partial_mask_simplification': partial, 'view_setup': setup_time}


def main():
    app = QApplication.instance() or QApplication([])
    cases = [(12000, 100), (50000, 1), (50000, 100), (200000, 1), (200000, 100), (200001, 100)]
    print(json.dumps({'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                                     'numpy': np.__version__, 'qt': qVersion(), 'qpa': 'offscreen',
                                     'repeats': 5, 'scene': 'synthetic random triangles, fixed seed',
                                     'device_pixel_ratio': app.devicePixelRatio()},
                      'cases': [run(*case) for case in cases]}, indent=2))


if __name__ == '__main__':
    main()

"""Локальный CPU-эксперимент с синтетической сеткой; не тест GPU или STEP."""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from time import perf_counter

import numpy as np
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.ui.canvas.cad_preview import CadPreview


def measure(callable_) -> float:
    start = perf_counter()
    callable_()
    return (perf_counter() - start) * 1000


def run(size: int, iterations: int, width: int, height: int) -> dict[str, object]:
    # Small random triangles, fixed seed. No user data, no geometric correctness claim.
    rng = np.random.default_rng(20261112)
    centers = rng.uniform(-100, 100, (size, 1, 3))
    triangles = centers + rng.normal(0, 1, (size, 3, 3))
    groups = np.arange(size, dtype=np.int32) % 2
    mesh = CadMesh(triangles, 1, part_names=('a', 'b'), triangle_parts=groups)
    view = CadPreview()
    view.resize(width, height)
    view.show()
    QApplication.processEvents()
    initial = measure(lambda: view.set_mesh(mesh))
    full_render = measure(lambda: view.grab())
    select, render_selected = [], []
    for index in range(iterations):
        mask = groups == (index % 2)
        select.append(measure(lambda mask=mask: view.set_mesh(mesh, mask)))
        render_selected.append(measure(lambda: view.grab()))
    moving_triangles = len(view._fast_triangles)
    view.close()
    return {'triangles': size, 'moving_triangles': moving_triangles, 'initial_setup_ms': round(initial, 1),
            'first_full_frame_ms': round(full_render, 1),
            'selection_setup_median_ms': round(statistics.median(select), 1),
            'selection_full_frame_median_ms': round(statistics.median(render_selected), 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', type=int, nargs='+', default=[12000, 50000, 200000])
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--width', type=int, default=800)
    parser.add_argument('--height', type=int, default=600)
    args = parser.parse_args()
    if (not all(1 <= size <= 250000 for size in args.sizes) or not 1 <= args.iterations <= 10 or
            not 320 <= args.width <= 2000 or not 280 <= args.height <= 2000):
        parser.error('outside diagnostic limits')
    app = QApplication.instance() or QApplication([])
    output = {'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                              'numpy': np.__version__, 'qt': qVersion(), 'qpa': os.getenv('QT_QPA_PLATFORM'),
                              'screen_logical_px': [args.width, args.height],
                              'device_pixel_ratio': app.devicePixelRatio()},
              'results': [run(size, args.iterations, args.width, args.height) for size in args.sizes]}
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()

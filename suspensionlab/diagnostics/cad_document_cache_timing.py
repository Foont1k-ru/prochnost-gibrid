"""Real CAD worker vs repeat cache hit, timing until UI accepts the mesh.

Run offscreen from suspensionlab: python diagnostics/cad_document_cache_timing.py
Excludes the deliberate 250 ms debounce, actual painting and user interaction.
The worker path is a forced rebuild, not an uncached first-start speedup.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from weldment_job_stages import documents, same_mesh

from suspensionlab.ui.weldment_3d import Weldment3D


def run(panel: Weldment3D, *, force: bool) -> tuple[float, object]:
    loop = QEventLoop()
    timed_out = False
    timer = QTimer()
    timer.setSingleShot(True)

    def timeout() -> None:
        nonlocal timed_out
        timed_out = True
        loop.quit()

    def changed(available: bool) -> None:
        if available:
            loop.quit()

    timer.timeout.connect(timeout)
    panel.availabilityChanged.connect(changed)
    panel._schedule(force=force)
    panel._timer.stop()
    start = perf_counter()
    timer.start(90_000)
    panel._start()
    if not panel._ready:
        loop.exec()
    elapsed = (perf_counter() - start) * 1000
    timer.stop()
    panel.availabilityChanged.disconnect(changed)
    if timed_out or not panel._ready or panel._view.mesh is None:
        raise RuntimeError(f'CAD preview failed: {panel._status.text()}')
    # Process the worker finished signal before scheduling the next run.
    while panel._worker is not None:
        QApplication.processEvents()
    return elapsed, panel._view.mesh


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error('repeat must be 1..20')
    app = QApplication.instance() or QApplication([])
    output = {'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                              'numpy': version('numpy'), 'ocp': version('cadquery-ocp-novtk'),
                              'repeat': args.repeat, 'deviation_mm': 2.,
                              'method': 'same panel and document; forced process then cache hit; '
                                        'mesh-ready, excluding 250ms debounce and paint'}, 'cases': {}}
    for name, document in documents().items():
        panel = Weldment3D(fixed_skeleton=True, is_current=lambda candidate, doc=document: candidate == doc)
        panel.set_document(document)
        panel._quality.setCurrentIndex(1)
        panel._enable.setChecked(True)
        panel._timer.stop()
        cold, hit = [], []
        try:
            for _ in range(args.repeat):
                elapsed, original = run(panel, force=True)
                assert not panel._active_cache_hit
                cold.append(elapsed)
                elapsed, cached = run(panel, force=False)
                assert panel._active_cache_hit and same_mesh(original, cached)
                hit.append(elapsed)
            output['cases'][name] = {'forced_ms': cold, 'cache_hit_ms': hit,
                                     'forced_median_ms': statistics.median(cold),
                                     'cache_hit_median_ms': statistics.median(hit),
                                     'triangles': len(cached.triangles)}
            print(name, output['cases'][name], flush=True)
        finally:
            panel.shutdown()
            panel.deleteLater()
            app.processEvents()
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

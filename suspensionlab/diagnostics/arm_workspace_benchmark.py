"""Opt-in local CAD/CPU-view benchmark. Synthetic data only; not a frame or strength test.

Run from suspensionlab: QT_QPA_PLATFORM=offscreen python diagnostics/arm_workspace_benchmark.py
The isolated CAD job total is measured separately from in-process stage timings.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from collections.abc import Callable
from functools import partial
from time import perf_counter
from typing import Any

import numpy as np
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication

from suspensionlab.core.cad_kim_prototype import build_fixed_arm_housing_preview, build_weldment_tubes_preview
from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_preview_parts import preview_parts
from suspensionlab.core.cad_raster import pick_triangle
from suspensionlab.core.cad_weldment_job import WeldmentCadJob
from suspensionlab.core.cad_weldment_worker import _mesh_shape_grouped, _parts_at_paths
from suspensionlab.model.fixed_arm_housings import make_housing_preview
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document, preview_fixed_arm
from suspensionlab.model.templates import load_template
from suspensionlab.ui.canvas.cad_preview import CadPreview


def timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    start = perf_counter()
    value = fn()
    return value, (perf_counter() - start) * 1000


def stats(values: list[float]) -> dict[str, float]:
    return {'median': round(statistics.median(values), 2), 'min': round(min(values), 2),
            'max': round(max(values), 2)}


def documents() -> dict[str, dict[str, Any]]:
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    vertex = [(anchors[0][i] + anchors[2][i]) / 2 for i in range(3)]
    vertex[2] += 50
    straight = fixed_arm_tube_document(snapshot, project, 10, 2)
    bent = fixed_arm_tube_document(snapshot, project, 10, 2,
                                   {'front': {'vertex_mm': vertex, 'radius_mm': 20}})
    housing = {'outer_diameter_mm': 120, 'bore_diameter_mm': 30, 'length_mm': 200,
               'axis': [0, 0, 1], 'offset_mm': [10, -30, 12]}
    return {'straight': straight, 'bent': bent,
            'bent_and_housing': make_housing_preview(bent, None, ball_housing=housing)}


def cad_timing(doc: dict[str, Any], repeat: int) -> tuple[CadMesh, dict[str, Any]]:
    from OCP.BRepCheck import BRepCheck_Analyzer

    build, check, triangulate, isolated = [], [], [], []
    mesh = None
    for _ in range(repeat):
        builder = build_fixed_arm_housing_preview if doc.get('format') == 'suspensionlab-fixed-arm-housing-preview' else build_weldment_tubes_preview
        shape, ms = timed(partial(builder, doc))
        build.append(ms)
        valid, ms = timed(partial(lambda shape: BRepCheck_Analyzer(shape).IsValid(), shape))
        if not valid:
            raise RuntimeError('CAD shape invalid')
        check.append(ms)
        descriptors = preview_parts(doc)
        parts = _parts_at_paths(shape, [part.path for part in descriptors])
        result, ms = timed(partial(_mesh_shape_grouped, shape, parts, 2.))
        triangulate.append(ms)
        triangles, faces, groups = result
        mesh = CadMesh(triangles, faces, part_names=tuple(part.identifier for part in descriptors),
                       triangle_parts=groups)
        _, ms = timed(lambda: WeldmentCadJob().run(doc, deviation=2.))
        isolated.append(ms)
    assert mesh is not None
    return mesh, {'build_ms': stats(build), 'shape_check_ms': stats(check),
                  'triangulation_and_extract_ms': stats(triangulate), 'isolated_job_total_ms': stats(isolated),
                  'triangles': len(mesh.triangles), 'parts': len(mesh.part_names)}


def synthetic(triangles: int, groups: int) -> CadMesh:
    rng = np.random.default_rng(20261112)
    centers = rng.uniform(-100, 100, (triangles, 1, 3))
    mesh = centers + rng.normal(0, 1, (triangles, 3, 3))
    group_ids = np.arange(triangles, dtype=np.int32) % groups
    return CadMesh(mesh, groups, part_names=tuple(f'part_{i}' for i in range(groups)), triangle_parts=group_ids)


def view_timing(mesh: CadMesh, repeat: int, width: int, height: int) -> dict[str, Any]:
    view = CadPreview()
    view.resize(width, height)
    view.show()
    QApplication.processEvents()
    try:
        _, setup = timed(lambda: view.set_mesh(mesh))
        _, first = timed(view.grab)
        frames, moving_frames, picks, selections = [], [], [], []
        for i in range(repeat):
            view.yaw += 0.07
            _, ms = timed(view.grab)
            frames.append(ms)
            view._moving = True
            view.yaw += 0.01
            _, ms = timed(view.grab)
            moving_frames.append(ms)
            view._moving = False
            ratio = view.devicePixelRatioF()
            w, h = round(view.width() * ratio), round(view.height() * ratio)
            _, ms = timed(partial(pick_triangle, mesh.triangles, view._center, view._radius, view.yaw, view.elevation,
                                  view.zoom, w, h, w // 2, h // 2, margin=24 * ratio,
                                  offset=view._pixel_offset(w, h)))
            picks.append(ms)
            mask = mesh.triangle_parts == (i % len(mesh.part_names))
            _, ms = timed(partial(view.set_mesh, mesh, mask))
            selections.append(ms)
        return {'triangles': len(mesh.triangles), 'parts': len(mesh.part_names),
                'mesh_array_mib': round((mesh.triangles.nbytes + mesh.triangle_parts.nbytes) / 1024**2, 2),
                'interaction_triangles': len(view._fast_triangles), 'setup_ms': round(setup, 2),
                'first_frame_ms': round(first, 2), 'rotated_full_frame_ms': stats(frames),
                'moving_frame_ms': stats(moving_frames), 'center_pick_ms': stats(picks),
                'selection_setup_ms': stats(selections)}
    finally:
        view.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--sizes', type=int, nargs='+', default=[12000, 50000, 200000])
    parser.add_argument('--groups', type=int, default=100)
    parser.add_argument('--width', type=int, default=800)
    parser.add_argument('--height', type=int, default=600)
    args = parser.parse_args()
    if (not 1 <= args.repeat <= 10 or not 1 <= args.groups <= 512 or
            not args.sizes or not all(args.groups <= size <= 250000 for size in args.sizes) or
            not 320 <= args.width <= 2000 or not 280 <= args.height <= 2000):
        parser.error('outside benchmark limits')
    app = QApplication.instance() or QApplication([])
    result: dict[str, Any] = {'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                               'numpy': np.__version__, 'qt': qVersion(), 'qpa': os.getenv('QT_QPA_PLATFORM'),
                               'logical_size_px': [args.width, args.height], 'device_pixel_ratio': app.devicePixelRatio(),
                               'renderer': 'CPU'}, 'cad': {}, 'synthetic_many_parts': []}
    for name, doc in documents().items():
        mesh, cad = cad_timing(doc, args.repeat)
        result['cad'][name] = {'geometry': cad, 'view': view_timing(mesh, args.repeat, args.width, args.height)}
    for size in args.sizes:
        result['synthetic_many_parts'].append(view_timing(synthetic(size, args.groups), args.repeat, args.width, args.height))
    if sys.platform.startswith('linux'):
        import resource
        # Process high-water mark, includes all previous cases, not per-case GPU memory or child processes.
        result['process_peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

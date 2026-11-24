"""Compare an explicit local reference module and current simplifier in alternating order.

The supplied file is Python code and is executed; pass only a trusted local copy.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

from suspensionlab.core import cad_interaction as current
from suspensionlab.core.cad_mesh import CadMesh


def describe(samples):
    return {'median_ms': round(statistics.median(samples), 2), 'min_ms': round(min(samples), 2),
            'max_ms': round(max(samples), 2)}


def run(old, count, groups, repeat):
    rng = np.random.default_rng(20261112)
    triangles = rng.uniform(-100, 100, (count, 1, 3)) + rng.normal(0, 1, (count, 3, 3))
    parts = np.arange(count, dtype=np.int32) % groups
    mesh = CadMesh(triangles, groups, part_names=tuple(f'part_{i}' for i in range(groups)), triangle_parts=parts)
    reference = old.interaction_geometry_by_part(mesh)
    actual = current.interaction_geometry_by_part(mesh)
    if not all(np.array_equal(x, y) for x, y in zip(reference, actual, strict=True)):
        raise AssertionError('reference and current outputs differ')
    samples = [[], []]
    for i in range(repeat):
        for j in ((0, 1) if i % 2 == 0 else (1, 0)):
            start = perf_counter()
            (old if j == 0 else current).interaction_geometry_by_part(mesh)
            samples[j].append((perf_counter() - start) * 1000)
    return {'triangles': count, 'groups': groups, 'fast_triangles': len(actual[0]),
            'before': describe(samples[0]), 'after': describe(samples[1])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path, help='trusted copy of previous cad_interaction.py')
    parser.add_argument('--repeat', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error('repeat must be 1–20')
    spec = importlib.util.spec_from_file_location('suspensionlab.core._interaction_reference', args.reference)
    if spec is None or spec.loader is None:
        parser.error('invalid reference file')
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    cases = [(50000, 1), (50000, 100), (200000, 1), (200000, 100), (200001, 100)]
    print(json.dumps({'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                                     'numpy': np.__version__, 'repeats': args.repeat,
                                     'scene': 'synthetic random triangles, fixed seed',
                                     'order': 'alternating after warmup'},
                      'cases': [run(old, n, g, args.repeat) for n, g in cases]}, indent=2))


if __name__ == '__main__':
    main()

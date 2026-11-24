"""Opt-in CPU raster timings using synthetic triangles; not a CAD/GPU/Windows test."""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
from time import perf_counter

import numpy as np
from PIL import __version__ as pillow_version

from suspensionlab.core.cad_raster import rasterize, triangle_shades


def run(count: int, repeat: int) -> dict:
    rng = np.random.default_rng(20261112)
    centers = rng.uniform(-100, 100, (count, 1, 3))
    triangles = centers + rng.normal(0, 1, (count, 3, 3))
    shades = triangle_shades(triangles)
    selected = np.arange(count) % 100 == 0
    cases = ((1., False, False), (1., True, False), (1., True, True), (4., True, False))
    results = {}
    for zoom, highlight, through in cases:
        times = []
        for _ in range(repeat):
            start = perf_counter()
            image = rasterize(triangles, shades, np.zeros(3), 175., -.65, .35, zoom, 800, 600, (10, 20, 30),
                              highlight=selected if highlight else None, through=through)
            assert image.mode == 'RGB' and image.size == (800, 600)
            times.append((perf_counter() - start) * 1000)
        key = f'zoom_{zoom:g}_highlight_{int(highlight)}_through_{int(through)}'
        results[key] = {'median_ms': round(statistics.median(times), 2), 'min_ms': round(min(times), 2),
                        'max_ms': round(max(times), 2)}
    return {'triangles': count, 'results': results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', nargs='+', type=int, default=[12000, 50000, 200000])
    parser.add_argument('--repeat', type=int, default=5)
    args = parser.parse_args()
    if not args.sizes or not all(1 <= n <= 250000 for n in args.sizes) or not 1 <= args.repeat <= 10:
        parser.error('outside diagnostic limits')
    print(json.dumps({'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                                      'numpy': np.__version__, 'pillow': pillow_version,
                                      'resolution_px': [800, 600], 'repeat': args.repeat,
                                      'scene': 'synthetic random triangles, fixed seed'},
                      'cases': [run(count, args.repeat) for count in args.sizes]}, indent=2))


if __name__ == '__main__':
    main()

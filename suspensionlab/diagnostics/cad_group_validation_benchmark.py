"""Paired CPU benchmark for checking that all displayed mesh groups have triangles.

Run from the project directory with NumPy installed. Synthetic groups are not CAD,
and timings exclude CadMesh construction, GUI, rendering and worker transport.
"""
from __future__ import annotations

import json
import platform
import statistics
import time
from pathlib import Path

import numpy as np

from suspensionlab.core.cad_mesh import CadMesh


def repeated_scans(parts: np.ndarray, count: int) -> bool:
    return all((parts == index).any() for index in range(count))


def benchmark(triangles: int, groups: int, *, missing: bool, sorted_groups: bool = False,
              repetitions: int = 9) -> dict:
    rng = np.random.default_rng(82471 + triangles + groups)
    parts = np.arange(triangles, dtype=np.int32) % groups
    if sorted_groups:
        parts.sort()
    else:
        rng.shuffle(parts)
    if missing:
        parts[parts == groups - 1] = 0
    mesh = CadMesh(np.zeros((triangles, 3, 3), dtype=np.float64), 1,
                   part_names=tuple(f'part_{index}' for index in range(groups)), triangle_parts=parts)
    assert mesh.triangle_parts is not None
    parts = mesh.triangle_parts
    expected = not missing
    assert repeated_scans(parts, groups) == mesh.all_parts_present() == expected
    timings: dict[str, list[float]] = {'scan_ms': [], 'adaptive_ms': []}
    # Alternate order each pair so drift does not systematically favour one path.
    for iteration in range(repetitions):
        methods = [('scan_ms', lambda: repeated_scans(parts, groups)), ('adaptive_ms', mesh.all_parts_present)]
        if iteration % 2:
            methods.reverse()
        for key, method in methods:
            start = time.perf_counter_ns()
            result = method()
            timings[key].append((time.perf_counter_ns() - start) / 1e6)
            assert result == expected
    return {'triangles': triangles, 'groups': groups, 'missing_last_group': missing, 'sorted_groups': sorted_groups,
            **{key: {'median': statistics.median(values), 'min': min(values), 'max': max(values), 'all': values}
               for key, values in timings.items()}}


def main() -> None:
    results = [benchmark(n, groups, missing=missing, sorted_groups=sorted_groups)
               for n, groups, missing, sorted_groups in
               [(12_000, 2, False, False), (50_000, 100, False, False), (200_000, 100, False, False),
                (200_000, 512, False, False), (200_000, 512, False, True), (200_000, 512, True, True)]]
    report = {'python': platform.python_version(), 'platform': platform.platform(), 'numpy': np.__version__,
              'method': 'alternating paired runs; finite int32 group indices already validated by CadMesh',
              'results': results}
    path = Path('docs/cad_group_validation_timing.json')
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()

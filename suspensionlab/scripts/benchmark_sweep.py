"""Повторяемый замер только кинематического свипа, без порогов и UI.

Запуск из каталога suspensionlab: python -m scripts.benchmark_sweep
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from collections.abc import Sequence

import numpy as np
import scipy

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.model.templates import load_template

THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def _count(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Ожидается целое число") from error
    if not 1 <= number <= 200:
        raise argparse.ArgumentTypeError("Число повторов должно быть от 1 до 200")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=_count, default=7, help="Количество измерений (1–200)")
    parser.add_argument("--warmup", type=_count, default=2, help="Число прогревочных прогонов (1–200)")
    args = parser.parse_args(argv)
    # Создание модели и массива, импорт, UI, метрики и экспорт не измеряются.
    model = DoubleWishbone(load_template("ring").front, "left")
    travels = [float(value) for value in range(-30, 31)]
    for _ in range(args.warmup):
        model.sweep(travels, max_step_mm=1.0)
    elapsed = []
    for _ in range(args.repeat):
        start = time.perf_counter_ns()
        poses = model.sweep(travels, max_step_mm=1.0)
        duration_ms = (time.perf_counter_ns() - start) / 1_000_000
        if len(poses) != len(travels):
            raise RuntimeError("Свип вернул не все запрошенные точки")
        elapsed.append(duration_ms)
    report = {
        "scope": "DoubleWishbone.sweep only; model construction, metrics, GUI and export excluded",
        "template": "ring.front.left (educational geometry)",
        "from_mm": -30, "to_mm": 30, "grid_spacing_mm": 1, "points": len(travels),
        "max_continuation_step_mm": 1, "warmup": args.warmup, "repeats": args.repeat,
        "clock": "time.perf_counter_ns", "individual_ms": [round(value, 3) for value in elapsed],
        "min_ms": round(min(elapsed), 3), "median_ms": round(statistics.median(elapsed), 3),
        "max_ms": round(max(elapsed), 3),
        "python": platform.python_version(), "platform": platform.platform(),
        "machine": platform.machine(), "processor": platform.processor() or "unknown",
        "numpy": np.__version__, "scipy": scipy.__version__,
        "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
        "note": "Local measurement, not a performance guarantee or physical validation",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Проверяется воспроизводимость методики, не порог скорости на CI."""
import json

import pytest

from scripts.benchmark_sweep import main


def test_benchmark_reports_workload_and_all_measurements(capsys):
    assert main(["--repeat", "2", "--warmup", "1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["points"] == 61 and data["from_mm"] == -30 and data["to_mm"] == 30
    assert data["grid_spacing_mm"] == data["max_continuation_step_mm"] == 1
    assert data["repeats"] == 2 and data["warmup"] == 1
    assert len(data["individual_ms"]) == 2
    assert 0 <= data["min_ms"] <= data["median_ms"] <= data["max_ms"]
    assert "GUI and export excluded" in data["scope"]
    assert data["python"] and data["numpy"] and data["scipy"]
    assert "OPENBLAS_NUM_THREADS" in data["thread_environment"]


@pytest.mark.parametrize("args", [["--repeat", "0"], ["--repeat", "201"], ["--warmup", "-1"]])
def test_benchmark_rejects_unbounded_work(args):
    with pytest.raises(SystemExit):
        main(args)

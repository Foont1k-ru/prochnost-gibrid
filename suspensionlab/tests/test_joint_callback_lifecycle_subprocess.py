"""Focused parentless lifetime regression, isolated from the pytest GUI process."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_closed_parentless_joint_releases_current_callback_before_worker_gc():
    script = Path(__file__).resolve().parents[1] / 'diagnostics' / 'qt_callback_cycle_probe.py'
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONFAULTHANDLER': '1'}
    result = subprocess.run([sys.executable, '-u', str(script), '--child', 'control'],
                            env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=60, check=False)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    output = next(line.removeprefix('CYCLE_RESULT ') for line in result.stdout.splitlines()
                  if line.startswith('CYCLE_RESULT '))
    data = json.loads(output)
    assert data['before_worker_gc'] == {'weakref_alive': False, 'destroyed_on_gui': [True]}
    assert data['after_worker_gc'] == {'weakref_alive': False, 'destroyed_on_gui': [True]}

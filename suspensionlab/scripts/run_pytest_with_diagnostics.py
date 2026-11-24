"""Run pytest with crash output recorded even if no JUnit report is produced."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    env = {**os.environ, 'PYTHONFAULTHANDLER': '1', 'PYTHONUTF8': '1'}
    output = Path(os.environ.get('PYTEST_DIAGNOSTIC_LOG', 'python311-console.txt'))
    with output.open('wb') as stream:
        result = subprocess.run([sys.executable, '-u', '-m', 'pytest', *sys.argv[1:]],
                                stdout=stream, stderr=subprocess.STDOUT, env=env, check=False)
    text = output.read_text(encoding='utf-8', errors='replace')
    print(text, flush=True)
    if result.returncode:
        tail = text[-12000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::error title=Python test output::{tail}', flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())

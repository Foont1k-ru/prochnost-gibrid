"""Диагностический запуск сохраняет текст даже при отсутствии JUnit."""
import subprocess
import sys
from types import SimpleNamespace

from scripts import run_pytest_with_diagnostics


def test_runner_keeps_unbuffered_failure_output(tmp_path, monkeypatch, capsys):
    output = tmp_path / 'console.txt'
    monkeypatch.setenv('PYTEST_DIAGNOSTIC_LOG', str(output))
    monkeypatch.setattr(sys, 'argv', ['runner', '-v', 'tests/example.py'])
    def run(command, *, stdout, stderr, env, check):
        assert command == [sys.executable, '-u', '-m', 'pytest', '-v', 'tests/example.py']
        assert stderr is subprocess.STDOUT and not check
        assert env['PYTHONFAULTHANDLER'] == '1' and env['PYTHONUTF8'] == '1'
        stdout.write(b'tests/example.py::test_example % FAILED\nWindows fatal exception')
        return SimpleNamespace(returncode=17)
    monkeypatch.setattr(subprocess, 'run', run)
    assert run_pytest_with_diagnostics.main() == 17
    assert 'Windows fatal exception' in output.read_text(encoding='utf-8')
    assert '::error title=Python test output::' in capsys.readouterr().out

"""Запуск CAD-предпросмотра в отдельном ограниченном по времени процессе."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

import numpy as np

from .cad_mesh import CadMesh


class CadPreviewError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CadJob:
    """Одноразовый процесс; отмена также работает до старта процесса."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                with suppress(OSError):
                    self._process.kill()

    def run(self, source: Path, deviation: float, *, timeout: float = 120) -> CadMesh:
        if self._cancelled.is_set():
            raise CadPreviewError("cancelled")
        with tempfile.TemporaryDirectory(prefix="suspension-cad-") as directory:
            output, report = Path(directory) / "mesh.npz", Path(directory) / "result.json"
            args = [str(source), str(output), str(report), str(deviation)]
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--cad-preview-worker", *args]
            else:
                command = [sys.executable, "-m", "suspensionlab.core.cad_worker", *args]
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, creationflags=creationflags)
            except OSError as error:
                raise CadPreviewError("start") from error
            with self._lock:
                self._process = process
                if self._cancelled.is_set():
                    process.kill()
            try:
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired as error:
                    process.kill()
                    process.wait()
                    raise CadPreviewError("timeout") from error
            finally:
                with self._lock:
                    self._process = None
            if self._cancelled.is_set():
                raise CadPreviewError("cancelled")
            try:
                if not report.is_file() or report.stat().st_size > 4096:
                    raise CadPreviewError("crash")
                state = json.loads(report.read_text(encoding="utf-8"))
                if state.get("status") != "ok" or code != 0:
                    known = {"file_size", "deviation", "missing_cad", "units", "read", "no_shape", "mesh",
                             "limit", "missing_face", "coordinates", "no_faces", "unexpected"}
                    error_code = state.get("code")
                    raise CadPreviewError(error_code if error_code in known else "crash")
                if not output.is_file() or output.stat().st_size > 32 * 1024 * 1024:
                    raise CadPreviewError("output")
                with np.load(output, allow_pickle=False) as data:
                    faces = data["faces"]
                    if faces.shape != (1,) or faces.dtype.kind not in "iu":
                        raise CadPreviewError("output")
                    return CadMesh(data["triangles"], int(faces[0]))
            except CadPreviewError:
                raise
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise CadPreviewError("output") from error

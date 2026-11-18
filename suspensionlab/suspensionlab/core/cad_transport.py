"""Запуск CAD-предпросмотра в отдельном ограниченном по времени процессе."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import zipfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from time import monotonic
from typing import Literal

import numpy as np

from .cad_mesh import MAX_MESH_BYTES, CadMesh

MAX_ARCHIVE_BYTES = MAX_MESH_BYTES + MAX_MESH_BYTES // 3 + 2 * 1024 * 1024
PROGRESS_STAGES = frozenset({"read", "transfer", "groups", "mesh", "faces", "save"})


class CadPreviewError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CadJob:
    """Одноразовый процесс; отмена также работает до старта процесса."""

    def __init__(self) -> None:
        self.progress_callback: Callable[[str, int], None] | None = None
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                with suppress(OSError):
                    self._process.kill()

    def run(self, source: Path, deviation: float, *, timeout: float = 600,
            mode: Literal["step", "weldment"] = "step") -> CadMesh:
        if mode not in ("step", "weldment"):
            raise CadPreviewError("start")
        if self._cancelled.is_set():
            raise CadPreviewError("cancelled")
        with tempfile.TemporaryDirectory(prefix="suspension-cad-") as directory:
            output, report = Path(directory) / "mesh.npz", Path(directory) / "result.json"
            progress_path = Path(directory) / "progress.json"
            args = [str(source), str(output), str(report), str(deviation)]
            flag = "--cad-preview-worker" if mode == "step" else "--weldment-preview-worker"
            module = "suspensionlab.core.cad_worker" if mode == "step" else "suspensionlab.core.cad_weldment_worker"
            if getattr(sys, "frozen", False):
                command = [sys.executable, flag, *args]
            else:
                command = [sys.executable, "-m", module, *args]
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, creationflags=creationflags,
                                           env={**os.environ, "SUSPENSIONLAB_CAD_PROGRESS_PATH": str(progress_path)})
            except OSError as error:
                raise CadPreviewError("start") from error
            with self._lock:
                self._process = process
                if self._cancelled.is_set():
                    process.kill()
            try:
                deadline = monotonic() + timeout
                last_progress: tuple[str, int] | None = None
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        process.kill()
                        process.wait()
                        raise CadPreviewError("timeout")
                    try:
                        code = process.wait(timeout=min(0.25, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        if self.progress_callback is not None:
                            try:
                                if progress_path.stat().st_size <= 1024:
                                    data = json.loads(progress_path.read_text(encoding="utf-8"))
                                    stage, faces = data.get("stage"), data.get("faces")
                                    if stage in PROGRESS_STAGES and type(faces) is int and 0 <= faces <= 100_000_000:
                                        state = (stage, faces)
                                        if state != last_progress:
                                            self.progress_callback(*state)
                                            last_progress = state
                            except (OSError, ValueError, TypeError, AttributeError):
                                pass
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
                             "limit", "memory", "missing_face", "coordinates", "no_faces", "unexpected"}
                    error_code = state.get("code")
                    raise CadPreviewError(error_code if error_code in known else "crash")
                if not output.is_file() or output.stat().st_size > MAX_ARCHIVE_BYTES:
                    raise CadPreviewError("output")
                with zipfile.ZipFile(output) as archive:
                    members = archive.infolist()
                    if len(members) != 8 or sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES:
                        raise CadPreviewError("output")
                with np.load(output, allow_pickle=False) as data:
                    faces, skipped, recovered = data["faces"], data["skipped"], data["recovered"]
                    if any(value.shape != (1,) or value.dtype.kind not in "iu"
                           for value in (faces, skipped, recovered)):
                        raise CadPreviewError("output")
                    names = data["names"]
                    if names.ndim != 1 or names.dtype.kind != "U":
                        raise CadPreviewError("output")
                    instance_groups = data["instance_groups"]
                    if instance_groups.ndim != 1 or instance_groups.dtype.kind not in "iu":
                        raise CadPreviewError("output")
                    return CadMesh(data["triangles"], int(faces[0]), int(skipped[0]), int(recovered[0]),
                                   tuple(names.tolist()), data["groups"], tuple(instance_groups.tolist()),
                                   data["instances"])
            except CadPreviewError:
                raise
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile, MemoryError) as error:
                raise CadPreviewError("output") from error

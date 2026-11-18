"""Безопасное создание отдельного STEP с изолированным CAD-процессом."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

from ..model.sketch_extrude_settings import extrusion_limits, hole_entry_side, validate_hole_depth
from ..model.sketch_io import SketchDocument, SketchIOError, write_new_sketch

MAX_STEP_BYTES = 100 * 1024 * 1024


class SketchSolidError(Exception):
    """Пользовательское сообщение об ошибке построения или сохранения."""


class SketchSolidJob:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._published = False

    def cancel(self) -> None:
        with self._lock:
            if self._published:
                return
            self._cancelled.set()
            if self._process is not None and self._process.poll() is None:
                with suppress(OSError):
                    self._process.kill()

    def run(self, document: SketchDocument, depth: float, destination: str | Path, *, timeout: float = 90, direction: str = "positive", hole_depth: float = 0, hole_side: str = "auto") -> Path:
        try:
            extrusion_limits(document.offset_mm, depth, direction)
            validate_hole_depth(depth, hole_depth)
            hole_entry_side(direction, hole_side)
        except (ValueError, TypeError) as exc:
            raise SketchSolidError(str(exc)) from exc
        target = Path(destination)
        if target.suffix.lower() not in (".step", ".stp"):
            raise SketchSolidError("Используйте расширение .step или .stp")
        if self._cancelled.is_set():
            raise SketchSolidError("Построение отменено")
        if os.path.lexists(target):
            raise SketchSolidError("Файл уже существует. Выберите новое имя; исходный файл не изменён")
        try:
            # Same filesystem as target for an atomic create-if-absent hard link.
            with tempfile.TemporaryDirectory(prefix=".sketch-solid-", dir=target.parent) as directory:
                work = Path(directory)
                write_new_sketch(work / "source.slsketch", document)
                args = ["source.slsketch", "result.step", "report.json", str(depth), direction, str(hole_depth), hole_side]
                if getattr(sys, "frozen", False):
                    command = [sys.executable, "--sketch-solid-worker", *args]
                    environment = None
                else:
                    command = [sys.executable, "-m", "suspensionlab.core.sketch_solid_worker", *args]
                    # The worker's cwd is temporary, even when running directly
                    # from a source checkout without an editable installation.
                    root = str(Path(__file__).resolve().parents[2])
                    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((root, os.environ.get("PYTHONPATH", "")))}
                # Worker writes ASCII relative paths so OCCT doesn't need Unicode
                # filename support; Popen itself resolves the Unicode cwd.
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                process = subprocess.Popen(command, cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, creationflags=creationflags, env=environment)
                with self._lock:
                    self._process = process
                    if self._cancelled.is_set():
                        process.kill()
                try:
                    try:
                        code = process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired as exc:
                        process.kill()
                        process.wait()
                        raise SketchSolidError("Превышено время построения CAD-тела") from exc
                finally:
                    with self._lock:
                        self._process = None
                if self._cancelled.is_set():
                    raise SketchSolidError("Построение отменено")
                report = work / "report.json"
                if not report.is_file() or report.stat().st_size > 4096:
                    raise SketchSolidError("CAD-процесс завершился без результата")
                state = json.loads(report.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    raise SketchSolidError("CAD-процесс вернул некорректный отчёт")
                if code != 0 or state.get("status") != "ok":
                    messages = {"missing_cad": "CAD-ядро недоступно в этой сборке",
                                "invalid_shape": "CAD-ядро не смогло построить корректное тело по этим контурам",
                                "contour_layout": "Нужен один внешний контур с отверстиями внутри; отдельные детали и вложенные острова не поддерживаются",
                                "unexpected": "Ошибка CAD-ядра при построении тела"}
                    raise SketchSolidError(messages.get(str(state.get("code")), "CAD-процесс завершился с ошибкой"))
                output = work / "result.step"
                info = output.lstat()
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_STEP_BYTES:
                    raise SketchSolidError("CAD-процесс создал некорректный STEP")
                with output.open("rb") as result:
                    if b"ISO-10303-21;" not in result.read(64):
                        raise SketchSolidError("CAD-процесс создал некорректный STEP")
                    result.seek(max(0, info.st_size - 128))
                    if b"END-ISO-10303-21;" not in result.read():
                        raise SketchSolidError("CAD-процесс создал неполный STEP")
                # Cancellation and publication are serialized: a successful
                # link is never reported as cancelled or silently removed.
                with self._lock:
                    if self._cancelled.is_set():
                        raise SketchSolidError("Построение отменено")
                    os.link(output, target)
                    self._published = True
                return target
        except FileExistsError as exc:
            raise SketchSolidError("Файл уже существует. Выберите новое имя; исходный файл не изменён") from exc
        except SketchSolidError:
            raise
        except (OSError, ValueError, TypeError, SketchIOError) as exc:
            raise SketchSolidError(f"Не удалось создать STEP: {exc}") from exc

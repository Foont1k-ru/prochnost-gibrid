"""Экспорт отдельной плоской копии в DXF, без записи в проект."""
from __future__ import annotations

import io
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from .sketch_io import SketchDocument, _as_data

MAX_DXF_BYTES = 16 * 1024 * 1024


class SketchDxfError(ValueError):
    """Ошибка экспорта эскиза."""


def write_new_dxf(path: str | Path, document: SketchDocument) -> Path:
    """DXF в координатах листа XY, миллиметры. Только создание нового файла.

    Выбранная пространственная плоскость и смещение не переносятся; поэтому
    пользователь должен явно подтвердить экспорт проекции в интерфейсе.
    """
    target = Path(path)
    if target.suffix.lower() != ".dxf":
        raise SketchDxfError("Используйте расширение .dxf")
    temporary: str | None = None
    try:
        import ezdxf

        _as_data(document)  # Reject invalid or oversized geometry before writing.
        drawing = ezdxf.new("R2010")
        drawing.header["$INSUNITS"] = 4  # DXF unit code: millimeters
        space = drawing.modelspace()
        for entity in document.entities:
            if entity.kind == "line":
                space.add_line((*entity.start, 0), (*entity.end, 0))
            else:
                space.add_circle((*entity.start, 0), entity.size)
        out = io.StringIO()
        drawing.write(out)
        content = out.getvalue().encode("utf-8")
        if len(content) > MAX_DXF_BYTES:
            raise SketchDxfError("Файл DXF слишком большой")
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=".sketch-dxf-", suffix=".tmp",
                                         delete=False) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic create-if-absent; never replace an existing file or symlink.
        os.link(temporary, target)
        return target
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RuntimeError, RecursionError) as exc:
        raise SketchDxfError(f"Не удалось экспортировать DXF: {exc}") from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)

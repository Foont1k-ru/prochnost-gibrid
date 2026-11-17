"""Одноразовый запуск CAD в отдельном процессе по временному снимку."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..model.kim_format import write_document
from .cad_mesh import CadMesh
from .cad_transport import CadJob, CadPreviewError


class WeldmentCadJob:
    def __init__(self) -> None:
        self._job = CadJob()

    def cancel(self) -> None:
        self._job.cancel()

    def run(self, document: dict[str, Any], *, deviation: float = 2.) -> CadMesh:
        if self._job.is_cancelled():
            raise CadPreviewError("cancelled")
        with tempfile.TemporaryDirectory(prefix="suspension-weldment-") as directory:
            source = Path(directory) / "snapshot.kima"
            write_document(source, "assembly", document, overwrite=False)
            return self._job.run(source, deviation, timeout=60, mode="weldment")

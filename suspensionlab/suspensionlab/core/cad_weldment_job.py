"""Одноразовый запуск CAD в отдельном процессе по временному снимку."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ..model.fixed_arm_housings import PREVIEW_FORMAT, validate_housing_preview
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
            if document.get('format') == PREVIEW_FORMAT:
                validate_housing_preview(document)
                source = Path(directory) / 'snapshot.slpreview'
                source.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            else:
                kind = "part" if document.get("format") == "kim-part" else "assembly"
                source = Path(directory) / ("snapshot.kim" if kind == "part" else "snapshot.kima")
                write_document(source, kind, document, overwrite=False)
            return self._job.run(source, deviation, timeout=60, mode="weldment")

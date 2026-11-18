"""Изолированная проверяемая CAD-проекция только для .kima 0.15/0.16."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..model.kim_format import read_document
from .cad_worker import CadWorkerError


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        return 2
    source, output, report = map(Path, args)
    try:
        from .cad_assembly_projection import project_document

        result = project_document(read_document(source, 'assembly'))
        output.write_text(json.dumps(result, allow_nan=False, separators=(',', ':')), encoding='utf-8')
        report.write_text('{"status":"ok"}', encoding='utf-8')
        return 0
    except (ImportError, OSError):
        code = 'missing_cad'
    except CadWorkerError as error:
        code = error.code
    except Exception:
        code = 'unexpected'
    report.write_text(json.dumps({'status': 'error', 'code': code}), encoding='utf-8')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

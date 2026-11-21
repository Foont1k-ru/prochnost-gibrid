"""Одноразовый изолированный процесс предварительного просмотра подрезки."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..model.kim_format import read_document
from .cad_tube_notch import TubeNotchError
from .cad_worker import CadWorkerError


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 6:
        return 2
    source, output, report = map(Path, args[:3])
    try:
        from .cad_tube_notch_preview import project_tube_notch

        try:
            clearance = float(args[5])
        except ValueError as error:
            raise TubeNotchError('invalid_clearance') from error
        result = project_tube_notch(read_document(source, 'assembly'), args[3], args[4],
                                    radial_clearance_mm=clearance)
        output.write_text(json.dumps(result, allow_nan=False, separators=(',', ':')), encoding='utf-8')
        report.write_text('{"status":"ok"}', encoding='utf-8')
        return 0
    except (ImportError, OSError):
        code = 'missing_cad'
    except (CadWorkerError, TubeNotchError) as error:
        code = error.code
    except Exception:
        code = 'unexpected'
    report.write_text(json.dumps({'status': 'error', 'code': code}), encoding='utf-8')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

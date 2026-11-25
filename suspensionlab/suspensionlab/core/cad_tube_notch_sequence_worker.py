"""Одноразовый процесс просмотра последовательной подрезки одной трубы."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..model.kim_format import read_document
from .cad_assembly_projection_job import MAX_OUTPUT_BYTES
from .cad_tube_notch import TubeNotchError
from .cad_tube_notch_sequence import MAX_SEQUENCE_BYTES, TubeNotchSequenceError
from .cad_worker import CadWorkerError


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not 5 <= len(args) <= 8:
        return 2
    source, output, report = map(Path, args[:3])
    try:
        from .cad_tube_notch_sequence_preview import project_notch_sequence

        result = project_notch_sequence(read_document(source, 'assembly'), args[3], args[4:])
        payload = json.dumps(result, allow_nan=False, separators=(',', ':'))
        if len(payload.encode('utf-8')) > min(MAX_SEQUENCE_BYTES, (1 + 3 * len(args[4:])) * MAX_OUTPUT_BYTES):
            raise CadWorkerError('limit')
        output.write_text(payload, encoding='utf-8')
        report.write_text('{"status":"ok"}', encoding='utf-8')
        return 0
    except TubeNotchSequenceError as error:
        state = {'status': 'error', 'code': error.code, 'step': error.step_index, 'cutter': error.cutter_id}
    except (ImportError, OSError):
        state = {'status': 'error', 'code': 'missing_cad'}
    except (CadWorkerError, TubeNotchError) as error:
        state = {'status': 'error', 'code': error.code}
    except Exception:
        state = {'status': 'error', 'code': 'unexpected'}
    report.write_text(json.dumps(state, ensure_ascii=True), encoding='utf-8')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

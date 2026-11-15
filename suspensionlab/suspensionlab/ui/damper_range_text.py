"""Текст дискретной сводки без округления при определении статуса."""
from __future__ import annotations

from ..core.damper_range import CandidateComparison, DamperRange
from ..core.stroke import StrokeLimits
from ..i18n import tr


def damper_range_text(summary: DamperRange) -> str:
    lines = [tr("damper_range.heading"), tr("damper_range.count", available=summary.total - summary.missing,
                total=summary.total, missing=summary.missing)]
    if summary.shortest is None or summary.longest is None:
        lines.append(tr("damper_range.no_points"))
    else:
        for key, point in (("shortest", summary.shortest), ("longest", summary.longest)):
            lines.append(tr(f"damper_range.{key}", length=f"{point.length_mm:.3f}",
                            travel=f"{point.travel_mm:+.2f}", row=point.row + 1))
        if summary.conflicts is None:
            lines.append(tr("damper_range.no_limits"))
        else:
            assert summary.compression_clearance_mm is not None and summary.extension_clearance_mm is not None
            lines.append(tr("damper_range.clearance", compression=f"{summary.compression_clearance_mm:+.3f}",
                            extension=f"{summary.extension_clearance_mm:+.3f}", conflicts=summary.conflicts))
            lines.append(tr("damper_range.has_conflicts" if summary.conflicts else "damper_range.no_conflicts"))
    lines.append(tr("damper_range.notice"))
    return "\n\n".join(lines)


def candidate_text(candidate: CandidateComparison, limits: StrokeLimits) -> str:
    summary = candidate.summary
    lines = [tr("damper_candidate.heading")]
    if summary.shortest is None or summary.longest is None:
        lines.append(tr("damper_candidate.no_points"))
    else:
        assert summary.conflicts is not None
        assert summary.compression_clearance_mm is not None and summary.extension_clearance_mm is not None
        lines.append(tr("damper_candidate.result", compression=f"{summary.compression_clearance_mm:+.3f}",
                        extension=f"{summary.extension_clearance_mm:+.3f}", stops=summary.conflicts,
                        reserve_short=candidate.insufficient_reserve))
        for key, point in (("first_stop", candidate.first_stop), ("first_short", candidate.first_insufficient)):
            if point is not None:
                lines.append(tr(f"damper_candidate.{key}", row=point.row + 1, travel=f"{point.travel_mm:+.2f}"))
        if summary.missing:
            lines.append(tr("damper_candidate.incomplete"))
        if summary.conflicts == 0 and candidate.insufficient_reserve == 0:
            lines.append(tr("damper_candidate.no_detected"))
    lines.extend((tr("damper_candidate.count", available=summary.total - summary.missing,
                     total=summary.total, missing=summary.missing),
                  tr("damper_candidate.inputs", compressed=repr(limits.compressed_mm),
                     extended=repr(limits.extended_mm), reserve=repr(candidate.reserve_mm)),
                  tr("damper_candidate.notice")))
    return "\n".join(lines)

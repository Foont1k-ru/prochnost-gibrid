"""Отображение сводки пружины, без определения статуса по округлённым числам."""
from __future__ import annotations

from ..core.spring_range import SpringRange
from ..i18n import tr


def spring_range_text(summary: SpringRange) -> str:
    lines = [tr("spring_range.count", available=summary.total - summary.missing,
                total=summary.total, missing=summary.missing),
             tr("spring_range.free", free=f"{summary.free_length_mm:.3f}")]
    if summary.shortest is None or summary.longest is None:
        lines.append(tr("spring_range.no_points"))
    else:
        for key, point in (("shortest", summary.shortest), ("longest", summary.longest)):
            lines.append(tr(f"spring_range.{key}", length=f"{point.length_mm:.3f}",
                            travel=f"{point.travel_mm:+.2f}", row=point.row + 1))
        if summary.coil_bind_count is None:
            lines.append(tr("spring_range.coil_unknown"))
        else:
            assert summary.min_coil_clearance_mm is not None
            lines.append(tr("spring_range.coil", limit=f"{summary.coil_bind_length_mm:.3f}",
                            clearance=f"{summary.min_coil_clearance_mm:+.3f}", count=summary.coil_bind_count))
        lines.append(tr("spring_range.free_counts", boundary=summary.free_boundary_count, slack=summary.slack_count,
                        force_missing=summary.force_missing_count))
        if summary.first_free is not None:
            point = summary.first_free
            lines.append(tr("spring_range.first_free", row=point.row + 1, travel=f"{point.travel_mm:+.2f}"))
    lines.append(tr("spring_range.notice"))
    return "\n\n".join(lines)

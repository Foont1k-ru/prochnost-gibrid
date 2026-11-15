"""Текст дискретной сводки без округления при определении статуса."""
from __future__ import annotations

from ..core.damper_range import DamperRange
from ..i18n import tr


def damper_range_text(summary: DamperRange) -> str:
    lines = [tr("damper_range.count", available=summary.total - summary.missing,
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

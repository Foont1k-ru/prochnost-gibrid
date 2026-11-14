"""Пояснение расчёта выбранной точки без повторного решения кинематики."""
from __future__ import annotations

from ..core.analysis import CornerSample
from ..i18n import tr
from ..model.entities import Spring


def explain_corner_sample(sample: CornerSample | None, spring: Spring) -> str:
    """Опирается на неокруглённые состояния; вывод чисел ознакомительно округлён."""
    if sample is None:
        return tr("analysis.explain.no_solution")
    lines = [tr("analysis.explain.heading", travel=f"{sample.pose.travel_mm:+.2f}")]
    if sample.spring is None:
        lines.append(tr("analysis.explain.spring_disabled"))
    else:
        lines.append(tr("analysis.explain.spring_input", free=f"{spring.free_len_mm:.2f}"))
        if spring.progressive:
            lines.append(tr("analysis.explain.spring_curve", count=len(spring.progressive)))
        else:
            lines.append(tr("analysis.explain.spring_linear", rate=f"{spring.rate_N_mm:.2f}"))
        lines.append(tr("analysis.explain.spring_preload"))
        state = sample.spring.state
        if sample.spring.error:
            lines.append(tr("analysis.explain.element_error", reason=sample.spring.error))
        if state is None:
            lines.append(tr("analysis.explain.spring_unavailable"))
        else:
            lines.append(tr("analysis.explain.spring_values", length=f"{state.length_mm:.2f}",
                            compression=f"{state.compression_mm:.2f}",
                            force=f"{state.force_n:.1f} Н" if state.force_n is not None else tr("analysis.explain.unavailable")))
            lines.append(tr(f"analysis.explain.spring_{state.status}"))
            if state.coil_clearance_mm is None:
                lines.append(tr("analysis.explain.coil_unknown"))
            else:
                lines.append(tr("analysis.explain.coil_clearance", clearance=f"{state.coil_clearance_mm:+.2f}"))
    if sample.damper is None:
        lines.append(tr("analysis.explain.damper_disabled"))
    else:
        damper = sample.damper
        lines.append(tr("analysis.explain.damper_length", length=f"{damper.length_mm:.2f}"))
        if damper.error:
            lines.append(tr("analysis.explain.element_error", reason=damper.error))
        if damper.stroke is None:
            lines.append(tr("analysis.explain.damper_unknown"))
        else:
            stroke = damper.stroke
            lines.append(tr(f"analysis.explain.damper_{stroke.status}"))
            lines.append(tr("analysis.explain.damper_gaps", compression=f"{stroke.compression_clearance_mm:+.2f}",
                            extension=f"{stroke.extension_clearance_mm:+.2f}"))
            if damper.has_detected_conflict:
                lines.append(tr("analysis.explain.damping_conflict"))
    lines.append(tr("analysis.explain.warning"))
    return "\n\n".join(lines)

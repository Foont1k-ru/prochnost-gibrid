"""Пояснение расчёта выбранной точки без повторного решения кинематики."""
from __future__ import annotations

from math import dist

from ..core.analysis import CornerSample
from ..i18n import tr
from ..model.entities import Axle, Spring


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


def explain_static_sample(sample: CornerSample | None, axle: Axle) -> str:
    """Отдельно показывает статику, не объявляя её физически достижимой."""
    if sample is not None and sample.pose.travel_mm != 0:
        raise ValueError("Ожидается точка нулевого хода")
    lines = [tr("analysis.static.scope")]
    if sample is not None and sample.spring is not None:
        lower, upper = axle.hardpoints["spring_lo"], axle.hardpoints["spring_up"]
        distance = dist((lower.x, lower.y, lower.z), (upper.x, upper.y, upper.z))
        lines.append(tr("analysis.static.spring_mounts", distance=f"{distance:.2f}"))
        if sample.spring.state is not None:
            difference = sample.spring.state.length_mm - distance
            lines.append(tr("analysis.static.spring_offset", difference=f"{difference:+.2f}"))
    if sample is not None and sample.damper is not None and sample.damper.stroke is not None:
        state = sample.damper.stroke
        lines.append(tr("analysis.static.damper_limits",
                        minimum=f"{state.length_mm - state.compression_clearance_mm:.2f}",
                        maximum=f"{state.length_mm + state.extension_clearance_mm:.2f}"))
    lines.append(explain_corner_sample(sample, axle.spring))
    return "\n\n".join(lines)

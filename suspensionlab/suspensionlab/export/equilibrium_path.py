"""Форматирование уже рассчитанных точек пути без повторного решения."""
from __future__ import annotations

from ..core.equilibrium import EquilibriumSample
from ..core.spring_candidate import SpringCandidate, candidate_geometry
from ..i18n import tr

PATH_COLUMNS = ("travel", "length", "coil_clearance", "force", "ratio", "support", "residual",
                "spring_status", "damper_length", "compression_clearance", "extension_clearance", "damper_status")


CANDIDATE_PATH_COLUMNS = ("candidate_compression", "candidate_coil_condition",
                          "candidate_compression_condition", "candidate_status")


def format_candidate_path_sample(sample: EquilibriumSample, candidate: SpringCandidate) -> tuple[str, ...]:
    """Сравнение только сохранённой точки, статусы определяются до округления."""
    geometry = candidate_geometry(candidate, sample.spring.length_mm)
    return (f"{geometry.compression_mm:.4f}",
            tr("candidate_balance_reserve.ok" if geometry.coil_reserve_ok else "candidate_balance_reserve.short"),
            tr("candidate_balance_reserve.ok" if geometry.compression_reserve_ok else "candidate_balance_reserve.short"),
            tr(f"spring_candidate.report.status.{geometry.status}"))


def format_path_sample(sample: EquilibriumSample) -> tuple[str, ...]:
    """Показать измеренные в точке величины; None не подменяется нулём."""
    def number(value: float | None, decimals: int = 4) -> str:
        return "—" if value is None else f"{value:.{decimals}f}"

    damper = sample.damper
    stroke = damper.stroke if damper is not None else None
    if damper is None:
        damper_status = tr("equilibrium_path.damper_disabled")
    elif damper.error is not None:
        damper_status = damper.error
    elif stroke is None:
        damper_status = tr("analysis.damper_status.unknown")
    else:
        damper_status = tr(f"analysis.damper_status.{stroke.status}")
    return (
        number(sample.travel_mm), number(sample.spring.length_mm), number(sample.spring.coil_clearance_mm),
        number(sample.spring.force_n), number(sample.motion_ratio, 6), number(sample.wheel_support_n),
        f"{sample.residual_n:+.4f}", tr(f"analysis.spring_status.{sample.spring.status}"),
        number(damper.length_mm if damper is not None else None),
        number(stroke.compression_clearance_mm if stroke is not None else None),
        number(stroke.extension_clearance_mm if stroke is not None else None), damper_status,
    )

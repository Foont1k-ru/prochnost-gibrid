"""Общие метаданные источника жёсткости для отчётов сравнения и баланса."""
from __future__ import annotations

from ..core.spring_candidate import SpringCandidate
from ..i18n import tr


def spring_rate_metadata(candidate: SpringCandidate) -> list[tuple[str, str]]:
    points = candidate.rate_points
    if candidate.linear_rate_n_mm is None:
        mode = "disabled"
    elif points is None:
        mode = "manual"
    else:
        mode = "two_points"
    metadata = [(tr("spring_rate.source_label"), tr(f"spring_rate.source_{mode}"))]
    if points is not None:
        estimate = points.estimate(candidate.free_mm)
        for key, value in (("length1", points.length_1_mm), ("force1", points.force_1_n),
                           ("length2", points.length_2_mm), ("force2", points.force_2_n),
                           ("zero_label", estimate.extrapolated_zero_length_mm),
                           ("model1_label", estimate.model_force_1_n), ("model2_label", estimate.model_force_2_n)):
            metadata.append((tr(f"spring_rate.{key}"), repr(value)))
    return metadata

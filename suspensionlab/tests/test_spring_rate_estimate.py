from math import inf, nan

import pytest

from suspensionlab.core.spring_rate_estimate import estimate_spring_rate


def test_two_points_and_reversed_order_reproduce_zero_and_model():
    result = estimate_spring_rate(280, 400, 240, 1200, 300)
    assert result.rate_n_mm == 20
    assert result.extrapolated_zero_length_mm == 300
    assert result.model_force_1_n == 400 and result.model_force_2_n == 1200
    reverse = estimate_spring_rate(240, 1200, 280, 400, 300)
    assert reverse.rate_n_mm == result.rate_n_mm and reverse.extrapolated_zero_length_mm == result.extrapolated_zero_length_mm
    assert reverse.model_force_1_n == result.model_force_2_n and reverse.model_force_2_n == result.model_force_1_n


def test_offset_is_not_silently_applied_to_existing_model():
    result = estimate_spring_rate(280, 600, 240, 1400, 300)
    assert result.rate_n_mm == 20 and result.extrapolated_zero_length_mm == 310
    assert result.model_force_1_n == 400 and result.model_force_2_n == 1200
    at_or_above_free = estimate_spring_rate(310, 10, 290, 410, 300)
    assert at_or_above_free.model_force_1_n == 0 and at_or_above_free.model_force_2_n == 200


@pytest.mark.parametrize("values", [
    (0, 100, 240, 500, 300), (280, -1, 240, 500, 300),
    (280, 100, 240, -1, 300), (280, 100, 240, 500, 0),
    (280, 100, 280, 500, 300), (280, 100, 240, 100, 300),
    (280, 500, 240, 100, 300), (280, nan, 240, 500, 300),
    (inf, 100, 240, 500, 300), (280, 100, 240, inf, 300),
    (1e-323, 0, 5e-324, 1e308, 300),
    (2, 1e308, 1, 1e308 + 1e293, 1e308),
])
def test_invalid_and_unrepresentable_values(values):
    with pytest.raises(ValueError):
        estimate_spring_rate(*values)


def test_candidate_rejects_inconsistent_or_invalid_rate_provenance():
    from suspensionlab.core.spring_candidate import SpringCandidate
    from suspensionlab.core.spring_rate_estimate import SpringRatePoints

    points = SpringRatePoints(280, 600, 240, 1400)
    candidate = SpringCandidate(300, 200, 100, 0, 0, 20, rate_points=points)
    assert candidate.rate_points == points
    for rate in (None, 19.999, 21):
        with pytest.raises(ValueError):
            SpringCandidate(300, 200, 100, 0, 0, rate, rate_points=points)
    with pytest.raises(ValueError):
        SpringCandidate(300, 200, 100, 0, 0, 20, rate_points=SpringRatePoints(280, 600, 280, 1400))

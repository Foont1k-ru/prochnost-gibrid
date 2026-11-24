import math

import pytest

from suspensionlab.model.bend_length import vertex_for_length
from suspensionlab.model.bent_tube import BentTubeError, make_bend_path


@pytest.mark.parametrize('target', [100.1, 105, 120, 145])
def test_length_retains_side_projection_and_radius(target):
    start, end, vertex = (0., 0., 0.), (100., 0., 0.), (35., 20., 10.)
    new = vertex_for_length(start, end, vertex, 20, 5, target)
    assert new[0] == pytest.approx(35)
    assert new[1] > 0 and new[2] / new[1] == pytest.approx(.5)
    assert make_bend_path(start, new, end, 20, 5).length == pytest.approx(target, abs=1e-5)


def test_invalid_lengths_and_bend_outside_chord_are_refused():
    a, b, p = (0., 0., 0.), (100., 0., 0.), (50., 15., 0.)
    for length in (float('nan'), math.inf, 100, 99, 999999):
        with pytest.raises(BentTubeError):
            vertex_for_length(a, b, p, 80, 5, length)
    with pytest.raises(BentTubeError, match='между опорами'):
        vertex_for_length(a, b, (-10., 30., 0.), 5, 1, 130)


@pytest.mark.parametrize('side', [-1., 1.])
def test_reachable_length_beyond_a_gap_in_valid_bends(side):
    # Both endpoints are valid even though intermediate bend heights do not fit.
    a, b = (0., 0., 0.), (56.3662398598089, 0., 0.)
    x, initial, requested, radius = 52.17366213524382, 1.3394635386219251, 30.111284658939333, 16.995141324006216
    outer = radius * .1
    with pytest.raises(BentTubeError):
        make_bend_path(a, (x, side * 4., 0.), b, radius, outer)
    desired = make_bend_path(a, (x, side * requested, 0.), b, radius, outer).length
    vertex = vertex_for_length(a, b, (x, side * initial, 0.), radius, outer, desired)
    assert vertex == pytest.approx((x, side * requested, 0.), abs=1e-6)
    assert make_bend_path(a, vertex, b, radius, outer).length == pytest.approx(desired, abs=1e-6)


def test_length_with_only_an_invalid_candidate_is_refused():
    a, b = (0., 0., 0.), (56.3662398598089, 0., 0.)
    x, radius, h = 52.17366213524382, 16.995141324006216, 4.
    u, v = x, b[0] - x
    sweep = math.atan2(h * b[0], u * v - h * h)
    target = math.hypot(u, h) + math.hypot(v, h) - 2 * radius * math.tan(sweep / 2) + radius * sweep
    with pytest.raises(BentTubeError):
        vertex_for_length(a, b, (x, 1.3394635386219251, 0.), radius, radius * .1, target)


def test_sampled_known_valid_targets_on_both_sides_of_initial_height():
    import random

    rng = random.Random(48271)
    count = 0
    for _ in range(1200):
        chord = 10 ** rng.uniform(1.5, 3)
        x = rng.uniform(.03, .97) * chord
        initial = 10 ** rng.uniform(-1.5, .5) * chord
        wanted = initial * 10 ** rng.uniform(-1.2, 1.2)
        radius = rng.uniform(.02, .49) * chord
        start, end = (0., 0., 0.), (chord, 0., 0.)
        try:
            make_bend_path(start, (x, initial, 0.), end, radius, 1.)
            target = make_bend_path(start, (x, wanted, 0.), end, radius, 1.).length
        except BentTubeError:
            continue
        if target <= chord + 1e-7 or target > 1_000_000:
            continue
        result = vertex_for_length(start, end, (x, initial, 0.), radius, 1., target)
        assert result[0] == pytest.approx(x, abs=1e-6)
        assert result[1] == pytest.approx(wanted, rel=1e-7, abs=1e-5)
        assert make_bend_path(start, result, end, radius, 1.).length == pytest.approx(target, abs=1e-5)
        count += 1
    assert count > 400


def test_large_radius_uses_valid_limit_without_skipping_a_reachable_length():
    a, b = (0., 0., 0.), (29.21403927525318, 0., 0.)
    x, height, desired_height, radius = 18.31762550553329, 5.226014716916631, 10.556731001375907, 19.9098111937381
    target = make_bend_path(a, (x, desired_height, 0.), b, radius, radius * .1).length
    result = vertex_for_length(a, b, (x, height, 0.), radius, radius * .1, target)
    assert result == pytest.approx((x, desired_height, 0.), abs=1e-6)


def test_three_dimensional_direction_and_projection_are_preserved():
    axis = (3 / math.sqrt(50), 4 / math.sqrt(50), 5 / math.sqrt(50))
    normal = (-.8, .6, 0.)
    start = (100., 50., -40.)
    end = tuple(start[i] + 200 * axis[i] for i in range(3))
    def vertex(height):
        return tuple(start[i] + 60 * axis[i] + height * normal[i] for i in range(3))
    desired = make_bend_path(start, vertex(80), end, 30, 5).length
    result = vertex_for_length(start, end, vertex(30), 30, 5, desired)
    assert result == pytest.approx(vertex(80), abs=1e-6)

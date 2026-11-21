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

"""Проверяется только содержимое выбранных по сетке источников в памяти."""
import pytest

from suspensionlab.core.cad_source_guard import summarize_sources


def test_identical_digests_and_unknown_inputs_are_distinctly_counted():
    summary = summarize_sources((b'a' * 32, None, b'a' * 32, None))
    assert (summary.known_points, summary.unknown_points, summary.distinct_sources) == (2, 2, 1)
    assert not summary.has_conflict
    assert summarize_sources((None, None)).distinct_sources == 0
    assert summarize_sources((b'a' * 32, b'b' * 32)).has_conflict


@pytest.mark.parametrize('invalid', [b'', b'a' * 31, b'a' * 33, 'x' * 32, 17])
def test_rejects_invalid_digest(invalid):
    with pytest.raises(ValueError, match='digest'):
        summarize_sources((invalid,))

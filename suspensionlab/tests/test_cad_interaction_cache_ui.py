"""Повторное использование временной сетки только при подсветке целых деталей."""
import numpy as np
import pytest

from suspensionlab.core.cad_interaction import interaction_geometry
from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.ui.canvas.cad_preview import CadPreview


def grouped_mesh(size):
    rng = np.random.default_rng(903)
    triangles = rng.uniform(-10, 10, (size, 3, 3))
    groups = np.arange(size, dtype=np.int32) % 4
    return CadMesh(triangles, 4, part_names=('a', 'b', 'c', 'd'), triangle_parts=groups)


@pytest.mark.parametrize('size', [12001, 50000, 200001])
def test_whole_part_cache_matches_original_and_partial_masks_fall_back(qtbot, size):
    mesh = grouped_mesh(size)
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh)
    first_fast = view._fast_triangles
    cache = view._part_interaction_cache
    assert cache is not None
    for selected in ((0,), (1, 3), (), (0, 1, 2, 3)):
        mask = np.isin(mesh.triangle_parts, selected)
        expected, expected_mask = interaction_geometry(mesh, mask)
        view.set_mesh(mesh, mask, through=True)
        assert view._fast_triangles is first_fast
        assert view._part_interaction_cache is cache
        np.testing.assert_array_equal(view._fast_triangles, expected)
        np.testing.assert_array_equal(view._fast_highlight, expected_mask)
        assert view._through
    # A partial selection of a part must not reuse the group-only mesh.
    partial = np.zeros(size, dtype=bool)
    partial[::7] = True
    expected, expected_mask = interaction_geometry(mesh, partial)
    view.set_mesh(mesh, partial)
    np.testing.assert_array_equal(view._fast_triangles, expected)
    np.testing.assert_array_equal(view._fast_highlight, expected_mask)
    assert view._part_interaction_cache is cache
    view.set_mesh(mesh)
    assert view._fast_triangles is first_fast and view._fast_highlight is None
    replacement = grouped_mesh(size)
    view.set_mesh(replacement)
    assert view._part_interaction_cache is not cache
    view.set_mesh(None)
    assert view._part_interaction_cache is None


def test_cache_is_only_for_grouped_mesh_and_does_not_break_degenerate_groups(qtbot):
    triangles = np.zeros((12001, 3, 3))
    groups = np.arange(len(triangles), dtype=np.int32) % 2
    mesh = CadMesh(triangles, 2, part_names=('a', 'b'), triangle_parts=groups)
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh, groups == 1)
    assert view._fast_triangles is mesh.triangles
    np.testing.assert_array_equal(view._fast_highlight, groups == 1)
    view.set_mesh(CadMesh(triangles, 1))
    assert view._part_interaction_cache is None

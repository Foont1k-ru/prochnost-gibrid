"""Compare preview simplification with the original implementation, not CAD geometry."""
import numpy as np
import pytest

from suspensionlab.core.cad_interaction import interaction_geometry, interaction_geometry_by_part
from suspensionlab.core.cad_mesh import CadMesh


def _original(mesh, highlight=None, *, with_parts=False):
    """Reference path before reusing the per-group minimum."""
    triangles = mesh.triangles
    if len(triangles) <= 12_000:
        return triangles, highlight, mesh.triangle_parts if with_parts else None
    diagonal = float(np.linalg.norm(np.ptp(triangles.reshape(-1, 3), axis=0)))
    if diagonal == 0:
        return triangles, highlight, mesh.triangle_parts if with_parts else None
    parts = mesh.triangle_parts
    keys = np.zeros(len(triangles), dtype=np.int32) if parts is None else parts.copy()
    if highlight is not None:
        keys = keys * 2 + highlight.astype(np.int32)
    order = np.argsort(keys, kind="stable")
    groups = np.split(order, np.flatnonzero(np.diff(keys[order])) + 1)
    chunks, masks, part_chunks = [], [], []
    for indices in groups:
        if len(triangles) > 200_000:
            quota = max(250, int(len(indices) * 60_000 / len(triangles)))
            if len(indices) > quota:
                indices = indices[np.linspace(0, len(indices) - 1, quota, dtype=np.int64)]
        group = triangles[indices]
        selected = bool(highlight[indices[0]]) if highlight is not None else False
        part = int(parts[indices[0]]) if with_parts else 0
        chunk = group
        if len(group) >= 250:
            origin = group.min(axis=(0, 1))
            extent = float(np.ptp(group.reshape(-1, 3), axis=0).max())
            step = min(diagonal / 50, extent / 16)
            if step > 0:
                cells = np.rint((group - origin) / step).astype(np.int64)
                keep = np.any(np.cross(cells[:, 1] - cells[:, 0], cells[:, 2] - cells[:, 0]) != 0, axis=1)
                cells = cells[keep]
                if len(cells):
                    vertices = np.sort(cells.view([("x", np.int64), ("y", np.int64), ("z", np.int64)])
                                       .reshape(-1, 3), axis=1)
                    _, index = np.unique(vertices, axis=0, return_index=True)
                    chunk = origin + cells[np.sort(index)].astype(np.float64) * step
        chunks.append(chunk)
        masks.append(np.full(len(chunk), selected, dtype=bool))
        if with_parts:
            part_chunks.append(np.full(len(chunk), part, dtype=np.int32))
    return (np.concatenate(chunks), np.concatenate(masks) if highlight is not None else None,
            np.concatenate(part_chunks) if with_parts else None)


def _assert_arrays(actual, expected):
    for left, right in zip(actual, expected, strict=True):
        if right is None:
            assert left is None
        else:
            np.testing.assert_array_equal(left, right)


@pytest.mark.parametrize("size,groups", [(12000, 4), (12001, 4), (50000, 1), (50000, 100),
                                         (200000, 100), (200001, 100)])
def test_simplification_matches_original(size, groups):
    rng = np.random.default_rng(691)
    centers = rng.uniform(-100, 100, (size, 1, 3))
    triangles = centers + rng.normal(0, 1, (size, 3, 3))
    triangles[::13, 1:] = triangles[::13, :1]  # degenerate triangles
    triangles[1::17] = triangles[2::17][:len(triangles[1::17]), ::-1]  # duplicate with reversed orientation
    parts = np.arange(size, dtype=np.int32) % groups
    mesh = CadMesh(triangles, groups, part_names=tuple(map(str, range(groups))), triangle_parts=parts)
    expected_grouped = _original(mesh, with_parts=True)
    _assert_arrays(interaction_geometry_by_part(mesh), (expected_grouped[0], expected_grouped[2]))
    for mask in (None, parts == 0, np.arange(size) % 7 == 0):
        expected = _original(mesh, mask)
        _assert_arrays(interaction_geometry(mesh, mask), expected[:2])


@pytest.mark.parametrize("degenerate", ["coincident", "flat", "line"])
def test_degenerate_and_ungrouped_match_original(degenerate):
    triangles = np.zeros((12001, 3, 3))
    if degenerate in ("flat", "line"):
        triangles[:, :, 0] = np.arange(12001)[:, None]
    if degenerate == "flat":
        triangles[:, 1, 1] = 1
        triangles[:, 2, 0] += 1
    mesh = CadMesh(triangles, 1)
    mask = np.arange(len(triangles)) % 5 == 0
    _assert_arrays(interaction_geometry(mesh, mask), _original(mesh, mask)[:2])

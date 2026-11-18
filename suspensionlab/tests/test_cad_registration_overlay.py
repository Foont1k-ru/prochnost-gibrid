from dataclasses import replace

import numpy as np
import pytest

from suspensionlab.core.cad_mesh import MAX_COORDINATE, CadMesh
from suspensionlab.core.cad_registration import evaluate_registration
from suspensionlab.core.cad_registration_overlay import overlay_pairs, transform_mesh_for_preview
from suspensionlab.core.spatial_transform import RigidTransform
from suspensionlab.model.entities import Project
from suspensionlab.model.point_csv import capture_points


def test_transform_mesh_rotation_translation_and_immutable_source():
    triangles = np.array([[[1., 0, 0], [0, 1, 0], [0, 0, 1]]])
    mesh = CadMesh(triangles, 4, 1, 1)
    transform = RigidTransform(((0., -1., 0.), (1., 0., 0.), (0., 0., 1.)), (10., 20., 30.))
    result = transform_mesh_for_preview(mesh, transform)
    np.testing.assert_allclose(result.triangles, [[[10, 21, 30], [9, 20, 30], [10, 20, 31]]])
    assert np.array_equal(mesh.triangles, triangles)
    assert not result.triangles.flags.writeable
    assert (result.face_count, result.skipped_faces, result.recovered_faces) == (4, 1, 1)


def test_transformed_bounds_rejected():
    mesh = CadMesh(np.zeros((1, 3, 3)), 1)
    transform = RigidTransform(RigidTransform.identity().rotation, (MAX_COORDINATE + 1, 0, 0))
    with pytest.raises(ValueError, match='coordinates'):
        transform_mesh_for_preview(mesh, transform)


def test_pairs_keep_control_order_and_world_distance():
    source = ((0., 0., 0.), (10., 0., 0.), (0., 10., 0.), (0., 0., 10.))
    target = (*source[:3], (1., 2., 13.))
    mask = (True, True, True, False)
    result = evaluate_registration(source, target, mask)
    records = tuple(replace(p, xyz=target[i]) for i, p in enumerate(capture_points(Project.create_default())[:4]))
    pairs = overlay_pairs(records, mask, result)
    assert [p.row for p in pairs] == [1, 2, 3, 4]
    assert [p.fit for p in pairs] == list(mask)
    assert pairs[3].target == target[3]
    assert pairs[3].transformed == pytest.approx(source[3])
    assert pairs[3].distance_mm == pytest.approx(np.sqrt(14))
    with pytest.raises(ValueError, match='count'):
        overlay_pairs(records, mask[:-1], result)

"""Exercise the actual subprocess and grouped mesh for the experimental v2 format."""
import numpy as np
import pytest
from test_free_arm_housing_io import make_draft

from suspensionlab.core.cad_preview_parts import preview_parts
from suspensionlab.core.cad_transport import CadPreviewError
from suspensionlab.core.cad_weldment_job import WeldmentCadJob
from suspensionlab.core.cad_weldment_worker import create_grouped_mesh
from suspensionlab.core.cad_worker import CadWorkerError
from suspensionlab.model.free_arm_housing_io import to_data, write_free_arm_housing
from suspensionlab.model.free_arm_io import to_data as arm_data
from suspensionlab.model.free_arm_io import write_free_arm


@pytest.mark.parametrize('bent', [(), ('front', 'rear')])
def test_real_worker_v2_preserves_groups(tmp_path, bent):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    draft = make_draft(bent)
    data = to_data(draft)
    path = write_free_arm_housing(tmp_path / 'arm.slarm', draft)
    triangles, faces, names, groups = create_grouped_mesh(path, 2.)
    assert faces > 0 and len(triangles) > 0
    assert names == ('tube_front', 'tube_rear', 'ball_housing')
    assert set(np.unique(groups)) == {0, 1, 2}
    assert tuple(part.identifier for part in preview_parts(data)) == names
    mesh = WeldmentCadJob().run(data, deviation=2.)
    assert mesh.part_names == names
    assert set(np.unique(mesh.triangle_parts)) == {0, 1, 2}


def test_old_v1_worker_and_parts_remain_unchanged(tmp_path):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    arm = make_draft().arm
    path = write_free_arm(tmp_path / 'old.slarm', arm)
    _, _, names, groups = create_grouped_mesh(path, 2.)
    assert names == ('tube_front', 'tube_rear')
    assert set(np.unique(groups)) == {0, 1}
    assert tuple(part.identifier for part in preview_parts(arm_data(arm))) == names


def test_valid_model_but_impossible_cad_contact_is_not_reported_as_success(tmp_path):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from dataclasses import replace

    draft = make_draft()
    draft = replace(draft, housing=replace(draft.housing, length_mm=5))
    path = write_free_arm_housing(tmp_path / 'bad-contact.slarm', draft)
    with pytest.raises(CadWorkerError) as error:
        create_grouped_mesh(path, 2.)
    assert error.value.code == 'ball_housing_failed'
    with pytest.raises(CadPreviewError) as transport_error:
        WeldmentCadJob().run(to_data(draft), deviation=2.)
    assert transport_error.value.code == 'ball_housing_failed'

"""Независимый стык: строгий файл и сохранение прежних версий."""
from copy import deepcopy
from dataclasses import replace

import pytest
from test_free_arm_housing_io import make_draft
from test_free_arm_inner_housings import make_inner

from suspensionlab.model.free_arm_housing_io import from_data as read_v2_data
from suspensionlab.model.free_arm_housing_io import read_independent_arm, write_free_arm_housing
from suspensionlab.model.free_arm_inner_housings_io import from_data as read_v3_data
from suspensionlab.model.free_arm_inner_housings_io import write_free_arm_inner_housings
from suspensionlab.model.free_arm_io import from_data as read_v1_data
from suspensionlab.model.free_arm_io import write_free_arm
from suspensionlab.model.free_arm_miter import FreeArmMiterDraft
from suspensionlab.model.free_arm_miter_io import FreeArmMiterFileError, from_data, to_data, write_free_arm_miter


@pytest.mark.parametrize('inner', [None, make_inner().housings])
def test_roundtrip_and_old_readers_do_not_lose_joint(tmp_path, inner):
    draft = FreeArmMiterDraft(make_draft(('front',)).arm, inner)
    data = to_data(draft)
    original = deepcopy(data)
    assert data['source'] == 'independent' and data['version'] == '4'
    assert data['joint'] == {'target': 'miter', 'radial_clearance_mm': 0}
    assert from_data(data) == draft and data == original
    for old_reader in (read_v1_data, read_v2_data, read_v3_data):
        with pytest.raises(ValueError):
            old_reader(data)
    path = write_free_arm_miter(tmp_path / 'miter.slarm', draft)
    assert read_independent_arm(path) == draft
    with pytest.raises(FreeArmMiterFileError):
        write_free_arm_miter(path, draft)
    assert read_independent_arm(path) == draft


def test_old_documents_still_read(tmp_path):
    old = make_draft()
    inner = make_inner(ball=True)
    assert read_independent_arm(write_free_arm(tmp_path / 'v1.slarm', old.arm)) == old.arm
    assert read_independent_arm(write_free_arm_housing(tmp_path / 'v2.slarm', old)) == old
    assert read_independent_arm(write_free_arm_inner_housings(tmp_path / 'v3.slarm', inner)) == inner


@pytest.mark.parametrize('change', [
    lambda d: d['joint'].update(target='front'),
    lambda d: d['joint'].update(radial_clearance_mm=1),
    lambda d: d['joint'].update(radial_clearance_mm=True),
    lambda d: d['joint'].update(extra=1),
    lambda d: d.update(ball_housing={}),
    lambda d: d.update(notches={'front': 0}),
    lambda d: d.update(source='snapshot'),
    lambda d: d.pop('joint'),
    lambda d: d.update(extra=1),
])
def test_bad_document_is_rejected(change):
    data = to_data(FreeArmMiterDraft(make_draft().arm))
    change(data)
    with pytest.raises(FreeArmMiterFileError):
        from_data(data)


def test_unknown_inner_and_invalid_cut_rejected():
    data = to_data(FreeArmMiterDraft(make_draft().arm, make_inner().housings))
    data['notches']['front'] = -1
    with pytest.raises(FreeArmMiterFileError):
        from_data(data)
    with pytest.raises(ValueError):
        replace(FreeArmMiterDraft(make_draft().arm), housings='bad')

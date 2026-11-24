"""Equivalence and bounded-work checks for multi-component CAD group acceptance."""
import numpy as np
import pytest

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.ui.weldment_3d import Weldment3D


def mesh_for(parts, groups):
    parts = np.asarray(parts, dtype=np.int32)
    return CadMesh(np.zeros((len(parts), 3, 3)), 1, part_names=tuple(f'part_{i}' for i in range(groups)),
                   triangle_parts=parts)


def reference(mesh):
    return all((mesh.triangle_parts == i).any() for i in range(len(mesh.part_names)))


@pytest.mark.parametrize('count,missing', [(count, missing) for count in (1, 2, 8, 9, 64, 100, 512)
                                           for missing in (False, True) if count > 1 or not missing])
@pytest.mark.parametrize('order', ['shuffled', 'sorted'])
def test_group_check_matches_original(count, order, missing):
    rng = np.random.default_rng(1000 + count)
    parts = np.arange(max(count * 7, 1000)) % count
    if missing:
        parts[parts == count - 1] = 0
    if order == 'shuffled':
        rng.shuffle(parts)
    else:
        parts.sort()
    mesh = mesh_for(parts, count)
    assert mesh.all_parts_present() == reference(mesh) == (not missing)


def test_many_chunks_and_group_only_present_at_end():
    parts = np.concatenate((np.tile(np.arange(9), 35_000), np.array([9])))
    mesh = mesh_for(parts, 10)
    assert mesh.all_parts_present() and reference(mesh)
    missing = mesh_for(parts[:-1], 10)
    assert not missing.all_parts_present() and not reference(missing)


def test_no_groups_is_not_a_complete_grouped_mesh():
    mesh = CadMesh(np.zeros((2, 3, 3)), 1)
    assert not mesh.all_parts_present()


def test_ui_accepts_all_groups_and_rejects_missing(qtbot):
    count = 20
    document = {'format': 'kima-assembly', 'version': '0.2',
                'parts': [{'id': f'part_{i}', 'name': f'Элемент {i}'} for i in range(count)]}
    panel = Weldment3D(fixed_skeleton=True)
    qtbot.addWidget(panel)
    panel.set_document(document)
    panel._enable.setChecked(True)
    panel._timer.stop()
    panel._completed(panel.generation, mesh_for(range(count), count))
    assert panel._ready and panel._parts_tree.topLevelItem(0).childCount() == count
    panel.set_document(document)
    panel._timer.stop()
    panel._completed(panel.generation, mesh_for(range(count - 1), count))
    assert not panel._ready and panel._view.mesh is None and panel._parts_tree.topLevelItemCount() == 0
    assert panel.shutdown()


def test_memory_failure_does_not_display_partial_result(qtbot, monkeypatch):
    document = {'format': 'kima-assembly', 'version': '0.2',
                'parts': [{'id': f'part_{i}', 'name': f'Элемент {i}'} for i in range(10)]}
    panel = Weldment3D(fixed_skeleton=True)
    qtbot.addWidget(panel)
    panel.set_document(document)
    panel._enable.setChecked(True)
    panel._timer.stop()
    mesh = mesh_for(range(10), 10)
    def no_memory(_self):
        raise MemoryError
    monkeypatch.setattr(CadMesh, 'all_parts_present', no_memory)
    panel._completed(panel.generation, mesh)
    assert not panel._ready and panel._view.mesh is None
    assert panel._parts_tree.topLevelItemCount() == 0 and panel._retry.isEnabled()
    assert panel.shutdown()

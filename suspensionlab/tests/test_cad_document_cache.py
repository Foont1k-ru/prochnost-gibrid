"""Exact document keys and per-window bounded, isolated mesh ownership."""
from copy import deepcopy

import numpy as np
import pytest

from suspensionlab.core.cad_document_cache import DOCUMENT_BYTES, DocumentMeshCache, document_key
from suspensionlab.core.cad_mesh import CadMesh


def mesh(n=2):
    return CadMesh(np.arange(n * 9, dtype=float).reshape(n, 3, 3), n,
                   part_names=('first', 'second'), triangle_parts=np.arange(n) % 2,
                   instance_groups=(0,), triangle_instances=np.zeros(n, dtype=int))


def test_exact_key_quality_metadata_and_container_types():
    doc = {'format': 'example', 'points': [[1., 2., 3.]], 'flag': True, 'none': None}
    key = document_key(doc, 2.)
    assert key is not None and document_key(deepcopy(doc), 2.) == key
    assert document_key(doc, .2) != key
    changed = deepcopy(doc)
    changed['points'][0][2] += 1e-10
    assert document_key(changed, 2.) != key
    changed = deepcopy(doc)
    changed['flag'] = 1
    assert document_key(changed, 2.) != key
    changed = deepcopy(doc)
    changed['points'] = ((1., 2., 3.),)
    assert document_key(changed, 2.) is None
    assert document_key({1: 'key'}, 2.) is None
    assert document_key({'value': np.float64(1)}, 2.) is None
    assert document_key({'value': float('nan')}, 2.) is None
    assert document_key({'value': float('inf')}, 2.) is None
    assert document_key({'text': '\ud800'}, 2.) is None
    assert document_key({'large': 'x' * (DOCUMENT_BYTES + 1)}, 2.) is None
    assert document_key({'huge': 1 << 257}, 2.) is None
    assert document_key(doc, 0.) is None


def test_cycles_shared_containers_and_depth_not_cached():
    cycle = []
    cycle.append(cycle)
    assert document_key({'value': cycle}, 2.) is None
    shared = [1]
    assert document_key({'a': shared, 'b': shared}, 2.) is None
    deep = 0
    for _ in range(70):
        deep = [deep]
    assert document_key({'value': deep}, 2.) is None
    assert document_key({'value': [0] * 100001}, 2.) is None


def test_cache_copies_inputs_and_outputs_with_real_metadata():
    cache = DocumentMeshCache()
    key = document_key({'id': 1}, 2.)
    original = mesh()
    cache.put(key, original)
    original.triangles.flags.writeable = True
    original.triangles[0, 0, 0] = 999
    first = cache.get(key)
    assert first.triangles[0, 0, 0] == 0
    assert first.part_names == ('first', 'second') and first.triangle_parts.tolist() == [0, 1]
    assert first.instance_groups == (0,) and not first.triangles.flags.writeable
    first.triangle_parts.flags.writeable = True
    first.triangle_parts[:] = 0
    second = cache.get(key)
    assert second.triangle_parts.tolist() == [0, 1] and second is not first
    cache.clear()
    assert cache.get(key) is None and cache._bytes == 0


def test_cache_bounds_lru_and_oversize():
    keys = [document_key({'id': i}, 2.) for i in range(3)]
    value = mesh()
    size = len(keys[0][0]) + value.triangles.nbytes + value.triangle_parts.nbytes + value.triangle_instances.nbytes
    cache = DocumentMeshCache(budget=size * 2 + 20, entries=2)
    cache.put(keys[0], value)
    cache.put(keys[1], value)
    assert cache.get(keys[0]) is not None
    cache.put(keys[2], value)
    assert cache.get(keys[1]) is None and cache.get(keys[0]) is not None and cache.get(keys[2]) is not None
    assert cache._bytes <= cache.budget and len(cache._items) <= 2
    small = DocumentMeshCache(budget=1)
    small.put(keys[0], value)
    assert small.get(keys[0]) is None and small._bytes == 0
    zero = DocumentMeshCache(entries=0)
    zero.put(keys[0], value)
    assert zero.get(keys[0]) is None
    with pytest.raises(ValueError):
        DocumentMeshCache(budget=-1)


def test_corrupted_cached_mesh_is_evicted_instead_of_returned():
    cache = DocumentMeshCache()
    key = document_key({'id': 1}, 2.)
    cache.put(key, mesh())
    stored = cache._items[key]
    stored.triangles.flags.writeable = True
    stored.triangles[0, 0, 0] = float('nan')
    assert cache.get(key) is None
    assert not cache._items and cache._bytes == 0


def test_byte_budget_evicts_even_below_entry_limit():
    first, second = document_key({'id': 1}, 2.), document_key({'id': 2}, 2.)
    value = mesh()
    size = len(first[0]) + value.triangles.nbytes + value.triangle_parts.nbytes + value.triangle_instances.nbytes
    cache = DocumentMeshCache(budget=size, entries=8)
    cache.put(first, value)
    cache.put(second, value)
    assert cache.get(first) is None and cache.get(second) is not None
    assert cache._bytes <= size

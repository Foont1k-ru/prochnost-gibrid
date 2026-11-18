import copy
import math

import pytest

from suspensionlab.core.snapshot_parameters import compare_parameters
from suspensionlab.model.entities import Project
from suspensionlab.model.snapshot_restore import prepare_snapshot


def find(rows, role, code):
    return next(row for row in rows if row.role == role and row.code == code)


def test_fields_units_rounding_and_non_mutation():
    current = Project.create_default()
    current.front.spring.rate_N_mm = 90.1234567
    current.add_snapshot('ref')
    reference = prepare_snapshot(current.snapshots[0].data)
    current.vehicle.mass_kg += 50
    current.vehicle.front_weight_pct += 1
    current.front.damper.bump_rate_Ns_mm += 0.5
    current.front.arb.enabled = False
    current.front.wheel.tire = '=untrusted'
    current.rear.travel.sweep_points += 2
    before = copy.deepcopy(current.to_dict())
    rows = compare_parameters(reference, current)
    assert len(rows) == len({(r.role, r.component, r.code) for r in rows}) == 83
    assert find(rows, 'front', 'spring.rate').old == 90.1235
    assert find(rows, 'front', 'spring.rate').new == 90.1234567
    assert find(rows, 'front', 'spring.rate').status == 'changed'
    for role, code, unit, delta in [
        ('vehicle', 'vehicle.mass', 'кг', 50), ('vehicle', 'vehicle.front_weight', '%', 1),
        ('front', 'damper.bump', 'Н·с/мм', 0.5), ('rear', 'travel.sweep_points', '', 2),
        ('front', 'setup.camber', '°', 0), ('front', 'wheel.k_tire', 'Н/мм', 0),
        ('front', 'wheel.width', 'мм', 0), ('front', 'bump_stop.engage', '%', 0),
    ]:
        row = find(rows, role, code)
        assert row.unit == unit and row.delta == delta
    assert find(rows, 'front', 'arb.enabled').status == 'changed'
    assert find(rows, 'front', 'arb.enabled').delta is None
    assert find(rows, 'front', 'wheel.tire').new == '=untrusted'
    assert not find(rows, 'rear', 'steering.ratio').selectable
    assert codeless_omissions(rows)
    assert current.to_dict() == before


def codeless_omissions(rows):
    return not any('progressive' in r.code or 'layout' in r.code and r.role != 'vehicle' for r in rows)


def test_invalid_types_axis_mismatch_and_nonfinite():
    original = Project.create_default()
    current = Project.create_default()
    current.set_axle_type('rear', 'live_axle_coil')
    current.front.spring.rate_N_mm = float('nan')
    original.front.damper.len_extended_mm = -1e308
    current.front.damper.len_extended_mm = 1e308
    current.front.arb.enabled = 1
    rows = compare_parameters(original, current)
    assert find(rows, 'front', 'spring.rate').status == 'invalid'
    assert find(rows, 'front', 'spring.rate').new is None
    assert find(rows, 'front', 'damper.len_extended').status == 'invalid'
    assert find(rows, 'front', 'damper.len_extended').delta is None
    assert find(rows, 'front', 'arb.enabled').status == 'invalid'
    row = find(rows, 'rear', 'spring.rate')
    assert row.status == 'incompatible' and row.delta is None
    assert row.old_type != row.new_type
    assert find(rows, 'vehicle', 'vehicle.mass').status == 'unchanged'


def test_no_tolerance_and_live_snapshot_stability():
    current = Project.create_default()
    current.add_snapshot('ref')
    reference = prepare_snapshot(current.snapshots[0].data)
    current.front.setup.camber_deg = math.nextafter(reference.front.setup.camber_deg, 0)
    rows = compare_parameters(reference, current)
    row = find(rows, 'front', 'setup.camber')
    assert row.status == 'changed' and row.delta != 0
    current.front.setup.camber_deg = 8
    assert row.new != current.front.setup.camber_deg


def test_duplicate_registry_key_rejected(monkeypatch):
    from suspensionlab.core import snapshot_parameters
    original = snapshot_parameters.specs.vehicle_specs
    def duplicates(vehicle):
        groups = original(vehicle)
        groups[0].params.append(groups[0].params[0])
        return groups
    monkeypatch.setattr(snapshot_parameters.specs, 'vehicle_specs', duplicates)
    p = Project.create_default()
    with pytest.raises(ValueError, match='duplicate'):
        compare_parameters(p, p)

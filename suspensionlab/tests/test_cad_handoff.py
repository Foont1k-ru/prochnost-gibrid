"""Подтверждаемый переход к черновому скелету, не инженерный допуск."""
from copy import deepcopy
from dataclasses import replace

import pytest

from suspensionlab.core.suspension_clearance import calculate_link_clearance
from suspensionlab.model.cad_handoff import ClearanceSettings, HandoffError, prepare_cad_handoff
from suspensionlab.model.fixed_arm_skeleton import fixed_arm_tube_document
from suspensionlab.model.fixed_arm_skeleton_io import make_skeleton_data
from suspensionlab.model.kinematic_elements import ElementSetup, KinematicElements
from suspensionlab.model.templates import load_template


def _settings(**changes):
    base = ClearanceSettings((('lower_arm', 5.), ('tierod', 5.)), 2., None, True, 5., .5)
    return replace(base, **changes)


def test_rechecks_same_rounded_snapshot_and_makes_detached_straight_tubes():
    project = load_template('ring')
    project.front.hardpoints['lca_f_in'].x += .00004
    old = deepcopy(project)
    result = prepare_cad_handoff(project, -10, 10, 10, _settings(), 1.)
    assert project == old and result.matches(project)
    assert result.refinement is not None and result.refinement.added >= 2
    frozen = result.snapshot.project_copy()
    targets = [sample.travel_mm for sample in result.sweep.samples]
    fresh = calculate_link_clearance(frozen.front, -10, 10, 10, dict(result.settings.radii), 2., targets=targets)
    assert fresh == result.sweep
    document = fixed_arm_tube_document(result.snapshot, project, result.radius_mm, result.wall_mm)
    assert len(document['parts']) == 2
    source = document['parts'][0]['geometry']['source']['coordinates_mm']
    assert source[0][0] == frozen.front.hardpoints['lca_f_in'].x
    assert source[0][0] != project.front.hardpoints['lca_f_in'].x
    saved = make_skeleton_data(result.snapshot, project, result.radius_mm, result.wall_mm, {})
    assert saved['geometry']['radius_mm'] == 5 and saved['geometry']['wall_mm'] == 1
    assert 'clearance' not in saved['calculation']  # the limited check is not a saved CAD certificate


def test_conflicts_do_not_become_an_approval_and_data_is_available_for_warning():
    project = load_template('ring')
    result = prepare_cad_handoff(project, 0, 0, 10,
                                 _settings(radii=(('lower_arm', 1000.), ('tierod', 1000.)), refine=False), 2.)
    assert result.refinement is None
    assert result.sweep.samples[0].pairs[0].status == 'overlap'
    assert 'wheel_cylinder' in result.sweep.omitted


def test_requires_measured_pair_with_lower_arm_and_supported_type():
    project = load_template('ring')
    with pytest.raises(HandoffError, match='нижний рычаг'):
        prepare_cad_handoff(project, 0, 0, 10, _settings(radii=(('upper_arm', 5.), ('tierod', 5.))), 1.)
    project.front.kinematic_elements = KinematicElements(project.front.type_code, ElementSetup('lower_arm', 'body'))
    with pytest.raises(HandoffError, match='Ни одна'):
        prepare_cad_handoff(project, 0, 0, 10, _settings(radii=(('lower_arm', 5.), ('spring_capsule', 5.))), 1.)
    project.front.type_code = 'macpherson'
    with pytest.raises(HandoffError, match='двухрычажной'):
        prepare_cad_handoff(project, 0, 0, 10, _settings(), 1.)


def test_dimensions_must_be_representable_and_valid():
    project = load_template('ring')
    for radius, wall in ((.01, .01), (.009, .01), (5.001, 1), (10001, 1), (5, 0),
                         (5, 5), (5, 1.001), (float('nan'), 1), (5, True)):
        with pytest.raises(HandoffError):
            prepare_cad_handoff(project, 0, 0, 10, _settings(radii=(('lower_arm', radius), ('tierod', 5))), wall)
    with pytest.raises(HandoffError):
        prepare_cad_handoff(project, 0, 0, 10, _settings(radii=(('lower_arm', 5), ('lower_arm', 6))), 1)


def test_small_unrounded_changes_to_non_solver_points_make_handoff_stale():
    project = load_template('ring')
    result = prepare_cad_handoff(project, 0, 0, 10, _settings(refine=False), 1.)
    project.front.hardpoints['spring_lo'].x += .00001
    assert result.snapshot.matches(project)  # Old snapshot comparison only included raw solver points.
    assert not result.matches(project)


def test_change_during_recalculation_is_rejected(monkeypatch):
    import suspensionlab.model.cad_handoff as module

    project = load_template('ring')
    calculate = module.calculate_link_clearance
    def mutate(*args, **kwargs):
        result = calculate(*args, **kwargs)
        project.front.hardpoints['spring_lo'].x += .00001
        return result
    monkeypatch.setattr(module, 'calculate_link_clearance', mutate)
    with pytest.raises(HandoffError, match='изменился'):
        prepare_cad_handoff(project, 0, 0, 10, _settings(refine=False), 1.)


def test_failed_kinematics_prevents_snapshot(monkeypatch):
    from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError

    step = DoubleWishbone._step
    def fail(self, pose, travel):
        if travel > 3:
            raise KinematicsError(travel, 'тестовый отказ')
        return step(self, pose, travel)
    monkeypatch.setattr(DoubleWishbone, '_step', fail)
    with pytest.raises(HandoffError, match='Нет решения'):
        prepare_cad_handoff(load_template('ring'), 0, 10, 10, _settings(), 1.)

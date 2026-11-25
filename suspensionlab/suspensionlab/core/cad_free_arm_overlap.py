"""CAD-детали независимого рычага для анализа без расчётного снимка.

Это подготовка численного анализа, а не проверка монтажа или пригодности.
"""
from __future__ import annotations

from typing import Any

from ..model.free_arm import FreeArmDraft
from ..model.free_arm_housing import FreeArmHousingDraft
from ..model.free_arm_housing_io import independent_arm_from_data
from ..model.free_arm_inner_housings import FreeArmInnerHousingDraft
from ..model.free_arm_miter import FreeArmMiterDraft
from ..model.free_arm_tube_joint import FreeArmTubeJointDraft


def independent_part_names(document: Any) -> tuple[str, ...]:
    """Проверить весь независимый документ и определить ожидаемые детали."""
    draft = independent_arm_from_data(document)
    names: tuple[str, ...] = ('tube_front', 'tube_rear')
    if isinstance(draft, FreeArmInnerHousingDraft):
        names += ('housing_front', 'housing_rear')
        if draft.ball_housing is not None:
            names += ('ball_housing',)
    elif isinstance(draft, (FreeArmMiterDraft, FreeArmTubeJointDraft)):
        if draft.housings is not None:
            names += ('housing_front', 'housing_rear')
    elif isinstance(draft, FreeArmHousingDraft):
        names += ('ball_housing',)
    return names


def build_independent_parts(document: Any) -> tuple[tuple[str, ...], tuple[Any, ...]]:
    """Построить фактические отдельные тела после всех выбранных резов."""
    from OCP.BRepCheck import BRepCheck_Analyzer

    from .cad_free_arm import (
        build_free_arm_ball_housing,
        build_free_arm_inner_housings,
        build_free_arm_miter,
        build_free_arm_tube_joint,
        build_free_arm_tubes,
    )

    names = independent_part_names(document)
    draft = independent_arm_from_data(document)
    if isinstance(draft, FreeArmInnerHousingDraft):
        _, parts = build_free_arm_inner_housings(draft)
    elif isinstance(draft, FreeArmMiterDraft):
        _, parts = build_free_arm_miter(draft)
    elif isinstance(draft, FreeArmTubeJointDraft):
        _, parts = build_free_arm_tube_joint(draft)
    elif isinstance(draft, FreeArmHousingDraft):
        parts = build_free_arm_ball_housing(draft.arm, draft.housing.as_data())
    elif isinstance(draft, FreeArmDraft):
        _, parts = build_free_arm_tubes(draft)
    else:
        raise ValueError('invalid_independent_arm')
    if len(parts) != len(names) or any(part.IsNull() or not BRepCheck_Analyzer(part).IsValid() for part in parts):
        raise ValueError('invalid_shape')
    return names, parts

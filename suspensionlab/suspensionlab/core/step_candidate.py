"""Ограниченная диагностика кандидатов относительного преобразования STEP.

Это не импорт, не доказанная поза и не проверка файла. Интерпретация порядка
проверена только на небольшом STEP, созданном Open CASCADE. Результат нельзя
применять к геометрии или автоматически переносить в проект.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from .spatial_transform import RigidTransform, SpatialFrame
from .step_inventory import StepInventory
from .step_placements import Frame

CandidateStatus = Literal["ready", "frames", "definitions", "association", "membership", "context", "unit", "unit_mismatch", "invalid"]


@dataclass(frozen=True)
class CandidateTransform:
    occurrence: int
    status: CandidateStatus
    transform: RigidTransform | None = None


def _spatial(frame: Frame, factor: float) -> SpatialFrame:
    position = (frame.origin[0] * factor, frame.origin[1] * factor, frame.origin[2] * factor)
    return SpatialFrame(position, frame.x, frame.y, frame.z)


def candidate_transforms(inventory: StepInventory) -> tuple[CandidateTransform, ...]:
    """Диагностические относительные кандидаты, без объединения дерева сборки.

    Поддерживается только отношение дочернее→родительское, с прямыми
    упоминаниями соответствующих систем и одинаковой распознанной SI-длиной
    обоих контекстов. Это условия отбора, а не доказательство правильности STEP.
    """
    frames = {frame.occurrence: frame for frame in inventory.placement_frames}
    units = {unit.context: unit for unit in inventory.context_units}
    result: list[CandidateTransform] = []
    for occurrence in inventory.occurrences:
        frame = frames.get(occurrence.entity)
        status: CandidateStatus
        transform = None
        if frame is None or frame.issue or frame.first is None or frame.second is None:
            status = "frames"
        elif occurrence.parent is None or occurrence.child is None:
            status = "definitions"
        elif frame.representation_match is None or frame.representation_match.status != "child_parent":
            status = "association"
        else:
            match = frame.representation_match
            if match.frame_1_membership[0] is not True or match.frame_2_membership[1] is not True:
                status = "membership"
            elif match.context_1 is None or match.context_2 is None:
                status = "context"
            else:
                first_unit, second_unit = units.get(match.context_1), units.get(match.context_2)
                if (first_unit is None or second_unit is None or first_unit.status != "known" or
                        second_unit.status != "known" or first_unit.mm_per_unit is None or
                        second_unit.mm_per_unit is None or not isfinite(first_unit.mm_per_unit) or
                        not isfinite(second_unit.mm_per_unit) or first_unit.mm_per_unit <= 0 or
                        second_unit.mm_per_unit <= 0):
                    status = "unit"
                elif first_unit.mm_per_unit != second_unit.mm_per_unit:
                    status = "unit_mismatch"
                else:
                    try:
                        transform = RigidTransform.align_frames_same_units(
                            _spatial(frame.first, first_unit.mm_per_unit), _spatial(frame.second, second_unit.mm_per_unit))
                        status = "ready"
                    except (ValueError, ArithmeticError, OverflowError):
                        status = "invalid"
        result.append(CandidateTransform(occurrence.entity, status, transform))
    return tuple(result)

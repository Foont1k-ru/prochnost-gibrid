"""Одна подрезка трубы по другой в независимом рычаге."""
from __future__ import annotations

from dataclasses import dataclass

from .fixed_arm_housings import HousingError, validate_tube_joint
from .free_arm import FreeArmDraft
from .free_arm_inner_housings import FreeArmInnerHousings


@dataclass(frozen=True, slots=True)
class FreeArmTubeJoint:
    """Одна выбранная подрезаемая ветвь и радиальный зазор."""
    target: str
    radial_clearance_mm: float

    def __post_init__(self) -> None:
        data = validate_tube_joint({'target': self.target, 'radial_clearance_mm': self.radial_clearance_mm})
        object.__setattr__(self, 'target', data['target'])
        object.__setattr__(self, 'radial_clearance_mm', data['radial_clearance_mm'])

    def as_data(self) -> dict[str, str | float]:
        return {'target': self.target, 'radial_clearance_mm': self.radial_clearance_mm}


@dataclass(frozen=True, slots=True)
class FreeArmTubeJointDraft:
    """Независимые трубы и один рез; внутренние корпуса опциональны."""
    arm: FreeArmDraft
    joint: FreeArmTubeJoint
    housings: FreeArmInnerHousings | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.arm, FreeArmDraft) or not isinstance(self.joint, FreeArmTubeJoint):
            raise HousingError('Нужны независимый рычаг и выбранная подрезка')
        if self.housings is not None and not isinstance(self.housings, FreeArmInnerHousings):
            raise HousingError('Недопустимые внутренние корпуса')

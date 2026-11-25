"""Независимый рычаг с общим стыком на ус, без расчётного снимка."""
from __future__ import annotations

from dataclasses import dataclass

from .free_arm import FreeArmDraft
from .free_arm_inner_housings import FreeArmInnerHousings


class FreeArmMiterError(ValueError):
    """Недопустимый независимый вариант стыка."""


@dataclass(frozen=True, slots=True)
class FreeArmMiterDraft:
    """Общий стык; внутренние корпуса опциональны, центральный несовместим."""

    arm: FreeArmDraft
    housings: FreeArmInnerHousings | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.arm, FreeArmDraft):
            raise FreeArmMiterError('Нужен независимый черновик рычага')
        if self.housings is not None and not isinstance(self.housings, FreeArmInnerHousings):
            raise FreeArmMiterError('Недопустимые внутренние корпуса')

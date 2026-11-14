"""Жёсткие 3D-преобразования; математика без интерпретации STEP или CAD.

Все позиции, включая начала систем, должны быть заранее выражены в одной
единице. Преобразование активно перемещает точку; смена системы координат —
другая операция. Порядок составления: parent.compose(child) = parent(child(p)).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Vector = tuple[float, float, float]
Matrix = tuple[Vector, Vector, Vector]
_MAX_COORD = 1e100
_TOL = 1e-9


def _array(value: object, shape: tuple[int, ...]) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Ожидаются конечные числовые координаты") from error
    if array.shape != shape or not np.all(np.isfinite(array)) or np.any(np.abs(array) > _MAX_COORD):
        raise ValueError("Неверная размерность или неконечные координаты")
    return array


def _rotation(value: object) -> np.ndarray:
    matrix = _array(value, (3, 3))
    if not np.allclose(matrix.T @ matrix, np.eye(3), atol=_TOL, rtol=0) or abs(np.linalg.det(matrix) - 1) > _TOL:
        raise ValueError("Матрица должна быть правосторонним жёстким вращением без масштаба")
    return matrix


def _vector_tuple(v: np.ndarray) -> Vector:
    return float(v[0]), float(v[1]), float(v[2])


def _matrix_tuple(m: np.ndarray) -> Matrix:
    return _vector_tuple(m[0]), _vector_tuple(m[1]), _vector_tuple(m[2])


@dataclass(frozen=True)
class SpatialFrame:
    """Начало и три единичные взаимно перпендикулярные правосторонние оси."""

    origin: Vector
    x: Vector
    y: Vector
    z: Vector

    def __post_init__(self) -> None:
        origin = _array(self.origin, (3,))
        basis = _rotation(np.column_stack((_array(self.x, (3,)), _array(self.y, (3,)), _array(self.z, (3,)))))
        object.__setattr__(self, "origin", _vector_tuple(origin))
        for index, name in enumerate(("x", "y", "z")):
            object.__setattr__(self, name, _vector_tuple(basis[:, index]))

    def basis(self) -> np.ndarray:
        return np.column_stack((self.x, self.y, self.z))


@dataclass(frozen=True)
class RigidTransform:
    """Активное перемещение x' = R x + t; не содержит масштабирования."""

    rotation: Matrix
    translation: Vector

    def __post_init__(self) -> None:
        object.__setattr__(self, "rotation", _matrix_tuple(_rotation(self.rotation)))
        object.__setattr__(self, "translation", _vector_tuple(_array(self.translation, (3,))))

    @classmethod
    def identity(cls) -> RigidTransform:
        return cls(((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), (0., 0., 0.))

    @classmethod
    def align_frames_same_units(cls, source: SpatialFrame, target: SpatialFrame) -> RigidTransform:
        """Переместить начало и оси source на начало и оси target.

        Это не выбор направления в STEP. Смешивать единицы без явного пересчёта нельзя.
        """
        rotation = target.basis() @ source.basis().T
        translation = np.asarray(target.origin) - rotation @ np.asarray(source.origin)
        return cls(_matrix_tuple(rotation), _vector_tuple(translation))

    def apply_point(self, point: Vector) -> Vector:
        value = np.asarray(self.rotation) @ _array(point, (3,)) + np.asarray(self.translation)
        return _vector_tuple(_array(value, (3,)))

    def apply_direction(self, direction: Vector) -> Vector:
        value = np.asarray(self.rotation) @ _array(direction, (3,))
        return _vector_tuple(_array(value, (3,)))

    def inverse(self) -> RigidTransform:
        inverse_rotation = np.asarray(self.rotation).T
        inverse_translation = -inverse_rotation @ np.asarray(self.translation)
        return RigidTransform(_matrix_tuple(inverse_rotation), _vector_tuple(inverse_translation))

    def compose(self, child: RigidTransform) -> RigidTransform:
        """Сначала child, затем self; преобразования с единицами не смешиваются."""
        parent_rotation = np.asarray(self.rotation)
        rotation = parent_rotation @ np.asarray(child.rotation)
        translation = parent_rotation @ np.asarray(child.translation) + np.asarray(self.translation)
        return RigidTransform(_matrix_tuple(rotation), _vector_tuple(translation))

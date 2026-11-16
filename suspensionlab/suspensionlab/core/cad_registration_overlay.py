"""Временный показ сетки CAD после пробного преобразования, без изменения STEP."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model.point_csv import PointRecord
from .cad_mesh import MAX_COORDINATE, CadMesh
from .cad_registration import MAX_PAIRS, RegistrationEvaluation
from .spatial_transform import RigidTransform, Vector


@dataclass(frozen=True, slots=True)
class OverlayPair:
    row: int
    role: str
    code: str
    fit: bool
    target: Vector
    transformed: Vector
    distance_mm: float


def overlay_pairs(records: tuple[PointRecord, ...], mask: tuple[bool, ...],
                  result: RegistrationEvaluation) -> tuple[OverlayPair, ...]:
    if not 3 <= len(records) <= MAX_PAIRS or len(records) != len(mask) or len(records) != len(result.points):
        raise ValueError("count")
    pairs = tuple(OverlayPair(i + 1, p.role, p.code, fit, p.xyz, result.points[i].predicted_mm,
                              result.points[i].distance_mm) for i, (p, fit) in enumerate(zip(records, mask, strict=True)))
    coords = np.asarray([(p.target, p.transformed) for p in pairs], dtype=float)
    if not np.isfinite(coords).all() or np.any(np.abs(coords) > MAX_COORDINATE):
        raise ValueError("coordinates")
    return pairs


def transform_mesh_for_preview(mesh: CadMesh, transform: RigidTransform) -> CadMesh:
    """Только временная копия треугольников в системе проекта, без групп и STEP B-rep."""
    coordinates = mesh.triangles @ np.asarray(transform.rotation).T + np.asarray(transform.translation)
    if not np.isfinite(coordinates).all() or np.any(np.abs(coordinates) > MAX_COORDINATE):
        raise ValueError("coordinates")
    return CadMesh(coordinates, mesh.face_count, mesh.skipped_faces, mesh.recovered_faces)

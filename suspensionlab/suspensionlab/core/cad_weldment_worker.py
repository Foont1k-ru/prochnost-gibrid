"""Изолированное CAD-построение только двух неподрезанных труб KIMA 0.2."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from ..model.kim_format import read_document
from .cad_kim_prototype import (
    build_front_arm_tubes_preview,
    build_front_joint_layout_preview,
    build_front_pair_preview,
    build_joint_preview,
    build_rear_joint_layout_preview,
    build_rear_pair_preview,
    build_rear_tube_preview,
    build_weldment_tubes_preview,
)
from .cad_mesh import MAX_COORDINATE
from .cad_worker import CadWorkerError

# Меньший отдельный бюджет для двух простых труб, чем у STEP-просмотрщика.
MAX_TRIANGLES = 100_000


def create_mesh(path: Path, deviation: float) -> tuple[np.ndarray, int]:
    if not math.isfinite(deviation) or not 0.2 <= deviation <= 20:
        raise CadWorkerError("deviation")
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopAbs import TopAbs_ShapeEnum
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
    except (ImportError, OSError) as error:
        raise CadWorkerError("missing_cad") from error
    doc = read_document(path, "assembly")
    if doc["version"] == "0.10":
        shape = build_rear_joint_layout_preview(doc)
    elif doc["version"] in ("0.9", "0.12", "0.13", "0.14"):
        shape = build_front_joint_layout_preview(doc)
    elif doc["version"] == "0.8":
        shape = build_joint_preview(doc)
    elif doc["version"] in ("0.7", "0.11"):
        shape = build_front_pair_preview(doc)
    elif doc["version"] == "0.6":
        shape = build_rear_pair_preview(doc)
    elif doc["version"] == "0.4":
        shape = build_rear_tube_preview(doc)
    elif doc["version"] == "0.5":
        shape = build_front_arm_tubes_preview(doc)
    else:
        shape = build_weldment_tubes_preview(doc)
    if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
        raise CadWorkerError("no_shape")
    angular_deviation = 0.25 if deviation <= 0.5 else 0.7
    mesher = BRepMesh_IncrementalMesh(shape, deviation, False, angular_deviation, False)
    if not mesher.IsDone():
        raise CadWorkerError("mesh")
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    chunks: list[np.ndarray] = []
    faces = total = 0
    while explorer.More():
        faces += 1
        face = TopoDS.Face(explorer.Current())
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, location)
        if poly is None or poly.NbTriangles() <= 0 or poly.NbNodes() <= 0:
            # Never display missing faces as if the preview were complete.
            raise CadWorkerError("missing_face")
        count = poly.NbTriangles()
        if total + count > MAX_TRIANGLES or poly.NbNodes() > MAX_TRIANGLES * 3:
            raise CadWorkerError("memory")
        transform = location.Transformation()
        nodes = np.empty((poly.NbNodes(), 3), dtype=np.float64)
        for i in range(1, poly.NbNodes() + 1):
            point = poly.Node(i).Transformed(transform)
            nodes[i - 1] = point.X(), point.Y(), point.Z()
        if not np.isfinite(nodes).all() or np.any(np.abs(nodes) > MAX_COORDINATE):
            raise CadWorkerError("coordinates")
        indices = np.empty((count, 3), dtype=np.int32)
        for i in range(1, count + 1):
            triangle = poly.Triangle(i)
            indices[i - 1] = triangle.Value(1) - 1, triangle.Value(2) - 1, triangle.Value(3) - 1
        if np.any(indices < 0) or np.any(indices >= len(nodes)):
            raise CadWorkerError("mesh")
        chunks.append(nodes[indices])
        total += count
        explorer.Next()
    if not chunks:
        raise CadWorkerError("no_faces")
    return np.concatenate(chunks), faces


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        return 2
    source, output, report = map(Path, args[:3])
    try:
        triangles, faces = create_mesh(source, float(args[3]))
        np.savez(output, triangles=triangles, faces=np.array([faces], dtype=np.int64),
                 skipped=np.array([0], dtype=np.int64), recovered=np.array([0], dtype=np.int64),
                 names=np.asarray(["tubes"], dtype="U128"), groups=np.zeros(len(triangles), dtype=np.int32),
                 instance_groups=np.array([0], dtype=np.int32), instances=np.zeros(len(triangles), dtype=np.int32))
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return 0
    except CadWorkerError as error:
        report.write_text(json.dumps({"status": "error", "code": error.code}), encoding="utf-8")
    except Exception:
        report.write_text(json.dumps({"status": "error", "code": "unexpected"}), encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

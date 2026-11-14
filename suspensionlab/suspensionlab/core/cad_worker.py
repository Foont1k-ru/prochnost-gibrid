"""Изолированный процесс OCC: читает STEP и сохраняет ограниченную сетку.

Это только визуализация граней. Другие типы представлений могут быть пропущены.
Не изменяет проект и не считает механику. Не предназначен для недоверенных файлов.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from .cad_mesh import MAX_COORDINATE, MAX_TRIANGLES
from .step_inventory import MAX_BYTES


class CadWorkerError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def create_mesh(path: Path, deviation: float) -> tuple[np.ndarray, int]:
    """OCCT самостоятельно читает сборочные положения; наши кандидаты не применяются."""
    if not path.is_file() or path.stat().st_size > MAX_BYTES or path.stat().st_size == 0:
        raise CadWorkerError("file_size")
    if not np.isfinite(deviation) or not 0.2 <= deviation <= 20:
        raise CadWorkerError("deviation")
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_ShapeEnum
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
    except (ImportError, OSError) as error:
        raise CadWorkerError("missing_cad") from error
    reader = STEPControl_Reader()
    if not Interface_Static.SetCVal_s("xstep.cascade.unit", "MM"):
        raise CadWorkerError("units")
    if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise CadWorkerError("read")
    if reader.TransferRoots() < 1 or reader.NbShapes() < 1:
        raise CadWorkerError("no_shape")
    shape = reader.OneShape()
    if shape.IsNull():
        raise CadWorkerError("no_shape")
    mesher = BRepMesh_IncrementalMesh(shape, deviation, False, 0.7, False)
    if not mesher.IsDone():
        raise CadWorkerError("mesh")
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    chunks: list[np.ndarray] = []
    faces = total = 0
    while explorer.More():
        faces += 1
        if faces > MAX_TRIANGLES:
            raise CadWorkerError("limit")
        face = TopoDS.Face(explorer.Current())
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, location)
        if poly is None or poly.NbTriangles() <= 0 or poly.NbNodes() <= 0:
            raise CadWorkerError("missing_face")
        number_triangles = poly.NbTriangles()
        if total + number_triangles > MAX_TRIANGLES or poly.NbNodes() > MAX_TRIANGLES * 3:
            raise CadWorkerError("limit")
        transformation = location.Transformation()
        nodes = np.empty((poly.NbNodes(), 3), dtype=np.float64)
        for index in range(1, poly.NbNodes() + 1):
            point = poly.Node(index).Transformed(transformation)
            nodes[index - 1] = point.X(), point.Y(), point.Z()
        if not np.all(np.isfinite(nodes)) or np.any(np.abs(nodes) > MAX_COORDINATE):
            raise CadWorkerError("coordinates")
        indices = np.empty((number_triangles, 3), dtype=np.int32)
        for index in range(1, number_triangles + 1):
            triangle = poly.Triangle(index)
            indices[index - 1] = triangle.Value(1) - 1, triangle.Value(2) - 1, triangle.Value(3) - 1
        if np.any(indices < 0) or np.any(indices >= len(nodes)):
            raise CadWorkerError("mesh")
        chunks.append(nodes[indices])
        total += number_triangles
        explorer.Next()
    if not chunks:
        raise CadWorkerError("no_faces")
    return np.concatenate(chunks, axis=0), faces


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        return 2
    source, output, report = map(Path, args[:3])
    try:
        triangles, faces = create_mesh(source, float(args[3]))
        np.savez_compressed(output, triangles=triangles, faces=np.array([faces], dtype=np.int64))
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return 0
    except CadWorkerError as error:
        report.write_text(json.dumps({"status": "error", "code": error.code}), encoding="utf-8")
    except Exception:
        # STEP/CAD может содержать личные данные; не записываем их в общий журнал.
        report.write_text(json.dumps({"status": "error", "code": "unexpected"}), encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

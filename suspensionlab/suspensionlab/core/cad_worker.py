"""Изолированный процесс OCC: читает STEP и сохраняет ограниченную сетку.

Это только визуализация граней. Другие типы представлений могут быть пропущены.
Не изменяет проект и не считает механику. Не предназначен для недоверенных файлов.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

from .cad_instances import collect_instances
from .cad_mesh import MAX_COORDINATE, MAX_MESH_BYTES
from .cad_parts import collect_part_groups, face_group
from .cad_recovery import recover_revolution_face
from .step_inventory import MAX_BYTES


class CadWorkerError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _progress(stage: str, faces: int = 0) -> None:
    """Только этап и счётчик; файловые пути и геометрия наружу не передаются."""
    name = os.environ.get("SUSPENSIONLAB_CAD_PROGRESS_PATH")
    if not name:
        return
    path = Path(name)
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"stage": stage, "faces": faces}), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def _face_triangulation(face, location):
    from OCP.BRep import BRep_Tool

    return BRep_Tool.Triangulation_s(face, location)


def _retry_face_triangulation(face, location):
    """Пробуем мелкую сетку только для тех граней, которые не построились."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    BRepMesh_IncrementalMesh(face, 0.2, False, 0.4, False)
    return _face_triangulation(face, location)


def create_mesh(path: Path, deviation: float) -> tuple[np.ndarray, int, int, int, tuple[str, ...], np.ndarray, tuple[int, ...], np.ndarray]:
    """OCCT самостоятельно читает сборочные положения; наши кандидаты не применяются."""
    if not path.is_file() or path.stat().st_size > MAX_BYTES or path.stat().st_size == 0:
        raise CadWorkerError("file_size")
    if not np.isfinite(deviation) or not 0.2 <= deviation <= 20:
        raise CadWorkerError("deviation")
    try:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.Interface import Interface_Static
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDocStd import TDocStd_Document
        from OCP.TopAbs import TopAbs_ShapeEnum
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
    except (ImportError, OSError) as error:
        raise CadWorkerError("missing_cad") from error
    _progress("read")
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if not Interface_Static.SetCVal_s("xstep.cascade.unit", "MM"):
        raise CadWorkerError("units")
    if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise CadWorkerError("read")
    _progress("transfer")
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    if not reader.Transfer(document):
        raise CadWorkerError("no_shape")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    shape = tool.GetOneShape()
    if shape.IsNull():
        raise CadWorkerError("no_shape")
    _progress("groups")
    names, face_groups = collect_part_groups(tool, shape)
    instance_groups, instance_faces = collect_instances(tool, face_groups)
    _progress("mesh")
    mesher = BRepMesh_IncrementalMesh(shape, deviation, False, 0.7, True)
    if not mesher.IsDone():
        raise CadWorkerError("mesh")
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    chunks: list[np.ndarray] = []
    group_chunks: list[np.ndarray] = []
    instance_chunks: list[np.ndarray] = []
    faces = total = skipped = recovered = 0
    _progress("faces")
    while explorer.More():
        faces += 1
        if faces % 200 == 0:
            _progress("faces", faces)
        face = TopoDS.Face(explorer.Current())
        location = TopLoc_Location()
        poly = _face_triangulation(face, location)
        if poly is None or poly.NbTriangles() <= 0:
            poly = _retry_face_triangulation(face, location)
        if poly is None or poly.NbTriangles() <= 0:
            restored = recover_revolution_face(face, deviation)
            if restored is not None:
                location = TopLoc_Location()
                poly = _face_triangulation(restored, location)
                if poly is not None and poly.NbTriangles() > 0:
                    recovered += 1
        if poly is None or poly.NbTriangles() <= 0:
            skipped += 1
            explorer.Next()
            continue
        if poly.NbNodes() <= 0:
            raise CadWorkerError("mesh")
        number_triangles = poly.NbTriangles()
        # Ограничение объёма, а не старый лимит в 100 тысяч элементов.
        if (total + number_triangles) * 72 > MAX_MESH_BYTES or poly.NbNodes() * 24 > MAX_MESH_BYTES:
            raise CadWorkerError("memory")
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
        group = face_group(face, face_groups)
        instance = face_group(face, instance_faces)
        if instance and instance_groups[instance] != group:
            instance = 0
        group_chunks.append(np.full(number_triangles, group, dtype=np.int32))
        instance_chunks.append(np.full(number_triangles, instance, dtype=np.int32))
        total += number_triangles
        explorer.Next()
    if not chunks:
        raise CadWorkerError("no_faces")
    return (np.concatenate(chunks, axis=0), faces, skipped, recovered, names, np.concatenate(group_chunks),
            instance_groups, np.concatenate(instance_chunks))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        return 2
    source, output, report = map(Path, args[:3])
    try:
        triangles, faces, skipped, recovered, names, groups, instance_groups, instances = create_mesh(source, float(args[3]))
        _progress("save", faces)
        np.savez(output, triangles=triangles, faces=np.array([faces], dtype=np.int64),
                            skipped=np.array([skipped], dtype=np.int64),
                            recovered=np.array([recovered], dtype=np.int64),
                            names=np.asarray(names, dtype="U128"), groups=groups,
                            instance_groups=np.asarray(instance_groups, dtype=np.int32), instances=instances)
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

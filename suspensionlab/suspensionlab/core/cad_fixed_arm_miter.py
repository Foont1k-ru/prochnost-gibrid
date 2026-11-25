"""Экспериментальная геометрия стыка двух труб одной плоскостью.

Только независимый CAD-прототип; не проверяет сварку, зазоры на ходу,
прочность, технологию и возможность изготовления.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..model.bent_tube import make_bend_path
from ..model.welded_arm import weldment_source_matches


class MiterError(ValueError):
    """Общий рез неоднозначен или не даёт две допустимые цельные трубы."""


@dataclass(frozen=True, slots=True)
class MiterGeometry:
    point: tuple[float, float, float]
    normal: tuple[float, float, float]
    directions: tuple[tuple[float, float, float], tuple[float, float, float]]
    extension_mm: float


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.hypot(*v)
    if not math.isfinite(length) or length < 1e-8:
        raise MiterError('Вырожденное направление трубы')
    return (v[0] / length, v[1] / length, v[2] / length)


def miter_geometry(document: dict[str, Any]) -> MiterGeometry:
    """Плоскость между конечными прямыми участками при одинаковых радиусах.

    Оси труб продолжаются только для построения реза; требуется, чтобы длина
    конечного прямого участка была больше необходимого продолжения. Очень
    острые, неоднозначные и несовместимые конфигурации отклоняются.
    """
    if not weldment_source_matches(document) or len(document['parts']) != 2:
        raise MiterError('Нужен актуальный снимок двух труб')
    parts = document['parts']
    geometry = [part['geometry'] for part in parts]
    if [g['leg'] for g in geometry] != ['front', 'rear']:
        raise MiterError('Нужны передняя и задняя трубы')
    points = geometry[0]['source']['coordinates_mm']
    return miter_geometry_for_tubes(points, geometry)


def miter_geometry_for_tubes(points: Any, geometry: list[dict[str, Any]]) -> MiterGeometry:
    """Общая операция по явным опорам и двум геометриям без снимка проекта."""
    if len(geometry) != 2 or len(points) != 3:
        raise MiterError('Нужны три опоры и две трубы')
    radii = [float(g['radius_mm']) for g in geometry]
    walls = [float(g['wall_mm']) for g in geometry]
    if radii[0] != radii[1] or walls[0] != walls[1]:
        raise MiterError('Общий рез пока поддерживает только одинаковые радиусы и стенки труб')
    joint = (float(points[2][0]), float(points[2][1]), float(points[2][2]))
    ends = []
    directions = []
    for index, g in enumerate(geometry):
        start = tuple(float(x) for x in points[index])
        if g['kind'] == 'prototype_arm_tube':
            end_of_straight = start
        elif g['kind'] == 'prototype_arm_bent_tube':
            path = make_bend_path(start, g['bend_vertex_mm'], joint, g['bend_radius_mm'], g['radius_mm'])
            end_of_straight = path.tangent_end
        else:
            raise MiterError('Тип трубы не поддерживает общий рез')
        direction = _unit((end_of_straight[0] - joint[0], end_of_straight[1] - joint[1],
                           end_of_straight[2] - joint[2]))
        directions.append(direction)
        ends.append(math.dist(joint, end_of_straight))
    difference = (directions[0][0] - directions[1][0], directions[0][1] - directions[1][1],
                  directions[0][2] - directions[1][2])
    difference_length = math.hypot(*difference)
    if difference_length < 0.02:
        raise MiterError('Оси труб слишком близки к совпадению; общий рез неоднозначен')
    normal = _unit(difference)
    dot = max(-1., min(1., sum(directions[0][i] * directions[1][i] for i in range(3))))
    extension = radii[0] * math.sqrt(max(0., (1. + dot) / (1. - dot)))
    if not math.isfinite(extension) or extension + 0.01 >= min(ends):
        raise MiterError('Рез выходит за конечный прямой участок трубы')
    return MiterGeometry(joint, normal, (directions[0], directions[1]), extension)


def build_miter_tubes(document: dict[str, Any]) -> tuple[Any, Any]:
    """Построить две валидные непересекающиеся трубы со стыком по плоскости.

    Возвращает только обе трубы, без корпусов и подрезок по ним.
    """
    from .cad_kim_prototype import build_part

    miter = miter_geometry(document)
    geometries = [part['geometry'] for part in document['parts']]
    points = geometries[0]['source']['coordinates_mm']
    originals = [build_part(part) for part in document['parts']]
    return build_miter_tubes_for_geometry(points, geometries, originals, miter)


def build_miter_tubes_for_geometry(points: Any, geometries: list[dict[str, Any]],
                                    originals: list[Any], miter: MiterGeometry) -> tuple[Any, Any]:
    """Общее CAD-ядро без фиктивного документа, с проверкой исходных тел."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeHalfSpace
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pln, gp_Pnt
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    from .cad_kim_prototype import _build_bent_tube

    if len(geometries) != 2 or len(originals) != 2:
        raise MiterError('Нужны две трубы')
    point, normal = miter.point, miter.normal
    plane = gp_Pln(gp_Pnt(*point), gp_Dir(*normal))
    face = BRepBuilderAPI_MakeFace(plane).Face()
    results = []
    for index, g in enumerate(geometries):
        u = miter.directions[index]  # points from common end toward the tube
        tip = tuple(point[i] - u[i] * (miter.extension_mm + 0.01) for i in range(3))
        start = tuple(float(x) for x in points[index])
        if g['kind'] == 'prototype_arm_bent_tube':
            tube = _build_bent_tube(g, endpoints=(start, tip))
        else:
            axis = gp_Ax2(gp_Pnt(*start), gp_Dir(*(tip[i] - start[i] for i in range(3))))
            length = math.dist(start, tip)
            outer = BRepPrimAPI_MakeCylinder(axis, float(g['radius_mm']), length).Shape()
            inner = BRepPrimAPI_MakeCylinder(axis, float(g['radius_mm'] - g['wall_mm']), length).Shape()
            hollow = BRepAlgoAPI_Cut(outer, inner)
            if not hollow.IsDone() or hollow.Shape().IsNull():
                raise MiterError('Не удалось построить исходную трубу')
            tube = hollow.Shape()
        reference = gp_Pnt(*(point[i] + u[i] * max(1., miter.extension_mm + 1.) for i in range(3)))
        halfspace = BRepPrimAPI_MakeHalfSpace(face, reference)
        if not halfspace.IsDone():
            raise MiterError('Не удалось построить разделяющую плоскость')
        cut = BRepAlgoAPI_Common(tube, halfspace.Solid())
        if not cut.IsDone() or cut.Shape().IsNull() or not BRepCheck_Analyzer(cut.Shape()).IsValid():
            raise MiterError('Невозможно построить корректный стык')
        result = cut.Shape()
        solids = TopExp_Explorer(result, TopAbs_SOLID)
        count = 0
        while solids.More():
            count += 1
            solids.Next()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(result, props, 1e-8)
        if count != 1 or not math.isfinite(props.Mass()) or props.Mass() <= 1e-6:
            raise MiterError('Рез удаляет или разрывает трубу')
        original_props = GProp_GProps()
        BRepGProp.VolumeProperties_s(originals[index], original_props, 1e-8)
        if not math.isclose(props.Mass(), original_props.Mass(), rel_tol=1e-6, abs_tol=1e-5):
            raise MiterError('Плоскость затрагивает другие участки трубы')
        validate_miter_face(result, miter, g, index)
        results.append(result)
    return results[0], results[1]


def validate_miter_face(shape: Any, miter: MiterGeometry, geometry: dict[str, Any], index: int) -> None:
    """После дополнительных резов полный торец стыка должен остаться целым."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    point, normal, u = miter.point, miter.normal, miter.directions[index]
    expected = (math.pi * (geometry['radius_mm'] ** 2 -
                           (geometry['radius_mm'] - geometry['wall_mm']) ** 2) /
                abs(sum(normal[i] * u[i] for i in range(3))))
    areas = []
    faces = TopExp_Explorer(shape, TopAbs_FACE)
    while faces.More():
        item = TopoDS.Face(faces.Current())
        surface = BRepAdaptor_Surface(item)
        if surface.GetType() == GeomAbs_Plane:
            face_plane = surface.Plane()
            location, axis = face_plane.Location(), face_plane.Axis().Direction()
            p = (location.X(), location.Y(), location.Z())
            n = (axis.X(), axis.Y(), axis.Z())
            offset = sum((p[i] - point[i]) * normal[i] for i in range(3))
            alignment = abs(sum(n[i] * normal[i] for i in range(3)))
            if abs(offset) < 1e-6 and alignment > 1 - 1e-8:
                props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(item, props, 1e-8)
                areas.append(float(props.Mass()))
        faces.Next()
    if len(areas) != 1 or not math.isclose(areas[0], expected, rel_tol=1e-6, abs_tol=1e-5):
        raise MiterError('Поверхность стыка неполная или вырожденная')

"""Изолированный опыт стыковки труб с корпусом; не проверка изготовления."""
from __future__ import annotations

import math
from typing import Any

from ..model.ball_housing import BallHousingError, validate_ball_housing
from ..model.bent_tube import make_bend_path
from ..model.welded_arm import weldment_source_matches


def build_ball_housing_tubes(document: dict[str, Any], parameters: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Две трубы, оканчивающиеся на конечном цилиндрическом корпусе, и сам корпус.

    Оси последнего прямого участка направлены в центр корпуса, а не в центр
    шаровой. Направление оси корпуса и его смещение от центра шаровой заданы
    пользователем. Все тела отдельные; сварка и подвижный шарнир не моделируются.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.GProp import GProp_GProps

    from .cad_kim_prototype import _build_bent_tube
    from .cad_tube_notch import TubeNotchError, _cut_tube

    data = validate_ball_housing(parameters)
    if not weldment_source_matches(document) or len(document['parts']) != 2:
        raise BallHousingError('Нужен актуальный снимок двух труб')
    geometries = [part['geometry'] for part in document['parts']]
    if [item['leg'] for item in geometries] != ['front', 'rear']:
        raise BallHousingError('Нужны передняя и задняя трубы')
    points = geometries[0]['source']['coordinates_mm']
    center = tuple(float(points[2][i]) + data['offset_mm'][i] for i in range(3))
    if any(not math.isfinite(x) or abs(x) > 1_000_000 for x in center):
        raise BallHousingError('Центр корпуса вне допустимого диапазона')
    norm = math.hypot(*data['axis'])
    axis = tuple(x / norm for x in data['axis'])
    length = data['length_mm']
    radius = data['outer_diameter_mm'] / 2
    origin = tuple(center[i] - axis[i] * length / 2 for i in range(3))
    frame = gp_Ax2(gp_Pnt(*origin), gp_Dir(*axis))
    envelope = BRepPrimAPI_MakeCylinder(frame, radius, length).Shape()
    bore = BRepPrimAPI_MakeCylinder(frame, data['bore_diameter_mm'] / 2, length).Shape()
    cut_housing = BRepAlgoAPI_Cut(envelope, bore)
    if not cut_housing.IsDone() or cut_housing.Shape().IsNull() or not BRepCheck_Analyzer(cut_housing.Shape()).IsValid():
        raise BallHousingError('Не удалось построить корпус')
    housing = cut_housing.Shape()
    tubes = []
    for index, geometry in enumerate(geometries):
        start = (float(points[index][0]), float(points[index][1]), float(points[index][2]))
        kind = geometry['kind']
        if kind == 'prototype_arm_bent_tube':
            try:
                path = make_bend_path(start, geometry['bend_vertex_mm'], center,
                                      geometry['bend_radius_mm'], geometry['radius_mm'])
                straight_start = path.tangent_end
                tube = _build_bent_tube(geometry, endpoints=(start, center))
            except (ValueError, RuntimeError) as error:
                raise BallHousingError('Изгиб не достигает заданного центра корпуса') from error
        elif kind == 'prototype_arm_tube':
            straight_start = start
            direction = tuple(center[i] - start[i] for i in range(3))
            if math.hypot(*direction) < .01:
                raise BallHousingError('Опора совпала с центром корпуса')
            tube_frame = gp_Ax2(gp_Pnt(*start), gp_Dir(*direction))
            tube_length = math.dist(start, center)
            outer = BRepPrimAPI_MakeCylinder(tube_frame, geometry['radius_mm'], tube_length).Shape()
            inner = BRepPrimAPI_MakeCylinder(tube_frame, geometry['radius_mm'] - geometry['wall_mm'], tube_length).Shape()
            operation = BRepAlgoAPI_Cut(outer, inner)
            if not operation.IsDone() or operation.Shape().IsNull():
                raise BallHousingError('Не удалось построить трубу')
            tube = operation.Shape()
        else:
            raise BallHousingError('Неподдерживаемая труба')
        direction = tuple(straight_start[i] - center[i] for i in range(3))
        distance = math.hypot(*direction)
        if distance < .01:
            raise BallHousingError('Последний прямой участок слишком короток')
        u = tuple(x / distance for x in direction)
        axial = abs(sum(u[i] * axis[i] for i in range(3)))
        radial = math.sqrt(max(0., 1. - axial * axial))
        # Conservative bound: the entire tube section must approach the lateral
        # cylinder, not its end cap. It is a numerical guard, not a weld design.
        if radial < 1e-4 or (radius * axial + geometry['radius_mm']) / radial >= length / 2:
            raise BallHousingError('Труба выходит за торец корпуса; измените ось, длину или положение')
        if radius / radial + geometry['radius_mm'] >= distance:
            raise BallHousingError('Корпус достигает изгиба или внутренней опоры')
        try:
            tubes.append(_cut_tube(tube, envelope, f'tube_{index}', 'ball_housing').shape)
        except TubeNotchError as error:
            raise BallHousingError(f'Не удалось подрезать трубу: {error.code}') from error
    common = BRepAlgoAPI_Common(tubes[0], tubes[1])
    if not common.IsDone() or common.Shape().IsNull():
        raise BallHousingError('Не удалось проверить взаимное пересечение труб')
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(common.Shape(), props, 1e-8)
    volume = float(props.Mass())
    if not math.isfinite(volume) or abs(volume) > 1e-6:
        raise BallHousingError('Трубы пересекаются до корпуса; измените положение или форму')
    return tubes[0], tubes[1], housing



def validate_ball_housing_contacts(document: dict[str, Any], parameters: dict[str, Any],
                                   original: list[Any], trimmed: list[Any]) -> None:
    """Последующая подрезка не должна удалять материал вблизи центрального стыка."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.GProp import GProp_GProps

    data = validate_ball_housing(parameters)
    point = document['parts'][0]['geometry']['source']['coordinates_mm'][2]
    center = [point[i] + data['offset_mm'][i] for i in range(3)]
    norm = math.hypot(*data['axis'])
    axis = [x / norm for x in data['axis']]
    for index, (before, after) in enumerate(zip(original, trimmed, strict=True)):
        margin = max(1., float(document['parts'][index]['geometry']['radius_mm']))
        length = data['length_mm'] + 2 * margin
        origin = [center[i] - axis[i] * length / 2 for i in range(3)]
        guard = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*origin), gp_Dir(*axis)),
                                         data['outer_diameter_mm'] / 2 + margin, length).Shape()
        removed = BRepAlgoAPI_Cut(before, after)
        if not removed.IsDone() or removed.Shape().IsNull():
            raise BallHousingError('Не удалось проверить прилегание к корпусу')
        nearby = BRepAlgoAPI_Common(removed.Shape(), guard)
        if not nearby.IsDone() or nearby.Shape().IsNull():
            raise BallHousingError('Не удалось проверить прилегание к корпусу')
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(nearby.Shape(), props, 1e-8)
        volume = abs(float(props.Mass()))
        if not math.isfinite(volume) or volume > 1e-6:
            raise BallHousingError('Подрезка внутренней опоры повреждает прилегание к центральному корпусу')

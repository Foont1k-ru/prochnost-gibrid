"""Экспериментальная подрезка трубы по корпусу, пластине или другой трубе.

Это только CAD-прототип; исходные .kim/.kima не изменяются и готовая деталь
не создаётся. Выбор пары выполняет вызывающая сторона, не алгоритм.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..model.scheme_arm_assembly import validate_scheme_arm_assembly
from .cad_kim_prototype import _place_scheme_arm_plate, build_part


class TubeNotchError(ValueError):
    """Подрезка не принята; code указывает причину, не инженерный допуск."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TubeNotch:
    tube_id: str
    cutter_id: str
    shape: Any
    original_volume_mm3: float
    remaining_volume_mm3: float
    removed_volume_mm3: float

    @property
    def housing_id(self) -> str:
        """Совместимость с первоначальным внутренним прототипом корпуса."""
        return self.cutter_id


def notch_tube_against_housing(document: dict[str, Any], tube_id: str, housing_id: str) -> TubeNotch:
    """Вычесть наружный конечный цилиндр корпуса из одной исходной трубы.

    Нулевой моделируемый зазор, без удлинения трубы или корпуса. Отверстие
    корпуса намеренно не используется как режущий объём: труба не должна
    оставаться внутри отверстия из-за вычитания лишь кольца материала корпуса.
    Нет скоса кромок, технологических или прочностных расчётов. Отклоняются
    отсутствие существенного пересечения, полное удаление и разрыв на части.
    Запускать вычисление отдельно от UI: CAD может работать долго или упасть.
    """
    validate_scheme_arm_assembly(document)
    if tube_id not in ('tube_front', 'tube_rear') or housing_id not in ('housing_front', 'housing_rear'):
        raise TubeNotchError('unsupported_pair')

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    tube_index = ('tube_front', 'tube_rear').index(tube_id)
    housing_index = ('housing_front', 'housing_rear').index(housing_id)
    tube = build_part(document['parts'][tube_index])
    geometry = document['parts'][housing_index + 2]['geometry']
    centre = document['parts'][0]['geometry']['source']['coordinates_mm'][housing_index]
    directions = {'x': (1., 0., 0.), 'y': (0., 1., 0.), 'z': (0., 0., 1.)}
    direction = directions[document['axis']]
    length = float(geometry['length_mm'])
    start = [float(centre[i]) - direction[i] * length / 2 for i in range(3)]
    cutter = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*start), gp_Dir(*direction)),
                                      float(geometry['outer_radius_mm']), length).Shape()
    return _cut_tube(tube, cutter, tube_id, housing_id)


def notch_tube_against_plate(document: dict[str, Any], tube_id: str) -> TubeNotch:
    """Вычесть реальное конечное тело пластины, включая её отверстие как пустоту.

    Нулевой зазор; труба может остаться внутри отверстия. Нет продления,
    моделирования прохода крепежа или проверки монтажа. Только временный результат.
    """
    validate_scheme_arm_assembly(document)
    if tube_id not in ('tube_front', 'tube_rear'):
        raise TubeNotchError('unsupported_pair')
    if document['version'] != '0.16':
        raise TubeNotchError('missing_plate')
    tube = build_part(document['parts'][('tube_front', 'tube_rear').index(tube_id)])
    return _cut_tube(tube, _place_scheme_arm_plate(document), tube_id, 'ball_plate')


def notch_tube_against_tube(document: dict[str, Any], tube_id: str, cutter_id: str) -> TubeNotch:
    """Вычесть конечный сплошной наружный цилиндр другой прямой трубы.

    Режущая труба остаётся полой в отображении, но используется её наружный
    объём: материал подрезаемой трубы не должен заходить внутрь её отверстия.
    Без продления труб и зазора; рассматривается только одна явно выбранная пара.
    """
    validate_scheme_arm_assembly(document)
    tubes = ('tube_front', 'tube_rear')
    if tube_id not in tubes or cutter_id not in tubes:
        raise TubeNotchError('unsupported_pair')
    if tube_id == cutter_id:
        raise TubeNotchError('same_tube')

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    target = build_part(document['parts'][tubes.index(tube_id)])
    geometry = document['parts'][tubes.index(cutter_id)]['geometry']
    points = geometry['source']['coordinates_mm']
    start = points[0 if geometry['leg'] == 'front' else 1]
    end = points[2]
    direction = [float(end[i]) - float(start[i]) for i in range(3)]
    envelope = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, start)), gp_Dir(*direction)),
                                        float(geometry['radius_mm']), math.dist(start, end)).Shape()
    return _cut_tube(target, envelope, tube_id, cutter_id)


def _cut_tube(tube: Any, cutter: Any, tube_id: str, cutter_id: str) -> TubeNotch:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if tube.IsNull() or not BRepCheck_Analyzer(tube).IsValid():
        raise TubeNotchError('invalid_tube')
    if cutter.IsNull() or not BRepCheck_Analyzer(cutter).IsValid():
        raise TubeNotchError('invalid_cutter')

    def volume(shape: Any) -> float:
        properties = GProp_GProps()
        # Adaptive integration is needed for the intersection curves of two
        # cylinders; the default fixed integration can give inconsistent volumes.
        BRepGProp.VolumeProperties_s(shape, properties, 1e-8)
        result = float(properties.Mass())
        if not math.isfinite(result) or result < 0:
            raise TubeNotchError('invalid_volume')
        return result

    original = volume(tube)
    if original <= 0:
        raise TubeNotchError('invalid_tube')
    common = BRepAlgoAPI_Common(tube, cutter)
    if not common.IsDone() or common.Shape().IsNull():
        raise TubeNotchError('intersection_failed')
    intersection = volume(common.Shape())
    # This is a numerical screening threshold, not a weld or machining tolerance.
    epsilon = max(1e-6, original * 1e-9)
    if intersection <= epsilon:
        raise TubeNotchError('no_overlap')
    cut = BRepAlgoAPI_Cut(tube, cutter)
    if not cut.IsDone() or cut.Shape().IsNull():
        raise TubeNotchError('cut_failed')
    explorer = TopExp_Explorer(cut.Shape(), TopAbs_SOLID)
    solids = []
    while explorer.More():
        solids.append(TopoDS.Solid(explorer.Current()))
        explorer.Next()
    if len(solids) != 1:
        raise TubeNotchError('empty_or_split')
    shape = solids[0]
    if not BRepCheck_Analyzer(shape).IsValid():
        raise TubeNotchError('invalid_result')
    remaining = volume(shape)
    removed = original - remaining
    if (remaining <= epsilon or removed <= epsilon or
            abs(removed - intersection) > max(1e-5, original * 1e-6)):
        raise TubeNotchError('invalid_result')
    residual = BRepAlgoAPI_Common(shape, cutter)
    if not residual.IsDone() or residual.Shape().IsNull() or volume(residual.Shape()) > epsilon:
        raise TubeNotchError('invalid_result')
    return TubeNotch(tube_id, cutter_id, shape, original, remaining, removed)

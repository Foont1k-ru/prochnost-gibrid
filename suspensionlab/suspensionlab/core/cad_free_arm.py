"""Неполный CAD-предпросмотр независимого рычага, без снимка подвески."""
from __future__ import annotations

import math
from typing import Any

from ..model.free_arm import FreeArmDraft
from .cad_kim_prototype import _build_bent_tube


def build_free_arm_ball_housing(draft: FreeArmDraft, parameters: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Опытная общая операция для независимых опор, без создания снимка проекта.

    Операция возвращает отдельные тела; монтаж и прочность не проверяются.
    """
    if not isinstance(draft, FreeArmDraft):
        raise ValueError('Ожидался независимый черновик')
    from .cad_ball_housing import _build_housing_for_tubes

    return _build_housing_for_tubes(draft.anchors, _free_arm_geometries(draft), parameters)


def _free_arm_geometries(draft: FreeArmDraft) -> list[dict[str, Any]]:
    geometries: list[dict[str, Any]] = []
    for bend in (draft.front_bend, draft.rear_bend):
        geometry: dict[str, Any] = {'kind': 'prototype_arm_tube' if bend is None else 'prototype_arm_bent_tube',
                                    'radius_mm': draft.radius_mm, 'wall_mm': draft.wall_mm}
        if bend is not None:
            geometry.update(bend_vertex_mm=bend.vertex_mm, bend_radius_mm=bend.radius_mm)
        geometries.append(geometry)
    return geometries



def build_free_arm_tubes(draft: FreeArmDraft) -> tuple[Any, tuple[Any, Any]]:
    """Две неподрезанные полые трубы; никаких проверок сборки или прочности.

    Функция вызывается внутри изолированного CAD-процесса, не из GUI-потока.
    """
    if not isinstance(draft, FreeArmDraft):
        raise ValueError('Ожидался независимый черновик')
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    shapes = []
    for start, bend in ((draft.front_mm, draft.front_bend), (draft.rear_mm, draft.rear_bend)):
        if bend is None:
            direction = tuple(end - origin for origin, end in zip(start, draft.outer_mm, strict=True))
            axis = gp_Ax2(gp_Pnt(*start), gp_Dir(*direction))
            length = math.dist(start, draft.outer_mm)
            outside = BRepPrimAPI_MakeCylinder(axis, draft.radius_mm, length).Shape()
            bore = BRepPrimAPI_MakeCylinder(axis, draft.radius_mm - draft.wall_mm, length).Shape()
            cut = BRepAlgoAPI_Cut(outside, bore)
            if not cut.IsDone() or cut.Shape().IsNull():
                raise RuntimeError('Не удалось построить полую трубу')
            shape = cut.Shape()
        else:
            geometry = {'radius_mm': draft.radius_mm, 'wall_mm': draft.wall_mm,
                        'bend_vertex_mm': bend.vertex_mm, 'bend_radius_mm': bend.radius_mm}
            shape = _build_bent_tube(geometry, endpoints=(start, draft.outer_mm))
        if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
            raise RuntimeError('Недопустимая геометрия предварительной трубы')
        shapes.append(shape)
        builder.Add(compound, shape)
    return compound, (shapes[0], shapes[1])


def build_free_arm_inner_housings(draft: Any) -> tuple[Any, tuple[Any, ...]]:
    """Построить независимые трубы и конечные внутренние корпуса в CAD-процессе."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Compound

    from ..model.free_arm_inner_housings import FreeArmInnerHousingDraft
    from .cad_ball_housing import validate_ball_housing_contacts_for_tubes
    from .cad_inner_housings import build_inner_housings_and_notch

    if not isinstance(draft, FreeArmInnerHousingDraft):
        raise ValueError('Ожидался независимый рычаг с внутренними корпусами')
    ball = None
    if draft.ball_housing is not None:
        front, rear, ball = build_free_arm_ball_housing(draft.arm, draft.ball_housing.as_data())
        original = [front, rear]
    else:
        _, pair = build_free_arm_tubes(draft.arm)
        original = list(pair)
    notches = draft.housings.as_notches() or {}
    tubes, housings = build_inner_housings_and_notch(original, draft.arm.anchors[:2],
                                                      draft.housings.as_housings(), notches)
    if draft.ball_housing is not None and ball is not None and notches:
        validate_ball_housing_contacts_for_tubes(draft.arm.outer_mm, [draft.arm.radius_mm] * 2,
                                                  draft.ball_housing.as_data(), original, tubes)
    components = (*tubes, *housings, *((ball,) if ball is not None else ()))
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for component in components:
        if component.IsNull() or not BRepCheck_Analyzer(component).IsValid():
            raise RuntimeError('Недопустимая геометрия')
        builder.Add(compound, component)
    return compound, components


def build_free_arm_miter(draft: Any) -> tuple[Any, tuple[Any, ...]]:
    """Общий стык и необязательные внутренние корпуса, без снимка подвески."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Compound

    from ..model.free_arm_miter import FreeArmMiterDraft
    from .cad_fixed_arm_miter import build_miter_tubes_for_geometry, miter_geometry_for_tubes, validate_miter_face
    from .cad_inner_housings import build_inner_housings_and_notch

    if not isinstance(draft, FreeArmMiterDraft):
        raise ValueError('Ожидался независимый рычаг со стыком на ус')
    geometries = _free_arm_geometries(draft.arm)
    miter = miter_geometry_for_tubes(draft.arm.anchors, geometries)
    _, original = build_free_arm_tubes(draft.arm)
    tubes = list(build_miter_tubes_for_geometry(draft.arm.anchors, geometries, list(original), miter))
    housings: list[Any] = []
    if draft.housings is not None:
        tubes, housings = build_inner_housings_and_notch(tubes, draft.arm.anchors[:2],
                                                          draft.housings.as_housings(),
                                                          draft.housings.as_notches() or {})
        if draft.housings.as_notches():
            for index, tube in enumerate(tubes):
                validate_miter_face(tube, miter, geometries[index], index)
    components = (*tubes, *housings)
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for component in components:
        if component.IsNull() or not BRepCheck_Analyzer(component).IsValid():
            raise RuntimeError('Недопустимая геометрия')
        builder.Add(compound, component)
    return compound, components


def build_free_arm_tube_joint(draft: Any) -> tuple[Any, tuple[Any, ...]]:
    """Подрезать выбранную ветвь по исходной противоположной трубе без снимка."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Compound

    from ..model.free_arm_tube_joint import FreeArmTubeJointDraft
    from .cad_inner_housings import build_inner_housings_and_notch
    from .cad_kim_prototype import FixedArmNotchError
    from .cad_tube_envelope import build_tube_envelope
    from .cad_tube_notch import TubeNotchError, _cut_tube

    if not isinstance(draft, FreeArmTubeJointDraft):
        raise ValueError('Ожидался независимый рычаг с подрезкой трубы')
    geometries = _free_arm_geometries(draft.arm)
    _, originals = build_free_arm_tubes(draft.arm)
    tubes = list(originals)
    housings: list[Any] = []
    if draft.housings is not None:
        tubes, housings = build_inner_housings_and_notch(tubes, draft.arm.anchors[:2],
                                                          draft.housings.as_housings(),
                                                          draft.housings.as_notches() or {})
    target = draft.joint.target
    index = ('front', 'rear').index(target)
    other = 1 - index
    try:
        cutter = build_tube_envelope(geometries[other], draft.arm.anchors[other], draft.arm.outer_mm,
                                     draft.joint.radial_clearance_mm)
        tubes[index] = _cut_tube(tubes[index], cutter, f'tube_{target}',
                                 f'tube_{("front", "rear")[other]}').shape
    except TubeNotchError as error:
        raise FixedArmNotchError(target, error.code, tube_joint=True) from error
    except MemoryError:
        raise
    except Exception as error:
        raise FixedArmNotchError(target, 'failed', tube_joint=True) from error
    components = (*tubes, *housings)
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for component in components:
        if component.IsNull() or not BRepCheck_Analyzer(component).IsValid():
            raise RuntimeError('Недопустимая геометрия')
        builder.Add(compound, component)
    return compound, components

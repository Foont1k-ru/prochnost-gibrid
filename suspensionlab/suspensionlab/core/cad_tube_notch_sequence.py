"""Внутренний CAD-прототип последовательных резов одной трубы, без сохранения."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..model.scheme_arm_assembly import validate_scheme_arm_assembly
from .cad_kim_prototype import _place_scheme_arm_plate, build_part
from .cad_tube_notch import TubeNotchError, _cut_tube, _housing_envelope, _tube_envelope

TUBES = ('tube_front', 'tube_rear')
CUTTERS = ('housing_front', 'housing_rear', 'ball_plate', *TUBES)
MAX_CUTS = 4  # Два корпуса, пластина и другая труба; повторы не принимаются.
MAX_SEQUENCE_BYTES = 24_000_000
MAX_SEQUENCE_SEGMENTS = 120_000


class TubeNotchSequenceError(TubeNotchError):
    """Ошибка конкретного шага; индекс начинается с нуля, частичного результата нет."""

    def __init__(self, code: str, step_index: int, cutter_id: str) -> None:
        super().__init__(code)
        self.step_index = step_index
        self.cutter_id = cutter_id


@dataclass(frozen=True, slots=True)
class NotchStep:
    cutter_id: str
    input_volume_mm3: float
    remaining_volume_mm3: float
    removed_volume_mm3: float


@dataclass(frozen=True, slots=True)
class TubeNotchSequence:
    tube_id: str
    shape: Any
    steps: tuple[NotchStep, ...]
    stage_shapes: tuple[Any, ...] = ()


def notch_tube_sequence(document: dict[str, Any], tube_id: str, cutter_ids: list[str] | tuple[str, ...], *,
                        capture_stages: bool = False) -> TubeNotchSequence:
    """Последовательно вычесть выбранные детали из одной трубы в указанном порядке.

    Корпуса и вторая труба режут конечным наружным цилиндром, пластина — своим
    телом с отверстием. Все режущие детали берутся из неизменённого снимка;
    никаких взаимных автоматических резов, зазора или продления нет. Каждый рез
    должен удалять объём и оставлять одно валидное тело. Нет пересечения после
    предыдущих резов — отказ всей последовательности, а не тихий пропуск.
    Возвращается только полная цепочка; исходный документ и файлы не меняются.
    При запросе промежуточных стадий их формы копируются до следующего реза,
    но не возвращаются при отказе всей цепочки. Использовать только в изоляции.
    """
    snapshot = deepcopy(document)
    order = validate_notch_sequence(snapshot, tube_id, cutter_ids)

    current = build_part(snapshot['parts'][TUBES.index(tube_id)])
    steps: list[NotchStep] = []
    cutters: list[Any] = []
    stages: list[Any] = []
    for index, cutter_id in enumerate(order):
        try:
            if cutter_id in TUBES:
                cutter_shape = _tube_envelope(snapshot, cutter_id)
            elif cutter_id == 'ball_plate':
                cutter_shape = _place_scheme_arm_plate(snapshot)
            else:
                cutter_shape = _housing_envelope(snapshot, cutter_id)
            result = _cut_tube(current, cutter_shape, tube_id, cutter_id)
            if capture_stages:
                from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

                copied = BRepBuilderAPI_Copy(result.shape, True, False)
                if not copied.IsDone() or copied.Shape().IsNull():
                    raise TubeNotchError('invalid_result')
                stages.append(copied.Shape())
        except TubeNotchError as error:
            raise TubeNotchSequenceError(error.code, index, cutter_id) from error
        except Exception as error:
            raise TubeNotchSequenceError('unexpected', index, cutter_id) from error
        steps.append(NotchStep(cutter_id, result.original_volume_mm3,
                               result.remaining_volume_mm3, result.removed_volume_mm3))
        cutters.append(cutter_shape)
        current = result.shape

    # A later boolean must not reintroduce a substantial overlap with an earlier cutter.
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    tolerance = max(1e-6, steps[0].input_volume_mm3 * 1e-9)  # numerical threshold, not an engineering tolerance
    for index, cutter_shape in enumerate(cutters):
        common = BRepAlgoAPI_Common(current, cutter_shape)
        if not common.IsDone() or common.Shape().IsNull():
            raise TubeNotchSequenceError('invalid_result', index, order[index])
        properties = GProp_GProps()
        BRepGProp.VolumeProperties_s(common.Shape(), properties, 1e-8)
        remaining = float(properties.Mass())
        if not 0 <= remaining <= tolerance:
            raise TubeNotchSequenceError('invalid_result', index, order[index])
    return TubeNotchSequence(tube_id, current, tuple(steps), tuple(stages))


def validate_notch_sequence(document: dict[str, Any], tube_id: str, cutter_ids: list[str] | tuple[str, ...]
                            ) -> tuple[str, ...]:
    """Проверить выбор целиком до запуска CAD; порядок важен."""
    validate_scheme_arm_assembly(document)
    if tube_id not in TUBES:
        raise TubeNotchError('unsupported_pair')
    if type(cutter_ids) not in (list, tuple) or not 1 <= len(cutter_ids) <= MAX_CUTS:
        raise TubeNotchError('invalid_sequence')
    order = tuple(cutter_ids)
    seen: set[str] = set()
    # Fail before doing any CAD work for invalid or unavailable selections.
    for index, cutter in enumerate(order):
        if type(cutter) is not str or cutter not in CUTTERS:
            raise TubeNotchSequenceError('unsupported_pair', index, str(cutter))
        if cutter == tube_id:
            raise TubeNotchSequenceError('same_tube', index, cutter)
        if cutter in seen:
            raise TubeNotchSequenceError('duplicate_cutter', index, cutter)
        if cutter == 'ball_plate' and document['version'] != '0.16':
            raise TubeNotchSequenceError('missing_plate', index, cutter)
        seen.add(cutter)

    return order

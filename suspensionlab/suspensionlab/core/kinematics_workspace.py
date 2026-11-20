"""Дискретная кинематика для рабочей области; не заключение о безопасности."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import cos, dist, isfinite, pi, sin

import numpy as np

from ..model.entities import Axle
from ..model.kinematic_elements import ElementSetup
from .double_wishbone import DoubleWishbone, Pose, RigidFiveLinkSolver
from .metrics import wheel_angles
from .pose_view import Point, pose_view
from .rear_five_link import LINKS, RearFiveLink
from .rocker_kinematics import RockerError, RockerGeometry, RockerSample
from .scene3d import Scene3D, Segment3D, pose_scene, wheel_segments
from .springs import lower_arm_point
from .sweep import limited_sweep, travel_grid
from .vehicle_schematic_scene import SelectableLink


@dataclass(frozen=True)
class WorkspaceAngles:
    camber_deg: float
    toe_deg: float


@dataclass(frozen=True)
class ElementMeasurement:
    length_mm: float | None
    lower: Point | None
    upper: Point | None
    status: str
    limits_complete: bool
    detail: str


@dataclass(frozen=True)
class WorkspaceSample:
    travel_mm: float
    scene: Scene3D | None
    metrics: WorkspaceAngles | None
    error: str | None
    spring: ElementMeasurement | None = None
    damper: ElementMeasurement | None = None
    rocker: RockerSample | None = None


@dataclass(frozen=True)
class WorkspaceResult:
    samples: tuple[WorkspaceSample, ...]
    reached_droop_mm: float
    reached_bump_mm: float


def static_scene(axle: Axle) -> tuple[Scene3D, tuple[SelectableLink, ...]]:
    """Левая сторона независимой схемы или явно заданные точки моста; без кинематики."""
    points: list[tuple[str, Point]] = []
    for point_spec in axle.spec.points:
        point = axle.hardpoints.get(point_spec.code)
        if point is not None:
            xyz = point.as_tuple()
            if not all(isfinite(x) and abs(x) <= 1_000_000 for x in xyz):
                raise ValueError('Координаты вне диапазона отображения')
            points.append((point_spec.code, xyz))
    segments: list[Segment3D] = []
    targets: list[SelectableLink] = []
    for spec in axle.spec.links:
        if any(code not in axle.hardpoints for code in (*spec.pivot, spec.end)):
            continue
        for start, end in axle.link_endpoints(spec.code):
            segment = Segment3D(start, end, 'steering' if spec.group == 'steering' else 'arm')
            segments.append(segment)
            targets.append(SelectableLink(axle.role, spec.code, segment))
    for prefix, kind in (('spring', 'spring'), ('damper', 'damper')):
        config = axle.kinematic_elements
        if (prefix == 'damper' and config is not None and config.type_code == axle.type_code and
                config.rocker is not None and config.rocker.enabled):
            continue  # Do not display the direct mount as if it were the rocker mechanism.
        low, high = axle.hardpoints.get(prefix + '_lo'), axle.hardpoints.get(prefix + '_up')
        if low is not None and high is not None:
            segments.append(Segment3D(low.as_tuple(), high.as_tuple(), kind))  # type: ignore[arg-type]
    wheel = axle.hardpoints.get(axle.wheel_center_code() or '')
    radius, width = axle.wheel.r_dynamic_mm, axle.wheel.width_mm
    if wheel is not None and all(isfinite(v) and 0 < v <= 100_000 for v in (radius, width)):
        x, y, z = wheel.as_tuple()
        rings = [[(x + radius * cos(2*pi*i/24), y + side*width/2, z + radius*sin(2*pi*i/24))
                  for i in range(24)] for side in (-1, 1)]
        for ring in rings:
            segments.extend(Segment3D(ring[i], ring[(i+1) % 24], 'wheel') for i in range(24))
        segments.extend(Segment3D(rings[0][i], rings[1][i], 'wheel') for i in range(0, 24, 4))
    return Scene3D(0., tuple(segments), tuple(points)), tuple(targets)


def supported(axle: Axle) -> bool:
    """Две проверяемые экспериментальные модели, остальные только статические."""
    return (axle.role, axle.type_code) in (('front', 'double_wishbone'), ('rear', 'multilink_rear'))


def rear_scene(model: RearFiveLink, pose: Pose, axle: Axle) -> Scene3D:
    """Пять тяг и условный жёсткий кулак, не геометрия деталей."""
    def point(code: str, *, moving: bool) -> Point:
        xyz = pose.point(model.points[code], model.center0) if moving else model.points[code]
        return float(xyz[0]), float(xyz[1]), float(xyz[2])

    points = [('wheel_center', (float(pose.center[0]), float(pose.center[1]), float(pose.center[2])))]
    segments = []
    for code, inner, outer in LINKS:
        a, b = point(inner, moving=False), point(outer, moving=True)
        points.extend(((inner, a), (outer, b)))
        segments.append(Segment3D(a, b, 'steering' if code == 'toe_link' else 'arm'))
    # Контур только схематически показывает, что наружные шарниры принадлежат кулаку.
    outline = [point(code, moving=True) for code in ('uf_out', 'ur_out', 'lr_out', 'lf_out')]
    segments.extend(Segment3D(outline[i], outline[(i + 1) % 4], 'knuckle') for i in range(4))
    segments.extend(wheel_segments(model, pose, axle, points[0][1]))
    return Scene3D(pose.travel_mm, tuple(segments), tuple(points))


def measure_element(axle: Axle, model: RigidFiveLinkSolver, pose: Pose, name: str) -> ElementMeasurement:
    """Проверяет только расстояние центров креплений в этом решённом положении."""
    unknown = ElementMeasurement(None, None, None, 'unknown', False, 'крепления не заданы')
    if name not in ('spring', 'damper'):
        raise ValueError('Неизвестный элемент')
    config = axle.kinematic_elements
    if config is None:
        return unknown
    if config.type_code != axle.type_code:
        return ElementMeasurement(None, None, None, 'unknown', False, 'настройки относятся к другой схеме')
    if name == 'damper' and config.rocker is not None and config.rocker.enabled:
        return ElementMeasurement(None, None, None, 'unknown', False, 'для коромысла нужен расчёт ветви хода')
    setup: ElementSetup = getattr(config, name)
    if setup.lower is None or setup.upper is None:
        return unknown

    def moved(code: str, mount: str) -> Point:
        source = axle.hardpoints[code]
        p = np.array((source.x, source.y * model.sign, source.z), dtype=float)
        if not np.all(np.isfinite(p)):
            raise ValueError('неконечные координаты крепления')
        if mount == 'body':
            current = p
        elif mount == 'upright':
            current = pose.point(p, model.center0)
        elif mount == 'lower_arm' and isinstance(model, DoubleWishbone):
            current = lower_arm_point(model, pose, p)
        else:
            raise ValueError('крепление неприменимо к этой схеме')
        if not np.all(np.isfinite(current)):
            raise ValueError('неконечные координаты крепления')
        return float(current[0]), float(current[1]), float(current[2])

    try:
        low, high = moved(name + '_lo', setup.lower), moved(name + '_up', setup.upper)
        length = dist(low, high)
        if not isfinite(length) or length < 1e-9:
            raise ValueError('центры креплений совпадают или некорректны')
    except (KeyError, ValueError, ArithmeticError) as error:
        return ElementMeasurement(None, None, None, 'error', False, str(error))
    return _classify_element(setup, low, high, length)


def _classify_element(setup: ElementSetup, low: Point, high: Point, length: float) -> ElementMeasurement:
    minimum, maximum = setup.minimum_mm, setup.maximum_mm
    if minimum is not None and maximum is not None and minimum >= maximum:
        return ElementMeasurement(length, low, high, 'invalid', False, 'не проверено: минимум должен быть меньше максимума')
    complete = minimum is not None and maximum is not None
    # Near-limit classification reflects numerical tolerance, not a clearance guarantee.
    tolerance = 1e-6
    if minimum is not None and length < minimum - tolerance:
        status, detail = 'below', 'меньше заданного минимума'
    elif maximum is not None and length > maximum + tolerance:
        status, detail = 'above', 'больше заданного максимума'
    elif ((minimum is not None and abs(length - minimum) <= tolerance) or
          (maximum is not None and abs(length - maximum) <= tolerance)):
        status, detail = 'limit', 'у заданной границы (численный допуск 0,000001 мм)'
    elif complete:
        status, detail = 'inside', 'между заданными пределами'
    else:
        status, detail = 'partial', 'полностью не проверено: пределы заданы не полностью'
    return ElementMeasurement(length, low, high, status, complete, detail)


def _rocker_error_text(error: str | None) -> str:
    messages = {
        'zero rocker axis': 'нулевое направление оси',
        'rocker attachment on axis': 'крепление находится на оси коромысла',
        'zero rod length': 'нулевая длина тяги',
        'zero damper length': 'совпадают центры амортизатора',
        'undetermined or unreachable rocker angle': 'угол коромысла не определён или недостижим',
        'unreachable or ambiguous rocker angle': 'положение недостижимо или неоднозначно',
        'ambiguous rocker branch': 'неоднозначная ветвь коромысла',
        'no suspension pose at zero': 'нет решения подвески в исходном положении',
        'zero pose differs from rocker reference': 'исходное положение не совпадает с геометрией',
        'zero pose does not match reference branch': 'не найдена исходная ветвь',
        'not evaluated: zero rocker pose failed': 'не рассчитано из-за отказа в исходном положении',
        'no suspension pose': 'нет положения подвески или крепления тяги',
        'not evaluated after branch failure': 'не рассчитано после отказа на этой ветви',
        'rocker angle step too large to track branch': 'слишком большой шаг угла для отслеживания ветви',
        'invalid damper length': 'длина амортизатора некорректна',
        'invalid point': 'некорректные координаты',
    }
    return messages.get(error or '', 'ошибка или неполные данные коромысла')


def calculate(axle: Axle, start: float, end: float, spacing: float, *,
              targets: Sequence[float] | None = None) -> WorkspaceResult:
    """Левая сторона; при явных целях обе ветви заново продолжаются от нуля."""
    if not supported(axle):
        raise ValueError('Расчёт хода для этого типа пока не реализован')
    if not (-150 <= start <= 0 <= end <= 150) or not (5 <= spacing <= 30):
        raise ValueError('Диапазон должен включать ноль и быть в пределах −150…+150 мм; шаг 5…30 мм')
    if targets is None:
        travels = travel_grid(start, end, max_spacing_mm=spacing)
    else:
        if (len(targets) == 0 or len(targets) > 5000 or
                any(type(t) not in (int, float) or not isfinite(t) or not start <= t <= end for t in targets) or
                any(a >= b for a, b in zip(targets, targets[1:], strict=False)) or
                targets[0] != start or targets[-1] != end or 0 not in targets):
            raise ValueError('Точки хода должны возрастать, включать границы и ноль и быть конечными')
        travels = [float(t) for t in targets]
    config = axle.kinematic_elements
    rocker_setup = config.rocker if config is not None and config.type_code == axle.type_code else None
    rocker_active = rocker_setup is not None and rocker_setup.enabled
    rocker_by_travel: dict[float, RockerSample] = {}
    rocker_error: str | None = None
    if rocker_active and rocker_setup is not None:
        from .rocker_workspace import calculate_rocker

        try:
            geometry = RockerGeometry(rocker_setup.pivot, rocker_setup.axis, rocker_setup.rod_rocker,
                                      rocker_setup.rod_suspension, rocker_setup.damper_rocker, rocker_setup.damper_body)
            rocker_by_travel = {s.travel_mm: s for s in
                                calculate_rocker(axle, geometry, rocker_setup.mount, start, end, targets=travels)}
        except (RockerError, ValueError, ArithmeticError) as error:
            rocker_error = str(error)
    model = DoubleWishbone(axle, 'left') if axle.role == 'front' else RearFiveLink(axle, 'left')
    sweep = limited_sweep(model, travels, max_step_mm=2)
    samples = []
    for item in sweep.points:
        if item.pose is None:
            samples.append(WorkspaceSample(item.travel_mm, None, None, str(item.error)))
            continue
        pose = item.pose
        if isinstance(model, DoubleWishbone):
            frame = pose_view(model, pose, axle, spring=False, damper=False)
            scene = pose_scene(model, pose, axle, frame)
        else:
            scene = rear_scene(model, pose, axle)
        try:
            camber, toe = wheel_angles(model, pose, static_camber_deg=axle.setup.camber_deg,
                                       static_toe_deg=axle.setup.toe_deg_total / 2)
            metrics = WorkspaceAngles(camber, toe)
        except ValueError:
            metrics = None
        spring = measure_element(axle, model, pose, 'spring')
        rocker = rocker_by_travel.get(item.travel_mm) if rocker_active else None
        if rocker_active:
            if rocker_error or rocker is None or rocker.pose is None:
                detail = _rocker_error_text(rocker_error or (rocker.error if rocker is not None else None))
                damper = ElementMeasurement(None, None, None, 'error', False, f'коромысло: {detail}')
            else:
                assert config is not None and rocker_setup is not None
                damper = _classify_element(config.damper, rocker.pose.damper_rocker,
                                           rocker_setup.damper_body, rocker.pose.damper_length_mm)
        else:
            damper = measure_element(axle, model, pose, 'damper')
        extra: list[Segment3D] = []
        points = list(scene.points)
        if rocker_active and rocker is not None and rocker.pose is not None and rocker_setup is not None:
            original = np.array(rocker_setup.rod_suspension, dtype=float)
            if rocker_setup.mount == 'lower_arm' and isinstance(model, DoubleWishbone):
                rod_point = lower_arm_point(model, pose, original)
            else:
                rod_point = pose.point(original, model.center0)
            moving_rod = (float(rod_point[0]), float(rod_point[1]), float(rod_point[2]))
            extra.extend((Segment3D(moving_rod, rocker.pose.rod_rocker, 'rod'),
                          Segment3D(rocker_setup.pivot, rocker.pose.rod_rocker, 'rocker'),
                          Segment3D(rocker_setup.pivot, rocker.pose.damper_rocker, 'rocker')))
        for name, measurement in (('spring', spring), ('damper', damper)):
            if measurement.lower is not None and measurement.upper is not None:
                if name == 'spring':
                    extra.append(Segment3D(measurement.lower, measurement.upper, 'spring'))
                else:
                    extra.append(Segment3D(measurement.lower, measurement.upper, 'damper'))
                if name != 'damper' or not rocker_active:
                    points.extend(((name + '_lo', measurement.lower), (name + '_up', measurement.upper)))
        scene = Scene3D(scene.travel_mm, (*scene.segments, *extra), tuple(points))
        samples.append(WorkspaceSample(item.travel_mm, scene, metrics, None, spring, damper, rocker))
    return WorkspaceResult(tuple(samples), sweep.reachable_droop_mm, sweep.reachable_bump_mm)


def moved_link_end(axle: Axle, code: str, length: float) -> tuple[str, Point]:
    """Задаёт расстояние до оси, передвигая только наружную точку перпендикулярно оси."""
    import numpy as np

    spec = axle.spec.link(code)
    if spec is None or not spec.movable_end or not isfinite(length) or not 0 < length <= 1_000_000:
        raise ValueError('Недопустимая длина или неподвижный конец')
    if len(spec.pivot) not in (1, 2) or any(k not in axle.hardpoints for k in (*spec.pivot, spec.end)):
        raise ValueError('Не хватает точек')
    a = np.array(axle.hardpoints[spec.pivot[0]].as_tuple())
    end = np.array(axle.hardpoints[spec.end].as_tuple())
    if len(spec.pivot) == 2:
        axis = np.array(axle.hardpoints[spec.pivot[1]].as_tuple()) - a
        norm = float(np.linalg.norm(axis))
        if norm < 1e-9:
            raise ValueError('Точки оси совпадают')
        unit = axis / norm
        base = a + np.dot(end - a, unit) * unit
    else:
        base = a
    radial = end - base
    distance = float(np.linalg.norm(radial))
    if not isfinite(distance) or distance < 1e-9:
        raise ValueError('Направление длины не определено')
    result = base + radial * (length / distance)
    if not all(isfinite(v) and abs(v) <= 1_000_000 for v in result):
        raise ValueError('Координаты вне допустимого диапазона')
    return spec.end, (float(result[0]), float(result[1]), float(result[2]))

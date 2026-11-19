"""Эксперимент: расчётный снимок и осевые линии нижнего рычага.

Только модель для будущего интерфейса. Не сохраняет файл и не изменяет проект;
не проверяет зазоры, прочность и непрерывный диапазон хода.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.double_wishbone import DoubleWishbone, KinematicsError
from ..core.sweep import limited_sweep, travel_grid
from .entities import Project
from .kim_format import KimFormatError
from .project_io import project_to_json
from .welded_arm import make_welded_arm, weldment_centerlines

# Capture raw solver coordinates as well as the serialized project: project files
# round numbers to 0.0001 mm, which alone could hide a small in-memory change.
_SOLVER_POINTS = ("uca_f_in", "uca_r_in", "ubj", "lca_f_in", "lca_r_in", "lbj",
                  "tierod_in", "tierod_out", "wheel_center")


class SkeletonError(ValueError):
    """Снимок не создан или построение скелета не может быть принято."""


_GEOMETRY_ERRORS = {
    'invalid tube wall or inner radius': 'толщина стенки должна оставлять положительный внутренний радиус',
    'coincident arm points': 'совпадают опоры рычага',
    'coincident bend vertex or end': 'вершина изгиба совпадает с опорой',
    'bend plane or angle is degenerate': 'плоскость изгиба вырождена: точки лежат на одной прямой',
    'bend does not fit between endpoints': 'выбранный радиус не помещается между опорами и вершиной',
    'bend radius must exceed outer tube radius': 'радиус изгиба должен быть больше радиуса трубы',
    'invalid coordinate': 'координаты изгиба должны быть числами',
    'coordinate outside bounds': 'координата изгиба вне допустимого диапазона',
    'invalid radius': 'радиус изгиба должен быть положительным числом',
    'radius outside bounds': 'радиус изгиба вне допустимого диапазона',
}


def _geometry_error(error: Exception) -> str:
    # KIM validation wraps the more precise geometric reason in __cause__.
    cause: BaseException | None = error
    while cause is not None:
        message = _GEOMETRY_ERRORS.get(str(cause))
        if message:
            return message
        cause = cause.__cause__
    return 'проверьте размеры трубы, координаты и радиус изгиба'


def _project_json(project: Project) -> str:
    try:
        return project_to_json(project)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise SkeletonError("Не удалось зафиксировать проект") from error


def _raw_points(project: Project) -> tuple[tuple[float, float, float], ...]:
    try:
        return tuple((float(project.front.hardpoints[code].x), float(project.front.hardpoints[code].y),
                      float(project.front.hardpoints[code].z)) for code in _SOLVER_POINTS)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise SkeletonError("Точки двухрычажной схемы недоступны") from error


@dataclass(frozen=True, slots=True)
class FixedArmSnapshot:
    """Неизменяемый снимок и сведения об отдельных решённых отсчётах.

    Проект сериализуется с точностью его формата (4 знака после запятой).
    Расчёт и скелет строятся по этой одной и той же восстановленной копии.
    Полное сравнение сериализованного проекта намеренно консервативно.
    """

    project_json: str
    raw_solver_points: tuple[tuple[float, float, float], ...]
    travels_mm: tuple[float, ...]
    max_residual_mm: float
    max_step_mm: float
    spacing_mm: float

    def matches(self, project: Project) -> bool:
        try:
            return _project_json(project) == self.project_json and _raw_points(project) == self.raw_solver_points
        except SkeletonError:
            return False

    def project_copy(self) -> Project:
        return Project.from_dict(json.loads(self.project_json))


def capture_fixed_arm(project: Project, from_mm: float, to_mm: float, *,
                      spacing_mm: float = 10.0, max_step_mm: float = 2.0) -> FixedArmSnapshot:
    """Проверяет дискретные точки левой передней двухрычажной схемы.

    Ошибка на любом отсчёте не создаёт снимок. Не является проверкой всего
    интервала или готовности автомобиля. Ограничение диапазона — защита UI.
    """
    if not (-250 <= from_mm <= 0 <= to_mm <= 250 and 1 <= spacing_mm <= 50 and 0.1 <= max_step_mm <= 2):
        raise SkeletonError("Требуется диапазон от −250 до +250 мм с нулём, шаг 1–50 мм и шаг решателя 0,1–2 мм")
    project_json = _project_json(project)
    raw = _raw_points(project)
    try:
        frozen = Project.from_dict(json.loads(project_json))
        if frozen.front.type_code != "double_wishbone":
            raise SkeletonError("Расчёт доступен только для передней двухрычажной подвески")
        travels = travel_grid(from_mm, to_mm, max_spacing_mm=spacing_mm)
        result = limited_sweep(DoubleWishbone(frozen.front, "left"), travels, max_step_mm=max_step_mm)
        for point in result.points:
            if point.error is not None or point.pose is None:
                raise SkeletonError(f"Нет решения при ходе {point.travel_mm:+.3f} мм: {point.error}")
        residual = max(point.pose.residual_mm for point in result.points if point.pose is not None)
    except SkeletonError:
        raise
    except (KinematicsError, ValueError, TypeError, OverflowError, KeyError) as error:
        raise SkeletonError(f"Не удалось рассчитать снимок: {error}") from error
    # Avoid a mixed snapshot if a caller changed the source during computation.
    snapshot = FixedArmSnapshot(project_json, raw, tuple(travels), residual, max_step_mm, spacing_mm)
    if not snapshot.matches(project):
        raise SkeletonError("Проект изменился во время расчёта; повторите")
    return snapshot


@dataclass(frozen=True, slots=True)
class SkeletonPreview:
    """Только временный результат; документ нельзя считать проверенным CAD."""

    centerlines: tuple[tuple[tuple[float, float, float], ...], ...]
    anchors: tuple[tuple[float, float, float], ...]


def fixed_arm_tube_document(snapshot: FixedArmSnapshot, current: Project, radius_mm: float, wall_mm: float,
                            bends: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Независимая копия для CAD-предпросмотра, только две неподрезанные трубы.

    Параметры и опоры извлечены из снимка; изменение открытого проекта не
    приводит к неявной привязке. Документ не является экспортом или расчётом CAD.
    """
    if not snapshot.matches(current):
        raise SkeletonError("Проект изменился: повторно рассчитайте и зафиксируйте снимок")
    try:
        document = make_welded_arm(snapshot.project_copy(), radius_mm, wall_mm, "unknown", bends=bends)
    except (KimFormatError, ValueError, TypeError, OverflowError, KeyError) as error:
        raise SkeletonError(f"Не удалось построить скелет: {_geometry_error(error)}") from error
    if not snapshot.matches(current):
        raise SkeletonError("Проект изменился во время построения")
    return document


def preview_fixed_arm(snapshot: FixedArmSnapshot, current: Project, radius_mm: float, wall_mm: float,
                      bends: dict[str, dict[str, Any]] | None = None) -> SkeletonPreview:
    """Новая копия геометрии по снимку; при устаревании не перестраивает опоры."""
    document = fixed_arm_tube_document(snapshot, current, radius_mm, wall_mm, bends)
    try:
        points = document["parts"][0]["geometry"]["source"]["coordinates_mm"]
        paths = weldment_centerlines(document)
        anchors = tuple(tuple(float(value) for value in point) for point in points)
    except (KimFormatError, ValueError, TypeError, OverflowError, KeyError) as error:
        raise SkeletonError(f"Не удалось построить скелет: {_geometry_error(error)}") from error
    if not snapshot.matches(current):
        raise SkeletonError("Проект изменился во время построения")
    return SkeletonPreview(paths, anchors)  # type: ignore[arg-type]

"""Учебная таблица: пружина, амортизатор и стойки при шаге 1 мм.

Запуск из каталога suspensionlab: python -m examples.dense_sweep_demo
Все входы учебные и не описывают реальный автомобиль.
"""
from __future__ import annotations

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.core.sweep import travel_grid
from suspensionlab.model.templates import load_template


def main() -> None:
    project = load_template("ring")
    # Параметры условные: их следует заменить измеренными значениями.
    grid = travel_grid(-30, 35, max_spacing_mm=1)
    left = analyze_corner(project.front, project.vehicle, grid, spring_mount="lower_arm",
                          static_spring_length_mm=230, coil_bind_length_mm=150,
                          damper_mount="lower_arm", damper_limits=StrokeLimits(350, 450))
    bar = AntiRollStudy(project.front, AntiRollScenario(axis_x_mm=-250, axis_z_mm=320,
                                                        torsion_rate_nm_rad=1000))
    result = bar.sweep_travel(-30, 35, mode="opposed", step_mm=1)
    print("УЧЕБНЫЙ ПРИМЕР — геометрия, жёсткость, упоры и нагрузка не являются данными автомобиля")
    print("Ход Л/П, мм | Сжатие пружины Л, мм | Длина амортизатора Л, мм | Угол плеча Л/П, град | Момент, Н·м | Сжатие стоек Л/П, Н")
    for sample, point in zip(left.samples, result.points, strict=True):
        if sample is None or sample.spring is None or sample.spring.state is None or sample.damper is None or point.state is None:
            print(f"{point.left_travel_mm:+.1f}/{point.right_travel_mm:+.1f} | нет результата: {point.error or 'геометрия/пружина'}")
            continue
        state = point.state
        print(f"{state.left_travel_mm:+.1f}/{state.right_travel_mm:+.1f} | "
              f"{sample.spring.state.compression_mm:.2f} | {sample.damper.length_mm:.2f} | "
              f"{state.left.arm_angle_deg:+.2f}/{state.right.arm_angle_deg:+.2f} | "
              f"{state.torque_nm:+.2f} | {state.left.compression_force_n:+.1f}/{state.right.compression_force_n:+.1f}")
    print("Отрицательное усилие стойки — растяжение. Упоры и препятствия между точками не гарантированно обнаружены.")


if __name__ == "__main__":
    main()

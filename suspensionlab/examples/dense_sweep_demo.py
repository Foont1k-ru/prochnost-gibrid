"""Учебная таблица: пружина, амортизатор и стойки при шаге 1 мм.

Запуск из каталога suspensionlab: python -m examples.dense_sweep_demo
Все входы учебные и не описывают реальный автомобиль.
"""
from __future__ import annotations

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
from suspensionlab.core.damper import LinearDamperCharacteristic, evaluate_linear_damping
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
    right = analyze_corner(project.front, project.vehicle, [-h for h in grid], side="right",
                           spring_mount="lower_arm", static_spring_length_mm=230,
                           coil_bind_length_mm=150, damper_mount="lower_arm",
                           damper_limits=StrokeLimits(350, 450))
    # Мгновенные скорости заданы, а не получены из временной симуляции.
    speed_mm_s = 20.0
    damping = LinearDamperCharacteristic(compression_n_s_per_mm=2.0, rebound_n_s_per_mm=4.0)
    bar = AntiRollStudy(project.front, AntiRollScenario(axis_x_mm=-250, axis_z_mm=320,
                                                        torsion_rate_nm_rad=1000))
    result = bar.sweep_travel(-30, 35, mode="opposed", step_mm=1)
    print("УЧЕБНЫЙ ПРИМЕР — геометрия, жёсткость, упоры и нагрузка не являются данными автомобиля")
    print("Скорость колёс Л/П: +20/−20 мм/с, условная линейная характеристика амортизаторов: 2/4 Н·с/мм")
    print("Ход Л/П, мм | Сжатие пружин Л/П, мм | Длина амортизаторов Л/П, мм | "
          "Сила амортизаторов на колёса Л/П, Н | Угол плеча Л/П, град | "
          "Момент, Н·м | Сжатие стоек Л/П, Н")
    for ls, rs, point in zip(left.samples, right.samples, result.points, strict=True):
        if (ls is None or rs is None or ls.spring is None or rs.spring is None
                or ls.spring.state is None or rs.spring.state is None
                or ls.damper is None or rs.damper is None or point.state is None):
            print(f"{point.left_travel_mm:+.1f}/{point.right_travel_mm:+.1f} | нет результата: {point.error or 'геометрия/пружина'}")
            continue
        state = point.state
        try:
            lf = evaluate_linear_damping(ls.damper, damping, speed_mm_s).wheel_force_n
            rf = evaluate_linear_damping(rs.damper, damping, -speed_mm_s).wheel_force_n
            forces = f"{lf:+.1f}/{rf:+.1f}"
        except ValueError:
            forces = "не определена (упор или ошибка)"
        print(f"{state.left_travel_mm:+.1f}/{state.right_travel_mm:+.1f} | "
              f"{ls.spring.state.compression_mm:.2f}/{rs.spring.state.compression_mm:.2f} | "
              f"{ls.damper.length_mm:.2f}/{rs.damper.length_mm:.2f} | {forces} | "
              f"{state.left.arm_angle_deg:+.2f}/{state.right.arm_angle_deg:+.2f} | "
              f"{state.torque_nm:+.2f} | {state.left.compression_force_n:+.1f}/{state.right.compression_force_n:+.1f}")
    print("Отрицательное усилие стойки — растяжение. Амортизатор: сила на колесо, положительная вверх.")
    print("Скорости заданы отдельно для каждой строки: это не симуляция движения во времени.")
    print("Упоры и препятствия между точками не гарантированно обнаружены; силовое равновесие не проверено.")



if __name__ == "__main__":
    main()

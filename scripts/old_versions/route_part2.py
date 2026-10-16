#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from robot_core import (
    XLeRobotBase,
    TelemetryReceiver,
    run_drive_step,
    valid,
    execute_route,
    SPEED_FORWARD,
    SPEED_BACKWARD,
)


def mission_part2(base: XLeRobotBase, tele: TelemetryReceiver):
    print("\n" + "=" * 60)
    print("        СТАРТ ЧАСТИ 2: ШАГИ 4 - 6")
    print("=" * 60)

    # Шаг 4
    run_drive_step(
        base,
        tele,
        4,
        "Назад -> стоп при (F >= 264 см ИЛИ B <= 108 см)",
        SPEED_BACKWARD,
        lambda f, b: (valid(f) and f >= 264.0) or (valid(b) and b <= 108.0),
    )

    # Шаг 5
    print("\n[ШАГ 5] Поворот вправо на 90°")
    base.turn_right_90()

    # Шаг 6
    run_drive_step(
        base,
        tele,
        6,
        "Вперёд -> стоп при (F <= 152 см ИЛИ B > 152 см)",
        SPEED_FORWARD,
        lambda f, b: (valid(f) and f <= 152.0) or (valid(b) and b > 152.0),
    )

    print("\n[OK] Часть 2 успешно завершена.")


if __name__ == "__main__":
    execute_route(mission_part2)
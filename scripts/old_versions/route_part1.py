#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from robot_core import (
    XLeRobotBase,
    TelemetryReceiver,
    run_drive_step,
    valid,
    execute_route,
    SPEED_FORWARD,
)


def mission_part1(base: XLeRobotBase, tele: TelemetryReceiver):
    print("\n" + "=" * 60)
    print("        СТАРТ ЧАСТИ 1: ШАГИ 1 - 3")
    print("=" * 60)

    # Шаг 1
    run_drive_step(
        base,
        tele,
        1,
        "Вперёд -> стоп при (F <= 180 см ИЛИ B >= 180 см)",
        SPEED_FORWARD,
        lambda f, b: (valid(f) and f <= 180.0) or (valid(b) and b >= 180.0),
    )

    # Шаг 2
    print("\n[ШАГ 2] Поворот влево на 90°")
    base.turn_left_90()

    # Шаг 3
    run_drive_step(
        base,
        tele,
        3,
        "Вперёд -> стоп при (F <= 80 см)",
        SPEED_FORWARD,
        lambda f, b: valid(f) and f <= 80.0,
    )

    print("\n[OK] Часть 1 успешно завершена.")


if __name__ == "__main__":
    execute_route(mission_part1)
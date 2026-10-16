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


def mission_part3(base: XLeRobotBase, tele: TelemetryReceiver):
    print("\n" + "=" * 60)
    print("        СТАРТ ЧАСТИ 3: ШАГИ 7 - 11")
    print("=" * 60)

    # Шаг 7
    run_drive_step(
        base,
        tele,
        7,
        "Назад -> стоп при (B <= 144 см)",
        SPEED_BACKWARD,
        lambda f, b: valid(b) and b <= 144.0,
    )

    # Шаг 8
    print("\n[ШАГ 8] Поворот влево на 90°")
    base.turn_left_90()

    # Шаг 9
    run_drive_step(
        base,
        tele,
        9,
        "Вперёд -> стоп при (F <= 168 см ИЛИ B > 207 см)",
        SPEED_FORWARD,
        lambda f, b: (valid(f) and f <= 168.0) or (valid(b) and b > 207.0),
    )

    # Шаг 10
    print("\n[ШАГ 10] Поворот вправо на 90°")
    base.turn_right_90()

    # Шаг 11
    run_drive_step(
        base,
        tele,
        11,
        "Назад -> стоп при (B <= 40 см)",
        SPEED_BACKWARD,
        lambda f, b: valid(b) and b <= 40.0,
    )

    print("\n[OK] Часть 3 успешно завершена.")


# EXITCODE_PATCH
if __name__ == "__main__":
    import sys
    sys.exit(0 if execute_route(mission_part3) else 1)

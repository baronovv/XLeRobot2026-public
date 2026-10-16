#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
route_dual_11steps.py
=====================================================================
Автономный маршрут из 11 шагов для XLeRobot (база LeKiwi, 3 омниколеса)
с использованием ДВУХ ультразвуковых датчиков (F = вперёд, B = назад),
которые ESP32 отдаёт по serial в формате "F:120.5,B:45.2".

Управление базой сделано по логике xlerobot_teleop_keyboard.py:
    base_action = {"x.vel": ..., "y.vel": ..., "theta.vel": ...}
    robot.send_action({**hold_pose, **base_action})

Это ровно тот словарь, который возвращает
robot._from_keyboard_to_base_action(), только собирается напрямую,
без эмуляции нажатий клавиш.

ВАЖНО про единицы (конвенция LeKiwi/XLerobot):
    x.vel, y.vel   -> м/с   (x > 0 вперёд, x < 0 назад)
    theta.vel      -> град/с (theta > 0 поворот ВЛЕВО / CCW)

Запуск:
    PYTHONPATH=src python route_dual_11steps.py
(при необходимости сначала поднять хост:
    PYTHONPATH=src python -m lerobot.robots.xlerobot.xlerobot_host --robot.id=my_xlerobot)
=====================================================================
"""

import re
import sys
import time
import threading

import serial

from lerobot.robots.xlerobot import XLerobotConfig, XLerobot

# =====================================================================
# НАСТРОЙКИ
# =====================================================================

# --- Датчики (ESP32) ---
SENSOR_PORT = "/dev/ttyUSB0"   # лучше заменить на /dev/serial/by-path/... для стабильности
BAUD_RATE = 115200

# --- Скорости базы ---
SPEED_FORWARD = 0.15    # м/с, движение вперёд
SPEED_BACKWARD = -0.15  # м/с, движение назад
TURN_SPEED_DEG = 30.0   # град/с, угловая скорость поворота (theta.vel)

# --- Калибровка поворота на 90° ---
# Теоретически 90 / TURN_SPEED_DEG = 2.25 c, но из-за проскальзывания
# колёс реальное время подбирается экспериментально (turn_calibration.py).
TURN_90_TIME = 3.5     # секунд на поворот 90° при TURN_SPEED_DEG
TURN_SETTLE = 1.0       # пауза после поворота на механическую стабилизацию

# --- Управляющий цикл ---
CONTROL_HZ = 30.0       # частота отправки команд на базу
CONTROL_DT = 1.0 / CONTROL_HZ

# --- Фильтрация данных датчиков ---
MIN_VALID_DIST_CM = 10.0   # всё, что <= 10 см, считается шумом/таймаутом
MAX_VALID_DIST_CM = 500.0  # верхняя граница правдоподобия для HC-SR04
CONFIRM_READINGS = 2       # сколько подряд замеров должны подтвердить условие
SENSOR_STALE_SEC = 1.0     # если данных нет дольше — аварийная остановка

# --- Защита ---
STEP_TIMEOUT_SEC = 60.0    # максимум времени на один шаг движения
STOP_SETTLE = 0.3          # пауза после остановки перед следующим шагом


# =====================================================================
# ПОТОК ЧТЕНИЯ ТЕЛЕМЕТРИИ (F / B)
# =====================================================================
class TelemetryReceiver:
    """Фоновое чтение "F:<число>,B:<число>" с ESP32."""

    # L (левый датчик) опционален — регекс его не требует
    PATTERN = re.compile(r"F:\s*([-+]?\d*\.?\d+).*?B:\s*([-+]?\d*\.?\d+)")

    def __init__(self, port=SENSOR_PORT, baudrate=BAUD_RATE):
        self.port = port
        self.baudrate = baudrate
        self.front = -1.0
        self.rear = -1.0
        self.last_update = 0.0
        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def _reader_loop(self):
        try:
            with serial.Serial(self.port, self.baudrate, timeout=0.5, exclusive=True) as ser:
                # Не дёргаем DTR/RTS, иначе ESP32 уйдёт в перезагрузку
                ser.dtr = False
                ser.rts = False
                time.sleep(0.5)
                ser.reset_input_buffer()
                self.connected = True
                print(f"[Telemetry] Подключено к {self.port}")

                while self.running:
                    if ser.in_waiting > 0:
                        raw = ser.readline().decode("utf-8", errors="ignore").strip()
                        if not raw or "=" in raw:
                            continue

                        m = self.PATTERN.search(raw)
                        if not m:
                            continue
                        try:
                            f_val = float(m.group(1))
                            b_val = float(m.group(2))
                        except ValueError:
                            continue

                        with self.lock:
                            self.front = f_val
                            self.rear = b_val
                            self.last_update = time.time()
                    else:
                        time.sleep(0.005)
        except serial.SerialException as e:
            self.connected = False
            print(f"[Telemetry] Ошибка порта: {e}")

    def get(self):
        """Возвращает (front_cm, rear_cm, age_sec)."""
        with self.lock:
            return self.front, self.rear, time.time() - self.last_update

    def wait_for_data(self, timeout=5.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            f, b, age = self.get()
            if age < SENSOR_STALE_SEC and (valid(f) or valid(b)):
                return True
            time.sleep(0.05)
        return False

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)


def valid(d):
    """Правдоподобен ли замер дальномера."""
    return MIN_VALID_DIST_CM < d < MAX_VALID_DIST_CM


# =====================================================================
# УПРАВЛЕНИЕ БАЗОЙ XLEROBOT
# =====================================================================
class XLeRobotBase:
    """
    Обёртка над XLerobot: движение базы + удержание позы рук/головы.

    Логика та же, что в xlerobot_teleop_keyboard.py: каждый такт
    отправляется полный словарь действий, где база задана скоростями
    x.vel / y.vel / theta.vel, а суставы удерживаются в стартовой позе.
    """

    def __init__(self, robot: XLerobot):
        self.robot = robot
        self.hold_pose = {}
        self._capture_hold_pose()

    def _capture_hold_pose(self):
        """
        Фиксируем текущие позиции всех суставов, чтобы руки не «падали»
        и не упирались во время движения базы (защита от overload STS3215).
        """
        try:
            obs = self.robot.get_observation()
        except Exception as e:
            print(f"[Base] Не удалось прочитать observation: {e}")
            return

        for k, v in obs.items():
            if k.endswith(".pos"):
                try:
                    self.hold_pose[k] = float(v.item() if hasattr(v, "item") else v)
                except (TypeError, ValueError):
                    pass
        print(f"[Base] Зафиксирована поза удержания: {len(self.hold_pose)} суставов")

    def _send(self, x_vel=0.0, y_vel=0.0, theta_vel=0.0):
        action = dict(self.hold_pose)
        action["x.vel"] = float(x_vel)
        action["y.vel"] = float(y_vel)
        action["theta.vel"] = float(theta_vel)
        self.robot.send_action(action)

    def drive_tick(self, x_vel=0.0, y_vel=0.0, theta_vel=0.0):
        """Один такт движения (команду нужно слать непрерывно)."""
        self._send(x_vel, y_vel, theta_vel)

    def stop(self, settle=STOP_SETTLE):
        """Остановка базы: несколько нулевых команд подряд + пауза."""
        for _ in range(5):
            self._send(0.0, 0.0, 0.0)
            time.sleep(CONTROL_DT)
        if settle > 0:
            time.sleep(settle)

    def turn(self, direction: str, duration: float = TURN_90_TIME):
        """
        Поворот на месте по времени.
        direction: 'left' (CCW, theta > 0) или 'right' (CW, theta < 0).
        """
        theta = TURN_SPEED_DEG if direction == "left" else -TURN_SPEED_DEG
        label = "ВЛЕВО" if direction == "left" else "ВПРАВО"
        print(f"    >>> Поворот {label} на 90° "
              f"(theta.vel={theta:+.1f} град/с, {duration:.2f} с)")

        t0 = time.time()
        while time.time() - t0 < duration:
            self._send(0.0, 0.0, theta)
            time.sleep(CONTROL_DT)

        self.stop(settle=TURN_SETTLE)

    def turn_left_90(self):
        self.turn("left")

    def turn_right_90(self):
        self.turn("right")


# =====================================================================
# ИСПОЛНИТЕЛЬ ШАГА ДВИЖЕНИЯ
# =====================================================================
def run_drive_step(base: XLeRobotBase,
                   tele: TelemetryReceiver,
                   step_no: int,
                   description: str,
                   x_vel: float,
                   condition,
                   timeout=STEP_TIMEOUT_SEC):
    """
    Едет с заданной скоростью, пока condition(f, b) не станет True
    CONFIRM_READINGS раз подряд.

    condition получает (front_cm, rear_cm) и возвращает bool.
    Внутри условия сравниваются только правдоподобные значения:
    невалидный датчик (-1, таймаут) не может «случайно» завершить шаг.
    """
    print(f"\n[ШАГ {step_no}] {description}")

    f0, b0, _ = tele.get()
    if condition(f0, b0):
        print(f"    [!] ВНИМАНИЕ: условие уже выполнено на старте "
              f"(F={f0:.1f}, B={b0:.1f}). Шаг завершится сразу.")

    t_start = time.time()
    confirms = 0
    last_log = 0.0

    while True:
        f, b, age = tele.get()

        # --- Датчики замолчали: аварийная остановка ---
        if age > SENSOR_STALE_SEC:
            base.stop()
            raise RuntimeError(f"Шаг {step_no}: нет данных с датчиков {age:.1f} с — остановка.")

        # --- Таймаут шага ---
        if time.time() - t_start > timeout:
            base.stop()
            raise RuntimeError(f"Шаг {step_no}: таймаут {timeout:.0f} с, условие не выполнено "
                               f"(F={f:.1f}, B={b:.1f}).")

        # --- Проверка условия с подтверждением ---
        if condition(f, b):
            confirms += 1
            if confirms >= CONFIRM_READINGS:
                print(f"    -> Условие выполнено: F={f:.1f} см, B={b:.1f} см "
                      f"(за {time.time() - t_start:.1f} с)")
                break
        else:
            confirms = 0

        # --- Движение ---
        base.drive_tick(x_vel=x_vel)

        # --- Лог 2 раза в секунду ---
        now = time.time()
        if now - last_log >= 0.5:
            print(f"    F={f:6.1f} см | B={b:6.1f} см")
            last_log = now

        time.sleep(CONTROL_DT)

    base.stop()


# =====================================================================
# МАРШРУТ: 11 ШАГОВ
# =====================================================================
def run_mission(base: XLeRobotBase, tele: TelemetryReceiver):
    print("\n" + "=" * 60)
    print("        СТАРТ АВТОНОМНОГО МАРШРУТА (11 ШАГОВ, 2 ДАТЧИКА)")
    print("=" * 60)

    F = SPEED_FORWARD
    B = SPEED_BACKWARD

    # ---- Шаг 1: вперёд, стоп при F <= 180 ИЛИ B >= 180 ----
    run_drive_step(base, tele, 1,
                   "Вперёд -> стоп при (F <= 180 см ИЛИ B >= 180 см)",
                   F,
                   lambda f, b: (valid(f) and f <= 180.0) or (valid(b) and b >= 180.0))

    # ---- Шаг 2: поворот влево 90° ----
    print("\n[ШАГ 2] Поворот влево на 90°")
    base.turn_left_90()

    # ---- Шаг 3: вперёд, стоп при F <= 63 ----
    run_drive_step(base, tele, 3,
                   "Вперёд -> стоп при (F <= 80 см)",
                   F,
                   lambda f, b: valid(f) and f <= 80.0)

    # ---- Шаг 4: назад, стоп при F >= 264 ИЛИ B <= 108 ----
    run_drive_step(base, tele, 4,
                   "Назад -> стоп при (F >= 264 см ИЛИ B <= 108 см)",
                   B,
                   lambda f, b: (valid(f) and f >= 264.0) or (valid(b) and b <= 108.0))

    # ---- Шаг 5: поворот вправо 90° ----
    print("\n[ШАГ 5] Поворот вправо на 90°")
    base.turn_right_90()

    # ---- Шаг 6: вперёд, стоп при F <= 162 ИЛИ B > 152 ----
    run_drive_step(base, tele, 6,
                   "Вперёд -> стоп при (F <= 162 см ИЛИ B > 152 см)",
                   F,
                   lambda f, b: (valid(f) and f <= 162.0) or (valid(b) and b > 152.0))

    # ---- Шаг 7: назад, стоп при B <= 144 ----
    run_drive_step(base, tele, 7,
                   "Назад -> стоп при (B <= 144 см)",
                   B,
                   lambda f, b: valid(b) and b <= 144.0)

    # ---- Шаг 8: поворот влево 90° ----
    print("\n[ШАГ 8] Поворот влево на 90°")
    base.turn_left_90()

    # ---- Шаг 9: вперёд, стоп при F <= 168 ИЛИ B > 20 ----
    run_drive_step(base, tele, 9,
                   "Вперёд -> стоп при (F <= 168 см ИЛИ B > 207 см)",
                   F,
                   lambda f, b: (valid(f) and f <= 168.0) or (valid(b) and b > 207.0))

    # ---- Шаг 10: поворот вправо 90° ----
    print("\n[ШАГ 10] Поворот вправо на 90°")
    base.turn_right_90()

    # ---- Шаг 11: назад, стоп при B <= 40 ----
    run_drive_step(base, tele, 11,
                   "Назад -> стоп при (B <= 40 см)",
                   B,
                   lambda f, b: valid(b) and b <= 40.0)

    print("\n" + "=" * 60)
    print("            МАРШРУТ УСПЕШНО ЗАВЕРШЁН")
    print("=" * 60 + "\n")


# =====================================================================
# ТОЧКА ВХОДА
# =====================================================================
def main():
    # --- 1. Телеметрия ---
    print(f"1. Запуск чтения датчиков ({SENSOR_PORT})...")
    tele = TelemetryReceiver()
    tele.start()

    if not tele.wait_for_data(timeout=5.0):
        print("[!] Нет валидных данных с датчиков F/B. Проверьте ESP32 и порт.")
        tele.stop()
        return

    f, b, _ = tele.get()
    print(f"   Датчики живы: F={f:.1f} см, B={b:.1f} см")

    # --- 2. Робот ---
    print("2. Подключение к XLerobot...")
    robot_config = XLerobotConfig()
    robot = XLerobot(robot_config)
    try:
        robot.connect()
        print("   XLerobot подключён.")
    except Exception as e:
        print(f"[!] Ошибка подключения к роботу: {e}")
        tele.stop()
        return

    base = XLeRobotBase(robot)

    # --- 3. Обратный отсчёт (успеть убрать руки / нажать Ctrl+C) ---
    for i in (3, 2, 1):
        print(f"   Старт через {i}...")
        time.sleep(1.0)

    # --- 4. Миссия ---
    try:
        run_mission(base, tele)
    except KeyboardInterrupt:
        print("\n[!] Экстренная остановка оператором (Ctrl+C).")
    except RuntimeError as e:
        print(f"\n[!] Миссия прервана: {e}")
    except Exception as e:
        print(f"\n[!] Непредвиденная ошибка: {e}")
    finally:
        print("Безопасная остановка базы и отключение...")
        try:
            base.stop(settle=0.2)
        except Exception:
            pass
        try:
            robot.disconnect()
        except Exception:
            pass
        tele.stop()
        print("Завершено. Порты освобождены.")


if __name__ == "__main__":
    sys.exit(main())

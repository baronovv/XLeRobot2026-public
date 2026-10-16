#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import builtins
import io
import re
import sys
import threading
import time

import serial
from lerobot.robots.xlerobot import XLerobot, XLerobotConfig

# =====================================================================
# НАСТРОЙКИ
# =====================================================================

# --- Датчики (ESP32) ---
SENSOR_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

# --- Скорости базы ---
SPEED_FORWARD = 0.15    # м/с, движение вперёд
SPEED_BACKWARD = -0.15  # м/с, движение назад
TURN_SPEED_DEG = 30.0   # град/с, угловая скорость поворота (theta.vel)

# --- Калибровка поворота на 90° ---
TURN_90_TIME = 3.7      # секунд на поворот 90° при TURN_SPEED_DEG
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


def valid(d: float) -> bool:
    """Правдоподобен ли замер дальномера."""
    return MIN_VALID_DIST_CM < d < MAX_VALID_DIST_CM


# =====================================================================
# ЗАГЛУШКА ПОТОКА ВВОДА (АВТО-ENTER)
# =====================================================================
class AutoEnterStream(io.StringIO):
    """Эмулирует терминал с автоматическим нажатием клавиши Enter."""

    def isatty(self):
        return True

    def readline(self, *args, **kwargs):
        return "\n"

    def read(self, *args, **kwargs):
        return "\n"


# =====================================================================
# ПОТОК ЧТЕНИЯ ТЕЛЕМЕТРИИ (F / B)
# =====================================================================
class TelemetryReceiver:
    """Фоновое чтение 'F:<число>,B:<число>' с ESP32."""

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


# =====================================================================
# УПРАВЛЕНИЕ БАЗОЙ XLEROBOT
# =====================================================================
class XLeRobotBase:
    """Обёртка над XLerobot: движение базы + удержание суставов."""

    def __init__(self, robot: XLerobot):
        self.robot = robot
        self.hold_pose = {}
        self._capture_hold_pose()

    def _capture_hold_pose(self):
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
        theta = TURN_SPEED_DEG if direction == "left" else -TURN_SPEED_DEG
        label = "ВЛЕВО" if direction == "left" else "ВПРАВО"
        print(f"    >>> Поворот {label} на 90° (theta.vel={theta:+.1f} град/с, {duration:.2f} с)")

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
    """Исполнитель шага прямолинейного движения по условию датчиков."""
    print(f"\n[ШАГ {step_no}] {description}")

    f0, b0, _ = tele.get()
    if condition(f0, b0):
        print(f"    [!] ВНИМАНИЕ: условие уже выполнено на старте (F={f0:.1f}, B={b0:.1f}).")

    t_start = time.time()
    confirms = 0
    last_log = 0.0

    while True:
        f, b, age = tele.get()

        if age > SENSOR_STALE_SEC:
            base.stop()
            raise RuntimeError(f"Шаг {step_no}: нет данных с датчиков {age:.1f} с — остановка.")

        if time.time() - t_start > timeout:
            base.stop()
            raise RuntimeError(f"Шаг {step_no}: таймаут {timeout:.0f} с (F={f:.1f}, B={b:.1f}).")

        if condition(f, b):
            confirms += 1
            if confirms >= CONFIRM_READINGS:
                print(f"    -> Условие выполнено: F={f:.1f} см, B={b:.1f} см (за {time.time() - t_start:.1f} с)")
                break
        else:
            confirms = 0

        base.drive_tick(x_vel=x_vel)

        now = time.time()
        if now - last_log >= 0.5:
            print(f"    F={f:6.1f} см | B={b:6.1f} см")
            last_log = now

        time.sleep(CONTROL_DT)

    base.stop()


# =====================================================================
# УНИВЕРСАЛЬНЫЙ РАННЕР МИССИЙ
# =====================================================================
def execute_route(mission_fn):  # EXITCODE_PATCH: returns True only on success
    """
    Универсальная точка запуска и безопасного завершения миссий.
    Автоматически перенаправляет ввод Enter при robot.connect().
    """
    # --- 1. Телеметрия ---
    print(f"1. Запуск чтения датчиков ({SENSOR_PORT})...")
    tele = TelemetryReceiver()
    tele.start()

    if not tele.wait_for_data(timeout=5.0):
        print("[!] Нет валидных данных с датчиков F/B. Проверьте ESP32 и порт.")
        tele.stop()
        return False

    f, b, _ = tele.get()
    print(f"   Датчики живы: F={f:.1f} см, B={b:.1f} см")

    # --- 2. Робот ---
    print("2. Подключение к XLerobot...")
    robot_config = XLerobotConfig()
    robot = XLerobot(robot_config)

    # Подменяем sys.stdin и builtins.input, чтобы библиотека автоматически получила Enter
    old_stdin = sys.stdin
    old_input = builtins.input
    sys.stdin = AutoEnterStream("\n\n\n\n\n")
    builtins.input = lambda *args, **kwargs: ""

    try:
        try:
            robot.connect()
        finally:
            # Восстанавливаем стандартные потоки ввода
            sys.stdin = old_stdin
            builtins.input = old_input

        print("   XLerobot подключён.")
    except Exception as e:
        print(f"[!] Ошибка подключения к роботу: {e}")
        tele.stop()
        return False

    base = XLeRobotBase(robot)

    # --- 3. Обратный отсчёт ---


    # --- 4. Миссия ---
    ok = False
    try:
        mission_fn(base, tele)
        ok = True
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

    return ok

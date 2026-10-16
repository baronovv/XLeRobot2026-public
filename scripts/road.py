import re
import sys
import time
import serial

# --- Импорт LeRobot ---
try:
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.lekiwi import LeKiwi, LeKiwiConfig
except ImportError:
    from lerobot.common.robot_devices.cameras.opencv import OpenCVCameraConfig
    from lerobot.common.robot_devices.robots.lekiwi import LeKiwi, LeKiwiConfig

# --- Настройки подключения ---
SENSOR_PORT = "/dev/ttyUSB0"  # Порт ESP32 с ультразвуковым датчиком
LEKIWI_PORT = "/dev/ttyACM1"  # Порт контроллера моторов LeKiwi
CAMERA_PATH = "/dev/video10"  # Камера
BAUD_RATE = 115200

# --- Параметры движения и фильтрации ---
DRIVE_SPEED = 0.20  # Линейная скорость перемещения (м/с)
TURN_SPEED = 1000  # Прямая скорость моторов для поворота
TIME_TURN_90_DEG = 3.4  # Время поворота на 90 градусов (сек)
TIME_TURN_180_DEG = 3.4 * 2  # Время разворота на 180 градусов (6.8 сек)
MIN_VALID_DIST_CM = 10.0  # Минимальный порог (игнорирует стартовые 1 см и шумы)


def extract_distance(text: str):
    """Извлечение числового значения дистанции из вывода ESP32."""
    match = re.search(r"[-+]?\d*\.\d+|\d+", text)
    return float(match.group(0)) if match else None


def patch_robot_bus(robot: LeKiwi):
    """Патч MotorsBus для предотвращения ошибок StopIteration и поддержки num_retry."""
    original_sync_write = robot.bus.sync_write

    def safe_sync_write(register_name, values_by_motor, *args, **kwargs):
        if not values_by_motor:
            return
        return original_sync_write(register_name, values_by_motor, *args, **kwargs)

    robot.bus.sync_write = safe_sync_write


def build_action(robot: LeKiwi, base_template: dict, x_vel: float = 0.0, y_vel: float = 0.0, theta_vel: float = 0.0):
    """Формирует действие линейного движения с сохранением позиции суставов манипулятора."""
    act = base_template.copy()
    act["x.vel"] = float(x_vel)
    act["y.vel"] = float(y_vel)
    act["theta.vel"] = float(theta_vel)
    return act


def turn_clockwise(robot: LeKiwi, speed: int, duration: float):
    """Прямой синхронный поворот по часовой стрелке через регистр Goal_Velocity."""
    cw_speeds = {motor: -abs(speed) for motor in robot.base_motors}
    stop_speeds = {motor: 0 for motor in robot.base_motors}

    t_start = time.time()
    while time.time() - t_start < duration:
        robot.bus.sync_write("Goal_Velocity", cw_speeds)
        time.sleep(0.02)

    robot.bus.sync_write("Goal_Velocity", stop_speeds)
    time.sleep(0.3)  # Пауза на механическую стабилизацию


def stop_base_motors(robot: LeKiwi, base_template: dict):
    """Полная остановка платформы."""
    if hasattr(robot, "base_motors"):
        robot.bus.sync_write("Goal_Velocity", {motor: 0 for motor in robot.base_motors})
    robot.send_action(build_action(robot, base_template, 0.0, 0.0, 0.0))


def main():
    print(f"1. Инициализация камеры {CAMERA_PATH} и робота LeKiwi ({LEKIWI_PORT})...")
    try:
        try:
            cameras_cfg = {"front": OpenCVCameraConfig(camera_index=CAMERA_PATH, width=640, height=480, fps=30)}
        except TypeError:
            cameras_cfg = {"front": OpenCVCameraConfig(index_or_path=CAMERA_PATH, width=640, height=480, fps=30)}

        config = LeKiwiConfig(port=LEKIWI_PORT, cameras=cameras_cfg)
        robot = LeKiwi(config)
        robot.connect()
        patch_robot_bus(robot)
        print("LeKiwi успешно подключен.")
    except Exception as e:
        print(f"Ошибка инициализации LeKiwi: {e}")
        return

    # Шаблон для удержания суставов манипулятора
    base_template = {}
    if hasattr(robot, "action_names"):
        for name in robot.action_names:
            base_template[name] = 0.0
    try:
        obs = robot.capture_observation()
        for k, v in obs.items():
            if ".pos" in k or k.startswith("arm_"):
                base_template[k] = float(v.item() if hasattr(v, "item") else v)
    except Exception:
        pass

    state = 1
    print(f"2. Подключение к датчику на {SENSOR_PORT}...")

    try:
        with serial.Serial(port=SENSOR_PORT, baudrate=BAUD_RATE, timeout=0.2, exclusive=True) as ser:
            ser.dtr = False
            ser.rts = False
            time.sleep(0.5)
            ser.reset_input_buffer()
            print("\n==========================================")
            print("         СТАРТ АВТОНОМНОГО МАРШРУТА        ")
            print("==========================================\n")

            while True:
                if ser.in_waiting > 0:
                    raw = ser.readline().decode('utf-8', errors='ignore').strip()
                    if not raw or "=" in raw:
                        continue

                    dist = extract_distance(raw)

                    # Игнорируем некорректные значения, таймауты и любые замеры <= 10 см
                    if dist is None or dist <= MIN_VALID_DIST_CM:
                        continue

                    # --- Шаг 1: Вперед до dist <= 165 см ---
                    if state == 1:
                        if dist <= 165.0:
                            print(f"\n[Шаг 1 завершен] Дистанция: {dist:.1f} см <= 165.0 см")
                            stop_base_motors(robot, base_template)
                            state = 2
                        else:
                            print(f"[Шаг 1: ВПЕРЕД] {dist:.1f} см -> цель <= 165.0 см")
                            robot.send_action(build_action(robot, base_template, x_vel=DRIVE_SPEED))

                    # --- Шаг 2: Поворот вправо на 90° ---
                    elif state == 2:
                        print(f"[Шаг 2] Поворот направо на 90° ({TIME_TURN_90_DEG} с)...")
                        turn_clockwise(robot, speed=TURN_SPEED, duration=TIME_TURN_90_DEG)
                        ser.reset_input_buffer()
                        print("[Шаг 2 завершен] Переход к движению назад.\n")
                        state = 3

                    # --- Шаг 3: Назад до dist >= 250 см ---
                    elif state == 3:
                        if dist >= 250.0:
                            print(f"\n[Шаг 3 завершен] Дистанция: {dist:.1f} см >= 250.0 см")
                            stop_base_motors(robot, base_template)
                            state = 4
                        else:
                            print(f"[Шаг 3: НАЗАД] {dist:.1f} см -> цель >= 250.0 см")
                            robot.send_action(build_action(robot, base_template, x_vel=-DRIVE_SPEED))

                    # --- Шаг 4: Вперед до dist <= 86 см ---
                    elif state == 4:
                        if dist <= 86.0:
                            print(f"\n[Шаг 4 завершен] Дистанция: {dist:.1f} см <= 86.0 см")
                            stop_base_motors(robot, base_template)
                            state = 5
                        else:
                            print(f"[Шаг 4: ВПЕРЕД] {dist:.1f} см -> цель <= 86.0 см")
                            robot.send_action(build_action(robot, base_template, x_vel=DRIVE_SPEED))

                    # --- Шаг 5: Поворот вправо на 90° ---
                    elif state == 5:
                        print(f"[Шаг 5] Поворот направо на 90° ({TIME_TURN_90_DEG} с)...")
                        turn_clockwise(robot, speed=TURN_SPEED, duration=TIME_TURN_90_DEG)
                        ser.reset_input_buffer()
                        print("[Шаг 5 завершен] Переход к финальному отрезку.\n")
                        state = 6

                    # --- Шаг 6: Вперед до dist <= 30 см ---
                    elif state == 6:
                        if dist <= 30.0:
                            print(f"\n[Шаг 6 завершен] Дистанция: {dist:.1f} см <= 30.0 см")
                            stop_base_motors(robot, base_template)
                            state = 7
                        else:
                            print(f"[Шаг 6: ВПЕРЕД] {dist:.1f} см -> цель <= 30.0 см")
                            robot.send_action(build_action(robot, base_template, x_vel=DRIVE_SPEED))

                    # --- Шаг 7: Разворот на 180° и финиш ---
                    elif state == 7:
                        print(f"[Шаг 7] Разворот на 180° ({TIME_TURN_180_DEG} с)...")
                        turn_clockwise(robot, speed=TURN_SPEED, duration=TIME_TURN_180_DEG)
                        print("\n==========================================")
                        print("       МАРШРУТ УСПЕШНО ВЫПОЛНЕН!          ")
                        print("==========================================")
                        break

                time.sleep(0.02)

    except KeyboardInterrupt:
        print("\nОстановка по сигналу пользователя...")
    except serial.SerialException as e:
        print(f"\n[Ошибка порта]: {e}")
    finally:
        print("Безопасная остановка моторов и отключение...")
        try:
            stop_base_motors(robot, base_template)
            robot.disconnect()
        except Exception:
            pass
        print("Завершено. Порты освобождены.")


if __name__ == "__main__":
    main()

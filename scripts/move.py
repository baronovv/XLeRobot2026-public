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
LEKIWI_PORT = "/dev/ttyACM0"  # Порт моторов LeKiwi
CAMERA_PATH = "/dev/video10"  # Камера
BAUD_RATE = 115200

# --- Настройки движения (м/с) ---
DRIVE_SPEED = 0.15  # Скорость движения (0.15 - 0.30 м/с)
MIN_DIST_CM = 60.0  # Порог спереди (0.5 м)
MAX_DIST_CM = 200.0  # Порог отката назад (2.0 м)


def extract_distance(text: str):
    """Извлечение дистанции из вывода ESP32."""
    match = re.search(r"[-+]?\d*\.\d+|\d+", text)
    return float(match.group(0)) if match else None


def patch_robot_bus(robot: LeKiwi):
    """
    Патч для MotorsBus: предотвращает падение StopIteration при пустых командах.
    """
    original_sync_write = robot.bus.sync_write

    def safe_sync_write(register_name, values_by_motor):
        if not values_by_motor:
            return  # Пропускаем запись, если список моторов пуст
        return original_sync_write(register_name, values_by_motor)

    robot.bus.sync_write = safe_sync_write


def build_action(robot: LeKiwi, base_action_template: dict, x_vel: float, y_vel: float = 0.0, theta_vel: float = 0.0):
    """
    Формирует полный словарь действий: скорости для базы + удержание позы руки.
    """
    action = base_action_template.copy()
    action["x.vel"] = float(x_vel)
    action["y.vel"] = float(y_vel)
    action["theta.vel"] = float(theta_vel)
    return action


def main():
    print(f"1. Инициализация камеры {CAMERA_PATH} и робота LeKiwi ({LEKIWI_PORT})...")

    try:
        cameras_config = {
            "front": OpenCVCameraConfig(
                camera_index=CAMERA_PATH,
                width=640,
                height=480,
                fps=30,
            )
        }
    except TypeError:
        cameras_config = {
            "front": OpenCVCameraConfig(
                index_or_path=CAMERA_PATH,
                width=640,
                height=480,
                fps=30,
            )
        }

    try:
        config = LeKiwiConfig(port=LEKIWI_PORT, cameras=cameras_config)
        robot = LeKiwi(config)
        robot.connect()

        # Применяем патч защиты от StopIteration
        patch_robot_bus(robot)
        print("Робот LeKiwi и камера успешно подключены (шина моторов пропатчена).")
    except Exception as e:
        print(f"Ошибка инициализации LeKiwi: {e}")
        return

    # Получаем шаблон действий по умолчанию (сохраняет позу руки при наличии)
    base_action_template = {}
    if hasattr(robot, "action_names"):
        for name in robot.action_names:
            base_action_template[name] = 0.0
    try:
        obs = robot.capture_observation()
        for k, v in obs.items():
            if ".pos" in k or k.startswith("arm_"):
                base_action_template[k] = float(v.item() if hasattr(v, "item") else v)
    except Exception:
        pass

    current_state = "FORWARD"

    print(f"2. Подключение к ультразвуковому датчику на {SENSOR_PORT}...")
    try:
        with serial.Serial(
                port=SENSOR_PORT,
                baudrate=BAUD_RATE,
                timeout=0.2,
                exclusive=True
        ) as ser:
            ser.dtr = False
            ser.rts = False
            time.sleep(0.5)
            ser.reset_input_buffer()
            print("Связь установлена. Запуск челночного движения (Ctrl+C для выхода)...")

            while True:
                if ser.in_waiting > 0:
                    raw_bytes = ser.readline()
                    line = raw_bytes.decode('utf-8', errors='ignore').strip()

                    if not line or "=" in line:
                        continue

                    dist = extract_distance(line)
                    if dist is None or dist <= 0:
                        continue

                    # Автомат состояний
                    if current_state == "FORWARD":
                        if dist <= MIN_DIST_CM:
                            print(f"[ПОРОГ] Дистанция: {dist:.1f} см <= {MIN_DIST_CM} см -> Переключение НАЗАД")
                            current_state = "BACKWARD"
                        else:
                            print(f"[ВПЕРЕД] Дистанция: {dist:.1f} см (Цель: <= {MIN_DIST_CM} см)")
                            act = build_action(robot, base_action_template, x_vel=DRIVE_SPEED)
                            robot.send_action(act)

                    elif current_state == "BACKWARD":
                        if dist >= MAX_DIST_CM:
                            print(f"[ПОРОГ] Дистанция: {dist:.1f} см >= {MAX_DIST_CM} см -> Переключение ВПЕРЕД")
                            current_state = "FORWARD"
                        else:
                            print(f"[НАЗАД] Дистанция: {dist:.1f} см (Цель: >= {MAX_DIST_CM} см)")
                            act = build_action(robot, base_action_template, x_vel=-DRIVE_SPEED)
                            robot.send_action(act)

                time.sleep(0.02)

    except KeyboardInterrupt:
        print("\nОстановка по сигналу пользователя...")
    except serial.SerialException as e:
        print(f"\n[Ошибка порта ESP32]: {e}")
    finally:
        print("Безопасная остановка робота...")
        try:
            stop_act = build_action(robot, base_action_template, x_vel=0.0, y_vel=0.0, theta_vel=0.0)
            robot.send_action(stop_act)
            robot.disconnect()
        except Exception:
            pass
        print("Завершено.")


if __name__ == "__main__":
    main()

import sys
import time

# --- Импорт LeRobot ---
try:
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.lekiwi import LeKiwi, LeKiwiConfig
except ImportError:
    from lerobot.common.robot_devices.cameras.opencv import OpenCVCameraConfig
    from lerobot.common.robot_devices.robots.lekiwi import LeKiwi, LeKiwiConfig

LEKIWI_PORT = "/dev/ttyACM1"

# --- Параметры калибровки ---
TURN_SPEED = 1000          # Базовая скорость моторов
TURN_DURATION = 3.4        # Длительность вращения в секундах

def patch_robot_bus(robot: LeKiwi):
    """Патч с корректной поддержкой всех аргументов sync_write."""
    original_sync_write = robot.bus.sync_write

    def safe_sync_write(register_name, values_by_motor, *args, **kwargs):
        if not values_by_motor:
            return
        return original_sync_write(register_name, values_by_motor, *args, **kwargs)

    robot.bus.sync_write = safe_sync_write

def turn_clockwise(robot: LeKiwi, speed: int, duration: float):
    """Прямой поворот базы по часовой стрелке через регистр Goal_Velocity."""
    # Отрицательная скорость вращает платформу по часовой стрелке
    cw_speeds = {motor: -abs(speed) for motor in robot.base_motors}
    stop_speeds = {motor: 0 for motor in robot.base_motors}

    print(f">>> Вращение ПО ЧАСОВОЙ стрелке (Speed: {-abs(speed)}, Время: {duration} с)...")
    start_time = time.time()
    while time.time() - start_time < duration:
        robot.bus.sync_write("Goal_Velocity", cw_speeds)
        time.sleep(0.02)

    # Остановка моторов
    robot.bus.sync_write("Goal_Velocity", stop_speeds)
    time.sleep(0.2)

def main():
    print("1. Подключение к LeKiwi...")
    try:

        config = LeKiwiConfig(port=LEKIWI_PORT)
        robot = LeKiwi(config)
        robot.connect()
        patch_robot_bus(robot)
        print("Робот успешно подключен.")
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return

    try:
        turn_clockwise(robot, speed=TURN_SPEED, duration=TURN_DURATION)
        print("Поворот выполнен.")
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
    finally:
        print("Безопасная остановка и отключение...")
        try:
            if hasattr(robot, "base_motors"):
                robot.bus.sync_write("Goal_Velocity", {motor: 0 for motor in robot.base_motors})
            robot.disconnect()
        except Exception as e:
            print(f"Ошибка при отключении: {e}")
        print("Завершено. Порт освобожден.")

if __name__ == "__main__":
    main()
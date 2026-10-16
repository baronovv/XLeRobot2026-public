import re
import time
import threading
import serial

# ==============================================================================
# НАСТРОЙКИ СВЯЗИ И ПАРАМЕТРЫ ДВИЖЕНИЯ
# ==============================================================================
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

# Калибровка времени поворотов на 90 градусов (в секундах)
TURN_90_TIME = 1.15  # Подберите точное значение для вашей поверхности

# Скорости движения
SPEED_FORWARD = 0.25
SPEED_BACKWARD = -0.25
SPEED_TURN = 0.30

# ==============================================================================
# ПОТОК ЧТЕНИЯ ТЕЛЕМЕТРИИ С ESP32 (F, B, L)
# ==============================================================================
class TelemetryReceiver:
    def __init__(self, port=SERIAL_PORT, baudrate=BAUD_RATE):
        self.port = port
        self.baudrate = baudrate
        self.front = -1.0
        self.rear = -1.0
        self.left = -1.0
        self.running = False
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
                print(f"[Telemetry] Подключено к {self.port}")

                pattern = re.compile(r"F:([-+]?\d*\.?\d+).*?B:([-+]?\d*\.?\d+).*?L:([-+]?\d*\.?\d+)")

                while self.running:
                    if ser.in_waiting > 0:
                        raw = ser.readline().decode("utf-8", errors="ignore").strip()
                        if not raw or "=" in raw:
                            continue

                        match = pattern.search(raw)
                        if match:
                            try:
                                f_val = float(match.group(1))
                                b_val = float(match.group(2))
                                l_val = float(match.group(3))

                                with self.lock:
                                    self.front = f_val
                                    self.rear = b_val
                                    self.left = l_val
                            except ValueError:
                                pass
                    time.sleep(0.005)
        except serial.SerialException as e:
            print(f"[Telemetry] Ошибка порта: {e}")

    def get_sensors(self):
        with self.lock:
            return self.front, self.rear, self.left

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)

# ==============================================================================
# УПРАВЛЕНИЕ БАЗОЙ LEKIWI
# ==============================================================================
class LeKiwiBase:
    def __init__(self):
        # Если используется LeRobot API или шина Feetech STS3215:
        # self.motors = ...
        pass

    def drive(self, vx: float, vy: float, vtheta: float):
        """
        vx: продольная скорость (вперед > 0, назад < 0)
        vy: боковая скорость (влево/вправо)
        vtheta: угловая скорость вращения
        """
        # Интеграция с вашей функцией отправки скоростей на сервоприводы
        pass

    def stop(self):
        self.drive(0.0, 0.0, 0.0)

    def turn_left_90(self):
        print(">>> [Turn] Влево на 90°")
        self.drive(0.0, 0.0, SPEED_TURN)
        time.sleep(TURN_90_TIME)
        self.stop()
        time.sleep(0.3)

    def turn_right_90(self):
        print(">>> [Turn] Вправо на 90°")
        self.drive(0.0, 0.0, -SPEED_TURN)
        time.sleep(TURN_90_TIME)
        self.stop()
        time.sleep(0.3)

# ==============================================================================
# ОСНОВНОЙ АВТОНОМНЫЙ МАРШРУТ (11 ШАГОВ)
# ==============================================================================
def run_mission(base: LeKiwiBase, tele: TelemetryReceiver):
    print("\n--- Запуск выполнения 11-шаговой миссии ---\n")
    time.sleep(1.0)

    def wait_for_valid_sensors():
        for _ in range(20):
            f, b, _ = tele.get_sensors()
            if b > 0 or f > 0:
                return True
            time.sleep(0.1)
        return False

    if not wait_for_valid_sensors():
        print("[Предупреждение] Нет актуальных данных с датчиков F/B, запуск с осторожностью.")

    # --- ШАГ 1: Вперед (F <= 180 или B >= 180) ---
    print("[ШАГ 1] Вперед -> Стоп при (F <= 180 см ИЛИ B >= 180 см)")
    base.drive(SPEED_FORWARD, 0.0, 0.0)
    while True:
        f, b, _ = tele.get_sensors()
        if (0 < f <= 180.0) or (b >= 180.0):
            print(f" -> Условие Шага 1 выполнено: F={f:.1f}, B={b:.1f}")
            break
        time.sleep(0.02)
    base.stop()
    time.sleep(0.3)

    # --- ШАГ 2: Поворот влево 90° ---
    print("[ШАГ 2] Поворот влево на 90°")
    base.turn_left_90()

    # --- ШАГ 3: Вперед (F <= 53) ---
    print("[ШАГ 3] Вперед -> Стоп при (F <= 53 см)")
    base.drive(SPEED_FORWARD, 0.0, 0.0)
    while True:
        f, b, _ = tele.get_sensors()
        if 0 < f <= 53.0:
            print(f" -> Условие Шага 3 выполнено: F={f:.1f}")
            break
        time.sleep(0.02)
    base.stop()
    time.sleep(0.3)

    # --- ШАГ 4: Назад (F >= 264 или B <= 108) ---
    print("[ШАГ 4] Назад -> Стоп при (F >= 264 см ИЛИ B <= 108 см)")
    base.drive(SPEED_BACKWARD, 0.0, 0.0)
    while True:
        f, b, _ = tele.get_sensors()
        if (f >= 264.0) or (0 < b <= 108.0):
            print(f" -> Условие Шага 4 выполнено: F={f:.1f}, B={b:.1f}")
            break
        time.sleep(0.02)
    base.stop()
    time.sleep(0.3)

    # --- ШАГ 5: Поворот вправо 90° ---
    print("[ШАГ 5] Поворот вправо на 90°")
    base.turn_right_90()

    # --- ШАГ 6: Вперед (F <= 152 или B > 152) ---
    print("[ШАГ 6] Вперед -> Стоп при (F <= 152 см ИЛИ B > 152 см)")
    base.drive(SPEED_FORWARD, 0.0, 0.0)
    while True:
        f, b, _ = tele.get_sensors()
        if (0 < f <= 152.0) or (b > 152.0):
            print(f" -> Условие Шага 6 выполнено: F={f:.1f}, B={b:.1f}")
            break
        time.sleep(0.02)
    base.stop()
    time.sleep(0.3)

    # --- ШАГ 7: Назад (B <= 134) ---
    print("[ШАГ 7] Назад -> Стоп при (B <= 134 см)")
    base.drive(SPEED_BACKWARD, 0.0, 0.0)
    while True:
        _, b, _ = tele.get_sensors()
        if 0 < b <= 134.0:
            print(f" -> Условие Шага 7 выполнено: B={b:.1f}")
            break
        time.sleep(0.02)
    base.stop()
    time.sleep(0.3)

    # --- ШАГ 8: Поворот влево 90° ---
    print("[ШАГ 8] Поворот влево на 90°")
    base.turn_left_90()

    # --- ШАГ 9: Вперед (F <= 168 или B > 20) ---
    print("[ШАГ 9] Вперед -> Стоп при (F <= 168 см ИЛИ B > 20 см)")
    base.drive(SPEED_FORWARD, 0.0, 0.0)
    while True:
        f, b, _ = tele.get_sensors()
        if (0 < f <= 168.0) or (b > 20.0):
            print(f" -> Условие Шага 9 выполнено: F={f:.1f}, B={b:.1f}")
            break
        time.sleep(0.02)
    base.stop()
    time.sleep(0.3)

    # --- ШАГ 10: Поворот вправо 90° ---
    print("[ШАГ 10] Поворот вправо на 90°")
    base.turn_right_90()

    # --- ШАГ 11: Назад (B <= 40) ---
    print("[ШАГ 11] Назад -> Стоп при (B <= 40 см)")
    base.drive(SPEED_BACKWARD, 0.0, 0.0)
    while True:
        _, b, _ = tele.get_sensors()
        if 0 < b <= 40.0:
            print(f" -> Условие Шага 11 выполнено: B={b:.1f}")
            break
        time.sleep(0.02)
    base.stop()
    time.sleep(0.3)

    print("\n--- Маршрут успешно завершен! ---\n")

# ==============================================================================
# ТОЧКА ВХОДА
# ==============================================================================
def main():
    telemetry = TelemetryReceiver()
    base = LeKiwiBase()

    telemetry.start()
    time.sleep(1.0)

    try:
        run_mission(base, telemetry)
    except KeyboardInterrupt:
        print("\n[!] Экстренная остановка оператором.")
    finally:
        base.stop()
        telemetry.stop()
        print("Двигатели остановлены, порт закрыт.")

if __name__ == "__main__":
    main()
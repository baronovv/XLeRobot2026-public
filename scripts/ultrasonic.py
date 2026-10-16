import re
import time
import serial

SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200


def move_forward():
    print(">> ДВИЖЕНИЕ: Вперед")


def turn_right():
    print(">> МАНЕВР: Поворот направо")
    time.sleep(1.2)


def stop_robot():
    print(">> СТОП: Остановка платформы")


def extract_distance(text):
    # Поиск первого числа с плавающей точкой в строке
    match = re.search(r"[-+]?\d*\.\d+|\d+", text)
    if match:
        return float(match.group(0))
    return None


def main():
    try:
        # Отключаем аппаратный сброс DTR/RTS, чтобы ESP32 не зависала в bootloader
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            timeout=0.5,
            dsrdtr=False,
            rtscts=False
        )
        ser.dtr = False
        ser.rts = False
        time.sleep(1.0)  # Пауза на инициализацию UART
        ser.reset_input_buffer()
        print(f"Успешно подключено к ESP32 на {SERIAL_PORT}")
    except Exception as e:
        print(f"Ошибка открытия порта: {e}")
        return

    state = 0

    try:
        while True:
            if ser.in_waiting > 0:
                raw_bytes = ser.readline()
                line = raw_bytes.decode('utf-8', errors='ignore').strip()

                # Если строка пустая или служебный разделитель ===
                if not line or "=" in line:
                    continue

                # Извлекаем дистанцию
                distance = extract_distance(line)

                if distance is None or distance <= 0:
                    print(f"[ESP32 RAW]: {line}")
                    continue

                print(f"[State {state}] Дистанция: {distance:.1f} см")

                # Логика перемещения
                if state == 0:
                    if distance > 100.0:
                        move_forward()
                    else:
                        print("--- Достигнут порог 100 см! ---")
                        stop_robot()
                        state = 1

                elif state == 1:
                    turn_right()
                    stop_robot()
                    time.sleep(0.5)
                    print("--- Переход ко 2-му отрезку ---")
                    state = 2

                elif state == 2:
                    if distance > 150.0:
                        move_forward()
                    else:
                        print("--- Достигнут порог 150 см! Маршрут завершен. ---")
                        stop_robot()
                        state = 3

                elif state == 3:
                    stop_robot()
                    print("Миссия выполнена.")
                    break

            time.sleep(0.01)

    except KeyboardInterrupt:
        stop_robot()
    finally:
        ser.close()


if __name__ == "__main__":
    main()
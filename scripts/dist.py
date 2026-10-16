import re
import time
import serial

SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

def parse_dual_distances(text: str):
    """Извлекает дистанции из строки формата f'F:120.5,B:45.2'"""
    match = re.search(r"F:([-+]?\d*\.?\d+).*?B:([-+]?\d*\.?\d+)", text)
    if match:
        try:
            return float(match.group(1)), float(match.group(2))
        except ValueError:
            return None, None
    return None, None

def main():
    print(f"Открытие порта {SERIAL_PORT}...")
    try:
        with serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            timeout=0.5,
            exclusive=True
        ) as ser:
            ser.dtr = False
            ser.rts = False
            time.sleep(0.5)
            ser.reset_input_buffer()
            print("Связь установлена. Вывод 2 раза в секунду без фильтрации (Ctrl+C для выхода):\n")

            last_print_time = 0.0

            while True:
                if ser.in_waiting > 0:
                    raw = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not raw or "=" in raw:
                        continue

                    current_time = time.time()
                    # Частота вывода: ровно раз в 0.5 секунды (2 Гц)
                    if current_time - last_print_time >= 0.5:
                        dist_f, dist_b = parse_dual_distances(raw)

                        if dist_f is not None and dist_b is not None:
                            print(f"[FRONT]: {dist_f:.1f} cm | [REAR]: {dist_b:.1f} cm")
                        else:
                            print(f"[RAW]: {raw}")

                        last_print_time = current_time
                        # Сбрасываем очередь, чтобы следующий замер был актуальным, а не из буфера
                        ser.reset_input_buffer()

                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nОстановка.")
    except serial.SerialException as e:
        print(f"\nОшибка порта: {e}")

if __name__ == "__main__":
    main()

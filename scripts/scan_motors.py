#!/usr/bin/env python3
"""Автономный тест колёсных сервоприводов: пингуем моторы 7/8/9 и выводим их позиции.
Покрутите каждое колесо рукой, чтобы проверить ID, направление вращения (знак) и переполнение тиков (rollover)."""
import sys, time
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

PORT = "/dev/serial/by-path/platform-3610000.usb-usb-0:2.4.1:1.0"
BAUD = 1_000_000
IDS = {7: "левое ", 8: "заднее", 9: "правое"}
ADDR_PRESENT_POSITION = 56  # 2 байта, значения 0..4095

port = PortHandler(PORT)
pkt = PacketHandler(0)  # protocol_end=0 для серии STS

if not port.openPort() or not port.setBaudRate(BAUD):
    sys.exit(f"Не удалось открыть порт {PORT}")

print("Пингуем колёсные моторы...")
for mid, name in IDS.items():
    model, res, err = pkt.ping(port, mid)
    ok = (res == COMM_SUCCESS)
    print(f"  ID {mid} ({name}): {'OK, модель ' + str(model) if ok else 'НЕТ ОТВЕТА'}")

print("\nВывод позиций с частотой 10 Гц. Покрутите колёса рукой. Ctrl-C для остановки.\n")
try:
    while True:
        line = []
        for mid, name in IDS.items():
            pos, res, err = pkt.read2ByteTxRx(port, mid, ADDR_PRESENT_POSITION)
            line.append(f"{name}={pos if res == COMM_SUCCESS else 'ОШИБКА':>5}")
        print("  ".join(str(x) for x in line), end="\r", flush=True)
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nготово")
port.closePort()

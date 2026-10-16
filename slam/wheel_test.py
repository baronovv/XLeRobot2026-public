#!/usr/bin/env python3
"""Standalone wheel servo test: ping motors 7/8/9 and stream positions.
Spin each wheel by hand to verify IDs, signs, and tick rollover."""
import sys, time
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

PORT = "/dev/serial/by-path/platform-3610000.usb-usb-0:2.4.1:1.0"
BAUD = 1_000_000
IDS = {7: "left ", 8: "back ", 9: "right"}
ADDR_PRESENT_POSITION = 56  # 2 bytes, 0..4095

port = PortHandler(PORT)
pkt = PacketHandler(0)  # protocol_end=0 for STS series

if not port.openPort() or not port.setBaudRate(BAUD):
    sys.exit(f"Failed to open {PORT}")

print("Pinging wheel motors...")
for mid, name in IDS.items():
    model, res, err = pkt.ping(port, mid)
    ok = (res == COMM_SUCCESS)
    print(f"  ID {mid} ({name}): {'OK, model ' + str(model) if ok else 'NO RESPONSE'}")

print("\nStreaming positions at 10 Hz. Spin wheels by hand. Ctrl-C to stop.\n")
try:
    while True:
        line = []
        for mid, name in IDS.items():
            pos, res, err = pkt.read2ByteTxRx(port, mid, ADDR_PRESENT_POSITION)
            line.append(f"{name}={pos if res == COMM_SUCCESS else 'ERR':>5}")
        print("  ".join(str(x) for x in line), end="\r", flush=True)
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\ndone")
port.closePort()

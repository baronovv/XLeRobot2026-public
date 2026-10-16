#!/usr/bin/env python3
import sys
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

PORTS = [
    "/dev/serial/by-path/platform-3610000.usb-usb-0:2.4.1:1.0",
    "/dev/serial/by-path/platform-3610000.usb-usb-0:2.4.4:1.0",
]
for p in PORTS:
    print(f"\n=== {p.split('/')[-1]} ===")
    port = PortHandler(p)
    if not port.openPort() or not port.setBaudRate(1_000_000):
        print("  cannot open (busy or missing)")
        continue
    pkt = PacketHandler(0)
    found = []
    for mid in range(1, 13):
        model, res, err = pkt.ping(port, mid)
        if res == COMM_SUCCESS:
            found.append(f"ID {mid} (model {model})")
    print("  found: " + (", ".join(found) if found else "NOTHING"))
    port.closePort()

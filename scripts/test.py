#!/usr/bin/python3
import time
import statistics
import Jetson.GPIO as GPIO

TRIG = 29
ECHO = 31
SPEED = 343.0

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)
GPIO.setup(TRIG, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(ECHO, GPIO.IN)


def vaihe1_lepotila():
    print("\n[1] ECHO lepotilassa (ei laukaisua, 1 s)")
    t0 = time.perf_counter()
    korkea = 0
    n = 0
    while time.perf_counter() - t0 < 1.0:
        korkea += GPIO.input(ECHO)
        n += 1
    osuus = 100.0 * korkea / n
    print(f"    ECHO korkealla {osuus:.1f} % ajasta ({n} näytettä)")
    if osuus > 5:
        print("    -> ECHO on jumissa ylhäällä. Tarkista GND ja VCC.")
        return False
    print("    -> OK, ECHO lepää alhaalla")
    return True


def yksi_ping(timeout=0.03):
    GPIO.output(TRIG, GPIO.HIGH)
    time.sleep(10e-6)
    GPIO.output(TRIG, GPIO.LOW)

    t0 = time.perf_counter()
    while GPIO.input(ECHO) == 0:
        if time.perf_counter() - t0 > timeout:
            return "ei_nousua", None
    rise = time.perf_counter()
    while GPIO.input(ECHO) == 1:
        if time.perf_counter() - rise > timeout:
            return "ei_laskua", None
    kesto = time.perf_counter() - rise
    return "ok", kesto * SPEED / 2.0


def vaihe2_yksittainen():
    print("\n[2] Yksittäinen laukaisu")
    tila, d = yksi_ping()
    if tila == "ei_nousua":
        print("    -> ECHO ei noussut lainkaan 30 ms aikana.")
        print("       Anturi ei saa virtaa, TRIG ei mene perille,")
        print("       tai ECHO-johto on irti / pinni väärä.")
        return False
    if tila == "ei_laskua":
        print("    -> ECHO nousi mutta ei laskenut. Ei kaikua:")
        print("       suuntaa anturi seinään 30-100 cm päähän.")
        return False
    print(f"    -> OK, kaiku saatu: {d*100:.1f} cm")
    return True


def vaihe3_sarja(n=20):
    print(f"\n[3] Sarja {n} mittausta")
    tulokset = []
    virheet = {"ei_nousua": 0, "ei_laskua": 0}
    for _ in range(n):
        tila, d = yksi_ping()
        if tila == "ok":
            tulokset.append(d)
        else:
            virheet[tila] += 1
        time.sleep(0.06)

    print(f"    Onnistui: {len(tulokset)}/{n}")
    print(f"    Ei nousua: {virheet['ei_nousua']}, ei laskua: {virheet['ei_laskua']}")
    if len(tulokset) >= 3:
        cm = [d * 100 for d in tulokset]
        print(f"    Min {min(cm):.1f} cm | mediaani {statistics.median(cm):.1f} cm "
              f"| max {max(cm):.1f} cm")
        hajonta = max(cm) - min(cm)
        if hajonta > 10:
            print(f"    -> Hajonta {hajonta:.1f} cm on suuri. Vino pinta tai häiriö.")
        else:
            print("    -> Vakaa lukema")


def vaihe4_jatkuva():
    print("\n[4] Jatkuva mittaus. Liikuta kättä anturin edessä. Ctrl-C lopettaa.")
    try:
        while True:
            tila, d = yksi_ping()
            print(f"    {d*100:7.1f} cm" if tila == "ok" else f"    {tila}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n    Lopetettu")


try:
    print(f"TRIG = pinni {TRIG}, ECHO = pinni {ECHO}")
    if vaihe1_lepotila() and vaihe2_yksittainen():
        vaihe3_sarja()
        vaihe4_jatkuva()
    else:
        print("\nKetju katkesi. Korjaa yllä mainittu ennen jatkoa.")
finally:
    GPIO.cleanup()

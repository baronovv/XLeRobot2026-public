#!/usr/bin/python3
import time
import Jetson.GPIO as GPIO
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)
GPIO.setup(16, GPIO.OUT, initial=GPIO.HIGH)
print("Pinni 16 = HIGH 60 s. Mittaa pinni 16 <-> pinni 6.")
time.sleep(60)
GPIO.cleanup()

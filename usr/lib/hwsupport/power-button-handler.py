#!/usr/bin/python

import evdev
import threading
import os

powerbuttondev = None

devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
for device in devices:
	if device.phys == "isa0060/serio0/input0":
		powerbuttondev = device;
	else:
		device.close()

longpresstimer = None

def longpress():
	os.system( "~/.steam/root/ubuntu12_32/steam -ifrunning steam://longpowerpress" )
	global longpresstimer
	longpresstimer = None

if powerbuttondev != None:
	for event in powerbuttondev.read_loop():
		if event.type == evdev.ecodes.EV_KEY and event.code == 116: # KEY_POWER
			if event.value == 1:
				longpresstimer = threading.Timer( 1.0, longpress )
				longpresstimer.start()
			elif event.value == 0:
				if longpresstimer != None:
					os.system( "~/.steam/root/ubuntu12_32/steam -ifrunning steam://shortpowerpress" )
					longpresstimer.cancel()
					longpresstimer = None

	powerbuttondev.close()
	exit()

print ( "power-button-handler.py: Can't find device for power button!" )

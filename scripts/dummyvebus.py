#!/usr/bin/env python3

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import argparse
import logging
import sys
import os

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
from dbusdummyservice import DbusDummyService
from logger import setup_logging

# Argument parsing
parser = argparse.ArgumentParser(description='dummy dbus service')

parser.add_argument("-n", "--name", help="the D-Bus service you want me to claim",
				type=str, default="com.victronenergy.vebus.ttyO1")
parser.add_argument("-i", "--instance", help="the device instance number",
				type=int, default=0)
parser.add_argument("-p", "--phases", help="the number of phases",
				type=int, default=1, choices=[1, 2, 3])
parser.add_argument("-a", "--inputs", help="the number of AC inputs",
				type=int, default=1, choices=[0, 1, 2])

args = parser.parse_args()

print(__file__ + " is starting up, use -h argument to see optional arguments")
logger = setup_logging(debug=True)

# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
DBusGMainLoop(set_as_default=True)

paths={
	'/Ac/ActiveIn/P': {'initial': 0},
	'/Ac/ActiveIn/ActiveInput': {'initial': 0 if args.inputs > 0 else 240},
	'/Ac/ActiveIn/Connected': {'initial': 1 if args.inputs > 0 else 0},
	'/Ac/Out/P': {'initial': 0},
	'/Ac/NumberOfPhases': {'initial': args.phases},
	'/Ac/NumberOfAcInputs': {'initial': args.inputs},
	'/Ac/Control/IgnoreAcIn1': {'initial': 0},
	'/Ac/Control/IgnoreAcIn2': {'initial': 0},
	'/Ac/State/IgnoreAcIn1': {'initial': 0},
	'/Ac/State/IgnoreAcIn2': {'initial': 0},
	'/Alarms/HighTemperature': {'initial': 0},
	'/Alarms/LowBattery': {'initial': 0},
	'/Alarms/Overload': {'initial': 0},
	'/Alarms/Ripple': {'initial': 0},
	'/Alarms/TemperatureSensor': {'initial': 0},
	'/Alarms/VoltageSensor': {'initial': 0},
	'/Alarms/GridLost': {'initial': 0},
	'/Alarms/HighDcVoltage': {'initial': 0},
	'/Alarms/HighDcCurrent': {'initial': 0},
	'/Dc/0/Voltage': {'initial': 11},
	'/Dc/0/Current': {'initial': 12},
	'/Dc/0/MaxChargeCurrent': {'initial': None},
	'/Dc/0/Temperature': {'initial': None},
	'/Energy/AcIn1ToAcOut': {'initial': 0.0},
	'/Energy/AcIn1ToInverter': {'initial': 0.0},
	'/Energy/AcOutToAcIn1': {'initial': 0.0},
	'/Energy/InverterToAcIn1': {'initial': 0.0},
	'/Energy/InverterToAcOut': {'initial': 0.0},
	'/Energy/OutToInverter': {'initial': 0.0},
	'/Devices/0/Assistants': {'initial': [0]*56},
	'/Devices/0/ExtendStatus/GridRelayReport/Code': {'initial': None},
	'/Devices/0/ExtendStatus/GridRelayReport/Count': {'initial': None},
	'/Devices/0/ExtendStatus/WaitingForRelayTest': {'initial': 0},
	'/ExtraBatteryCurrent': {'initial': 0},
	'/FirmwareFeatures/BolFrame': {'initial': None},
	'/FirmwareFeatures/BolUBatAndTBatSense': {'initial': None},
	'/Soc': {'initial': 10},
	'/State': {'initial': None},
	'/Mode': {'initial': None},
	'/VebusMainState': {'initial': None},
	'/Hub/ChargeVoltage': {'initial': None},
	'/Hub4/AssistantId': {'initial': None},
	'/Hub4/Sustain': {'initial': None},
	'/Hub4/L1/AcPowerSetpoint': {'initial': None},
	'/Hub4/DisableFeedIn': {'initial': None},
	'/Hub4/TargetPowerIsMaxFeedIn': {'initial': 0},
	'/Hub4/FixSolarOffsetTo100mV': {'initial': 0},
	'/Hub4/DoNotFeedInOvervoltage': {'initial': 0},
	'/BatteryOperationalLimits/MaxChargeVoltage': {'initial': None},
	'/BatteryOperationalLimits/MaxChargeCurrent': {'initial': None},
	'/BatteryOperationalLimits/MaxDischargeCurrent': {'initial': None},
	'/BatteryOperationalLimits/BatteryLowVoltage': {'initial': None},
	'/Ac/Control/RemoteGeneratorSelected': {'initial': 0}}

for phase in range(1, args.phases + 1):
	paths[f'/Ac/Out/L{phase}/P'] = {'initial': 0}
	paths[f'/Ac/ActiveIn/L{phase}/V'] = {'initial': 0}
	paths[f'/Ac/ActiveIn/L{phase}/I'] = {'initial': 0}
	paths[f'/Ac/ActiveIn/L{phase}/F'] = {'initial': 0}
	paths[f'/Ac/ActiveIn/L{phase}/P'] = {'initial': 0}
	paths[f'/Alarms/L{phase}/HighTemperature'] = {'initial': 0}
	paths[f'/Alarms/L{phase}/LowBattery'] = {'initial': 0}
	paths[f'/Alarms/L{phase}/Overload'] = {'initial': 0}
	paths[f'/Alarms/L{phase}/Ripple'] = {'initial': 0}

s = DbusDummyService(servicename=args.name, deviceinstance=args.instance, paths=paths,
	productname='Multi 12/3000',
	connection='CCGX-VE.Bus port')

logging.info('Connected to dbus, and switching over to GLib.MainLoop() (= event based)')
mainloop = GLib.MainLoop()
mainloop.run()

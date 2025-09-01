from gi.repository import GLib
import logging
import os
import traceback
from glob import glob
from functools import partial

# Victron packages
from ve_utils import exit_on_error

from delegates.base import SystemCalcDelegate

class RelayState(SystemCalcDelegate):
	RELAY_GLOB = '/dev/gpio/relay_*'

	def __init__(self):
		SystemCalcDelegate.__init__(self)
		self._relays = {}

	def get_input(self):
		return [
			('com.victronenergy.settings', [
				 '/Settings/Relay/Function',
				 '/Settings/Relay/1/Function',
				 '/Settings/Relay/Polarity',
				 '/Settings/Relay/1/Polarity'])] # Managed by venus-platform

	def get_settings(self):
		return [
			('/Relay/0/State', '/Settings/Relay/0/InitialState', 0, 0, 1),
			('/SwitchableOutput/0/Settings/Group', '/Settings/Relay/0/Group', "", 0, 0),
			('/SwitchableOutput/0/Settings/CustomName', '/Settings/Relay/0/CustomName', "", 0, 0),
			('/SwitchableOutput/0/Settings/ShowUIControl', '/Settings/Relay/0/ShowUIControl', 1, 0, 1),

			('/Relay/1/State', '/Settings/Relay/1/InitialState', 0, 0, 1),
			('/SwitchableOutput/1/Settings/Group', '/Settings/Relay/1/Group', "", 0, 0),
			('/SwitchableOutput/1/Settings/CustomName', '/Settings/Relay/1/CustomName', "", 0, 0),
			('/SwitchableOutput/1/Settings/ShowUIControl', '/Settings/Relay/1/ShowUIControl', 1, 0, 1),
		]

	def _relay_function(self, idx):
		return self._dbusmonitor.get_value('com.victronenergy.settings',
			('/Settings/Relay/Function' if idx == 0 else
			 f'/Settings/Relay/{idx}/Function'))

	def set_relay_function(self, valid, idx, v):
		# check that function is allowed. The relevant bit must be in the
		# valid mask
		if 0 <= v <= 5 and bool(2**v & valid):
			self._dbusmonitor.set_value('com.victronenergy.settings',
				('/Settings/Relay/Function' if idx == 0 else
				 f'/Settings/Relay/{idx}/Function'), v)
			return True
		return False

	@property
	def relay_function(self):
		return self._relay_function(0)

	def _relay_polarity(self, idx):
		# Only manual polarity is flipped here. Alarm polarity is flipped
		# in venus-platform
		if self._relay_function(idx) == 2:
			# This ensures it can only ever return 0 or 1
			return int(self._dbusmonitor.get_value('com.victronenergy.settings',
				('/Settings/Relay/Polarity' if idx == 0 else
				 f'/Settings/Relay/{idx}/Polarity')) == 1)
		return 0

	def set_sources(self, dbusmonitor, settings, dbusservice):
		SystemCalcDelegate.set_sources(self, dbusmonitor, settings, dbusservice)
		relays = sorted(glob(self.RELAY_GLOB))

		if len(relays) == 0:
			logging.info('No relays found')
			return

		self._relays.update({i: os.path.join(r, 'value') \
			for i, r in enumerate(relays) })

		GLib.idle_add(exit_on_error, self._init_relay_state)
		logging.info('Relays found: {}'.format(', '.join(self._relays.values())))

	def _init_relay_state(self):
		if self.relay_function is None:
			return True # Try again on the next idle event

		for idx, path in self._relays.items():
			with self._dbusservice as s:
				s.add_path(f'/Relay/{idx}/State', value=None, writeable=True,
					onchangecallback=partial(self._on_relay_state_changed, idx))

				# Switchable output paths
				s.add_path(f'/SwitchableOutput/{idx}/State', value=None,
					writeable=True, onchangecallback=partial(self._on_relay_state_changed, idx))

				s.add_path(f'/SwitchableOutput/{idx}/Name', f'GX internal relay {idx+1}')
				s.add_path(f'/SwitchableOutput/{idx}/Status', value=None)

				# Switchable output settings
				for setting, typ in (('Group', str), ('CustomName', str), ('ShowUIControl', bool)):
					s.add_path(p := f'/SwitchableOutput/{idx}/Settings/{setting}',
						value=self._settings[p], writeable=True,
						onchangecallback=partial(self._on_relay_setting_changed, idx, typ))

				s.add_path(f'/SwitchableOutput/{idx}/Settings/Type',
					value=1, writeable=True, onchangecallback=(lambda p, v: v == 1)) # R/W, but only accepts toggle
				s.add_path(f'/SwitchableOutput/{idx}/Settings/ValidTypes',
					value=2) # Toggle

				# All functions for first relay, Manual and temperature for the rest
				functions = 0b111111 if idx == 0 else 0b10100
				s.add_path(f'/SwitchableOutput/{idx}/Settings/Function',
					value=self._relay_function(idx), writeable=True,
					onchangecallback=lambda p, v, f=functions, idx=idx: self.set_relay_function(f, idx, int(v)))
				s.add_path(f'/SwitchableOutput/{idx}/Settings/ValidFunctions',
					value=functions)

			# If relay is manual, restore previous state. Otherwise the
			# controlling service will set it correctly once it comes up.
			if (f := self._relay_function(idx)) == 2:
				try:
					state = self._settings[f'/Relay/{idx}/State']
				except KeyError:
					pass
				else:
					self._set_relay_dbus_state(idx, state) # set dbus
					self.__on_relay_state_changed(idx, state) # set hardware
			elif f < 0:
				# relay is disabled, switch it off
				self._disable_relay(idx)
				self.__on_relay_state_changed(idx, 0)
			else:
				self.__update_relay_state(idx, path)

		# Watch changes and update dbus. Do we still need this?
		GLib.timeout_add(5000, exit_on_error, self._update_relay_state)
		return False

	def _update_relay_state(self):
		""" Maintenance tasked called periodically to make sure everything
		    remains in sync. """
		for idx, file_path in self._relays.items():
			if self._relay_function(idx) < 0: # disabled
				self._disable_relay(idx)
			else:
				self.__update_relay_state(idx, file_path)

			# Make sure updates to relay function in settings is reflected here
			self._dbusservice[f'/SwitchableOutput/{idx}/Settings/Function'] = self._relay_function(idx)

		return True

	def __update_relay_state(self, idx, file_path):
		""" Sync back the actual state of the relay to dbus. """
		try:
			with open(file_path, 'rt') as r:
				state = int(r.read().strip())
		except (IOError, ValueError):
			traceback.print_exc()
		else:
			# Flip state if polarity is NC and function is manual
			state = state ^ self._relay_polarity(idx)
			self._set_relay_dbus_state(idx, state)

	def _set_relay_dbus_state(self, idx, state):
		self._dbusservice[f'/Relay/{idx}/State'] = state
		self._dbusservice[f'/SwitchableOutput/{idx}/State'] = state
		self._dbusservice[f'/SwitchableOutput/{idx}/Status'] = 0x09 if state else 0x00

	def _disable_relay(self, idx):
		self._dbusservice[f'/Relay/{idx}/State'] = None
		self._dbusservice[f'/SwitchableOutput/{idx}/State'] = None
		self._dbusservice[f'/SwitchableOutput/{idx}/Status'] = 0x20

	def __on_relay_state_changed(self, idx, state):
		try:
			# Flip state if polarity is NC and function is manual
			state = state ^ self._relay_polarity(idx)
			path = self._relays[idx]
			with open(path, 'wt') as w:
				w.write(str(state))
		except IOError:
			traceback.print_exc()
			return False
		return True

	def _on_relay_state_changed(self, idx, dbus_path, value):
		""" This is called when a write is done from dbus. """
		if self._relay_function(idx) < 0:
			return False # No writes to disabled relays

		try:
			state = int(bool(value))
		except ValueError:
			traceback.print_exc()
			return False

		self._set_relay_dbus_state(idx, state)
		try:
			return self.__on_relay_state_changed(idx, state)
		finally:
			# Remember the state to restore after a restart
			self._settings[f'/Relay/{idx}/State'] = state

	def _on_relay_setting_changed(self, idx, _type, dbus_path, value):
		try:
			self._settings[dbus_path] = _type(value)
		except (KeyError, ValueError):
			return False
		return True

import fcntl
from gi.repository import GLib
import logging
import os
import sc_utils
import traceback

# Victron packages
from ve_utils import exit_on_error

from delegates.base import SystemCalcDelegate

class BuzzerControl(SystemCalcDelegate):
	CLOCK_TICK_RATE = 1193180
	KIOCSOUND = 0x4B2F
	TTY_PATH = '/dev/tty0'
	GPIO_BUZZER_PATH = '/dev/gpio/buzzer'
	PWM_BUZZER_PATH = '/etc/venus/pwm_buzzer'

	def __init__(self):
		SystemCalcDelegate.__init__(self)
		self._buzzer_on = False
		self._timer = None
		self._gpio_path = None
		self._pwm_frequency = None

	def set_paths(self):
		# Find GPIO buzzer
		gpio_path = os.path.join(self.GPIO_BUZZER_PATH, "value")
		if os.path.exists(gpio_path):
			self._gpio_path = gpio_path
			logging.info(f'GPIO buzzer found: {self._gpio_path}')

		# Find PWM buzzer
		self._pwm_frequency = None
		pwm_frequency = sc_utils.gpio_paths(BuzzerControl.PWM_BUZZER_PATH)
		try:
			self._pwm_frequency = int(pwm_frequency[0])
		except IndexError:
			pass
		except ValueError:
			logging.error('Parsing of PWM buzzer settings at %s failed', BuzzerControl.PWM_BUZZER_PATH)
		else:
			logging.info('PWM buzzer found @ frequency: {}'.format(self._pwm_frequency))

		return not (self._gpio_path is None and self._pwm_frequency is None)

	def set_sources(self, dbusmonitor, settings, dbusservice):
		SystemCalcDelegate.set_sources(self, dbusmonitor, settings, dbusservice)
		if not self.set_paths():
			logging.info('No buzzer found')
			return

		self._dbusservice.add_path('/Buzzer/State', value=0, writeable=True,
			onchangecallback=lambda p, v: exit_on_error(self._on_buzzer_state_changed, v))
		# Reset the buzzer so the buzzer state equals the D-Bus value. It will also silence the buzzer after
		# a restart of the service/system.
		self.set_buzzer(False)

	def _on_buzzer_state_changed(self, value):
		try:
			value = 1 if int(value) == 1 else 0
			if value == 1:
				if self._timer is None:
					self._timer = GLib.timeout_add(500, exit_on_error, self._on_timer)
					self.set_buzzer(True)
			elif self._timer is not None:
				GLib.source_remove(self._timer)
				self._timer = None
				self.set_buzzer(False)
			self._dbusservice['/Buzzer/State'] = value
		except (TypeError, ValueError):
			logging.error('Incorrect value received on /Buzzer/State: %s', value)
		return False

	def _on_timer(self):
		self.set_buzzer(not self._buzzer_on)
		return True

	def set_buzzer(self, on):
		self._set_gpio_buzzer(on)
		self._set_pwm_buzzer(on)
		self._buzzer_on = on

	def _set_gpio_buzzer(self, on):
		if self._gpio_path is None:
			return
		try:
			with open(self._gpio_path, 'wt') as w:
				w.write('1' if on else '0')
		except (IOError, OSError):
			traceback.print_exc()

	def _set_pwm_buzzer(self, on):
		if self._pwm_frequency is None:
			return
		console_fd = None
		interval = BuzzerControl.CLOCK_TICK_RATE // self._pwm_frequency if on else 0
		try:
			# The return value of os.open does not have an __exit__ function, so we cannot use 'with' here.
			console_fd = os.open(BuzzerControl.TTY_PATH, os.O_RDONLY | os.O_NOCTTY)
			fcntl.ioctl(console_fd, BuzzerControl.KIOCSOUND, interval)
		except (IOError, OSError):
			traceback.print_exc()
		finally:
			try:
				if console_fd is not None:
					os.close(console_fd)
			except:
				traceback.print_exc()

from gi.repository import GLib
from dbus.exceptions import DBusException
from delegates.base import SystemCalcDelegate

class Battery(object):
	def __init__(self, monitor, service, instance):
		self.monitor = monitor
		self.service = service
		self.instance = instance

	@property
	def is_bms(self):
		return self.monitor.get_value(self.service,
			'/Info/MaxChargeVoltage') is not None

	@property
	def device_instance(self):
		""" Returns the DeviceInstance of this device. """
		return self.monitor.get_value(self.service, '/DeviceInstance')

	@property
	def maxchargecurrent(self):
		""" Returns maxumum charge current published by the BMS. """
		return self.monitor.get_value(self.service, '/Info/MaxChargeCurrent')

	@property
	def chargevoltage(self):
		""" Returns charge voltage published by the BMS. """
		return self.monitor.get_value(self.service, '/Info/MaxChargeVoltage')

	@property
	def batterylowvoltage(self):
		""" Returns battery low voltage published by the BMS. """
		return self.monitor.get_value(self.service, '/Info/BatteryLowVoltage')

	@property
	def maxdischargecurrent(self):
		""" Returns max discharge current published by the BMS. """
		return self.monitor.get_value(self.service, '/Info/MaxDischargeCurrent')

	@property
	def voltage(self):
		""" Returns current voltage of battery. """
		return self.monitor.get_value(self.service, '/Dc/0/Voltage')

	@property
	def current(self):
		""" Returns charge/discharge current. """
		return self.monitor.get_value(self.service, '/Dc/0/Current')

	@property
	def temperature(self):
		""" Returns battery temperature. """
		return self.monitor.get_value(self.service, '/Dc/0/Temperature')

	@property
	def soc(self):
		""" Returns battery SOC. """
		return self.monitor.get_value(self.service, '/Soc')

	@property
	def product_id(self):
		""" Returns Product ID of battery. """
		return self.monitor.get_value(self.service, '/ProductId')

	@property
	def name(self):
		return self.monitor.get_value(self.service, '/CustomName') or \
			self.monitor.get_value(self.service, '/ProductName')

	@property
	def capacity(self):
		""" Capacity of battery, if defined. """
		return self.monitor.get_value(self.service, '/InstalledCapacity')

	@property
	def mincellvoltage(self):
		return self.monitor.get_value(self.service, '/System/MinCellVoltage')

	@property
	def maxcellvoltage(self):
		return self.monitor.get_value(self.service, '/System/MaxCellVoltage')

class BatteryService(SystemCalcDelegate):
	""" Keeps track of the (auto-)selected bms service. """
	BMSSERVICE_DEFAULT = -1
	BMSSERVICE_NOBMS = -255

	def __init__(self, sc):
		super(BatteryService, self).__init__()
		self.systemcalc = sc
		self._batteries = {}
		self.bms = None
		self._notify = []

	def set_sources(self, dbusmonitor, settings, dbusservice):
		super(BatteryService, self).set_sources(dbusmonitor, settings, dbusservice)
		self._dbusservice.add_path('/ActiveBmsService', value=None)
		self._dbusservice.add_path('/ActiveBmsInstance', value=None)
		self._dbusservice.add_path('/AvailableBmsServices', value=None)

	def get_input(self):
		return [
			('com.victronenergy.battery', [
				'/DeviceInstance',
				'/Info/MaxChargeVoltage',
				'/Info/BatteryLowVoltage',
				'/Info/MaxChargeCurrent',
				'/Info/MaxDischargeCurrent',
				'/Dc/0/Voltage',
				'/Dc/0/Current',
				'/Dc/0/Temperature',
				'/ProductId',
				'/ProductName',
				'/CustomName',
				'/InstalledCapacity',
				'/Soc',
				'/System/MinCellVoltage',
				'/System/MaxCellVoltage']),
		]

	def get_settings(self):
		return [
			('bmsinstance', '/Settings/SystemSetup/BmsInstance', BatteryService.BMSSERVICE_DEFAULT, 0, 0)
		]

	def device_added(self, service, instance, *args):
		if service.startswith('com.victronenergy.battery.'):
			self._batteries[instance] = Battery(self._dbusmonitor, service, instance)
			self._dbusmonitor.track_value(service, "/Info/MaxChargeVoltage", self._set_bms)
			self._dbusmonitor.track_value(service, "/CustomName", self._set_bms)
			# If you call _set_bms directly now, changes to MaxChargeVoltage
			# that is still in the pipeline will not reflect yet. Instead
			# schedule it for as soon as everything settles.
			GLib.idle_add(self._set_bms)

	def device_removed(self, service, instance):
		if service.startswith('com.victronenergy.battery.') and instance in self._batteries:
			del self._batteries[instance]
			self._set_bms()

	def battery_service_changed(self, auto, oldservice, newservice):
		self._set_bms()

	def settings_changed(self, setting, oldvalue, newvalue):
		if setting == 'bmsinstance':
			self._set_bms()

	@property
	def selected_bms_instance(self):
		return self._settings['bmsinstance']

	@property
	def batteries(self):
		return self._batteries.values()

	@property
	def bmses(self):
		return [b for b in self._batteries.values() if b.is_bms]

	@property
	def batteryservice(self):
		if self.systemcalc.batteryservice is not None and \
				self.systemcalc.batteryservice.startswith('com.victronenergy.battery.'):
			return Battery(self._dbusmonitor, self.systemcalc.batteryservice, -1)

		return None

	def add_bms_changed_callback(self, cb):
		self._notify.append(cb)

	def __set_bms(self, service, instance):
		self._dbusservice['/ActiveBmsService'] = service
		self._dbusservice['/ActiveBmsInstance'] = instance
		for cb in self._notify:
			cb(service)

	def _set_bms(self, *args, **kwargs):
		bmses = self.bmses
		if bmses:
			self._dbusservice['/AvailableBmsServices'] = [
				{
					'name': b.name,
					'instance': b.device_instance
				} for b in bmses if isinstance(b.name, str) and isinstance(b.device_instance, int)
			]
		else:
			self._dbusservice['/AvailableBmsServices'] = None

		# Disabled
		if self.selected_bms_instance == BatteryService.BMSSERVICE_NOBMS:
			self.bms = None
			self.__set_bms(None, None)
			return


		# Explicit selection
		if self.selected_bms_instance != BatteryService.BMSSERVICE_DEFAULT:
			try:
				b = self._batteries[int(self.selected_bms_instance)]
			except (ValueError, KeyError):
				self.bms = None
				self.__set_bms(None, None)
			else:
				if b.is_bms:
					self.bms = b
					self.__set_bms(b.service, b.device_instance)
				else:
					self.bms = None
					self.__set_bms(None, None)
			return

		# Automatic selection. Try the main battery service first, hence
		# hardcoded instance = -1
		b = self.batteryservice
		if b is not None and b.is_bms:
			bmses.append(b)

		if bmses:
			# Prefer Lynx parallel BMS services over individual Lynx BMSes. Such that when 2 or more 
			# Lynx smart BMSes are present and combined into a Lynx parallel BMS, the parallel one gets autoselected.
			self.bms = sorted([b for b in bmses if b.service.startswith('com.victronenergy.battery.lynxparallel')] or bmses,
					 key=lambda x: x.instance)[0]
			self.__set_bms(self.bms.service, self.bms.device_instance)
		else:
			self.bms = None
			self.__set_bms(None, None)

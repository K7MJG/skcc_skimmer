from __future__ import annotations

import sys
import getopt

from typing      import Any, Literal, NoReturn, get_args, TypedDict

from Lib.cCommon import cCommon

class cConfig:
	class cProgressDots:
		ENABLED:         bool
		DISPLAY_SECONDS: int
		DOTS_PER_LINE:   int
	PROGRESS_DOTS = cProgressDots()

	class cLogFile:
		FILE_NAME:         str
		ENABLED:           bool
		LOG_FILE:          str
		DELETE_ON_STARTUP: bool
	LOG_FILE = cLogFile()

	class cHighWpm:
		tAction = Literal['suppress', 'warn', 'always-display']
		ACTION: tAction
		THRESHOLD: int
	HIGH_WPM = cHighWpm

	class cOffFrequency:
		ACTION:    Literal['suppress', 'warn']
		TOLERANCE: int
	OFF_FREQUENCY = cOffFrequency()

	class cSked:
		ENABLED:       bool
		CHECK_SECONDS: int
	SKED = cSked

	class cNotification:
		ENABLED:                      bool
		CONDITION:                    list[str]   # list[Literal['goals', 'targets', 'friends']]
		RENOTIFICATION_DELAY_SECONDS: int
	NOTIFICATION = cNotification


	MY_CALLSIGN:              str
	ADI_FILE:                 str
	MY_GRIDSQUARE:            str
	GOALS:                    list[str]
	TARGETS:                  list[str]
	BANDS:                    list[int]
	FRIENDS:                  list[str]
	EXCLUSIONS:               list[str]
	DISTANCE_UNITS:           str
	SPOT_PERSISTENCE_MINUTES: int
	VERBOSE:                  bool
	LOG_BAD_SPOTS:            bool
	SPOTTER_RADIUS:           int

	configFile: dict[str, Any]

	class TypedConfig(TypedDict):
		HIGH_WPM: 'cConfig.cHighWpm'


	configFile2: TypedConfig

	def __init__(self, ArgV: list[str]):
		def ReadSkccSkimmerCfg() -> dict[str, Any]:
			try:
				with open('skcc_skimmer.cfg', 'r', encoding='utf-8') as File:
					ConfigFileString = File.read()
					exec(ConfigFileString)
			except IOError:
				print("Unable to open configuration file 'skcc_skimmer.cfg'.")
				sys.exit()

			return locals()

		self.configFile = ReadSkccSkimmerCfg()

		if 'MY_CALLSIGN' in self.configFile:
			self.MY_CALLSIGN = self.configFile['MY_CALLSIGN']

		if 'ADI_FILE' in self.configFile:
			self.ADI_FILE = self.configFile['ADI_FILE']

		if 'MY_GRIDSQUARE' in self.configFile:
			self.MY_GRIDSQUARE = self.configFile['MY_GRIDSQUARE']

		if 'SPOTTER_RADIUS' in self.configFile:
			self.SPOTTER_RADIUS = int(self.configFile['SPOTTER_RADIUS'])

		if 'GOALS' in self.configFile:
			self.GOALS = self.Parse(self.configFile['GOALS'], 'C CXN T TXN S SXN WAS WAS-C WAS-T WAS-S P BRAG K3Y', 'goal')

		if 'TARGETS' in self.configFile:
			self.TARGETS = self.Parse(self.configFile['TARGETS'], 'C CXN T TXN S SXN', 'target')

		if 'BANDS' in self.configFile:
			self.BANDS = [int(Band)  for Band in cCommon.Split(self.configFile['BANDS'])]

		if 'FRIENDS' in self.configFile:
			self.FRIENDS = [friend  for friend in cCommon.Split(self.configFile['FRIENDS'])]

		if 'EXCLUSIONS' in self.configFile:
			self.EXCLUSIONS = [friend  for friend in cCommon.Split(self.configFile['EXCLUSIONS'])]

		if 'LOG_FILE' in self.configFile:
			logFile = self.configFile['LOG_FILE']

			if 'ENABLED' in logFile:
				self.LOG_FILE.ENABLED = bool(logFile['ENABLED'])

			if 'FILE_NAME' in logFile:
				self.LOG_FILE.FILE_NAME = logFile['FILE_NAME']

			if 'DELETE_ON_STARTUP' in logFile:
				self.LOG_FILE.DELETE_ON_STARTUP = logFile['DELETE_ON_STARTUP']


		if 'PROGRESS_DOTS' in self.configFile:
			progressDots = self.configFile['PROGRESS_DOTS']

			if 'ENABLED' in progressDots:
				self.PROGRESS_DOTS.ENABLED = bool(progressDots['ENABLED'])

			if 'DISPLAY_SECONDS' in progressDots:
				self.PROGRESS_DOTS.DISPLAY_SECONDS = progressDots['DISPLAY_SECONDS']

			if 'DOTS_PER_LINE' in progressDots:
				self.PROGRESS_DOTS.DOTS_PER_LINE = progressDots['DOTS_PER_LINE']

		if 'SKED' in self.configFile:
			sked = self.configFile['SKED']

			if 'ENABLED' in sked:
				self.SKED.ENABLED = bool(sked['ENABLED'])

			if 'CHECK_SECONDS' in sked:
				self.SKED.CHECK_SECONDS = int(sked['CHECK_SECONDS'])

		if 'OFF_FREQUENCY' in self.configFile:
			offFrequency = self.configFile['OFF_FREQUENCY']

			if 'ACTION' in offFrequency:
				self.OFF_FREQUENCY.ACTION = offFrequency['ACTION']

			if 'TOLERANCE' in offFrequency:
				self.OFF_FREQUENCY.TOLERANCE = int(offFrequency['TOLERANCE'])

		if 'HIGH_WPM' in self.configFile:
			highWpm = self.configFile['HIGH_WPM']

			if 'ACTION' in highWpm:
				action: cConfig.cHighWpm.tAction = highWpm['ACTION']

				if action not in get_args(cConfig.cHighWpm.tAction):
					print(f"Must be one of {get_args(cConfig.cHighWpm.tAction)}.")

				self.HIGH_WPM.ACTION = action

			if 'THRESHOLD' in highWpm:
				self.HIGH_WPM.THRESHOLD = int(highWpm['THRESHOLD'])

		if 'NOTIFICATION' in self.configFile:
			notification = self.configFile['NOTIFICATION']

			if 'ENABLED' in notification:
				self.NOTIFICATION.ENABLED = bool(notification['ENABLED'])

			if 'CONDITION' in notification:
				conditions = cCommon.Split(notification['CONDITION'])

				for condition in conditions:
					if condition not in ['goals', 'targets', 'friends']:
						print(f"NOTIFICATION CONDITION '{condition}' must be 'goals' and/or 'targets' and/or 'friends'")
						sys.exit()

				self.NOTIFICATION.CONDITION = conditions

			if 'THRESHOLD' in notification:
				self.NOTIFICATION.RENOTIFICATION_DELAY_SECONDS = int(notification['RENOTIFICATION_DELAY_SECONDS'])
			else:
				self.NOTIFICATION.RENOTIFICATION_DELAY_SECONDS = 30

		if 'VERBOSE' in self.configFile:
			self.VERBOSE = bool(self.configFile['VERBOSE'])
		else:
			self.VERBOSE = False

		if 'LOG_BAD_SPOTS' in self.configFile:
			self.LOG_BAD_SPOTS = bool(self.configFile['LOG_BAD_SPOTS'])
		else:
			self.LOG_BAD_SPOTS = False

		if 'DISTANCE_UNITS' in self.configFile and self.configFile['DISTANCE_UNITS'] in ('mi', 'km'):
			self.DISTANCE_UNITS = self.configFile['DISTANCE_UNITS']
		else:
			self.DISTANCE_UNITS = 'mi'

		self._ParseArgs(ArgV)

		self._ValidateConfig()

	def _ParseArgs(self, ArgV: list[str]):
		try:
			Options, _ = getopt.getopt(ArgV, \
					'a:   b:     B:           c:        d:              g:     h    i           l:       m:          n:            r:      s:    t:       v'.replace(' ', ''), \
					'adi= bands= brag-months= callsign= distance-units= goals= help interactive logfile= maidenhead= notification= radius= sked= targets= verbose'.split())
		except getopt.GetoptError as e:
			print(e)
			self.Usage()

		self.INTERACTIVE = False

		for Option, Arg in Options:
			if Option ==  '-a' or Option == '--adi':
					self.ADI_FILE = Arg

			elif Option == '-b' or Option == '--bands':
					self.BANDS = [int(Band)  for Band in cCommon.Split(Arg)]

			elif Option == '-B' or Option == '--brag-months':
					self.BRAG_MONTHS = int(Arg)

			elif Option == '-c'  or Option == '--callsign':
					self.MY_CALLSIGN = Arg.upper()

			elif Option == '-d' or Option == '--distance-units':
					argLower = Arg.lower()

					if argLower not in ('mi', 'km'):
						print("DISTANCE_UNITS option must be either 'mi' or 'km'.")
						sys.exit()

					self.DISTANCE_UNITS = argLower

			elif Option == '-g' or Option == '--goals':
					self.GOALS = self.Parse(Arg, 'C CXN T TXN S SXN WAS WAS-C WAS-T WAS-S P BRAG K3Y', 'goal')

			elif Option == '-h' or Option == '--help':
					self.Usage()

			elif Option == '-i' or Option == '--interactive':
					self.INTERACTIVE = True

			elif Option == '-l' or Option == '--logfile':
					self.LOG_FILE.ENABLED           = True
					self.LOG_FILE.DELETE_ON_STARTUP = True
					self.LOG_FILE.FILE_NAME         = Arg

			elif Option == '-m' or Option == '--maidenhead':
					self.MY_GRIDSQUARE = Arg

			elif Option == '-n' or Option == '--notification':
					Arg = Arg.lower()

					if Arg not in ('on', 'off'):
						print("Notificiation option must be either 'on' or 'off'.")
						sys.exit()

					self.NOTIFICATION.ENABLED = Arg == 'on'

			elif Option == '-r' or Option == '--radius':
					self.SPOTTER_RADIUS = int(Arg)

			elif Option == '-s' or Option == '--sked':
					Arg = Arg.lower()

					if Arg not in ('on', 'off'):
						print("SKED option must be either 'on' or 'off'.")
						sys.exit()

					self.SKED.ENABLED = Arg == 'on'

			elif Option == '-t' or Option == '--targets':
					self.TARGETS = self.Parse(Arg, 'C CXN T TXN S SXN', 'target')

			elif Option == '-v' or Option == '--verbose':
					self.VERBOSE = True

			else:
					self.Usage()


	def _ValidateConfig(self):
		#
		# MY_CALLSIGN can be defined in skcc_skimmer.cfg.  It is not required
		# that it be supplied on the command line.
		#
		if not self.MY_CALLSIGN:
			print("You must specify your callsign, either on the command line or in 'skcc_skimmer.cfg'.")
			print('')
			self.Usage()

		if not self.ADI_FILE:
			print("You must supply an ADI file, either on the command line or in 'skcc_skimmer.cfg'.")
			print('')
			self.Usage()

		if not self.GOALS and not self.TARGETS:
			print('You must specify at least one goal or target.')
			sys.exit()

		if not self.MY_GRIDSQUARE:
			print("'MY_GRIDSQUARE' in skcc_skimmer.cfg must be a 4 or 6 character maidenhead grid value.")
			sys.exit()

		if 'SPOTTER_RADIUS' not in self.configFile:
			print("'SPOTTER_RADIUS' must be defined in skcc_skimmer.cfg.")
			sys.exit()

		if 'QUALIFIERS' in self.configFile:
			print("'QUALIFIERS' is no longer supported and can be removed from 'skcc_skimmer.cfg'.")
			sys.exit()

		if 'NEARBY' in self.configFile:
			print("'NEARBY' has been replaced with 'SPOTTERS_NEARBY'.")
			sys.exit()

		if 'SPOTTER_PREFIXES' in self.configFile:
			print("'SPOTTER_PREFIXES' has been deprecated.")
			sys.exit()

		if 'SPOTTERS_NEARBY' in self.configFile:
			print("'SPOTTERS_NEARBY' has been deprecated.")
			sys.exit()

		if 'SKCC_FREQUENCIES' in self.configFile:
			print("'SKCC_FREQUENCIES' is now caluclated internally.  Remove it from 'skcc_skimmer.cfg'.")
			sys.exit()

		if 'HITS_FILE' in self.configFile:
			print("'HITS_FILE' is no longer supported.")
			sys.exit()

		if 'HitCriteria' in self.configFile:
			print("'HitCriteria' is no longer supported.")
			sys.exit()

		if 'StatusCriteria' in self.configFile:
			print("'StatusCriteria' is no longer supported.")
			sys.exit()

		if 'SkedCriteria' in self.configFile:
			print("'SkedCriteria' is no longer supported.")
			sys.exit()

		if 'SkedStatusCriteria' in self.configFile:
			print("'SkedStatusCriteria' is no longer supported.")
			sys.exit()

		if 'SERVER' in self.configFile:
			print('SERVER is no longer supported.')
			sys.exit()

		if 'SPOT_PERSISTENCE_MINUTES' not in self.configFile:
			self.SPOT_PERSISTENCE_MINUTES = 15

		if 'GOAL' in self.configFile:
			print("'GOAL' has been replaced with 'GOALS' and has a different syntax and meaning.")
			sys.exit()

		if 'GOALS' not in self.configFile:
			print("GOALS must be defined in 'skcc_skimmer.cfg'.")
			sys.exit()

		if 'TARGETS' not in self.configFile:
			print("TARGETS must be defined in 'skcc_skimmer.cfg'.")
			sys.exit()

		if 'HIGH_WPM' not in self.configFile:
			print("HIGH_WPM must be defined in 'skcc_skimmer.cfg'.")
			sys.exit()

		if self.HIGH_WPM.ACTION not in ('suppress', 'warn', 'always-display'):
			print("HIGH_WPM['ACTION'] must be one of ('suppress', 'warn', 'always-display')")
			sys.exit()

		if 'OFF_FREQUENCY' not in self.configFile:
			print("OFF_FREQUENCY must be defined in 'skcc_skimmer.cfg'.")
			sys.exit()

		if self.OFF_FREQUENCY.ACTION not in ('suppress', 'warn'):
			print("OFF_FREQUENCY['ACTION'] must be one of ('suppress', 'warn')")
			sys.exit()

		if 'NOTIFICATION' not in self.configFile:
			print("'NOTIFICATION' must be defined in skcc_skimmer.cfg.")
			sys.exit()

	def Usage(self) -> NoReturn:
		print('Usage:')
		print('')
		print('   skcc_skimmer.py')
		print('                   [--adi <adi-file>]')
		print('                   [--bands <comma-separated-bands>]')
		print('                   [--brag-months <number-of-months-back>]')
		print('                   [--callsign <your-callsign>]')
		print('                   [--goals <goals>]')
		print('                   [--help]')
		print('                   [--interactive]')
		print('                   [--logfile <logfile-name>]')
		print('                   [--maidenhead <grid-square>]')
		print('                   [--notification <on|off>]')
		print('                   [--radius <distance-in-miles>]')
		print('                   [--targets <targets>]')
		print('                   [--verbose]')
		print(' or...')
		print('')
		print('   skcc_skimmer.py')
		print('                   [-a <adi-file>]')
		print('                   [-b <comma-separated-bands>]')
		print('                   [-c <your-callsign>]')
		print('                   [-g <goals>]')
		print('                   [-h]')
		print('                   [-i]')
		print('                   [-l <logfile-name>]')
		print('                   [-m <grid-square>]')
		print('                   [-n <on|off>]')
		print('                   [-r <distance-in-miles>]')
		print('                   [-t <targets>]')
		print('                   [-v]')
		print('')
		sys.exit()

	def Parse(self, String: str, ALL_str: str, Type: str) -> list[str]:
		ALL  = ALL_str.split()
		List = cCommon.Split(String.upper())

		for x in List:
			if x == 'ALL':
				return ALL

			if x == 'NONE':
				return []

			if x == 'CXN' and 'C' not in List:
				List.append('C')

			if x == 'TXN' and 'T' not in List:
				List.append('T')

			if x == 'SXN' and 'S' not in List:
				List.append('S')

			if x not in ALL:
				print(f"Unrecognized {Type} '{x}'.")
				sys.exit()

		return List

#!/usr/bin/python3
'''

	 The MIT License (MIT)

	 Copyright (c) 2015-2022 Mark J Glenn

	 Permission is hereby granted, free of charge, to any person obtaining a copy
	 of this software and associated documentation files (the "Software"), to deal
	 in the Software without restriction, including without limitation the rights
	 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	 copies of the Software, and to permit persons to whom the Software is
	 furnished to do so, subject to the following conditions:

	 The above copyright notice and this permission notice shall be included in all
	 copies or substantial portions of the Software.

	 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
	 SOFTWARE.

	 Mark Glenn, 2015
	 mglenn@cox.net

'''
#
# skcc_skimmer.py
#
# A program that uses the Reverse Beacon Network (RBN)
# to locate unique, unworked SKCC members for the purpose of
# attaining SKCC award levels.
#

#
# Contact: mark@k7mjg.com
#
# Code and bug fix contributions by Jim - NM1W, Mark - NX1K, and Marty - N9SE.
#
# WAS-T and WAS-C changes contributed by Nick, KC0MYW.

#

#
# Quickstart:
#
#  1. Make sure that you have Python installed.
#
#  2. Prepare an ADI logfile with stations worked thus far.
#
#  3. Run this utility from the command line with Python.
#
#     python skcc_skimmer.py [-c your-call-sign] [-a AdiFile] [-g "GoalString"] [-t "TargetString"] [-v]
#
#       The callsign is required unless you've specified MY_CALLSIGN in the skcc_skimmer.cfg file.
#
#       The ADI file is required unless you've specified ADI_FILE in the skcc_skimmer.cfg file.
#
#       GoalString: Any or all of: C,T,S,CXN,TXN,SXN,WAS,WAS-C,WAS-T,WAS-S,ALL,K3Y,NONE.
#
#       TargetString: Any or all of: C,T,S,CXN,TXN,SXN,ALL,NONE.
#
#         (You must specify at least one GOAL or TARGET.)
#

#
# Portability:
#
#   Requires Python version 3.8.10 or better. Also requires the following imports
#   which may require a pip install.
#

from __future__ import annotations

from datetime import timedelta
from datetime import datetime

from typing        import Any, NoReturn, Literal

from math          import radians, sin, cos, atan2, sqrt

from Lib.cSocketLoop   import cSocketLoop
from Lib.cStateMachine import cStateMachine
from Lib.cRBN          import cRBN_Client
from Lib.cConfig       import cConfig
from Lib.cCommon       import cCommon

import signal
import time
import sys
import os
import re
import string
import textwrap
import calendar
import json
import requests

def Split(spaceSeparatedString: str) -> list[str | Any]:
  return re.split('[, ][ ]*', spaceSeparatedString.strip())

def Effective(Date: str) -> str:
	TodayGMT = time.strftime('%Y%m%d000000', time.gmtime())

	if TodayGMT >= Date:
		return Date

	return ''

def Miles2Km(Miles: int) -> int:
	return int((Miles * 1.609344) + .5)

def Stripped(text: str) -> str:
	return ''.join([c for c in text if 31 < ord(c) < 127])

class cFastDateTime:
	FastDateTime: str

	MonthNames = 'January February March April May June July August September October November December'.split()

	def __init__(self, Object: datetime | time.struct_time | tuple[int, int, int] | tuple[int, int, int, int, int, int] | str | None) -> None:
		if isinstance(Object, datetime):
			self.FastDateTime = Object.strftime('%Y%m%d%H%M%S')

		elif isinstance(Object, time.struct_time):
			self.FastDateTime = time.strftime('%Y%m%d%H%M%S', Object)

		elif isinstance(Object, tuple):
			if len(Object) == 3:
				Year, Month, Day = Object
				self.FastDateTime = f'{Year:0>4}{Month:0>2}{Day:0>2}000000'
			elif len(Object) == 6:
				Year, Month, Day, Hour, Minute, Second = Object
				self.FastDateTime = f'{Year:0>4}{Month:0>2}{Day:0>2}{Hour:0>2}{Minute:0>2}{Second:0>2}'.format(Year, Month, Day, Hour, Minute, Second)

		elif isinstance(Object, str):
			self.FastDateTime = Object

		else:
			self.FastDateTime = ''

	def SplitDateTime(self) -> list[int]:
		List: list[int] = []
		String = self.FastDateTime

		for Width in (4, 2, 2, 2, 2, 2):
			List.append(int(String[:Width]))
			String = String[Width:]

		return List

	def StartOfMonth(self) -> cFastDateTime:
		Year, Month, _Day, _Hour, _Minute, _Second = self.SplitDateTime()
		return cFastDateTime(f'{Year:0>4}{Month:0>2}{1:0>2}000000')

	def EndOfMonth(self) -> cFastDateTime:
		Year, Month, _Day, _Hour, _Minute, _Second = self.SplitDateTime()
		_, DaysInMonth = calendar.monthrange(Year, Month)
		return cFastDateTime(f'{Year:0>4}{Month:0>2}{DaysInMonth:0>2}235959')

	def Year(self) -> int:
		return int(self.FastDateTime[0:4])

	def Month(self) -> int:
		return int(self.FastDateTime[4:6])

	def ToDateTime(self) -> datetime:
		return datetime.strptime(self.FastDateTime, '%Y%m%d%H%M%S')

	def FirstWeekdayFromDate(self, TargetWeekday: str) -> cFastDateTime:
		TargetWeekdayNumber = time.strptime(TargetWeekday, '%a').tm_wday
		DateTime = self.ToDateTime()

		while DateTime.weekday() != TargetWeekdayNumber:
			DateTime += timedelta(days=1)

		return cFastDateTime(DateTime)


	def FirstWeekdayAfterDate(self, TargetWeekday: str) -> cFastDateTime:
		TargetWeekdayNumber = time.strptime(TargetWeekday, '%a').tm_wday
		DateTime = self.ToDateTime()

		while True:
			DateTime += timedelta(days=1)

			if DateTime.weekday() == TargetWeekdayNumber:
				return cFastDateTime(DateTime)

	def __repr__(self) -> str:
		return self.FastDateTime

	def __lt__(self, Right: cFastDateTime) -> bool:
		return self.FastDateTime < Right.FastDateTime

	def __le__(self, Right: cFastDateTime) -> bool:
		return self.FastDateTime <= Right.FastDateTime

	def __gt__(self, Right: cFastDateTime) -> bool:
		return self.FastDateTime > Right.FastDateTime

	def __add__(self, Delta: timedelta) -> cFastDateTime:
		return cFastDateTime(self.ToDateTime() + Delta)

	@staticmethod
	def NowGMT() -> cFastDateTime:
		return cFastDateTime(time.gmtime())


class cDisplay(cStateMachine):
	def __init__(self):
		cStateMachine.__init__(self, self.STATE_Running, Debug = False)
		self.DotsOutput = 0
		self.Run()

	def STATE_Running(self):
		def ENTER():
			if config.PROGRESS_DOTS.ENABLED:
				self.TimeoutInSeconds(config.PROGRESS_DOTS.DISPLAY_SECONDS)

		def PRINT(text: str):
			if self.DotsOutput > 0:
				print('')

			text = Stripped(text)
			print(text)
			self.DotsOutput = 0

			if config.PROGRESS_DOTS.ENABLED:
				self.TimeoutInSeconds(config.PROGRESS_DOTS.DISPLAY_SECONDS)

		def TIMEOUT():
			sys.stdout.write('.')
			sys.stdout.flush()
			self.DotsOutput += 1

			if self.DotsOutput > config.PROGRESS_DOTS.DOTS_PER_LINE:
				print('')
				self.DotsOutput = 0

			if config.PROGRESS_DOTS.ENABLED:
				self.TimeoutInSeconds(config.PROGRESS_DOTS.DISPLAY_SECONDS)

		_ = ENTER, PRINT, TIMEOUT # Forced reference for type checking.
		return locals()

	def Print(self, text: str = ''):
		self.SendEventArg('PRINT', text)

def Beep() -> None:
	sys.stdout.write('\a')
	sys.stdout.flush()

class cSked(cStateMachine):
	RegEx = re.compile('<span class="callsign">(.*?)<span>(?:.*?<span class="userstatus">(.*?)</span>)?')

	def __init__(self):
		cStateMachine.__init__(self, self.STATE_Running, Debug = False)
		self.SkedSite = None
		self.PreviousLogins = {}
		self.FirstPass = True

	def STATE_Running(self):
		def Common():
			self.DisplayLogins()
			self.TimeoutInSeconds(config.SKED.CHECK_SECONDS)

		def ENTER():
			Common()

		def TIMEOUT():
			Common()

		_ = ENTER, TIMEOUT
		return locals()

	def HandleLogins(self, SkedLogins: list[tuple[str, str]], Heading: str):
		SkedHit: dict[str, list[str]] = {}
		GoalList: list[str] = []
		TargetList: list[str] = []

		for CallSign, Status in SkedLogins:
			if CallSign == config.MY_CALLSIGN:
				continue

			CallSign = SKCC.ExtractCallSign(CallSign)

			if not CallSign:
				continue

			if CallSign in config.EXCLUSIONS:
				continue

			Report: list[str] = [BuildMemberInfo(CallSign)]

			if CallSign in RBN.LastSpotted:
				fFrequency, StartTime = RBN.LastSpotted[CallSign]

				Now = time.time()
				DeltaSeconds = max(int(Now - StartTime), 1)

				if DeltaSeconds > config.SPOT_PERSISTENCE_MINUTES * 60:
					del RBN.LastSpotted[CallSign]
				elif DeltaSeconds > 60:
					DeltaMinutes = DeltaSeconds // 60
					Units = 'minutes' if DeltaMinutes > 1 else 'minute'
					Report.append(f'Last spotted {DeltaMinutes} {Units} ago on {fFrequency}')
				else:
					Units = 'seconds' if DeltaSeconds > 1 else 'second'
					Report.append(f'Last spotted {DeltaSeconds} {Units} ago on {fFrequency}')

			GoalList = []

			if 'K3Y' in config.GOALS:
				K3Y_Freq_RegEx = r'.*?K3Y[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)(?:.*?\b(\d+(?:\.\d+)?))?'
				Matches = re.match(K3Y_Freq_RegEx, Status, re.IGNORECASE)

				if Matches:
					CallSignSuffix = Matches.group(1)
					CallSignSuffix = CallSignSuffix.upper()
					Freq = 0.0

					if Matches.group(2):
						FreqString = Matches.group(2)

						# Group 1 examples: 7.055.5 14.055.5
						# Group 2 examples: 7.055   14.055
						# Group 3 examples: 7055.5  14055.5
						# Group 4 examples: 7055    14055
						Freq_RegEx = r"(\d{1,2}\.\d{3}\.\d{1})|(\d{1,2}\.\d{3})|(\d+\.\d{1})|(\d{4,5})"
						FreqMatches = re.match(Freq_RegEx, FreqString)

						if FreqMatches:
							if FreqMatches.group(1):
								FreqString = FreqString.replace('.', '', 1)
								Freq = float(FreqString) * 1000
							if FreqMatches.group(2):
								Freq = float(FreqString) * 1000
							elif FreqMatches.group(3) or FreqMatches.group(4):
								Freq = float(FreqString)

							Band = cSKCC.WhichBand(Freq)

							if Band:
								if (not CallSignSuffix in QSOs.ContactsForK3Y) or (not Band in QSOs.ContactsForK3Y[CallSignSuffix]):
									GoalList.append(f'K3Y/{CallSignSuffix} ({Band}m)')
					else:
						GoalList.append(f'K3Y/{CallSignSuffix}')

			GoalList = GoalList + QSOs.GetGoalHits(CallSign)

			if GoalList:
				Report.append(f'YOU need them for {",".join(GoalList)}')

			TargetList = QSOs.GetTargetHits(CallSign)

			if TargetList:
				Report.append(f'THEY need you for {",".join(TargetList)}')

			IsFriend = CallSign in config.FRIENDS

			if IsFriend:
				Report.append('friend')

			if Status:
				Report.append(f'STATUS: {Stripped(Status)}')

			if TargetList or GoalList or IsFriend:
				SkedHit[CallSign] = Report

		if SkedHit:
			GMT = time.gmtime()
			ZuluTime = time.strftime('%H%MZ', GMT)
			ZuluDate = time.strftime('%Y-%m-%d', GMT)

			if self.FirstPass:
				NewLogins = []
			else:
				NewLogins = list(set(SkedHit)-set(self.PreviousLogins))

			Display.Print('=========== '+Heading+' Sked Page '+'=' * (16-len(Heading)))

			for CallSign in sorted(SkedHit):
				if CallSign in NewLogins:
					if config.NOTIFICATION.ENABLED:
						if (CallSign in config.FRIENDS and 'friends' in config.NOTIFICATION.CONDITION) or (GoalList and 'goals' in config.NOTIFICATION.CONDITION) or (TargetList and 'targets' in config.NOTIFICATION.CONDITION):
							Beep()

					NewIndicator = '+'
				else:
					NewIndicator = ' '

				Out = f'{ZuluTime}{NewIndicator}{CallSign:<6} {"; ".join(SkedHit[CallSign])}'
				Display.Print(Out)
				Log(f'{ZuluDate} {Out}')

		return SkedHit

	def DisplayLogins(self) -> None:
		try:
			response = requests.get('http://sked.skccgroup.com/get-status.php')

			if response.status_code != 200:
				return

			Content = response.text
			Hits = {}

			if Content:
				try:
					SkedLogins: list[tuple[str, str]] = json.loads(Content)
					Hits = self.HandleLogins(SkedLogins, 'SKCC')
				except Exception as ex:
					with open('DEBUG.txt', 'a', encoding='utf-8') as File:
						File.write(Content + '\n')

					print(f"*** Problem parsing data sent from the SKCC Sked Page: '{Content}'.  Details: '{ex}'.")

			self.PreviousLogins = Hits
			self.FirstPass = False

			if Hits:
				Display.Print('=======================================')
		except:
			print(f"\nProblem retrieving information from the Sked Page.  Skipping...")

class cRBN_Filter(cRBN_Client):
	LastSpotted: dict[str, tuple[float, float]]
	Notified: dict[str, float]

	Zulu_RegEx = re.compile(r'^([01]?[0-9]|2[0-3])[0-5][0-9]Z$')
	dB_RegEx   = re.compile(r'^\s{0,1}\d{1,2} dB$')

	def __init__(self, SocketLoop: cSocketLoop, CallSign: str, Clusters: str):
		cRBN_Client.__init__(self, SocketLoop, CallSign, Clusters)
		self.Data = ''
		self.LastSpotted = {}
		self.Notified = {}
		self.RenotificationDelay = config.NOTIFICATION.RENOTIFICATION_DELAY_SECONDS

	def RawData(self, Data: str):
		self.Data += Data

		while '\r\n' in self.Data:
			Line, self.Data = self.Data.split('\r\n', 1)
			self.HandleSpot(Line)

	@staticmethod
	def ParseSpot(Line: str) -> None | tuple[str, str, float, str, str, int, int]:
		# If the line isn't exactly 75 characters, something is wrong.
		if len(Line) != 75:
			LogError(Line)
			return None

		if not Line.startswith('DX de '):
			LogError(Line)
			return None

		Spotter, Frequency = Line[6:24].split('-#:')

		Frequency = float(Frequency.lstrip())
		CallSign  = Line[26:35].rstrip()
		dB        = int(Line[47:49].strip())
		Zulu      = Line[70:75]
		CW        = Line[41:47].rstrip()
		Beacon    = Line[62:68].rstrip()

		if CW != 'CW':
			return None

		if Beacon == 'BEACON':
			return None

		if not cRBN_Filter.Zulu_RegEx.match(Zulu):
			LogError(Line)
			return None

		if not cRBN_Filter.dB_RegEx.match(Line[47:52]):
			LogError(Line)
			return None

		try:
			WPM = int(Line[53:56])
		except ValueError:
			LogError(Line)
			return None

		try:
			fFrequency = float(Frequency)
		except ValueError:
			LogError(Line)
			return None

		CallSignSuffix = ''

		if '/' in CallSign:
			CallSign, CallSignSuffix = CallSign.split('/', 1)
			CallSignSuffix = CallSignSuffix.upper()

		return Zulu, Spotter, fFrequency, CallSign, CallSignSuffix, dB, WPM

	def HandleNotification(self, CallSign: str, GoalList: list[str], TargetList: list[str]) -> Literal['+', ' ']:
		NotificationFlag = ' '

		Now = time.time()

		for Call in dict(self.Notified):
			if Now > self.Notified[Call]:
				del self.Notified[Call]

		if CallSign not in self.Notified:
			if config.NOTIFICATION.ENABLED:
				if (CallSign in config.FRIENDS and 'friends' in config.NOTIFICATION.CONDITION) or (GoalList and 'goals' in config.NOTIFICATION.CONDITION) or (TargetList and 'targets' in config.NOTIFICATION.CONDITION):
					Beep()

			NotificationFlag = '+'
			self.Notified[CallSign] = Now + self.RenotificationDelay

		return NotificationFlag

	def HandleSpot(self, Line: str) -> None:
		if config.VERBOSE:
			print(f'   {Line}')

		Spot = cRBN_Filter.ParseSpot(Line)

		if not Spot:
			return

		Zulu, Spotter, fFrequency, CallSign, CallSignSuffix, dB, WPM = Spot

		Report: list[str] = []

		#-------------

		CallSign = SKCC.ExtractCallSign(CallSign)

		if not CallSign:
			return

		if CallSign in config.EXCLUSIONS:
			return

		#-------------

		if not IsInBANDS(fFrequency):
			return

		#-------------

		SpottedNearby = Spotter in SPOTTERS_NEARBY

		if SpottedNearby or CallSign == config.MY_CALLSIGN:
			if Spotter in Spotters.Spotters:
				Miles = Spotters.GetDistance(Spotter)

				MilesDisplay      = f'{Miles}mi'
				KilometersDisplay = f'{Miles2Km(Miles)}km'
				Distance          = MilesDisplay if config.DISTANCE_UNITS == 'mi' else KilometersDisplay

				Report.append(f'by {Spotter}({Distance}, {int(dB)}dB)')
			else:
				Report.append(f'by {Spotter}({int(dB)}dB)')

		#-------------

		You = CallSign == config.MY_CALLSIGN

		if You:
			Report.append('(you)')

		#-------------

		OnFrequency = cSKCC.IsOnSkccFrequency(fFrequency, config.OFF_FREQUENCY.TOLERANCE)

		if not OnFrequency:
			if config.OFF_FREQUENCY.ACTION == 'warn':
				Report.append('OFF SKCC FREQUENCY!')
			elif config.OFF_FREQUENCY.ACTION == 'suppress':
				return

		#-------------

		if config.HIGH_WPM.ACTION == 'always-display':
			Report.append(f'{WPM} WPM')
		else:
			if WPM >= config.HIGH_WPM.THRESHOLD:
				if config.HIGH_WPM.ACTION == 'warn':
					Report.append(f'{WPM} WPM!')
				elif config.HIGH_WPM.ACTION == 'suppress':
					return

		#-------------

		IsFriend = CallSign in config.FRIENDS

		if IsFriend:
			Report.append('friend')

		#-------------

		GoalList = []

		if 'K3Y' in config.GOALS and CallSign == 'K3Y':
			if (CallSignSuffix != ''):
				Band = cSKCC.WhichArrlBand(fFrequency)

				if (not CallSignSuffix in QSOs.ContactsForK3Y) or (not Band in QSOs.ContactsForK3Y[CallSignSuffix]):
					GoalList = [f'K3Y/{CallSignSuffix} ({Band}m)']

		GoalList = GoalList + QSOs.GetGoalHits(CallSign, fFrequency)

		if GoalList:
			Report.append(f'YOU need them for {",".join(GoalList)}')

		#-------------

		TargetList = QSOs.GetTargetHits(CallSign)

		if TargetList:
			Report.append(f'THEY need you for {",".join(TargetList)}')

		#-------------

		if (SpottedNearby and (GoalList or TargetList)) or You or IsFriend:
			RBN.LastSpotted[CallSign] = (fFrequency, time.time())

			ZuluDate = time.strftime('%Y-%m-%d', time.gmtime())

			FrequencyString = f'{fFrequency:.1f}'

			'''
			Now = time.time()

			for Call in dict(self.Notified):
				if Now > self.Notified[Call]:
					del self.Notified[Call]

			if CallSign not in self.Notified:
				if NOTIFICATION['ENABLED']:
					if (CallSign in FRIENDS and 'friends' in BeepCondition) or (GoalList and 'goals' in BeepCondition) or (TargetList and 'targets' in BeepCondition):
						Beep()

				NotificationFlag = '+'
				self.Notified[CallSign] = Now + self.RenotificationDelay
			'''

			if CallSign == 'K3Y':
				NotificationFlag = self.HandleNotification(f'K3Y/{CallSignSuffix}', GoalList, TargetList)
				Out = f'{Zulu}{NotificationFlag}K3Y/{CallSignSuffix} on {FrequencyString:>8} {"; ".join(Report)}'
			else:
				MemberInfo = BuildMemberInfo(CallSign)
				NotificationFlag = self.HandleNotification(CallSign, GoalList, TargetList)
				Out = f'{Zulu}{NotificationFlag}{CallSign:<6} {MemberInfo} on {FrequencyString:>8} {"; ".join(Report)}'

			Display.Print(Out)
			Log(f'{ZuluDate} {Out}')

class cQSO(cStateMachine):
	MyMemberNumber: str

	ContactsForC:     dict[str, tuple[str, str, str]]
	ContactsForT:     dict[str, tuple[str, str, str]]
	ContactsForS:     dict[str, tuple[str, str, str]]

	ContactsForWAS:   dict[str, tuple[str, str, str]]
	ContactsForWAS_C: dict[str, tuple[str, str, str]]
	ContactsForWAS_T: dict[str, tuple[str, str, str]]
	ContactsForWAS_S: dict[str, tuple[str, str, str]]
	ContactsForP:     dict[str, tuple[str, str, int, str]]
	ContactsForK3Y:   Any  # Resolve this type

	Brag: dict[str, tuple[str, str, str, float]]


	QSOsByMemberNumber: dict[str, list[str]]

	QSOs: list[tuple[str, str, str, float, str]]

	Prefix_RegEx = re.compile(r'(?:.*/)?([0-9]*[a-zA-Z]+\d+)')

	def __init__(self):
		cStateMachine.__init__(self, self.STATE_Running, Debug = False)
		self.QSOs = []

		self.Brag               = {}
		self.ContactsForC       = {}
		self.ContactsForT       = {}
		self.ContactsForS       = {}
		self.ContactsForWAS     = {}
		self.ContactsForWAS_C   = {}
		self.ContactsForWAS_T   = {}
		self.ContactsForWAS_S   = {}
		self.ContactsForP       = {}
		self.ContactsForK3Y     = []
		self.QSOsByMemberNumber = {}

		self.ReadQSOs()

		self.RefreshPeriodSeconds = 3

		MyMemberEntry       = SKCC.Members[config.MY_CALLSIGN]
		self.MyJoin_Date    = Effective(MyMemberEntry['join_date'])
		self.MyC_Date       = Effective(MyMemberEntry['c_date'])
		self.MyT_Date       = Effective(MyMemberEntry['t_date'])
		self.MyS_Date       = Effective(MyMemberEntry['s_date'])
		self.MyTX8_Date     = Effective(MyMemberEntry['tx8_date'])

		self.MyMemberNumber = MyMemberEntry['plain_number']

	def STATE_Running(self) -> dict[str, Any]:
		def ENTER():
			self.TimeoutInSeconds(self.RefreshPeriodSeconds)

		def TIMEOUT():
			if os.path.getmtime(config.ADI_FILE) != self.AdiFileReadTimeStamp:
				Display.Print(f"'{config.ADI_FILE}' file is changing. Waiting for write to finish...")

				# Once we detect the file has changed, we can't necessarily read it
				# immediately because the logger may still be writing to it, so we wait
				# until the write is complete.
				while True:
					Size = os.path.getsize(config.ADI_FILE)
					time.sleep(1)

					if os.path.getsize(config.ADI_FILE) == Size:
						break

				QSOs.Refresh()

			self.TimeoutInSeconds(self.RefreshPeriodSeconds)

		_ = ENTER, TIMEOUT
		return locals()

	def AwardsCheck(self) -> None:
		C_Level = len(self.ContactsForC)  // Levels['C']
		T_Level = len(self.ContactsForT)  // Levels['T']
		S_Level = len(self.ContactsForS)  // Levels['S']
		P_Level = self.CalcPrefixPoints() // Levels['P']

		### C ###

		if self.MyC_Date:
			Award_C_Level = SKCC.CenturionLevel[self.MyMemberNumber]

			while (C_Level > 10) and (C_Level % 5):
				C_Level -= 1

			if C_Level > Award_C_Level:
				C_or_Cx = 'C' if Award_C_Level == 1 else f'Cx{Award_C_Level}'
				print(f'FYI: You qualify for Cx{C_Level} but have only applied for {C_or_Cx}.')
		else:
			if C_Level == 1 and self.MyMemberNumber not in SKCC.CenturionLevel:
				print('FYI: You qualify for C but have not yet applied for it.')

		### T ###

		if self.MyT_Date:
			Award_T_Level = SKCC.TribuneLevel[self.MyMemberNumber]

			while (T_Level > 10) and (T_Level % 5):
				T_Level -= 1

			if T_Level > Award_T_Level:
				T_or_Tx = 'T' if Award_T_Level == 1 else f'Tx{Award_T_Level}'
				print(f'FYI: You qualify for Tx{T_Level} but have only applied for {T_or_Tx}.')
		else:
			if T_Level == 1 and self.MyMemberNumber not in SKCC.TribuneLevel:
				print('FYI: You qualify for T but have not yet applied for it.')

		### S ###

		if self.MyS_Date:
			Award_S_Level = SKCC.SenatorLevel[self.MyMemberNumber]

			if S_Level > Award_S_Level:
				S_or_Sx = 'S' if Award_S_Level == 1 else f'Sx{Award_S_Level}'
				print(f'FYI: You qualify for Sx{S_Level} but have only applied for {S_or_Sx}.')
		else:
			if S_Level == 1 and self.MyMemberNumber not in SKCC.SenatorLevel:
				print('FYI: You qualify for S but have not yet applied for it.')

		### WAS and WAS-C and WAS-T and WAS-S ###

		if 'WAS' in config.GOALS:
			if len(self.ContactsForWAS) == len(US_STATES) and config.MY_CALLSIGN not in SKCC.WasLevel:
				print('FYI: You qualify for WAS but have not yet applied for it.')

		if 'WAS-C' in config.GOALS:
			if len(self.ContactsForWAS_C) == len(US_STATES) and config.MY_CALLSIGN not in SKCC.WasCLevel:
				print('FYI: You qualify for WAS-C but have not yet applied for it.')

		if 'WAS-T' in config.GOALS:
			if len(self.ContactsForWAS_T) == len(US_STATES) and config.MY_CALLSIGN not in SKCC.WasTLevel:
				print('FYI: You qualify for WAS-T but have not yet applied for it.')

		if 'WAS-S' in config.GOALS:
			if len(self.ContactsForWAS_S) == len(US_STATES) and config.MY_CALLSIGN not in SKCC.WasSLevel:
				print('FYI: You qualify for WAS-S but have not yet applied for it.')

		if 'P' in config.GOALS:
			if config.MY_CALLSIGN in SKCC.PrefixLevel:
				Award_P_Level = SKCC.PrefixLevel[config.MY_CALLSIGN]

				if P_Level > Award_P_Level:
					print(f'FYI: You qualify for Px{P_Level} but have only applied for Px{Award_P_Level}')
			elif P_Level >= 1:
				print(f'FYI: You qualify for Px{P_Level} but have not yet applied for it.')

	@staticmethod
	def CalculateNumerics(Class: str, Total: int) -> tuple[int, int]:
		Increment = Levels[Class]
		SinceLastAchievement = Total % Increment

		Remaining = Increment - SinceLastAchievement

		X_Factor = (Total + Increment) // Increment

		return Remaining, X_Factor

	def ReadQSOs(self) -> None:
		Display.Print(f'Reading QSOs from {config.ADI_FILE}...')

		self.QSOs = []

		self.AdiFileReadTimeStamp = os.path.getmtime(config.ADI_FILE)

		with open(config.ADI_FILE, 'rb') as File:
			Contents = File.read().decode('utf-8', 'ignore')

		_Header, Body = re.split(r'<eoh>', Contents, 0, re.I|re.M)

		Body = Body.strip(' \t\r\n\x1a')  # Include CNTL-Z

		RecordTextList = re.split(r'<eor>', Body, 0, re.I|re.M)

		Adi_RegEx = re.compile(r'<(\w+?):\d+(?::.*?)*>(.*?)\s*(?=<(?:\w+?):\d+(?::.*?)*>|$)', re.I | re.M | re.S)

		for RecordText in RecordTextList:
			RecordText = RecordText.strip()

			if not RecordText:
				continue

			AdiFileMatches = Adi_RegEx.findall(RecordText)

			Record: dict[str, str] = {}

			for Key, Value in AdiFileMatches:
				Record[Key.upper()] = Value

			#
			# ADIF allows for QSO_DATE_OFF without QSO_DATE & TIME_OFF without TIME_ON.
			#
			# The Skimmer really doesn't care, so lets normalize and convert QSO_DATE_OFF to QSO_DATE
			# and TIME_OFF to TIME_ON.
			#
			if ('QSO_DATE' not in Record) and ('QSO_DATE_OFF' in Record):
				Record['QSO_DATE'] = Record['QSO_DATE_OFF']
				del Record['QSO_DATE_OFF']

			if ('TIME_ON' not in Record) and ('TIME_OFF' in Record):
				Record['TIME_ON'] = Record['TIME_OFF']
				del Record['TIME_OFF']

			if not all(x in Record for x in ('CALL', 'QSO_DATE', 'TIME_ON')):
				print('Warning: ADI record must have CALL, QSO_DATE, and TIME_ON fields. Skipping:')
				print(RecordText)
				continue

			if 'MODE' in Record and Record['MODE'] != 'CW':
				continue

			fFrequency = 0.0

			if 'FREQ' in Record:
				try:
					fFrequency = float(Record['FREQ']) * 1000   # kHz
				except ValueError:
					pass

			QsoCallSign = Record['CALL']
			QsoDate     = Record['QSO_DATE']+Record['TIME_ON']
			QsoSPC      = Record['STATE'] if 'STATE' in Record else ''
			QsoFreq     = fFrequency
			QsoComment  = Record['COMMENT'] if 'COMMENT' in Record else ''

			self.QSOs.append((QsoDate, QsoCallSign, QsoSPC, QsoFreq, QsoComment))

		self.QSOs = sorted(self.QSOs, key=lambda QsoTuple: QsoTuple[0])

		for QsoDate, CallSign, _SPC, _Freq, _Comment in self.QSOs:
			CallSign = SKCC.ExtractCallSign(CallSign)

			if not CallSign or CallSign == 'K3Y':
				continue

			MemberNumber = SKCC.Members[CallSign]['plain_number']

			if MemberNumber not in self.QSOsByMemberNumber:
				self.QSOsByMemberNumber[MemberNumber] = [QsoDate]
			else:
				self.QSOsByMemberNumber[MemberNumber].append(QsoDate)

	def CalcPrefixPoints(self) -> int:
		iPoints = 0

		for _, Value in self.ContactsForP.items():
			_, _, iMemberNumber, _FirstName = Value
			iPoints += iMemberNumber

		return iPoints

	def PrintProgress(self) -> None:
		def PrintRemaining(Class: str, Total: int):
			Remaining, X_Factor = cQSO.CalculateNumerics(Class, Total)

			if Class in config.GOALS:
				Abbrev = AbbreviateClass(Class, X_Factor)
				print(f'Total worked towards {Class}: {Total:,}, only need {Remaining:,} more for {Abbrev}.')

		print('')

		if config.GOALS:
			print(f'GOAL{"S" if len(config.GOALS) > 1 else ""}: {", ".join(config.GOALS)}')

		if config.TARGETS:
			print(f'TARGET{"S" if len(config.TARGETS) > 1 else ""}: {", ".join(config.TARGETS)}')

		print(f'BANDS: {", ".join(str(Band)  for Band in config.BANDS)}')

		print('')

		PrintRemaining('C', len(self.ContactsForC))

		if QSOs.MyC_Date:
			PrintRemaining('T', len(self.ContactsForT))

		if QSOs.MyTX8_Date:
			PrintRemaining('S', len(self.ContactsForS))

		PrintRemaining('P', self.CalcPrefixPoints())

		def RemainingStates(Class: str, QSOs: dict[str, tuple[str, str, str]]) -> None:
			if len(QSOs) == len(US_STATES):
				Need = 'none needed'
			else:
				RemainingStates = [State  for State in US_STATES  if State not in QSOs]

				if len(RemainingStates) > 14:
					Need = f'only need {len(RemainingStates)} more'
				else:
					Need = f'only need {",".join(RemainingStates)}'

			print(f'Total worked towards {Class}: {len(QSOs)}, {Need}.')

		if 'WAS' in config.GOALS:
			RemainingStates('WAS', self.ContactsForWAS)

		if 'WAS-C' in config.GOALS:
			RemainingStates('WAS-C', self.ContactsForWAS_C)

		if 'WAS-T' in config.GOALS:
			RemainingStates('WAS-T', self.ContactsForWAS_T)

		if 'WAS-S' in config.GOALS:
			RemainingStates('WAS-S', self.ContactsForWAS_S)

		if 'BRAG' in config.GOALS:
			NowGMT = cFastDateTime.NowGMT()
			MonthIndex = NowGMT.Month()-1
			MonthName = cFastDateTime.MonthNames[MonthIndex]
			print(f'Total worked towards {MonthName} Brag: {len(self.Brag)}')

	def GetGoalHits(self, TheirCallSign: str, fFrequency: float | None = None) -> list[str]:
		if TheirCallSign not in SKCC.Members:
			return []

		if TheirCallSign == config.MY_CALLSIGN:
			return []

		TheirMemberEntry  = SKCC.Members[TheirCallSign]
		TheirC_Date       = Effective(TheirMemberEntry['c_date'])
		TheirT_Date       = Effective(TheirMemberEntry['t_date'])
		TheirS_Date       = Effective(TheirMemberEntry['s_date'])
		TheirMemberNumber = TheirMemberEntry['plain_number']

		List: list[str] = []

		if 'BRAG' in config.GOALS:
			if TheirMemberNumber not in self.Brag:
				NowGMT       = cFastDateTime.NowGMT()
				DuringSprint = cSKCC.DuringSprint(NowGMT)

				if fFrequency:
					OnWarcFreq = cSKCC.IsOnWarcFrequency(fFrequency)
					BragOkay   = OnWarcFreq or (not DuringSprint)
				else:
					BragOkay = not DuringSprint

				if BragOkay:
					List.append('BRAG')

		if 'C' in config.GOALS and not self.MyC_Date:
			if TheirMemberNumber not in self.ContactsForC:
				List.append('C')

		if 'CXN' in config.GOALS and self.MyC_Date:
			if TheirMemberNumber not in self.ContactsForC:
				_, X_Factor = cQSO.CalculateNumerics('C', len(self.ContactsForC))
				List.append(AbbreviateClass('C', X_Factor))

		if 'T' in config.GOALS and self.MyC_Date and not self.MyT_Date:
			if TheirC_Date and TheirMemberNumber not in self.ContactsForT:
				List.append('T')

		if 'TXN' in config.GOALS and self.MyT_Date:
			if TheirC_Date and TheirMemberNumber not in self.ContactsForT:
				_Remaining, X_Factor = cQSO.CalculateNumerics('T', len(self.ContactsForT))
				List.append(AbbreviateClass('T', X_Factor))

		if 'S' in config.GOALS and self.MyTX8_Date and not self.MyS_Date:
			if TheirT_Date and TheirMemberNumber not in self.ContactsForS:
				List.append('S')

		if 'SXN' in config.GOALS and self.MyS_Date:
			if TheirT_Date and TheirMemberNumber not in self.ContactsForS:
				_Remaining, X_Factor = cQSO.CalculateNumerics('S', len(self.ContactsForS))
				List.append(AbbreviateClass('S', X_Factor))

		if 'WAS' in config.GOALS:
			SPC = TheirMemberEntry['spc']
			if SPC in US_STATES and SPC not in self.ContactsForWAS:
				List.append('WAS')

		if 'WAS-C' in config.GOALS:
			if TheirC_Date:
				SPC = TheirMemberEntry['spc']
				if SPC in US_STATES and SPC not in self.ContactsForWAS_C:
					List.append('WAS-C')

		if 'WAS-T' in config.GOALS:
			if TheirT_Date:
				SPC = TheirMemberEntry['spc']
				if SPC in US_STATES and SPC not in self.ContactsForWAS_T:
					List.append('WAS-T')

		if 'WAS-S' in config.GOALS:
			if TheirS_Date:
				SPC = TheirMemberEntry['spc']
				if SPC in US_STATES and SPC not in self.ContactsForWAS_S:
					List.append('WAS-S')

		if 'P' in config.GOALS:
			Match = cQSO.Prefix_RegEx.match(TheirCallSign)

			if Match:
				Prefix = Match.group(1)
				iTheirMemberNumber   = int(TheirMemberNumber)
				_Remaining, X_Factor = cQSO.CalculateNumerics('P', self.CalcPrefixPoints())

				if Prefix in self.ContactsForP:
					iCurrentMemberNumber = self.ContactsForP[Prefix][2]

					if iTheirMemberNumber > iCurrentMemberNumber:
						List.append(f'{AbbreviateClass("P", X_Factor)}(+{iTheirMemberNumber - iCurrentMemberNumber})')
				else:
					List.append(f'{AbbreviateClass("P", X_Factor)}(new +{iTheirMemberNumber})')

		return List

	def GetTargetHits(self, TheirCallSign: str) -> list[str]:
		if TheirCallSign not in SKCC.Members:
			return []

		if TheirCallSign == config.MY_CALLSIGN:
			return []

		TheirMemberEntry  = SKCC.Members[TheirCallSign]
		TheirJoin_Date    = Effective(TheirMemberEntry['join_date'])
		TheirC_Date       = Effective(TheirMemberEntry['c_date'])
		TheirT_Date       = Effective(TheirMemberEntry['t_date'])
		TheirTX8_Date     = Effective(TheirMemberEntry['tx8_date'])
		TheirS_Date       = Effective(TheirMemberEntry['s_date'])
		TheirMemberNumber = TheirMemberEntry['plain_number']

		List: list[str] = []

		if 'C' in config.TARGETS and not TheirC_Date:
			if TheirMemberNumber in self.QSOsByMemberNumber:
				for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
					if QsoDate > TheirJoin_Date and QsoDate > self.MyJoin_Date:
						break
				else:
					List.append('C')
			else:
				List.append('C')

		if 'CXN' in config.TARGETS and TheirC_Date:
			NextLevel = SKCC.CenturionLevel[TheirMemberNumber]+1

			if NextLevel <= 10:
				if TheirMemberNumber in self.QSOsByMemberNumber:
					for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
						if QsoDate > TheirJoin_Date and QsoDate > self.MyJoin_Date:
							break
					else:
						List.append(f'Cx{NextLevel}')
				else:
					List.append(f'Cx{NextLevel}')

		if 'T' in config.TARGETS and TheirC_Date and not TheirT_Date and self.MyC_Date:
			if TheirMemberNumber in self.QSOsByMemberNumber:
				for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
					if QsoDate > TheirC_Date and QsoDate > self.MyC_Date:
						break
				else:
					List.append('T')
			else:
				List.append('T')

		if 'TXN' in config.TARGETS and TheirT_Date and self.MyC_Date:
			NextLevel = SKCC.TribuneLevel[TheirMemberNumber]+1

			if NextLevel <= 10:
				if TheirMemberNumber in self.QSOsByMemberNumber:
					for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
						if QsoDate > TheirC_Date and QsoDate > self.MyC_Date:
							break
					else:
						List.append(f'Tx{NextLevel}')
				else:
					List.append(f'Tx{NextLevel}')

		if 'S' in config.TARGETS and TheirTX8_Date and not TheirS_Date and self.MyT_Date:
			if TheirMemberNumber in self.QSOsByMemberNumber:
				for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
					if QsoDate > TheirTX8_Date and QsoDate > self.MyT_Date:
						break
				else:
					List.append('S')
			else:
				List.append('S')

		if 'SXN' in config.TARGETS and TheirS_Date and self.MyT_Date:
			NextLevel = SKCC.SenatorLevel[TheirMemberNumber]+1

			if NextLevel <= 10:
				if TheirMemberNumber in self.QSOsByMemberNumber:
					for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
						if QsoDate > TheirTX8_Date and QsoDate > self.MyT_Date:
							break
					else:
						List.append(f'Sx{NextLevel}')
				else:
					List.append(f'Sx{NextLevel}')

		return List

	def Refresh(self) -> None:
		self.ReadQSOs()
		QSOs.GetGoalQSOs()
		self.PrintProgress()

	def GetBragQSOs(self, PrevMonth: int = 0, Print: bool = False) -> None:
		self.Brag = {}

		DateOfInterestGMT = cFastDateTime.NowGMT()

		if PrevMonth > 0:
			Year, Month, Day, _Hour, _Minute, _Second = DateOfInterestGMT.SplitDateTime()

			YearsBack  = int(PrevMonth  / 12)
			MonthsBack = PrevMonth % 12

			Year  -= YearsBack
			Month -= MonthsBack

			if Month <= 0:
				Year  -= 1
				Month += 12

			DateOfInterestGMT = cFastDateTime((Year, Month, Day))

		fastStartOfMonth = DateOfInterestGMT.StartOfMonth()
		fastEndOfMonth   = DateOfInterestGMT.EndOfMonth()

		for Contact in self.QSOs:
			QsoDate, QsoCallSign, _QsoSPC, QsoFreq, _QsoComment = Contact

			if QsoCallSign in ('K9SKC'):
				continue

			QsoCallSign = SKCC.ExtractCallSign(QsoCallSign)

			if not QsoCallSign or QsoCallSign == 'K3Y':
				continue

			MainCallSign = SKCC.Members[QsoCallSign]['main_call']

			TheirMemberEntry  = SKCC.Members[MainCallSign]
			TheirMemberNumber = TheirMemberEntry['plain_number']

			fastQsoDate = cFastDateTime(QsoDate)

			if fastStartOfMonth < fastQsoDate < fastEndOfMonth:
				TheirJoin_Date = Effective(TheirMemberEntry['join_date'])

				if TheirJoin_Date and TheirJoin_Date < QsoDate:
					DuringSprint = cSKCC.DuringSprint(fastQsoDate)

					if not QsoFreq:
						continue

					OnWarcFreq   = cSKCC.IsOnWarcFrequency(QsoFreq)

					BragOkay = OnWarcFreq or (not DuringSprint)

					#print(BragOkay, DuringSprint, OnWarcFreq, QsoFreq, QsoDate)

					if TheirMemberNumber not in self.Brag and BragOkay:
						self.Brag[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign, QsoFreq)
						#print('Brag contact: {} on {} {}'.format(QsoCallSign, QsoDate, QsoFreq))
					else:
						#print('Not brag eligible: {} on {}  {}  warc: {}  sprint: {}'.format(QsoCallSign, QsoDate, QsoFreq, OnWarcFreq, DuringSprint))
						pass

		if Print and 'BRAG' in config.GOALS:
			Year = DateOfInterestGMT.Year()
			MonthIndex = DateOfInterestGMT.Month()-1
			MonthAbbrev = cFastDateTime.MonthNames[MonthIndex][:3]
			print(f'Total Brag contacts in {MonthAbbrev} {Year}: {len(self.Brag)}')

	def GetGoalQSOs(self) -> None:
		def Good(QsoDate: str, MemberDate: str, MyDate: str, EligibleDate: str | None = None):
			if MemberDate == '' or MyDate == '':
				return False

			if EligibleDate and QsoDate < EligibleDate:
				return False

			return QsoDate >= MemberDate and QsoDate >= MyDate

		self.ContactsForC     = {}
		self.ContactsForT     = {}
		self.ContactsForS     = {}

		self.ContactsForWAS   = {}
		self.ContactsForWAS_C = {}
		self.ContactsForWAS_T = {}
		self.ContactsForWAS_S = {}
		self.ContactsForP     = {}
		self.ContactsForK3Y   = {}

		#TodayGMT = cFastDateTime.NowGMT()
		#fastStartOfMonth = TodayGMT.StartOfMonth()
		#fastEndOfMonth   = TodayGMT.EndOfMonth()

		if 'BRAG_MONTHS' in globals() and 'BRAG' in config.GOALS:
			for PrevMonth in range(abs(config.BRAG_MONTHS), 0, -1):
				QSOs.GetBragQSOs(PrevMonth = PrevMonth, Print=True)

		# MWS - Process current month as well.
		QSOs.GetBragQSOs(PrevMonth=0, Print=False)

		for Contact in self.QSOs:
			QsoDate, QsoCallSign, QsoSPC, QsoFreq, QsoComment = Contact

			if QsoCallSign in ('K9SKC', 'K3Y'):
				continue

			QsoCallSign = SKCC.ExtractCallSign(QsoCallSign)

			if not QsoCallSign:
				continue

			MainCallSign = SKCC.Members[QsoCallSign]['main_call']

			TheirMemberEntry  = SKCC.Members[MainCallSign]
			TheirJoin_Date    = Effective(TheirMemberEntry['join_date'])
			TheirC_Date       = Effective(TheirMemberEntry['c_date'])
			TheirT_Date       = Effective(TheirMemberEntry['t_date'])
			TheirS_Date       = Effective(TheirMemberEntry['s_date'])

			TheirMemberNumber = TheirMemberEntry['plain_number']

			#fastQsoDate = cFastDateTime(QsoDate)

			# K3Y
			if 'K3Y' in config.GOALS:
				StartDate = f'{K3Y_YEAR}0102000000'
				EndDate   = f'{K3Y_YEAR}0201000000'

				if QsoDate >= StartDate and QsoDate < EndDate:
					K3Y_RegEx = r'.*?K3Y[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)'
					Matches = re.match(K3Y_RegEx, QsoComment, re.IGNORECASE)

					if Matches:
						Suffix = Matches.group(1)
						Suffix = Suffix.upper()

						Band = cSKCC.WhichArrlBand(QsoFreq)

						if Band:
							if not Suffix in self.ContactsForK3Y:
								self.ContactsForK3Y[Suffix] = {}

							self.ContactsForK3Y[Suffix][Band] = QsoCallSign

			# Prefix
			if Good(QsoDate, TheirJoin_Date, self.MyJoin_Date, '20130101000000'):
				if TheirMemberNumber != self.MyMemberNumber:
					Match  = cQSO.Prefix_RegEx.match(QsoCallSign)

					if Match:
						Prefix = Match.group(1)

						iTheirMemberNumber = int(TheirMemberNumber)

						if Prefix not in self.ContactsForP or iTheirMemberNumber > self.ContactsForP[Prefix][2]:
							FirstName = SKCC.Members[QsoCallSign]['name']
							self.ContactsForP[Prefix] = (QsoDate, Prefix, iTheirMemberNumber, FirstName)

			# Centurion
			if Good(QsoDate, TheirJoin_Date, self.MyJoin_Date):
				if TheirMemberNumber not in self.ContactsForC:
					self.ContactsForC[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

			# Tribune
			if Good(QsoDate, TheirC_Date, self.MyC_Date, '20070301000000'):
				if TheirMemberNumber not in self.ContactsForT:
					self.ContactsForT[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

			# Senator
			if Good(QsoDate, TheirT_Date, self.MyTX8_Date, '20130801000000'):
				if TheirMemberNumber not in self.ContactsForS:
					self.ContactsForS[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

			if QsoSPC in US_STATES:
				# WAS
				if TheirJoin_Date and QsoDate >= TheirJoin_Date and QsoDate >= self.MyJoin_Date:
					if QsoSPC not in self.ContactsForWAS:
						self.ContactsForWAS[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

				# WAS_C
				if QsoDate >= '20110612000000':
					if TheirC_Date and QsoDate >= TheirC_Date:
						if QsoSPC not in self.ContactsForWAS_C:
							self.ContactsForWAS_C[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

				# WAS_T
				if QsoDate >= '20160201000000':
					if TheirT_Date and QsoDate >= TheirT_Date:
						if QsoSPC not in self.ContactsForWAS_T:
							self.ContactsForWAS_T[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

				# WAS_S
				if QsoDate >= '20160201000000':
					if TheirS_Date and QsoDate >= TheirS_Date:
						if QsoSPC not in self.ContactsForWAS_S:
							self.ContactsForWAS_S[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

		def AwardP(QSOs: dict[str, tuple[str, str, int, str]]) -> None:
			PrefixList = QSOs.values()
			PrefixList = sorted(PrefixList, key=lambda QsoTuple: QsoTuple[1])

			with open(f'{QSOs_Dir}/{config.MY_CALLSIGN}-P.txt', 'w', encoding='utf-8') as File:
				iPoints = 0
				for Index, (_QsoDate, Prefix, iMemberNumber, FirstName) in enumerate(PrefixList):
					iPoints += iMemberNumber
					File.write(f'{Index+1:>4} {iMemberNumber:>8} {FirstName:<10.10} {Prefix:<6} {iPoints:>12,}\n')

		def AwardCTS(Class: str, QSOs_dict: dict[str, tuple[str, str, str]]) -> None:
			QSOs = QSOs_dict.values()
			QSOs = sorted(QSOs, key=lambda QsoTuple: (QsoTuple[0], QsoTuple[2]))

			with open(f'{QSOs_Dir}/{config.MY_CALLSIGN}-{Class}.txt', 'w', encoding='utf-8') as File:
				for Count, (QsoDate, TheirMemberNumber, MainCallSign) in enumerate(QSOs):
					Date = f'{QsoDate[0:4]}-{QsoDate[4:6]}-{QsoDate[6:8]}'
					File.write(f'{Count+1:<4}  {Date}   {MainCallSign:<9}   {TheirMemberNumber:<7}\n')

		def AwardWAS(Class: str, QSOs_dict: dict[str, tuple[str, str, str]]) -> None:
			QSOs = QSOs_dict.values()
			QSOs = sorted(QSOs, key=lambda QsoTuple: QsoTuple[0])

			QSOsByState = {QsoSPC: (QsoSPC, QsoDate, QsoCallsign) for QsoSPC, QsoDate, QsoCallsign in QSOs}

			with open(f'{QSOs_Dir}/{config.MY_CALLSIGN}-{Class}.txt', 'w', encoding='utf-8') as File:
				for State in US_STATES:
					if State in QSOsByState:
						QsoSPC, _, QsoCallSign = QSOsByState[State]
						FormattedDate = f'{QsoDate[0:4]}-{QsoDate[4:6]}-{QsoDate[6:8]}'
						File.write(f'{QsoSPC}    {QsoCallSign:<12}  {FormattedDate}\n')
					else:
						File.write(f'{State}\n')

		def TrackBRAG(QSOs: Any) -> None:
			QSOs = QSOs.values()
			QSOs = sorted(QSOs)

			with open(f'{QSOs_Dir}/{config.MY_CALLSIGN}-BRAG.txt', 'w', encoding='utf-8') as File:
				for Count, (QsoDate, TheirMemberNumber, MainCallSign, QsoFreq) in enumerate(QSOs):
					Date = f'{QsoDate[0:4]}-{QsoDate[4:6]}-{QsoDate[6:8]}'
					if QsoFreq:
						File.write(f'{Count+1:<4} {Date}  {TheirMemberNumber:<6}  {MainCallSign}  {QsoFreq / 1000:.3f}\n')
					else:
						File.write(f'{Count+1:<4} {Date}  {TheirMemberNumber:<6}  {MainCallSign}\n')

		QSOs_Dir = 'QSOs'

		if not os.path.exists(QSOs_Dir):
			os.makedirs(QSOs_Dir)

		AwardCTS('C',     self.ContactsForC)
		AwardCTS('T',     self.ContactsForT)
		AwardCTS('S',     self.ContactsForS)
		AwardWAS('WAS',   self.ContactsForWAS)
		AwardWAS('WAS-C', self.ContactsForWAS_C)
		AwardWAS('WAS-T', self.ContactsForWAS_T)
		AwardWAS('WAS-S', self.ContactsForWAS_S)

		AwardP(self.ContactsForP)
		TrackBRAG(self.Brag)

		def PrintK3Y_Contacts():
			# Could be cleaner, but want to match order on the SKCC K3Y website.
			print('')
			print(f'K3Y {K3Y_YEAR}')
			print('========')
			print(f'{"Station": <8}|', end = '')
			print(f'{"160m": ^7}|', end = '')
			print(f'{"80m": ^7}|', end = '')
			print(f'{"40m": ^7}|', end = '')
			print(f'{"30m": ^7}|', end = '')
			print(f'{"20m": ^7}|', end = '')
			print(f'{"17m": ^7}|', end = '')
			print(f'{"15m": ^7}|', end = '')
			print(f'{"12m": ^7}|', end = '')
			print(f'{"10m": ^7}|', end = '')
			print(f'{"6m": ^7}|', end = '')
			print()


			def PrintStation(Station: str):
				def PrintBand(Band: int):
					if (Station in self.ContactsForK3Y) and (Band in self.ContactsForK3Y[Station]):
						print(f'{" " + self.ContactsForK3Y[Station][Band]: <7}|', end = '')
					else:
						print(f'{"": <7}|', end = '')

				print(f'{"K3Y/"+Station: <8}|', end = '')
				PrintBand(160)
				PrintBand(80)
				PrintBand(40)
				PrintBand(30)
				PrintBand(20)
				PrintBand(17)
				PrintBand(15)
				PrintBand(12)
				PrintBand(10)
				PrintBand(6)
				print()

			PrintStation('0')
			PrintStation('1')
			PrintStation('2')
			PrintStation('3')
			PrintStation('4')
			PrintStation('5')
			PrintStation('6')
			PrintStation('7')
			PrintStation('8')
			PrintStation('9')
			PrintStation('KH6')
			PrintStation('KL7')
			PrintStation('KP4')
			PrintStation('AF')
			PrintStation('AS')
			PrintStation('EU')
			PrintStation('NA')
			PrintStation('OC')
			PrintStation('SA')

		if 'K3Y' in config.GOALS:
			PrintK3Y_Contacts()

class cSpotters:
	def __init__(self):
		self.Spotters: dict[str, tuple[int, list[int]]] = {}

	@staticmethod
	def locator_to_latlong(locator: str) -> tuple[float, float | int]:
		''' From pyhamtools '''

		'''
		The MIT License (MIT)

		Copyright (c) 2014 Tobias Wellnitz

		Permission is hereby granted, free of charge, to any person obtaining a copy
		of this software and associated documentation files (the "Software"), to deal
		in the Software without restriction, including without limitation the rights
		to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
		copies of the Software, and to permit persons to whom the Software is
		furnished to do so, subject to the following conditions:

		The above copyright notice and this permission notice shall be included in all
		copies or substantial portions of the Software.

		THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
		IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
		FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
		AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
		LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
		OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
		SOFTWARE.
		'''

		'''converts Maidenhead locator in the corresponding WGS84 coordinates

				Args:
						locator (string): Locator, either 4 or 6 characters

				Returns:
						tuple (float, float): Latitude, Longitude

				Raises:
						ValueError: When called with wrong or invalid input arg
						TypeError: When arg is not a string

				Example:
					 The following example converts a Maidenhead locator into Latitude and Longitude

					 >>> from pyhamtools.locator import locator_to_latlong
					 >>> latitude, longitude = locator_to_latlong("JN48QM")
					 >>> print latitude, longitude
					 48.5208333333 9.375

				Note:
						 Latitude (negative = West, positive = East)
						 Longitude (negative = South, positive = North)

		'''

		locator = locator.upper()

		if len(locator) == 5 or len(locator) < 4:
				raise ValueError

		if ord(locator[0]) > ord('R') or ord(locator[0]) < ord('A'):
				raise ValueError

		if ord(locator[1]) > ord('R') or ord(locator[1]) < ord('A'):
				raise ValueError

		if ord(locator[2]) > ord('9') or ord(locator[2]) < ord('0'):
				raise ValueError

		if ord(locator[3]) > ord('9') or ord(locator[3]) < ord('0'):
				raise ValueError

		if len(locator) == 6:
				if ord(locator[4]) > ord('X') or ord(locator[4]) < ord('A'):
						raise ValueError
				if ord(locator[5]) > ord('X') or ord(locator[5]) < ord('A'):
						raise ValueError

		longitude  = (ord(locator[0]) - ord('A')) * 20 - 180
		latitude   = (ord(locator[1]) - ord('A')) * 10 - 90
		longitude += (ord(locator[2]) - ord('0')) * 2
		latitude  += (ord(locator[3]) - ord('0'))

		if len(locator) == 6:
				longitude += ((ord(locator[4])) - ord('A')) * (2 / 24)
				latitude  += ((ord(locator[5])) - ord('A')) * (1 / 24)

				# move to center of subsquare
				longitude += 1 / 24.0
				latitude  += 0.5 / 24.0

		else:
				# move to center of square
				longitude += 1
				latitude  += 0.5

		return latitude, longitude

	@staticmethod
	def calculate_distance(locator1: str, locator2: str) -> float:
		''' From pyhamtools '''

		'''
		The MIT License (MIT)

		Copyright (c) 2014 Tobias Wellnitz

		Permission is hereby granted, free of charge, to any person obtaining a copy
		of this software and associated documentation files (the "Software"), to deal
		in the Software without restriction, including without limitation the rights
		to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
		copies of the Software, and to permit persons to whom the Software is
		furnished to do so, subject to the following conditions:

		The above copyright notice and this permission notice shall be included in all
		copies or substantial portions of the Software.

		THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
		IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
		FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
		AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
		LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
		OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
		SOFTWARE.
		'''

		'''calculates the (shortpath) distance between two Maidenhead locators

				Args:
						locator1 (string): Locator, either 4 or 6 characters
						locator2 (string): Locator, either 4 or 6 characters

				Returns:
						float: Distance in km

				Raises:
						ValueError: When called with wrong or invalid input arg
						AttributeError: When args are not a string

				Example:
					 The following calculates the distance between two Maidenhead locators in km

					 >>> from pyhamtools.locator import calculate_distance
					 >>> calculate_distance("JN48QM", "QF67bf")
					 16466.413

		'''

		R = 6371 #earth radius
		lat1, long1 = cSpotters.locator_to_latlong(locator1)
		lat2, long2 = cSpotters.locator_to_latlong(locator2)

		d_lat = radians(lat2) - radians(lat1)
		d_long = radians(long2) - radians(long1)

		r_lat1 = radians(lat1)
		#r_long1 = radians(long1)
		r_lat2 = radians(lat2)
		#r_long2 = radians(long2)

		a = sin(d_lat/2) * sin(d_lat/2) + cos(r_lat1) * cos(r_lat2) * sin(d_long/2) * sin(d_long/2)
		c = 2 * atan2(sqrt(a), sqrt(1-a))
		d = R * c #distance in km

		return d

	def GetSpotters(self) -> None:
		def ParseBands(bandStringCsv: str):
			# Each band ends with an 'm'.

			BandList = [int(x[:-1]) for x in bandStringCsv.split(',') if x in '160m 80m 60m 40m 30m 20m 17m 15m 12m 10m 6m'.split()]
			return BandList

		print('')
		print(f"Finding RBN Spotters within {config.SPOTTER_RADIUS} miles of '{config.MY_GRIDSQUARE}'...")

		response = requests.get('https://reversebeacon.net/cont_includes/status.php?t=skt')

		if response.status_code != 200:
			print('*** Fatal Error: Unable to retrieve spotters from RBN.  Is RBN down?')
			sys.exit()

		HTML = response.text

		Rows: list[str] = []

		while HTML.find('online24h online7d total">') != -1:
			EndIndex  = HTML.find('</tr>')
			FullIndex = EndIndex+len('</tr>')

			Row = HTML[:FullIndex]
			Rows.append(Row)
			HTML = HTML[FullIndex:]

		Columns_RegEx = re.compile(r'<td.*?><a href="/dxsd1.php\?f=.*?>\s*(.*?)\s*</a>.*?</td>\s*<td.*?>\s*(.*?)</a></td>\s*<td.*?>(.*?)</td>', re.M|re.I|re.S)

		for Row in Rows:
			ColumnMatches = Columns_RegEx.findall(Row)

			for Column in (x for _, x in enumerate(ColumnMatches)):
				Spotter, csvBands, Grid = Column

				if Grid == 'XX88LL':
					continue

				try:
					fKilometers = cSpotters.calculate_distance(config.MY_GRIDSQUARE, Grid)
				except ValueError:
					#print('Bad GridSquare {} for Spotter {}'.format(Grid, Spotter))
					continue

				fMiles      = fKilometers * 0.62137
				Miles       = int(fMiles)
				BandList    = ParseBands(csvBands)
				self.Spotters[Spotter] = (Miles, BandList)

	def GetNearbySpotters(self) -> list[tuple[str, int]]:
		List: list[tuple[str, int, list[int]]] = []

		for Spotter, Value in self.Spotters.items():
			Miles, Bands = Value
			List.append((Spotter, Miles, Bands))

		List = sorted(List, key=lambda Tuple: Tuple[1])

		NearbyList: list[tuple[str, int]] = []

		for Spotter, Miles, Bands in List:
			if Miles <= config.SPOTTER_RADIUS:
				NearbyList.append((Spotter, Miles))

		return NearbyList

	def GetDistance(self, Spotter: str) -> int:
		Miles, _ = self.Spotters[Spotter]
		return Miles


class cSKCC:
	CenturionLevel: dict[str, int]
	TribuneLevel: dict[str, int]
	SenatorLevel: dict[str, int]

	MonthAbbreviations = {
		'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4,  'May':5,  'Jun':6,
		'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12
	}

	Frequencies = {
		160 : [1813],
		80  : [3530,  3550],
		60  : [],
		40  : [7055,  7120],
		30  : [10120],
		20  : [14050, 14114],
		17  : [18080],
		15  : [21050, 21114],
		12  : [24910],
		10  : [28050, 28114],
		6   : [50090]
	}

	def __init__(self):
		self.Members: dict[str, dict[str, str]] = {}

		self.ReadSkccData()

		self.CenturionLevel = cSKCC.ReadLevelList('Centurion', 'centurionlist.txt')
		self.TribuneLevel   = cSKCC.ReadLevelList('Tribune',   'tribunelist.txt')
		self.SenatorLevel   = cSKCC.ReadLevelList('Senator',   'senator.txt')

		self.WasLevel       = cSKCC.ReadRoster('WAS',   'operating_awards/was/was_roster.php')
		self.WasCLevel      = cSKCC.ReadRoster('WAS-C', 'operating_awards/was-c/was-c_roster.php')
		self.WasTLevel      = cSKCC.ReadRoster('WAS-T', 'operating_awards/was-t/was-t_roster.php')
		self.WasSLevel      = cSKCC.ReadRoster('WAS-S', 'operating_awards/was-s/was-s_roster.php')
		self.PrefixLevel    = cSKCC.ReadRoster('PFX',   'operating_awards/pfx/prefix_roster.php')

	@staticmethod
	def WES(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
		FromDate       = cFastDateTime((Year, Month, 1))

		FirstSaturday  = FromDate.FirstWeekdayFromDate('Sat')       # first Saturday
		SecondSaturday = FirstSaturday.FirstWeekdayAfterDate('Sat') # second Saturday

		StartDateTime  = SecondSaturday + timedelta(hours=12)
		EndDateTime    = StartDateTime + timedelta(hours=35, minutes=59, seconds=59)

		return StartDateTime, EndDateTime

	@staticmethod
	def SKS(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
		FromDate = cFastDateTime((Year, Month, 1))

		StartDate = cFastDateTime(None)

		for _ in range(1, 4 +1):
			StartDate = FromDate.FirstWeekdayAfterDate('Wed')
			FromDate = StartDate

		StartDateTime = StartDate + timedelta(hours=0)
		EndDateTime   = StartDateTime + timedelta(hours=2)

		return StartDateTime, EndDateTime

	@staticmethod
	def SKSA(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
		FromDate      = cFastDateTime((Year, Month, 1))

		FirstFriday   = FromDate.FirstWeekdayFromDate('Fri')     # first Friday
		SecondFriday  = FirstFriday.FirstWeekdayAfterDate('Fri') # second Friday

		StartDateTime = SecondFriday + timedelta(hours=22)
		EndDateTime   = StartDateTime + timedelta(hours=1, minutes=59, seconds=59)

		return StartDateTime, EndDateTime

	@staticmethod
	def SKSE(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
		FromDate      = cFastDateTime((Year, Month, 1))
		FirstThursday = FromDate.FirstWeekdayFromDate('Thu')

		if Month in [1, 2, 3, 11, 12]:
			StartDateTime = FirstThursday + timedelta(hours=20)
		else:
			StartDateTime = FirstThursday + timedelta(hours=19)

		EndDateTime = StartDateTime + timedelta(hours=1, minutes=59, seconds=59)

		return StartDateTime, EndDateTime

	@staticmethod
	def DuringSprint(fastDateTime: cFastDateTime) -> bool:
		Year  = fastDateTime.Year()
		Month = fastDateTime.Month()

		fastWesDateTimeStart, fastWesDateTimeEnd = cSKCC.WES(Year, Month)

		if fastWesDateTimeStart <= fastDateTime <= fastWesDateTimeEnd:
			return True

		fastSksDateTimeStart, fastSksDateTimeEnd = cSKCC.SKS(Year, Month)

		if fastSksDateTimeStart <= fastDateTime <= fastSksDateTimeEnd:
			return True

		fastSkseDateTimeStart, fastSkseDateTimeEnd = cSKCC.SKSE(Year, Month)

		if fastSkseDateTimeStart <= fastDateTime <= fastSkseDateTimeEnd:
			return True

		fastSksaDateTimeStart, fastSksaDateTimeEnd = cSKCC.SKSA(Year, Month)

		if fastSksaDateTimeStart <= fastDateTime <= fastSksaDateTimeEnd:
			return True

		return False

	@staticmethod
	def BlockDuringUpdateWindow() -> None:
		def TimeNowGMT():
			TimeNowGMT = time.strftime('%H%M00', time.gmtime())
			return int(TimeNowGMT)

		if TimeNowGMT() % 20000 == 0:
			print('The SKCC website updates files every even UTC hour.')
			print('SKCC Skimmer will start when complete.  Please wait...')

			while TimeNowGMT() % 20000 == 0:
				time.sleep(2)
				sys.stderr.write('.')
			else:
				print('')


	''' The SKCC month abbreviations are always in US format.  We
			don't want to use the built in date routines because they are
			locale sensitive and could be misinterpreted in other countries.
	'''
	@staticmethod
	def NormalizeSkccDate(Date: str) -> str:
		if not Date:
			return ''

		sDay, sMonthAbbrev, sYear = Date.split()
		iMonth = cSKCC.MonthAbbreviations[sMonthAbbrev]

		return f'{sYear:0>4}{iMonth:0>2}{sDay:0>2}000000'

	def ExtractCallSign(self, CallSign: str) -> str | None:
		#
		# Strip any punctuation other than '/'.
		#
		CallSign = CallSign.strip(string.punctuation.strip('/'))

		if '/' in CallSign:
			if CallSign in self.Members:
				return CallSign

			Parts = CallSign.split('/')

			if len(Parts) == 2:
				Prefix, Suffix = Parts
			elif len(Parts) == 3:
				Prefix, Suffix, _ = Parts
			else:
				return None

			if Prefix in self.Members:
				return Prefix

			if Suffix in self.Members:
				return Suffix
		elif CallSign in self.Members or CallSign == 'K3Y':
			return CallSign

		return None

	@staticmethod
	def ReadLevelList(Type: str, URL: str) -> dict[str, int] | NoReturn:
		print(f'Retrieving SKCC award info from {URL}...')

		try:
			response = requests.get(f'https://www.skccgroup.com/{URL}')

			if response.status_code != 200:
				return {}

			LevelList = response.text

			Level: dict[str, int] = {}
			TodayGMT = time.strftime('%Y%m%d000000', time.gmtime())

			for Line in (x for I, x in enumerate(LevelList.splitlines()) if I > 0):
				CertNumber, CallSign, MemberNumber,_FirstName,_City,_SPC,EffectiveDate,Endorsements = Line.split('|')

				if ' ' in CertNumber:
					CertNumber, X_Factor = CertNumber.split()
					X_Factor = int(X_Factor[1:])
				else:
					X_Factor = 1

				Level[MemberNumber] = X_Factor

				SkccEffectiveDate = cSKCC.NormalizeSkccDate(EffectiveDate)

				if TodayGMT < SkccEffectiveDate:
					print(f'  FYI: Brand new {Type}, {CallSign}, will be effective 00:00Z {EffectiveDate}')
				elif Type == 'Tribune':
					Match = re.search(r'\*Tx8: (.*?)$', Endorsements)

					if Match:
						Tx8_Date = Match.group(1)
						SkccEffectiveTx8_Date = cSKCC.NormalizeSkccDate(Tx8_Date)

						if TodayGMT < SkccEffectiveTx8_Date:
							print(f'  FYI: Brand new Tx8, {CallSign}, will be effective 00:00Z {Tx8_Date}')

			return Level
		except:
			print(f"Unable to retrieve award info from main SKCC website.  Unable to continue.")
			sys.exit()

	@staticmethod
	def ReadRoster(Name: str, URL: str) -> dict[str, int] | NoReturn:
		print(f'Retrieving SKCC {Name} roster...')

		try:
			response = requests.get(f'https://www.skccgroup.com/{URL}')

			if response.status_code != 200:
				return {}

			HTML = response.text

			Rows_RegEx    = re.compile(r'<tr.*?>(.*?)</tr>', re.M|re.I|re.S)
			Columns_RegEx = re.compile(r'<td.*?>(.*?)</td>', re.M|re.I|re.S)

			RowMatches    = Rows_RegEx.findall(HTML)

			Roster: dict[str, int] = {}

			for Row in (x for I, x in enumerate(RowMatches) if I > 0):
				ColumnMatches = Columns_RegEx.findall(Row)
				CertNumber    = ColumnMatches[0]
				CallSign      = ColumnMatches[1]

				if ' ' in CertNumber:
					CertNumber, X_Factor = CertNumber.split()
					X_Factor = int(X_Factor[1:])
				else:
					X_Factor = 1

				Roster[CallSign] = X_Factor

			return Roster
		except:
			print("Unable to retrieve an award roster from the main SKCC site.  Unable to continue.")
			sys.exit()

	def ReadSkccData(self) -> None | NoReturn:
		print('Retrieving SKCC award dates...')

		try:
			response = requests.get('https://www.skccgroup.com/membership_data/skccdata.txt')

			if response.status_code != 200:
				return

			SkccList = response.text

			Lines = SkccList.splitlines()

			for Line in (x for I, x in enumerate(Lines) if I > 0):
				_Number,CurrentCall,Name,_City,SPC,OtherCalls,PlainNumber,_,Join_Date,C_Date,T_Date,TX8_Date,S_Date,_Country = Line.split('|')

				if OtherCalls:
					OtherCallList = [x.strip() for x in OtherCalls.split(',')]
				else:
					OtherCallList = []

				AllCalls = [CurrentCall] + OtherCallList

				for Call in AllCalls:
					self.Members[Call] = {
							'name'         : Name,
							'plain_number' : PlainNumber,
							'spc'          : SPC,
							'join_date'    : cSKCC.NormalizeSkccDate(Join_Date),
							'c_date'       : cSKCC.NormalizeSkccDate(C_Date),
							't_date'       : cSKCC.NormalizeSkccDate(T_Date),
							'tx8_date'     : cSKCC.NormalizeSkccDate(TX8_Date),
							's_date'       : cSKCC.NormalizeSkccDate(S_Date),
							'main_call'    : CurrentCall,
					}
		except:
			print(f"Unable to retrieve award dates from main SKCC website.  Exiting.")
			sys.exit()

	@staticmethod
	def IsOnSkccFrequency(fFrequency: float, Tolerance: int = 10) -> bool:
		for Band, Value in cSKCC.Frequencies.items():
			if Band == 60 and fFrequency >= 5332-1.5 and fFrequency <= 5405+1.5:
				return True

			MidPoints = Value

			for MidPoint in MidPoints:
				if fFrequency >= MidPoint-Tolerance and fFrequency <= MidPoint+Tolerance:
					return True

		return False

	@staticmethod
	def WhichBand(fFrequency: float, Tolerance: int = 10) -> None | int:
		for Band, Value in cSKCC.Frequencies.items():
			MidPoints = Value

			for MidPoint in MidPoints:
				if fFrequency >= MidPoint-Tolerance and fFrequency <= MidPoint+Tolerance:
					return Band

		return None

	@staticmethod
	def WhichArrlBand(fFrequency: float) -> int | None:
		if fFrequency > 1800 and fFrequency < 2000:
			return 160

		if fFrequency > 3500 and fFrequency < 3600:
			return 80

		if fFrequency > 7000 and fFrequency < 7125:
			return 40

		if fFrequency > 10100 and fFrequency < 10150:
			return 30

		if fFrequency > 14000 and fFrequency < 14150:
			return 20

		if fFrequency > 18068 and fFrequency < 18168:
			return 17

		if fFrequency > 21000 and fFrequency < 21450:
			return 15

		if fFrequency > 24890 and fFrequency < 24990:
			return 12

		if fFrequency > 28000 and fFrequency < 29700:
			return 10

		if fFrequency > 50000 and fFrequency < 54000:
			return 6

		return None

	@staticmethod
	def IsOnWarcFrequency(fFrequency: float, Tolerance: int = 10) -> bool:
		WarcBands = [30, 17, 12]

		for Band in WarcBands:
			MidPoints = cSKCC.Frequencies[Band]

			for MidPoint in MidPoints:
				if fFrequency >= MidPoint-Tolerance and fFrequency <= MidPoint+Tolerance:
					return True

		return False

	def GetFullMemberNumber(self, CallSign: str) -> tuple[str, str]:
		Entry = self.Members[CallSign]

		MemberNumber = Entry['plain_number']

		Suffix = ''
		Level  = 1

		if Effective(Entry['s_date']):
			Suffix = 'S'
			Level = self.SenatorLevel[MemberNumber]
		elif Effective(Entry['t_date']):
			Suffix = 'T'
			Level = self.TribuneLevel[MemberNumber]

			if Level == 8 and not Effective(Entry['tx8_date']):
				Level = 7
		elif Effective(Entry['c_date']):
			Suffix = 'C'
			Level = self.CenturionLevel[MemberNumber]

		if Level > 1:
			Suffix += f'x{Level}'

		return (MemberNumber, Suffix)

def Log(Line: str) -> None:
	if config.LOG_FILE.ENABLED:
		with open(config.LOG_FILE.FILE_NAME, 'a', encoding='utf-8') as File:
			File.write(Line + '\n')

def LogError(Line: str) -> None:
	if config.LOG_BAD_SPOTS:
		with open('Bad_RBN_Spots.log', 'a', encoding='utf-8') as File:
			File.write(Line + '\n')

def signal_handler(_signal: Any, _frame: Any):
	sys.exit()

def AbbreviateClass(Class: str, X_Factor: int) -> str:
	if X_Factor > 1:
		return f'{Class}x{X_Factor}'

	return Class

def BuildMemberInfo(CallSign: str) -> str:
	Entry = SKCC.Members[CallSign]

	Number, Suffix = SKCC.GetFullMemberNumber(CallSign)

	Name = Entry['name']
	SPC  = Entry['spc']

	return f'({Number:>5} {Suffix:<4} {Name:<9.9} {SPC:>3})'

def IsInBANDS(Frequency: float) -> bool:
	def InRange(Band: int, fFrequency: float, Low: float, High: float) -> bool:
		return Band in config.BANDS and fFrequency >= Low and fFrequency <= High

	if InRange(160, Frequency, 1800, 2000):
		return True

	if InRange(80, Frequency, 3500, 4000):
		return True

	if InRange(60, Frequency, 5330.5-1.5, 5403.5+1.5):
		return True

	if InRange(40, Frequency, 7000, 7300):
		return True

	if InRange(30, Frequency, 10100, 10150):
		return True

	if InRange(20, Frequency, 14000, 14350):
		return True

	if InRange(17, Frequency, 18068, 18168):
		return True

	if InRange(15, Frequency, 21000, 21450):
		return True

	if InRange(12, Frequency, 24890, 24990):
		return True

	if InRange(10, Frequency, 28000, 29700):
		return True

	if InRange(6, Frequency, 50000, 50100):
		return True

	return False

def Lookups(LookupString: str) -> None:
	def PrintCallSign(CallSign: str):
		Entry = SKCC.Members[CallSign]

		MyNumber = SKCC.Members[config.MY_CALLSIGN]['plain_number']

		Report = [BuildMemberInfo(CallSign)]

		if Entry['plain_number'] == MyNumber:
			Report.append('(you)')
		else:
			GoalList = QSOs.GetGoalHits(CallSign)

			if GoalList:
				Report.append(f'YOU need them for {",".join(GoalList)}')

			TargetList = QSOs.GetTargetHits(CallSign)

			if TargetList:
				Report.append(f'THEY need you for {",".join(TargetList)}')

			# NX1K 12-Nov-2017 Put in check for friend.
			IsFriend = CallSign in config.FRIENDS

			if IsFriend:
				Report.append('friend')

			if not GoalList and not TargetList:
				Report.append("You don't need to work each other.")

		print(f'  {CallSign} - {"; ".join(Report)}')

	LookupList = cCommon.Split(LookupString.upper())

	for Item in LookupList:
		Match = re.match(r'^([0-9]+)[CTS]{0,1}$', Item)

		if Match:
			Number = Match.group(1)

			for CallSign, Value in SKCC.Members.items():
				Entry = Value

				if Entry['plain_number'] == Number:
					if CallSign == Entry['main_call'] == CallSign:
						break
			else:
				print(f'  No member with the number {Number}.')
				continue

			PrintCallSign(CallSign)
		else:
			CallSign = SKCC.ExtractCallSign(Item)

			if not CallSign:
				print(f'  {Item} - not an SKCC member.')
				continue

			PrintCallSign(CallSign)

	print('')

def FileCheck(Filename: str) -> None | NoReturn:
	if os.path.exists(Filename):
		return

	print('')
	print(f"File '{Filename}' does not exist.")
	print('')
	sys.exit()

#
# Main
#

#
# cVersion is an uncontrolled file (not committed to Git).  It is created by
# a release script to properly identify the version stamp of the release, so
# this code imports the file if it exists or, if it does not, reverts to a
# generic string.
#
try:
	# pyright: reportMissingImports=false
	import Lib.cVersion

	# pyright: reportUnknownVariableType=false
	# pyright: reportUnknownMemberType=false
	VERSION = Lib.cVersion.VERSION
except:
	VERSION = '<dev>'

print(f'SKCC Skimmer version {VERSION}\n')

US_STATES = 'AK AL AR AZ CA CO CT DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN MO MS MT NC ND NE NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT WA WI WV WY'.split(' ')

ArgV = sys.argv[1:]

config = cConfig(ArgV)


# Default the K3Y_YEAR in case it isn't set in the config file.
K3Y_YEAR = datetime.now().year


CLUSTERS = 'SKCC RBN'


cSKCC.BlockDuringUpdateWindow()

config.MY_CALLSIGN = config.MY_CALLSIGN.upper()

Levels = {
 'C'  :    100,
 'T'  :     50,
 'S'  :    200,
 'P'  : 500000,
}

if config.VERBOSE:
	config.PROGRESS_DOTS.ENABLED = False

signal.signal(signal.SIGINT, signal_handler)

FileCheck(config.ADI_FILE)

Display  = cDisplay()
SKCC     = cSKCC()

if config.MY_CALLSIGN not in SKCC.Members:
	print(f"'{config.MY_CALLSIGN}' is not a member of SKCC.")
	sys.exit()

QSOs = cQSO()

QSOs.GetGoalQSOs()
QSOs.PrintProgress()

print('')
QSOs.AwardsCheck()

if config.INTERACTIVE:
	print('')
	print('Interactive mode. Enter one or more comma or space separated callsigns.')
	print('')
	print("(Enter 'q' to quit, 'r' to refresh)")
	print('')

	while True:
		sys.stdout.write('> ')
		sys.stdout.flush()
		Line = sys.stdin.readline().strip().lower()

		if Line in ('q', 'quit'):
			sys.exit()
		elif Line in ('r', 'refresh'):
			QSOs.Refresh()
		elif Line == '':
			continue
		else:
			print('')
			Lookups(Line)

Spotters = cSpotters()
Spotters.GetSpotters()

def FormatDistance(Miles: int) -> str:
	if config.DISTANCE_UNITS == "mi":
		return f'{Miles}mi'

	return f'{Miles2Km(Miles)}km'


NearbyList = Spotters.GetNearbySpotters()
SpotterList = [f'{Spotter}({FormatDistance(Miles)})'  for Spotter, Miles in NearbyList]
SPOTTERS_NEARBY = [Spotter  for Spotter, _ in NearbyList]

print(f'  Found {len(SpotterList)} spotters:')

List = textwrap.wrap(', '.join(SpotterList), width=80)

for Element in List:
	print(f'    {Element}')


if config.LOG_FILE.DELETE_ON_STARTUP:
	Filename = config.LOG_FILE.FILE_NAME

	if os.path.exists(Filename):
		os.remove(Filename)

print('')
print('Running...')
print('')

SocketLoop = cSocketLoop()

RBN = cRBN_Filter(SocketLoop, CallSign=config.MY_CALLSIGN, Clusters=CLUSTERS)

if config.SKED.ENABLED:
	cSked()

SocketLoop.Run()

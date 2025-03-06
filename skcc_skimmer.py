#!/usr/bin/python3
'''

     The MIT License (MIT)

     Copyright (c) 2015-2025 Mark J Glenn

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

     Mark Glenn
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
#   Requires Python version 3.11 or better. Also requires the following imports
#   which may require a pip install.
#

from datetime        import timedelta, datetime
from types           import FrameType
from typing          import Any, NoReturn, Literal, get_args
from math            import radians, sin, cos, atan2, sqrt

from collections.abc import AsyncGenerator
from dataclasses     import dataclass, field

import asyncio
import argparse
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
import threading
import platform

RBN_SERVER = 'skimmer.skccgroup.com'
RBN_PORT   = 7000

shutdown_event = asyncio.Event()

def handle_shutdown():
    """Sets the shutdown event when Ctrl+C is detected."""
    print("\nCtrl+C detected. Shutting down gracefully...")
    shutdown_event.set()

class cUtil:
    @staticmethod
    def Split(text: str) -> list[str]:
        return re.split(r'[,\s]+', text.strip())

    @staticmethod
    def Effective(date: str) -> str:
        return date if time.strftime('%Y%m%d000000', time.gmtime()) >= date else ''

    @staticmethod
    def Miles2Km(Miles: int) -> int:
        return round(Miles * 1.609344)

    @staticmethod
    def Stripped(text: str) -> str:
        return ''.join([c for c in text if 31 < ord(c) < 127])

    @staticmethod
    def Beep() -> None:
        sys.stdout.write('\a')
        sys.stdout.flush()

    @staticmethod
    def FormatDistance(Miles: int) -> str:
        if config.DISTANCE_UNITS == "mi":
            return f'{Miles}mi'

        return f'{cUtil.Miles2Km(Miles)}km'

class cConfig:
    @dataclass
    class cProgressDots:
        ENABLED:         bool = True
        DISPLAY_SECONDS: int  = 10
        DOTS_PER_LINE:   int  = 30
    def init_progress_dots(self):
        progress_config = self.configFile.get("PROGRESS_DOTS", {})
        self.PROGRESS_DOTS = cConfig.cProgressDots(
            ENABLED         = bool(progress_config.get("ENABLED", cConfig.cProgressDots.ENABLED)),
            DISPLAY_SECONDS = progress_config.get("DISPLAY_SECONDS", cConfig.cProgressDots.DISPLAY_SECONDS),
            DOTS_PER_LINE   =  progress_config.get("DOTS_PER_LINE", cConfig.cProgressDots.DOTS_PER_LINE),
        )

    @dataclass
    class cLogFile:
        FILE_NAME:         str | None = None
        ENABLED:           bool = True
        LOG_FILE:          str | None = None
        DELETE_ON_STARTUP: bool = False
    def init_logfile(self):
        log_file_config = self.configFile.get("LOG_FILE", {})
        self.LOG_FILE = cConfig.cLogFile(
            ENABLED           = bool(log_file_config.get("ENABLED", cConfig.cLogFile.ENABLED)),
            FILE_NAME         = log_file_config.get("FILE_NAME", cConfig.cLogFile.FILE_NAME),
            DELETE_ON_STARTUP = bool(log_file_config.get("DELETE_ON_STARTUP", cConfig.cLogFile.DELETE_ON_STARTUP))
        )

    @dataclass
    class cHighWpm:
        tAction = Literal['suppress', 'warn', 'always-display']
        ACTION: tAction = 'always-display'
        THRESHOLD: int = 15
    def init_high_wpm(self):
        high_wpm_config = self.configFile.get("HIGH_WPM", {})
        action: cConfig.cHighWpm.tAction = high_wpm_config.get("ACTION", cConfig.cHighWpm.ACTION)
        if action not in get_args(cConfig.cHighWpm.tAction):
            print(f"Invalid ACTION: {action}. Must be one of {get_args(cConfig.cHighWpm.tAction)}.")
            action = cConfig.cHighWpm.ACTION

        self.HIGH_WPM = cConfig.cHighWpm(
            ACTION    = action,
            THRESHOLD = int(high_wpm_config.get("THRESHOLD", cConfig.cHighWpm.THRESHOLD))
        )

    @dataclass
    class cOffFrequency:
        ACTION:    Literal['suppress', 'warn'] = 'suppress'
        TOLERANCE: int = 0
    def init_off_frequency(self):
        off_frequency_config = self.configFile.get("OFF_FREQUENCY", {})
        self.OFF_FREQUENCY = cConfig.cOffFrequency(
            ACTION    =     off_frequency_config.get("ACTION",    cConfig.cOffFrequency.ACTION),
            TOLERANCE = int(off_frequency_config.get("TOLERANCE", cConfig.cOffFrequency.TOLERANCE))
        )

    @dataclass
    class cSked:
        ENABLED:       bool = True
        CHECK_SECONDS: int  = 60
    def init_sked(self):
        sked_config = self.configFile.get("SKED", {})
        self.SKED = cConfig.cSked(
            ENABLED       = sked_config.get("ENABLED",       cConfig.cSked.ENABLED),
            CHECK_SECONDS = sked_config.get("CHECK_SECONDS", cConfig.cSked.CHECK_SECONDS),
        )

    @dataclass
    class cNotification:
        DEFAULT_CONDITION = ['goals', 'targets', 'friends']  # ✅ Class-level default
        ENABLED: bool = True
        CONDITION: list[str] = field(default_factory=lambda: cConfig.cNotification.DEFAULT_CONDITION)
        RENOTIFICATION_DELAY_SECONDS: int = 30
    def init_notifications(self):
        notification_config = self.configFile.get("NOTIFICATION", {})
        conditions = cUtil.Split(notification_config.get("CONDITION", cConfig.cNotification.DEFAULT_CONDITION))  # ✅ Use DEFAULT_CONDITION
        invalid_conditions = [c for c in conditions if c not in ['goals', 'targets', 'friends']]
        if invalid_conditions:
            print(f"Invalid NOTIFICATION CONDITION(s): {invalid_conditions}. Must be 'goals', 'targets', or 'friends'.")
            sys.exit()
        self.NOTIFICATION = cConfig.cNotification(
            ENABLED                      = bool(notification_config.get("ENABLED", cConfig.cNotification.ENABLED)),
            CONDITION                    = conditions,
            RENOTIFICATION_DELAY_SECONDS = int(notification_config.get("RENOTIFICATION_DELAY_SECONDS", cConfig.cNotification.RENOTIFICATION_DELAY_SECONDS))
        )

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
    K3Y_YEAR:                 int

    configFile:               dict[str, Any]

    def __init__(self, ArgV: list[str]):
        def ReadSkccSkimmerCfg() -> dict[str, Any]:
            config_vars: dict[str, Any] = {}

            with open('skcc_skimmer.cfg', 'r', encoding='utf-8') as configFile:
                ConfigFileString = configFile.read()
                exec(ConfigFileString, {}, config_vars)

            return config_vars

        self.configFile = ReadSkccSkimmerCfg()

        self.MY_CALLSIGN = self.configFile.get('MY_CALLSIGN', '')
        self.ADI_FILE = self.configFile.get('ADI_FILE', '')
        self.MY_GRIDSQUARE = self.configFile.get('MY_GRIDSQUARE', '')

        if 'SPOTTER_RADIUS' in self.configFile:
            self.SPOTTER_RADIUS = int(self.configFile['SPOTTER_RADIUS'])

        if 'GOALS' in self.configFile:
            self.GOALS = self.ParseGoals(self.configFile['GOALS'], 'C CXN T TXN S SXN WAS WAS-C WAS-T WAS-S P BRAG K3Y', 'goal')

        if 'TARGETS' in self.configFile:
            self.TARGETS = self.ParseGoals(self.configFile['TARGETS'], 'C CXN T TXN S SXN', 'target')

        if 'BANDS' in self.configFile:
            self.BANDS = [int(Band)  for Band in cUtil.Split(self.configFile['BANDS'])]

        if 'FRIENDS' in self.configFile:
            self.FRIENDS = [friend  for friend in cUtil.Split(self.configFile['FRIENDS'])]

        if 'EXCLUSIONS' in self.configFile:
            self.EXCLUSIONS = [friend  for friend in cUtil.Split(self.configFile['EXCLUSIONS'])]

        self.init_logfile()
        self.init_progress_dots()
        self.init_sked()
        self.init_notifications()
        self.init_off_frequency()
        self.init_high_wpm()

        self.VERBOSE = bool(self.configFile.get('VERBOSE', False))
        self.LOG_BAD_SPOTS = bool(self.configFile.get('LOG_BAD_SPOTS', False))

        self.DISTANCE_UNITS = self.configFile.get('DISTANCE_UNITS', 'mi')
        if self.DISTANCE_UNITS not in ('mi', 'km'):
            self.DISTANCE_UNITS = 'mi'


        if 'K3Y_YEAR' in self.configFile:
            self.K3Y_YEAR = self.configFile['K3Y_YEAR']
        else:
            self.K3Y_YEAR = datetime.now().year

        self._ParseArgs(ArgV)
        self._ValidateConfig()

    def _ParseArgs(self, ArgV: list[str]) -> None:
        parser = argparse.ArgumentParser(description="SKCC Skimmer Configuration")

        parser.add_argument("-a", "--adi", type=str, help="ADI file")
        parser.add_argument("-b", "--bands", type=str, help="Comma-separated bands")
        parser.add_argument("-B", "--brag-months", type=int, help="Number of months back for bragging")
        parser.add_argument("-c", "--callsign", type=str, help="Your callsign")
        parser.add_argument("-d", "--distance-units", type=str, choices=["mi", "km"], help="Distance units (mi/km)")
        parser.add_argument("-g", "--goals", type=str, help="Goals")
        parser.add_argument("-i", "--interactive", action="store_true", help="Enable interactive mode")
        parser.add_argument("-l", "--logfile", type=str, help="Logfile name")
        parser.add_argument("-m", "--maidenhead", type=str, help="Grid square")
        parser.add_argument("-n", "--notification", type=str, choices=["on", "off"], help="Enable notifications (on/off)")
        parser.add_argument("-r", "--radius", type=int, help="Distance radius in miles")
        parser.add_argument("-s", "--sked", type=str, choices=["on", "off"], help="Enable scheduled mode (on/off)")
        parser.add_argument("-t", "--targets", type=str, help="Targets")
        parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose mode")

        args = parser.parse_args(ArgV)

        self.INTERACTIVE = args.interactive
        self.VERBOSE = args.verbose

        if args.adi:
            self.ADI_FILE = args.adi
        if args.bands:
            self.BANDS = [int(band) for band in cUtil.Split(args.bands)]
        if args.brag_months:
            self.BRAG_MONTHS = args.brag_months
        if args.callsign:
            self.MY_CALLSIGN = args.callsign.upper()
        if args.distance_units:
            self.DISTANCE_UNITS = args.distance_units
        if args.goals:
            self.GOALS = self.ParseGoals(args.goals, "C CXN T TXN S SXN WAS WAS-C WAS-T WAS-S P BRAG K3Y", "goal")
        if args.logfile:
            self.LOG_FILE.ENABLED = True
            self.LOG_FILE.DELETE_ON_STARTUP = True
            self.LOG_FILE.FILE_NAME = args.logfile
        if args.maidenhead:
            self.MY_GRIDSQUARE = args.maidenhead
        if args.notification:
            self.NOTIFICATION.ENABLED = args.notification == "on"
        if args.radius:
            self.SPOTTER_RADIUS = args.radius
        if args.sked:
            self.SKED.ENABLED = args.sked == "on"
        if args.targets:
            self.TARGETS = self.ParseGoals(args.targets, "C CXN T TXN S SXN", "target")

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

    def ParseGoals(self, String: str, ALL_str: str, Type: str) -> list[str]:
        ALL    = ALL_str.split()
        parsed = cUtil.Split(String.upper())

        for x in parsed:
            if x == 'ALL':
                return ALL

            if x == 'NONE':
                return []

            if x == 'CXN' and 'C' not in parsed:
                parsed.append('C')

            if x == 'TXN' and 'T' not in parsed:
                parsed.append('T')

            if x == 'SXN' and 'S' not in parsed:
                parsed.append('S')

            if x not in ALL:
                print(f"Unrecognized {Type} '{x}'.")
                sys.exit()

        return parsed

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
                self.FastDateTime = f"{Year:04}{Month:02}{Day:02}{Hour:02}{Minute:02}{Second:02}"

        elif isinstance(Object, str):
            self.FastDateTime = Object

        else:
            self.FastDateTime = ''

    def SplitDateTime(self) -> list[int]:
        return list(map(int, [self.FastDateTime[:4],   self.FastDateTime[4:6],   self.FastDateTime[6:8],
                              self.FastDateTime[8:10], self.FastDateTime[10:12], self.FastDateTime[12:14]]))

    def StartOfMonth(self) -> 'cFastDateTime':
        Year, Month, _Day, _Hour, _Minute, _Second = self.SplitDateTime()
        return cFastDateTime(f'{Year:0>4}{Month:0>2}{1:0>2}000000')

    def EndOfMonth(self) -> 'cFastDateTime':
        Year, Month, _Day, _Hour, _Minute, _Second = self.SplitDateTime()
        _, DaysInMonth = calendar.monthrange(Year, Month)
        return cFastDateTime(f'{Year:0>4}{Month:0>2}{DaysInMonth:0>2}235959')

    def Year(self) -> int:
        return int(self.FastDateTime[0:4])

    def Month(self) -> int:
        return int(self.FastDateTime[4:6])

    def ToDateTime(self) -> datetime:
        return datetime.strptime(self.FastDateTime, '%Y%m%d%H%M%S')

    def FirstWeekdayFromDate(self, TargetWeekday: str) -> 'cFastDateTime':
        TargetWeekdayNumber = time.strptime(TargetWeekday, '%a').tm_wday
        DateTime = self.ToDateTime()

        while DateTime.weekday() != TargetWeekdayNumber:
            DateTime += timedelta(days=1)

        return cFastDateTime(DateTime)

    def FirstWeekdayAfterDate(self, TargetWeekday: str) -> 'cFastDateTime':
        TargetWeekdayNumber = time.strptime(TargetWeekday, '%a').tm_wday
        DateTime = self.ToDateTime()

        while True:
            DateTime += timedelta(days=1)

            if DateTime.weekday() == TargetWeekdayNumber:
                return cFastDateTime(DateTime)

    def __repr__(self) -> str:
        return self.FastDateTime

    def __lt__(self, Right: 'cFastDateTime') -> bool:
        return self.FastDateTime < Right.FastDateTime

    def __le__(self, Right: 'cFastDateTime') -> bool:
        return self.FastDateTime <= Right.FastDateTime

    def __gt__(self, Right: 'cFastDateTime') -> bool:
        return self.FastDateTime > Right.FastDateTime

    def __add__(self, Delta: timedelta) -> 'cFastDateTime':
        return cFastDateTime(self.ToDateTime() + Delta)

    @staticmethod
    def NowGMT() -> 'cFastDateTime':
        return cFastDateTime(time.gmtime())

class cDisplay:
    DotsOutput = 0

    @classmethod
    def Print(cls, text: str):
        if cls.DotsOutput > 0:
            print()

        print(text)
        cls.DotsOutput = 0

    @classmethod
    async def DotsLoop(cls):
        try:
            while not shutdown_event.is_set():
                await asyncio.sleep(config.PROGRESS_DOTS.DISPLAY_SECONDS)
                print('.', end='', flush=True)
                cls.DotsOutput += 1
        except asyncio.CancelledError:
            print("cDisplay.DotsLoop task cancelled.")
            raise

class cSked:
    RegEx = re.compile('<span class="callsign">(.*?)<span>(?:.*?<span class="userstatus">(.*?)</span>)?')
    SkedSite = None

    PreviousLogins = {}
    FirstPass = True

    @classmethod
    def HandleLogins(cls, SkedLogins: list[tuple[str, str]], Heading: str):
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

            if CallSign in cSPOTS.LastSpotted:
                FrequencyKHz, StartTime = cSPOTS.LastSpotted[CallSign]

                Now = time.time()
                DeltaSeconds = max(int(Now - StartTime), 1)

                if DeltaSeconds > config.SPOT_PERSISTENCE_MINUTES * 60:
                    del cSPOTS.LastSpotted[CallSign]
                elif DeltaSeconds > 60:
                    DeltaMinutes = DeltaSeconds // 60
                    Units = 'minutes' if DeltaMinutes > 1 else 'minute'
                    Report.append(f'Last spotted {DeltaMinutes} {Units} ago on {FrequencyKHz}')
                else:
                    Units = 'seconds' if DeltaSeconds > 1 else 'second'
                    Report.append(f'Last spotted {DeltaSeconds} {Units} ago on {FrequencyKHz}')

            GoalList = []

            if 'K3Y' in config.GOALS:
                def CollectStation() -> tuple[str, str] | None:
                    K3Y_RegEx = r'\b(K3Y)/([0-9]|KP4|KH6|KL7)\b'
                    Matches = re.search(K3Y_RegEx, Status, re.IGNORECASE)

                    if Matches:
                        return Matches.group(1), Matches.group(2).upper()

                    SKM_RegEx = r'\b(SKM)[\/-](AF|AS|EU|NA|OC|SA)\b'
                    Matches = re.search(SKM_RegEx, Status, re.IGNORECASE)

                    if Matches:
                        return Matches.group(1), Matches.group(2).upper()

                    return None

                def CollectFrequencyKHz() -> float | None:
                    # Group 1 examples: 7.055.5 14.055.5
                    # Group 2 examples: 7.055   14.055
                    # Group 3 examples: 7055.5  14055.5
                    # Group 4 examples: 7055    14055
                    Freq_RegEx = re.compile(r"\b(\d{1,2}\.\d{3}\.\d{1,3})|(\d{1,2}\.\d{1,3})|(\d{4,5}\.\d{1,3})|(\d{4,5})\b\s*$")

                    if match := Freq_RegEx.search(Status):
                        FrequencyStr = match.group(1) or match.group(2) or match.group(3) or match.group(4)

                        if FrequencyStr:
                            return float(FrequencyStr.replace('.', '', 1)) if match.group(1) else float(FrequencyStr) * (1000 if match.group(2) else 1)

                    return None

                def Combine(Type: str, Station: str):
                    if Type == 'SKM':
                        return f'SKM-{Station}'
                    else:
                        return f'K3Y/{Station}'

                if Status != '':
                    FullTuple = CollectStation()

                    if FullTuple:
                        Type, Station = FullTuple
                        FrequencyKHz = CollectFrequencyKHz()

                        if FrequencyKHz:
                            Band = cSKCC.WhichBand(FrequencyKHz)

                            if Band:
                                if (not Station in QSOs.ContactsForK3Y) or (not Band in QSOs.ContactsForK3Y[Station]):
                                    GoalList.append(f'{Combine(Type, Station)} ({Band}m)')
                        else:
                            GoalList.append(f'{Combine(Type, Station)}')

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
                Report.append(f'STATUS: {cUtil.Stripped(Status)}')

            if TargetList or GoalList or IsFriend:
                SkedHit[CallSign] = Report

        if SkedHit:
            GMT = time.gmtime()
            ZuluTime = time.strftime('%H%MZ', GMT)
            ZuluDate = time.strftime('%Y-%m-%d', GMT)

            if cls.FirstPass:
                NewLogins = []
            else:
                NewLogins = list(set(SkedHit)-set(cls.PreviousLogins))

            cDisplay.Print('=========== '+Heading+' Sked Page '+'=' * (16-len(Heading)))

            for CallSign in sorted(SkedHit):
                if CallSign in NewLogins:
                    if config.NOTIFICATION.ENABLED:
                        if (CallSign in config.FRIENDS and 'friends' in config.NOTIFICATION.CONDITION) or (GoalList and 'goals' in config.NOTIFICATION.CONDITION) or (TargetList and 'targets' in config.NOTIFICATION.CONDITION):
                            cUtil.Beep()

                    NewIndicator = '+'
                else:
                    NewIndicator = ' '

                Out = f'{ZuluTime}{NewIndicator}{CallSign:<6} {"; ".join(SkedHit[CallSign])}'
                cDisplay.Print(Out)
                Log(f'{ZuluDate} {Out}')

        return SkedHit

    @classmethod
    def DisplayLogins(cls) -> None:
        try:
            response = requests.get('http://sked.skccgroup.com/get-status.php')

            if response.status_code != 200:
                return

            Content = response.text
            Hits = {}

            if Content:
                try:
                    SkedLogins: list[tuple[str, str]] = json.loads(Content)
                    Hits = cls.HandleLogins(SkedLogins, 'SKCC')
                except Exception as ex:
                    with open('DEBUG.txt', 'a', encoding='utf-8') as File:
                        File.write(Content + '\n')

                    print(f"*** Problem parsing data sent from the SKCC Sked Page: '{Content}'.  Details: '{ex}'.")

            cls.PreviousLogins = Hits
            cls.FirstPass = False

            if Hits:
                cDisplay.Print('=======================================')
        except:
            print(f"\nProblem retrieving information from the Sked Page.  Skipping...")

    @classmethod
    async def RunForever(cls):
        try:
            while not shutdown_event.is_set():
                cls.DisplayLogins()
                await asyncio.sleep(config.SKED.CHECK_SECONDS)
        except asyncio.CancelledError:
            await cRBN.feed_generator(config.MY_CALLSIGN).aclose()  # ✅ Properly close generator
            print("cSked.RunForever task cancelled.")
            raise

class cSPOTS:
    LastSpotted: dict[str, tuple[float, float]] = {}
    Notified: dict[str, float] = {}

    Zulu_RegEx = re.compile(r'^([01]?[0-9]|2[0-3])[0-5][0-9]Z$')
    dB_RegEx   = re.compile(r'^\s{0,1}\d{1,2} dB$')

    @classmethod
    async def HandleSpots(cls):
        try:
            async for data in cRBN.feed_generator(config.MY_CALLSIGN):
                if shutdown_event.is_set():  # ✅ Gracefully exit if shutdown is requested
                    break
                cSPOTS.HandleSpot(data.rstrip().decode("ascii"))

        except asyncio.CancelledError:
            await cRBN.feed_generator(config.MY_CALLSIGN).aclose()  # ✅ Properly close generator
            print("cSPOTS.HandleSpots task cancelled.")
            raise

    @staticmethod
    def ParseSpot(Line: str) -> None | tuple[str, str, float, str, str, int, int]:
        # If the line isn't exactly 75 characters, something is wrong.
        if len(Line) != 75:
            LogError(Line)
            return None

        if not Line.startswith('DX de '):
            LogError(Line)
            return None

        Spotter, FrequencyKHzStr = Line[6:24].split('-#:')

        FrequencyKHzStr = FrequencyKHzStr.lstrip()
        CallSign        = Line[26:35].rstrip()
        dB              = int(Line[47:49].strip())
        Zulu            = Line[70:75]
        CW              = Line[41:47].rstrip()
        Beacon          = Line[62:68].rstrip()

        if CW != 'CW':
            return None

        if Beacon == 'BEACON':
            return None

        if not cSPOTS.Zulu_RegEx.match(Zulu):
            LogError(Line)
            return None

        if not cSPOTS.dB_RegEx.match(Line[47:52]):
            LogError(Line)
            return None

        try:
            WPM = int(Line[53:56])
        except ValueError:
            LogError(Line)
            return None

        try:
            FrequencyKHz = float(FrequencyKHzStr)
        except ValueError:
            LogError(Line)
            return None

        CallSignSuffix = ''

        if '/' in CallSign:
            CallSign, CallSignSuffix = CallSign.split('/', 1)
            CallSignSuffix = CallSignSuffix.upper()

        return Zulu, Spotter, FrequencyKHz, CallSign, CallSignSuffix, dB, WPM

    @classmethod
    def HandleNotification(cls, CallSign: str, GoalList: list[str], TargetList: list[str]) -> Literal['+', ' ']:
        NotificationFlag = ' '

        Now = time.time()

        for Call in dict(cls.Notified):
            if Now > cls.Notified[Call]:
                del cls.Notified[Call]

        if CallSign not in cls.Notified:
            if config.NOTIFICATION.ENABLED:
                if (CallSign in config.FRIENDS and 'friends' in config.NOTIFICATION.CONDITION) or (GoalList and 'goals' in config.NOTIFICATION.CONDITION) or (TargetList and 'targets' in config.NOTIFICATION.CONDITION):
                    cUtil.Beep()

            NotificationFlag = '+'
            cls.Notified[CallSign] = Now + config.NOTIFICATION.RENOTIFICATION_DELAY_SECONDS

        return NotificationFlag

    @classmethod
    def HandleSpot(cls, Line: str) -> None:
        if config.VERBOSE:
            print(f'   {Line}')

        Spot = cSPOTS.ParseSpot(Line)

        if not Spot:
            return

        Zulu, Spotter, FrequencyKHz, CallSign, CallSignSuffix, dB, WPM = Spot


        Report: list[str] = []

        #-------------

        CallSign = SKCC.ExtractCallSign(CallSign)

        if not CallSign:
            return

        if CallSign in config.EXCLUSIONS:
            return

        #-------------

        if not IsInBANDS(FrequencyKHz):
            return

        #-------------

        SpottedNearby = Spotter in SPOTTERS_NEARBY

        if SpottedNearby or CallSign == config.MY_CALLSIGN:
            if Spotter in Spotters.Spotters:
                Miles = Spotters.GetDistance(Spotter)

                MilesDisplay      = f'{Miles}mi'
                KilometersDisplay = f'{cUtil.Miles2Km(Miles)}km'
                Distance          = MilesDisplay if config.DISTANCE_UNITS == 'mi' else KilometersDisplay

                Report.append(f'by {Spotter}({Distance}, {int(dB)}dB)')
            else:
                Report.append(f'by {Spotter}({int(dB)}dB)')

        #-------------

        You = CallSign == config.MY_CALLSIGN

        if You:
            Report.append('(you)')

        #-------------

        if CallSign != 'K3Y':
            OnFrequency = cSKCC.IsOnSkccFrequency(FrequencyKHz, config.OFF_FREQUENCY.TOLERANCE)

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
                Band = cSKCC.WhichArrlBand(FrequencyKHz)

                if (not CallSignSuffix in QSOs.ContactsForK3Y) or (not Band in QSOs.ContactsForK3Y[CallSignSuffix]):
                    GoalList = [f'K3Y/{CallSignSuffix} ({Band}m)']

        GoalList = GoalList + QSOs.GetGoalHits(CallSign, FrequencyKHz)

        if GoalList:
            Report.append(f'YOU need them for {",".join(GoalList)}')

        #-------------

        TargetList = QSOs.GetTargetHits(CallSign)

        if TargetList:
            Report.append(f'THEY need you for {",".join(TargetList)}')

        #-------------

        if (SpottedNearby and (GoalList or TargetList)) or You or IsFriend:
            cSPOTS.LastSpotted[CallSign] = (FrequencyKHz, time.time())

            ZuluDate = time.strftime('%Y-%m-%d', time.gmtime())

            FrequencyString = f'{FrequencyKHz:.1f}'

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
                NotificationFlag = cls.HandleNotification(f'K3Y/{CallSignSuffix}', GoalList, TargetList)
                Out = f'{Zulu}{NotificationFlag}K3Y/{CallSignSuffix} on {FrequencyString:>8} {"; ".join(Report)}'
            else:
                MemberInfo = BuildMemberInfo(CallSign)
                NotificationFlag = cls.HandleNotification(CallSign, GoalList, TargetList)
                Out = f'{Zulu}{NotificationFlag}{CallSign:<6} {MemberInfo} on {FrequencyString:>8} {"; ".join(Report)}'

            cDisplay.Print(Out)
            Log(f'{ZuluDate} {Out}')

class cQSO:
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

    Brag:             dict[str, tuple[str, str, str, float]]

    QSOsByMemberNumber: dict[str, list[str]]

    QSOs: list[tuple[str, str, str, float, str]]

    Prefix_RegEx = re.compile(r'(?:.*/)?([0-9]*[a-zA-Z]+\d+)')

    def __init__(self):
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

        MyMemberEntry       = SKCC.Members[config.MY_CALLSIGN]
        self.MyJoin_Date    = cUtil.Effective(MyMemberEntry['join_date'])
        self.MyC_Date       = cUtil.Effective(MyMemberEntry['c_date'])
        self.MyT_Date       = cUtil.Effective(MyMemberEntry['t_date'])
        self.MyS_Date       = cUtil.Effective(MyMemberEntry['s_date'])
        self.MyTX8_Date     = cUtil.Effective(MyMemberEntry['tx8_date'])

        self.MyMemberNumber = MyMemberEntry['plain_number']

    @classmethod
    async def WatchLogFile(cls):
        try:
            while not shutdown_event.is_set():
                if os.path.getmtime(config.ADI_FILE) != QSOs.AdiFileReadTimeStamp:
                    cDisplay.Print(f"'{config.ADI_FILE}' file is changing. Waiting for write to finish...")

                    # Once we detect the file has changed, we can't necessarily read it
                    # immediately because the logger may still be writing to it, so we wait
                    # until the write is complete.
                    while True:
                        Size = os.path.getsize(config.ADI_FILE)
                        await asyncio.sleep(1)

                        if os.path.getsize(config.ADI_FILE) == Size:
                            break

                    QSOs.Refresh()

                await asyncio.sleep(3)
        except asyncio.CancelledError:
            print("cQSOs.WatchLogFile task cancelled.")
            raise

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
        increment = Levels[Class]
        return increment - (Total % increment), (Total + increment) // increment

    def ReadQSOs(self) -> None:
        """ Reads QSOs from the ADIF log file and processes them efficiently. """

        AdiFileAbsolute = os.path.abspath(config.ADI_FILE)
        cDisplay.Print(f"\nReading QSOs for {config.MY_CALLSIGN} from '{AdiFileAbsolute}'...")

        self.QSOs = []
        self.AdiFileReadTimeStamp = os.path.getmtime(config.ADI_FILE)

        with open(AdiFileAbsolute, 'rb') as file:
            Body = re.split(r'<eoh>', file.read().decode('utf-8', 'ignore'), flags=re.I | re.M)[-1].strip(' \t\r\n\x1a')

        Adi_RegEx = re.compile(r'<(\w+?):\d+(?::.*?)*>(.*?)\s*(?=<(?:\w+?):\d+(?::.*?)*>|$)', re.I | re.M | re.S)

        for record_text in filter(None, map(str.strip, re.split(r'<eor>', Body, flags=re.I | re.M))):
            record = {k.upper(): v for k, v in Adi_RegEx.findall(record_text)}

            # Normalize QSO_DATE and TIME_ON fields
            record.setdefault('QSO_DATE', record.pop('QSO_DATE_OFF', None))
            record.setdefault('TIME_ON', record.pop('TIME_OFF', None))

            if not all(k in record for k in ('CALL', 'QSO_DATE', 'TIME_ON')) or record.get('MODE') != 'CW':
                continue

            # Frequency conversion to kHz (default 0.0 if missing or invalid)
            fFrequency = float(record.get('FREQ', 0.0)) * 1000 if record.get('FREQ', '').replace('.', '', 1).isdigit() else 0.0

            # Append QSO data
            self.QSOs.append((
                record['QSO_DATE'] + record['TIME_ON'],
                record['CALL'],
                record.get('STATE', ''),
                fFrequency,
                record.get('COMMENT', '')
            ))

        # Sort QSOs by date
        self.QSOs.sort(key=lambda qso: qso[0])

        # Process and map QSOs by member number
        for qso_date, call_sign, _, _, _ in self.QSOs:
            call_sign = SKCC.ExtractCallSign(call_sign)
            if not call_sign or call_sign == 'K3Y':
                continue

            member_number = SKCC.Members.get(call_sign, {}).get('plain_number')
            if member_number:
                self.QSOsByMemberNumber.setdefault(member_number, []).append(qso_date)

    def CalcPrefixPoints(self) -> int:
        return sum(value[2] for value in self.ContactsForP.values())

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
        if TheirCallSign not in SKCC.Members or TheirCallSign == config.MY_CALLSIGN:
            return []

        TheirMemberEntry  = SKCC.Members[TheirCallSign]
        TheirC_Date       = cUtil.Effective(TheirMemberEntry['c_date'])
        TheirT_Date       = cUtil.Effective(TheirMemberEntry['t_date'])
        TheirS_Date       = cUtil.Effective(TheirMemberEntry['s_date'])
        TheirMemberNumber = TheirMemberEntry['plain_number']

        GoalHitList: list[str] = []

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
                    GoalHitList.append('BRAG')

        if 'C' in config.GOALS and not self.MyC_Date:
            if TheirMemberNumber not in self.ContactsForC:
                GoalHitList.append('C')

        if 'CXN' in config.GOALS and self.MyC_Date:
            if TheirMemberNumber not in self.ContactsForC:
                _, X_Factor = cQSO.CalculateNumerics('C', len(self.ContactsForC))
                GoalHitList.append(AbbreviateClass('C', X_Factor))

        if 'T' in config.GOALS and self.MyC_Date and not self.MyT_Date:
            if TheirC_Date and TheirMemberNumber not in self.ContactsForT:
                GoalHitList.append('T')

        if 'TXN' in config.GOALS and self.MyT_Date:
            if TheirC_Date and TheirMemberNumber not in self.ContactsForT:
                _Remaining, X_Factor = cQSO.CalculateNumerics('T', len(self.ContactsForT))
                GoalHitList.append(AbbreviateClass('T', X_Factor))

        if 'S' in config.GOALS and self.MyTX8_Date and not self.MyS_Date:
            if TheirT_Date and TheirMemberNumber not in self.ContactsForS:
                GoalHitList.append('S')

        if 'SXN' in config.GOALS and self.MyS_Date:
            if TheirT_Date and TheirMemberNumber not in self.ContactsForS:
                _Remaining, X_Factor = cQSO.CalculateNumerics('S', len(self.ContactsForS))
                GoalHitList.append(AbbreviateClass('S', X_Factor))

        if 'WAS' in config.GOALS:
            SPC = TheirMemberEntry['spc']
            if SPC in US_STATES and SPC not in self.ContactsForWAS:
                GoalHitList.append('WAS')

        if 'WAS-C' in config.GOALS:
            if TheirC_Date:
                SPC = TheirMemberEntry['spc']
                if SPC in US_STATES and SPC not in self.ContactsForWAS_C:
                    GoalHitList.append('WAS-C')

        if 'WAS-T' in config.GOALS:
            if TheirT_Date:
                SPC = TheirMemberEntry['spc']
                if SPC in US_STATES and SPC not in self.ContactsForWAS_T:
                    GoalHitList.append('WAS-T')

        if 'WAS-S' in config.GOALS:
            if TheirS_Date:
                SPC = TheirMemberEntry['spc']
                if SPC in US_STATES and SPC not in self.ContactsForWAS_S:
                    GoalHitList.append('WAS-S')

        if 'P' in config.GOALS:
            Match = cQSO.Prefix_RegEx.match(TheirCallSign)

            if Match:
                Prefix = Match.group(1)
                iTheirMemberNumber   = int(TheirMemberNumber)
                _Remaining, X_Factor = cQSO.CalculateNumerics('P', self.CalcPrefixPoints())

                if Prefix in self.ContactsForP:
                    iCurrentMemberNumber = self.ContactsForP[Prefix][2]

                    if iTheirMemberNumber > iCurrentMemberNumber:
                        GoalHitList.append(f'{AbbreviateClass("P", X_Factor)}(+{iTheirMemberNumber - iCurrentMemberNumber})')
                else:
                    GoalHitList.append(f'{AbbreviateClass("P", X_Factor)}(new +{iTheirMemberNumber})')

        return GoalHitList

    def GetTargetHits(self, TheirCallSign: str) -> list[str]:
        if TheirCallSign not in SKCC.Members:
            return []

        if TheirCallSign == config.MY_CALLSIGN:
            return []

        TheirMemberEntry  = SKCC.Members[TheirCallSign]
        TheirJoin_Date    = cUtil.Effective(TheirMemberEntry['join_date'])
        TheirC_Date       = cUtil.Effective(TheirMemberEntry['c_date'])
        TheirT_Date       = cUtil.Effective(TheirMemberEntry['t_date'])
        TheirTX8_Date     = cUtil.Effective(TheirMemberEntry['tx8_date'])
        TheirS_Date       = cUtil.Effective(TheirMemberEntry['s_date'])
        TheirMemberNumber = TheirMemberEntry['plain_number']

        TargetHitList: list[str] = []

        if 'C' in config.TARGETS and not TheirC_Date:
            if TheirMemberNumber in self.QSOsByMemberNumber:
                for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
                    if QsoDate > TheirJoin_Date and QsoDate > self.MyJoin_Date:
                        break
                else:
                    TargetHitList.append('C')
            else:
                TargetHitList.append('C')

        if 'CXN' in config.TARGETS and TheirC_Date:
            NextLevel = SKCC.CenturionLevel[TheirMemberNumber]+1

            if NextLevel <= 10:
                if TheirMemberNumber in self.QSOsByMemberNumber:
                    for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
                        if QsoDate > TheirJoin_Date and QsoDate > self.MyJoin_Date:
                            break
                    else:
                        TargetHitList.append(f'Cx{NextLevel}')
                else:
                    TargetHitList.append(f'Cx{NextLevel}')

        if 'T' in config.TARGETS and TheirC_Date and not TheirT_Date and self.MyC_Date:
            if TheirMemberNumber in self.QSOsByMemberNumber:
                for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
                    if QsoDate > TheirC_Date and QsoDate > self.MyC_Date:
                        break
                else:
                    TargetHitList.append('T')
            else:
                TargetHitList.append('T')

        if 'TXN' in config.TARGETS and TheirT_Date and self.MyC_Date:
            NextLevel = SKCC.TribuneLevel[TheirMemberNumber]+1

            if NextLevel <= 10:
                if TheirMemberNumber in self.QSOsByMemberNumber:
                    for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
                        if QsoDate > TheirC_Date and QsoDate > self.MyC_Date:
                            break
                    else:
                        TargetHitList.append(f'Tx{NextLevel}')
                else:
                    TargetHitList.append(f'Tx{NextLevel}')

        if 'S' in config.TARGETS and TheirTX8_Date and not TheirS_Date and self.MyT_Date:
            if TheirMemberNumber in self.QSOsByMemberNumber:
                for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
                    if QsoDate > TheirTX8_Date and QsoDate > self.MyT_Date:
                        break
                else:
                    TargetHitList.append('S')
            else:
                TargetHitList.append('S')

        if 'SXN' in config.TARGETS and TheirS_Date and self.MyT_Date:
            NextLevel = SKCC.SenatorLevel[TheirMemberNumber] + 1

            if NextLevel <= 10:
                if TheirMemberNumber in self.QSOsByMemberNumber:
                    for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
                        if QsoDate > TheirTX8_Date and QsoDate > self.MyT_Date:
                            break
                    else:
                        TargetHitList.append(f'Sx{NextLevel}')
                else:
                    TargetHitList.append(f'Sx{NextLevel}')

        return TargetHitList

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
                TheirJoin_Date = cUtil.Effective(TheirMemberEntry['join_date'])

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
            TheirJoin_Date    = cUtil.Effective(TheirMemberEntry['join_date'])
            TheirC_Date       = cUtil.Effective(TheirMemberEntry['c_date'])
            TheirT_Date       = cUtil.Effective(TheirMemberEntry['t_date'])
            TheirS_Date       = cUtil.Effective(TheirMemberEntry['s_date'])

            TheirMemberNumber = TheirMemberEntry['plain_number']

            #fastQsoDate = cFastDateTime(QsoDate)

            # K3Y
            if 'K3Y' in config.GOALS:
                StartDate = f'{config.K3Y_YEAR}0102000000'
                EndDate   = f'{config.K3Y_YEAR}0201000000'

                if QsoDate >= StartDate and QsoDate < EndDate:
                    K3Y_RegEx = r'.*?(?:K3Y|SKM)[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)'
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
                        QsoSPC, QsoDate, QsoCallSign = QSOsByState[State]
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
            print(f'K3Y {config.K3Y_YEAR}')
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
                _Prefix, Suffix = re.split('[/-]', Station)

                def PrintBand(Band: int):
                    if (Suffix in self.ContactsForK3Y) and (Band in self.ContactsForK3Y[Suffix]):
                        print(f'{" " + self.ContactsForK3Y[Suffix][Band]: <7}|', end = '')
                    else:
                        print(f'{"": <7}|', end = '')

                print(f'{Station: <8}|', end = '')
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

            PrintStation('K3Y/0')
            PrintStation('K3Y/1')
            PrintStation('K3Y/2')
            PrintStation('K3Y/3')
            PrintStation('K3Y/4')
            PrintStation('K3Y/5')
            PrintStation('K3Y/6')
            PrintStation('K3Y/7')
            PrintStation('K3Y/8')
            PrintStation('K3Y/9')
            PrintStation('K3Y/KH6')
            PrintStation('K3Y/KL7')
            PrintStation('K3Y/KP4')
            PrintStation('SKM-AF')
            PrintStation('SKM-AS')
            PrintStation('SKM-EU')
            PrintStation('SKM-NA')
            PrintStation('SKM-OC')
            PrintStation('SKM-SA')

        if 'K3Y' in config.GOALS:
            PrintK3Y_Contacts()

class cSpotters:
    def __init__(self):
        self.Spotters: dict[str, tuple[int, list[int]]] = {}

    @staticmethod
    def locator_to_latlong(locator: str) -> tuple[float, float]:
        """Converts a Maidenhead locator into corresponding WGS84 coordinates."""
        locator = locator.upper()
        length = len(locator)

        if length not in {4, 6} or any(
            not ('A' <= locator[i] <= 'R') if i in {0, 1} else
            not ('0' <= locator[i] <= '9') if i in {2, 3} else
            not ('A' <= locator[i] <= 'X') for i in range(length)
        ):
            raise ValueError("Invalid Maidenhead locator.")

        longitude = (ord(locator[0]) - ord('A')) * 20 - 180 + (ord(locator[2]) - ord('0')) * 2
        latitude = (ord(locator[1]) - ord('A')) * 10 - 90 + (ord(locator[3]) - ord('0'))

        if length == 6:
            longitude += (ord(locator[4]) - ord('A')) * (2 / 24) + (1 / 24.0)
            latitude += (ord(locator[5]) - ord('A')) * (1 / 24) + (0.5 / 24.0)
        else:
            longitude += 1
            latitude += 0.5

        return latitude, longitude

    @staticmethod
    def calculate_distance(locator1: str, locator2: str) -> float:
        """Calculates the great-circle distance between two Maidenhead locators in km."""
        R = 6371  # Earth radius in km

        try:
            lat1, lon1 = cSpotters.locator_to_latlong(locator1)
            lat2, lon2 = cSpotters.locator_to_latlong(locator2)
        except Exception as e:
            raise ValueError(f"Invalid Maidenhead locator: {e}")

        # Compute differences in latitude and longitude
        lat_diff: float = lat2 - lat1
        lon_diff: float = lon2 - lon1

        # Convert differences to radians
        d_lat: float = radians(lat_diff)
        d_lon: float = radians(lon_diff)

        # Convert individual latitudes to radians
        r_lat1: float = radians(lat1)
        r_lat2: float = radians(lat2)

        a = sin(d_lat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(d_lon / 2) ** 2
        return 2 * R * atan2(sqrt(a), sqrt(1 - a))

    def GetSpotters(self) -> None:
        def parse_bands(band_csv: str) -> list[int]:
            valid_bands = {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"}
            return [int(b[:-1]) for b in band_csv.split(',') if b in valid_bands]

        print(f"\nFinding RBN spotters within {config.SPOTTER_RADIUS} miles of '{config.MY_GRIDSQUARE}'...")

        try:
            response = requests.get('https://reversebeacon.net/cont_includes/status.php?t=skt', timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            print('*** Fatal Error: Unable to retrieve spotters from RBN. Is RBN down?')
            sys.exit()

        rows = re.findall(r'<tr.*?online24h online7d total">(.*?)</tr>', response.text, re.S)

        columns_regex = re.compile(
            r'<td.*?><a href="/dxsd1.php\?f=.*?>\s*(.*?)\s*</a>.*?</td>\s*'
            r'<td.*?>\s*(.*?)</a></td>\s*<td.*?>(.*?)</td>',
            re.S
        )

        for row in rows:
            for spotter, csv_bands, grid in columns_regex.findall(row):
                if grid == "XX88LL":
                    continue

                try:
                    miles = int(cSpotters.calculate_distance(config.MY_GRIDSQUARE, grid) * 0.62137)
                    self.Spotters[spotter] = (miles, parse_bands(csv_bands))
                except ValueError:
                    continue


    def GetNearbySpotters(self) -> list[tuple[str, int]]:
        spotters_sorted = sorted(self.Spotters.items(), key=lambda item: item[1][0])
        nearbySpotters = [(spotter, miles) for spotter, (miles, _) in spotters_sorted if miles <= config.SPOTTER_RADIUS]
        return nearbySpotters

    def GetDistance(self, Spotter: str) -> int:
        Miles, _ = self.Spotters[Spotter]
        return Miles

class cSKCC:
    CenturionLevel: dict[str, int]
    TribuneLevel: dict[str, int]
    SenatorLevel: dict[str, int]

    MonthAbbreviations: dict[str, int] = {
        'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4,  'May':5,  'Jun':6,
        'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12
    }

    CallingFrequenciesKHz: dict[int, list[float]] = {
        160 : [1813.5],
        80  : [3530,  3550],
        60  : [],
        40  : [7038, 7055, 7114],
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
        start_time = cFastDateTime((Year, Month, 1)).FirstWeekdayFromDate('Sat').FirstWeekdayAfterDate('Sat') + timedelta(hours=12)
        return start_time, start_time + timedelta(hours=35, minutes=59, seconds=59)

    @staticmethod
    def SKS(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
        start_date = cFastDateTime((Year, Month, 1))

        for _ in range(4):  # Loop exactly 4 times
            start_date = start_date.FirstWeekdayAfterDate('Wed')

        return start_date, start_date + timedelta(hours=2)

    @staticmethod
    def SKSA(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
        start_time = cFastDateTime((Year, Month, 1)).FirstWeekdayFromDate('Fri').FirstWeekdayAfterDate('Fri') + timedelta(hours=22)
        return start_time, start_time + timedelta(hours=1, minutes=59, seconds=59)

    @staticmethod
    def SKSE(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
        start_time = cFastDateTime((Year, Month, 1)).FirstWeekdayFromDate('Thu') + timedelta(hours=20 if Month in {1, 2, 3, 11, 12} else 19)
        return start_time, start_time + timedelta(hours=1, minutes=59, seconds=59)

    @staticmethod
    def DuringSprint(fastDateTime: cFastDateTime) -> bool:
        year, month = fastDateTime.Year(), fastDateTime.Month()

        return any(
            start <= fastDateTime <= end
            for start, end in (cSKCC.WES(year, month),  cSKCC.SKS(year, month),
                               cSKCC.SKSE(year, month), cSKCC.SKSA(year, month))
        )

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
            return ""

        sDay, sMonthAbbrev, sYear = Date.split()
        return f"{int(sYear):04}{cSKCC.MonthAbbreviations[sMonthAbbrev]:02}{int(sDay):02}000000"

    def ExtractCallSign(self, CallSign: str) -> str | None:
        # Strip punctuation except '/'
        CallSign = CallSign.strip(string.punctuation.replace("/", ""))

        if CallSign in self.Members or CallSign == "K3Y":
            return CallSign

        if "/" in CallSign:
            parts = CallSign.split("/")
            if len(parts) in {2, 3}:  # Valid cases
                prefix, suffix = parts[:2]
                return prefix if prefix in self.Members else suffix if suffix in self.Members else None

        return None

    @staticmethod
    def ReadLevelList(Type: str, URL: str) -> dict[str, int] | NoReturn:
        print(f"Retrieving SKCC award info from {URL}...")

        try:
            response = requests.get(f"https://www.skccgroup.com/{URL}", timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error retrieving award info: {e}")
            sys.exit(1)

        today_gmt = time.strftime("%Y%m%d000000", time.gmtime())
        level: dict[str, int] = {}

        for line in response.text.splitlines()[1:]:
            try:
                cert_number, call_sign, member_number, *_rest, effective_date, endorsements = line.split("|")
            except ValueError:
                continue  # Skip malformed lines

            x_factor = int(cert_number.split()[1][1:]) if " " in cert_number else 1
            level[member_number] = x_factor

            skcc_effective_date = cSKCC.NormalizeSkccDate(effective_date)

            if today_gmt < skcc_effective_date:
                print(f"  FYI: Brand new {Type}, {call_sign}, will be effective 00:00Z {effective_date}")
            elif Type == "Tribune" and (match := re.search(r"\*Tx8: (.*?)$", endorsements)):
                skcc_effective_tx8_date = cSKCC.NormalizeSkccDate(match.group(1))
                if today_gmt < skcc_effective_tx8_date:
                    print(f"  FYI: Brand new Tx8, {call_sign}, will be effective 00:00Z {match.group(1)}")

        return level

    @staticmethod
    def ReadRoster(Name: str, URL: str) -> dict[str, int] | NoReturn:
        print(f"Retrieving SKCC {Name} roster...")

        try:
            response = requests.get(f"https://www.skccgroup.com/{URL}", timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error retrieving {Name} roster: {e}")
            sys.exit(1)

        rows = re.findall(r"<tr.*?>(.*?)</tr>", response.text, re.I | re.S)
        columns_regex = re.compile(r"<td.*?>(.*?)</td>", re.I | re.S)

        return {
            (cols := columns_regex.findall(row))[1]: int(cols[0].split()[1][1:]) if " " in cols[0] else 1
            for row in rows[1:]
            if (cols := columns_regex.findall(row))  # Ensure valid row data
        }

    def ReadSkccData(self) -> None | NoReturn:
        print('Retrieving SKCC award dates...')

        try:
            response = requests.get('https://www.skccgroup.com/membership_data/skccdata.txt')
        except requests.exceptions.RequestException:
            print(f"Unable to retrieve award dates from main SKCC website.  Exiting.")
            sys.exit(1)

        if response.status_code != 200:
            return

        SkccList = response.text
        Lines = SkccList.splitlines()

        for line in Lines[1:]:
            try:
                fields = line.split("|")
                (
                    _number, current_call, name, _city, spc, other_calls, plain_number,_, join_date, c_date, t_date, tx8_date, s_date, _country
                ) = fields
            except ValueError:
                print("Error parsing SKCC data. Exiting.")
                sys.exit(1)

            all_calls = [current_call] + [x.strip() for x in other_calls.split(",")] if other_calls else [current_call]


            for call in all_calls:
                self.Members[call] = {
                    'name'         : name,
                    'plain_number' : plain_number,
                    'spc'          : spc,
                    'join_date'    : cSKCC.NormalizeSkccDate(join_date),
                    'c_date'       : cSKCC.NormalizeSkccDate(c_date),
                    't_date'       : cSKCC.NormalizeSkccDate(t_date),
                    'tx8_date'     : cSKCC.NormalizeSkccDate(tx8_date),
                    's_date'       : cSKCC.NormalizeSkccDate(s_date),
                    'main_call'    : current_call,
                }

    @staticmethod
    def IsOnSkccFrequency(FrequencyKHz: float, ToleranceKHz: int = 10) -> bool:
        return (
            5332 - 1.5 <= FrequencyKHz <= 5405 + 1.5
            if 60 in cSKCC.CallingFrequenciesKHz
            else any(
                (MidPoint - ToleranceKHz) <= FrequencyKHz <= (MidPoint + ToleranceKHz)
                for Band, MidPoints in cSKCC.CallingFrequenciesKHz.items()
                if Band != 60
                for MidPoint in MidPoints
            )
        )

    @staticmethod
    def WhichBand(FrequencyKHz: float, ToleranceKHz: float = 10) -> int | None:
        return next(
            (Band for Band, MidPointsKHz in cSKCC.CallingFrequenciesKHz.items()
            for MidPointKHz in MidPointsKHz
            if (MidPointKHz - ToleranceKHz) <= FrequencyKHz <= (MidPointKHz + ToleranceKHz)),
            None
        )

    @staticmethod
    def WhichArrlBand(FrequencyKHz: float) -> int | None:
        for band, lower, upper in [
            (160,  1800,  2000),
            (80,   3500,  3600),
            (40,   7000,  7125),
            (30,  10100, 10150),
            (20,  14000, 14150),
            (17,  18068, 18168),
            (15,  21000, 21450),
            (12,  24890, 24990),
            (10,  28000, 29700),
            (6,   50000, 54000),
        ]:
            if lower < FrequencyKHz < upper:
                return band

        return None

    @staticmethod
    def IsOnWarcFrequency(FrequencyKHz: float, ToleranceKHz: int = 10) -> bool:
        return any(
            (CallingFrequencyKHz - ToleranceKHz) <= FrequencyKHz <= (CallingFrequencyKHz + ToleranceKHz)
            for Band in (30, 17, 12)
            for CallingFrequencyKHz in cSKCC.CallingFrequenciesKHz[Band]
        )


    def GetFullMemberNumber(self, CallSign: str) -> tuple[str, str]:
        Entry = self.Members[CallSign]

        MemberNumber = Entry['plain_number']

        Suffix = ''
        Level  = 1

        if cUtil.Effective(Entry['s_date']):
            Suffix = 'S'
            Level = self.SenatorLevel[MemberNumber]
        elif cUtil.Effective(Entry['t_date']):
            Suffix = 'T'
            Level = self.TribuneLevel[MemberNumber]

            if Level == 8 and not cUtil.Effective(Entry['tx8_date']):
                Level = 7
        elif cUtil.Effective(Entry['c_date']):
            Suffix = 'C'
            Level = self.CenturionLevel[MemberNumber]

        if Level > 1:
            Suffix += f'x{Level}'

        return (MemberNumber, Suffix)

def Log(Line: str) -> None:
    if config.LOG_FILE.ENABLED and config.LOG_FILE.FILE_NAME is not None:
        with open(config.LOG_FILE.FILE_NAME, 'a', encoding='utf-8') as File:
            File.write(Line + '\n')

def LogError(Line: str) -> None:
    if config.LOG_BAD_SPOTS:
        with open('Bad_RBN_Spots.log', 'a', encoding='utf-8') as File:
            File.write(Line + '\n')

def signal_handler(_signal: int, _frame: FrameType | None) -> NoReturn:
    sys.exit()

def AbbreviateClass(Class: str, X_Factor: int) -> str:
    if X_Factor > 1:
        return f'{Class}x{X_Factor}'

    return Class

def BuildMemberInfo(CallSign: str) -> str:
    entry = SKCC.Members[CallSign]
    number, suffix = SKCC.GetFullMemberNumber(CallSign)

    return f'({number:>5} {suffix:<4} {entry["name"]:<9.9} {entry["spc"]:>3})'

def IsInBANDS(FrequencyKHz: float) -> bool:
    bands: dict[int, tuple[float, float]] = {
        160: (1800.0, 2000.0),
        80:  (3500.0, 4000.0),
        60:  (5330.5 - 1.5, 5403.5 + 1.5),  # Small buffer for band edges
        40:  (7000.0, 7300.0),
        30:  (10100.0, 10150.0),
        20:  (14000.0, 14350.0),
        17:  (18068.0, 18168.0),
        15:  (21000.0, 21450.0),
        12:  (24890.0, 24990.0),
        10:  (28000.0, 29700.0),
        6:   (50000.0, 50100.0),
    }

    return any(
        band in config.BANDS and lowKHz <= FrequencyKHz <= highKHz
        for band, (lowKHz, highKHz) in bands.items()
    )


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

    LookupList = cUtil.Split(LookupString.upper())

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


class cRBN:
    @staticmethod
    async def feed_generator(callsign: str) -> AsyncGenerator[bytes, None]:
        while True:
            reader: asyncio.StreamReader | None = None
            writer: asyncio.StreamWriter | None = None

            try:
                reader, writer = await asyncio.open_connection(RBN_SERVER, RBN_PORT)

                await reader.readuntil(b"call: ")
                writer.write(f"{callsign}\r\n".encode("ascii"))
                await writer.drain()
                await reader.readuntil(b">\r\n\r\n")

                while True:
                    yield await reader.readuntil(b'\n')

            except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError) as e:
                print(f"RBN feed connection error: {e}, reconnecting...")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Unexpected RBN feed error: {e}")
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass


#
# Main
#

#
# cVersion is an uncontrolled file (not committed to Git).  It is created by
# a release script to properly identify the version stamp of the release, so
# this code imports the file if it exists or, if it does not, reverts to a
# generic string.
#

VERSION: str | None = None

try:
    from Lib.cVersion import VERSION
except ImportError:
    VERSION = '<dev>'

print(f'SKCC Skimmer version {VERSION}\n')

US_STATES: list[str] = [
    'AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD',
    'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH',
    'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY',
]

ArgV = sys.argv[1:]

config = cConfig(ArgV)

cSKCC.BlockDuringUpdateWindow()

Levels: dict[str, int] = {
    'C'  :    100,
    'T'  :     50,
    'S'  :    200,
    'P'  : 500000,
}

if config.VERBOSE:
    config.PROGRESS_DOTS.ENABLED = False

FileCheck(config.ADI_FILE)

SKCC = cSKCC()

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

nearby_list_with_distance = Spotters.GetNearbySpotters()
formatted_nearby_list_with_distance = [f'{Spotter}({cUtil.FormatDistance(Miles)})'  for Spotter, Miles in nearby_list_with_distance]
SPOTTERS_NEARBY = [Spotter  for Spotter, _ in nearby_list_with_distance]

print(f'  Found {len(formatted_nearby_list_with_distance)} nearby spotters:')

wrapped_spotter_lines = textwrap.wrap(', '.join(formatted_nearby_list_with_distance), width=80)

for spotter_line in wrapped_spotter_lines:
    print(f'    {spotter_line}')

if config.LOG_FILE.DELETE_ON_STARTUP:
    Filename = config.LOG_FILE.FILE_NAME

    if Filename is not None and os.path.exists(Filename):
        os.remove(Filename)

eventLoop = asyncio.new_event_loop()
asyncio.set_event_loop(eventLoop)

print()
print('Running...')
print()

def watch_for_ctrl_c():
    """Runs in a separate thread to detect Ctrl+C on Windows."""
    try:
        while not shutdown_event.is_set():
            pass #signal.pause()  # Blocks until a signal is received (Linux/macOS only)
    except KeyboardInterrupt:
        handle_shutdown()

async def run():
    """Starts all conditional tasks with proper Ctrl+C handling."""
    # Handle Ctrl+C for Windows
    if platform.system() == "win32":
        thread = threading.Thread(target=watch_for_ctrl_c, daemon=True)
        thread.start()
    else:
        signal.signal(signal.SIGINT, lambda sig, frame: handle_shutdown())

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(cQSO.WatchLogFile()),
        asyncio.create_task(cSPOTS.HandleSpots()),
        asyncio.create_task(cDisplay.DotsLoop()),
    ]

    if config.SKED.ENABLED:
        tasks.append(asyncio.create_task(cSked.RunForever()))

    await shutdown_event.wait()
    print(f"Shutdown event received. Cancelling {len(tasks)} tasks...")

    # Cancel all tasks
    for task in tasks:
        task.cancel()

    # Wait for them to finish
    await asyncio.gather(*tasks, return_exceptions=True)

    print("All tasks finished. Exiting cleanly.")

asyncio.run(run())

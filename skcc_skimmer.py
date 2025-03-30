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


from datetime import timedelta, datetime
from typing import Any, NoReturn, Literal, get_args, AsyncGenerator, ClassVar, Final
from math import radians, sin, cos, atan2, sqrt
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

import asyncio
import argparse
import signal
import socket
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

RBN_SERVER = 'telnet.reversebeacon.net'
RBN_PORT   = 7000

US_STATES: Final[list[str]] = [
    'AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD',
    'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH',
    'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY',
]

Levels: Final[dict[str, int]] = {
    'C'  :    100,
    'T'  :     50,
    'S'  :    200,
    'P'  : 500000,
}

class cUtil:
    @staticmethod
    def split(text: str) -> list[str]:
        return re.split(r'[,\s]+', text.strip())

    @staticmethod
    def effective(date: str) -> str:
        return date if time.strftime('%Y%m%d000000', time.gmtime()) >= date else ''

    @staticmethod
    def miles_to_km(Miles: int) -> int:
        return round(Miles * 1.609344)

    @staticmethod
    def stripped(text: str) -> str:
        return ''.join([c for c in text if 31 < ord(c) < 127])

    @staticmethod
    def beep() -> None:
        print('\a', end='', flush=True)

    @staticmethod
    def format_distance(Miles: int) -> str:
        if config.DISTANCE_UNITS == "mi":
            return f'{Miles}mi'

        return f'{cUtil.miles_to_km(Miles)}km'

    @staticmethod
    def log(Line: str) -> None:
        if config.LOG_FILE.ENABLED and config.LOG_FILE.FILE_NAME is not None:
            with open(config.LOG_FILE.FILE_NAME, 'a', encoding='utf-8') as File:
                File.write(Line + '\n')

    @staticmethod
    def log_error(Line: str) -> None:
        if config.LOG_BAD_SPOTS:
            with open('Bad_RBN_Spots.log', 'a', encoding='utf-8') as File:
                File.write(Line + '\n')

    @staticmethod
    def abbreviate_class(Class: str, X_Factor: int) -> str:
        if X_Factor > 1:
            return f'{Class}x{X_Factor}'

        return Class

    @staticmethod
    def build_member_info(CallSign: str) -> str:
        entry = cSKCC.members[CallSign]
        number, suffix = cSKCC.get_full_member_number(CallSign)

        return f'({number:>5} {suffix:<4} {entry["name"]:<9.9} {entry["spc"]:>3})'

    @staticmethod
    def file_check(Filename: str) -> None | NoReturn:
        if os.path.exists(Filename):
            return

        print('')
        print(f"File '{Filename}' does not exist.")
        print('')
        sys.exit()

    @staticmethod
    def is_in_bands(FrequencyKHz: float) -> bool:
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

    @staticmethod
    def handle_shutdown(signum: int, frame: object | None = None) -> None:
        """Exits immediately when Ctrl+C is detected."""
        print("\nExiting immediately on Ctrl+C...")
        # Force immediate exit without any cleanup
        os._exit(0)

    @staticmethod
    def watch_for_ctrl_c():
        """Runs in a separate thread to detect Ctrl+C on Windows."""
        try:
            # Just wait for KeyboardInterrupt
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nExiting immediately on Ctrl+C...")
            os._exit(0)

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
        DEFAULT_CONDITION = ['goals', 'targets', 'friends']  # Class-level default
        ENABLED: bool = True
        CONDITION: list[str] = field(default_factory=lambda: cConfig.cNotification.DEFAULT_CONDITION)
        RENOTIFICATION_DELAY_SECONDS: int = 30
    def init_notifications(self):
        notification_config = self.configFile.get("NOTIFICATION", {})
        conditions = cUtil.split(notification_config.get("CONDITION", cConfig.cNotification.DEFAULT_CONDITION))  # Use DEFAULT_CONDITION
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
        def read_skcc_skimmer_cfg() -> dict[str, Any]:
            config_vars: dict[str, Any] = {}

            ConfigFileAbsolute = os.path.abspath('skcc_skimmer.cfg')
            cDisplay.print(f"Reading skcc_skimmer.cfg from '{ConfigFileAbsolute}'...")
            with open(ConfigFileAbsolute, 'r', encoding='utf-8') as configFile:
                ConfigFileString = configFile.read()
                exec(ConfigFileString, {}, config_vars)

            return config_vars

        self.configFile = read_skcc_skimmer_cfg()

        self.MY_CALLSIGN = self.configFile.get('MY_CALLSIGN', '')
        self.ADI_FILE = self.configFile.get('ADI_FILE', '')
        self.MY_GRIDSQUARE = self.configFile.get('MY_GRIDSQUARE', '')

        if 'SPOTTER_RADIUS' in self.configFile:
            self.SPOTTER_RADIUS = int(self.configFile['SPOTTER_RADIUS'])

        if 'GOALS' in self.configFile:
            self.GOALS = self.parse_goals(self.configFile['GOALS'], 'C CXN T TXN S SXN WAS WAS-C WAS-T WAS-S P BRAG K3Y', 'goal')

        if 'TARGETS' in self.configFile:
            self.TARGETS = self.parse_goals(self.configFile['TARGETS'], 'C CXN T TXN S SXN', 'target')

        if 'BANDS' in self.configFile:
            self.BANDS = [int(Band)  for Band in cUtil.split(self.configFile['BANDS'])]

        if 'FRIENDS' in self.configFile:
            self.FRIENDS = [friend  for friend in cUtil.split(self.configFile['FRIENDS'])]

        if 'EXCLUSIONS' in self.configFile:
            self.EXCLUSIONS = [friend  for friend in cUtil.split(self.configFile['EXCLUSIONS'])]

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
            self.BANDS = [int(band) for band in cUtil.split(args.bands)]
        if args.brag_months:
            self.BRAG_MONTHS = args.brag_months
        if args.callsign:
            self.MY_CALLSIGN = args.callsign.upper()
        if args.distance_units:
            self.DISTANCE_UNITS = args.distance_units
        if args.goals:
            self.GOALS = self.parse_goals(args.goals, "C CXN T TXN S SXN WAS WAS-C WAS-T WAS-S P BRAG K3Y", "goal")
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
            self.TARGETS = self.parse_goals(args.targets, "C CXN T TXN S SXN", "target")

    def _ValidateConfig(self):
        #
        # MY_CALLSIGN can be defined in skcc_skimmer.cfg.  It is not required
        # that it be supplied on the command line.
        #
        if not self.MY_CALLSIGN:
            print("You must specify your callsign, either on the command line or in 'skcc_skimmer.cfg'.")
            print('')
            self.usage()

        if not self.ADI_FILE:
            print("You must supply an ADI file, either on the command line or in 'skcc_skimmer.cfg'.")
            print('')
            self.usage()

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

    def usage(self) -> NoReturn:
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

    def parse_goals(self, String: str, ALL_str: str, Type: str) -> list[str]:
        ALL    = ALL_str.split()
        parsed = cUtil.split(String.upper())

        # Using pattern matching simplifies the logic
        match parsed:
            case ['ALL']: return ALL
            case ['NONE']: return []
            case items:
                # Add implied dependencies
                for x in ['CXN', 'TXN', 'SXN']:
                    base = x[0]
                    if x in items and base not in items:
                        items.append(base)

                # Check for invalid items
                invalid = [x for x in items if x not in ALL]
                if invalid:
                    print(f"Unrecognized {Type} '{invalid[0]}'.")
                    sys.exit()

                return items

class cFastDateTime:
    FastDateTime: str

    MONTH_NAMES: Final = tuple('January February March April May June July August September October November December'.split())

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

    def split_date_time(self) -> list[int]:
        return list(map(int, [self.FastDateTime[:4],   self.FastDateTime[4:6],   self.FastDateTime[6:8],
                              self.FastDateTime[8:10], self.FastDateTime[10:12], self.FastDateTime[12:14]]))

    def start_of_month(self) -> 'cFastDateTime':
        Year, Month, _Day, _Hour, _Minute, _Second = self.split_date_time()
        return cFastDateTime(f'{Year:0>4}{Month:0>2}{1:0>2}000000')

    def end_of_month(self) -> 'cFastDateTime':
        Year, Month, _Day, _Hour, _Minute, _Second = self.split_date_time()
        _, DaysInMonth = calendar.monthrange(Year, Month)
        return cFastDateTime(f'{Year:0>4}{Month:0>2}{DaysInMonth:0>2}235959')

    def year(self) -> int:
        return int(self.FastDateTime[0:4])

    def month(self) -> int:
        return int(self.FastDateTime[4:6])

    def to_datetime(self) -> datetime:
        return datetime.strptime(self.FastDateTime, '%Y%m%d%H%M%S')

    def first_weekday_from_date(self, TargetWeekday: str) -> 'cFastDateTime':
        TargetWeekdayNumber = time.strptime(TargetWeekday, '%a').tm_wday
        DateTime = self.to_datetime()

        while DateTime.weekday() != TargetWeekdayNumber:
            DateTime += timedelta(days=1)

        return cFastDateTime(DateTime)

    def first_weekday_after_date(self, TargetWeekday: str) -> 'cFastDateTime':
        TargetWeekdayNumber = time.strptime(TargetWeekday, '%a').tm_wday
        DateTime = self.to_datetime()

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
        return cFastDateTime(self.to_datetime() + Delta)

    @staticmethod
    def now_gmt() -> 'cFastDateTime':
        return cFastDateTime(time.gmtime())

class cDisplay:
    @staticmethod
    def print(text: str):
        if cRBN.dot_count > 0:
            print()

        print(text)
        cRBN.dot_count_reset()

class cSked:
    _RegEx:          ClassVar[re.Pattern[str]] = re.compile('<span class="callsign">(.*?)<span>(?:.*?<span class="userstatus">(.*?)</span>)?')
    _SkedSite:       ClassVar[str | None] = None

    _PreviousLogins: ClassVar[dict[str, list[str]]] = {}
    _FirstPass:      ClassVar[bool] = True

    @classmethod
    def handle_logins(cls, SkedLogins: list[tuple[str, str]], Heading: str):
        SkedHit: dict[str, list[str]] = {}
        GoalList: list[str] = []
        TargetList: list[str] = []

        for CallSign, Status in SkedLogins:
            if CallSign == config.MY_CALLSIGN:
                continue

            CallSign = cSKCC.extract_callsign(CallSign)

            if not CallSign:
                continue

            if CallSign in config.EXCLUSIONS:
                continue

            Report: list[str] = [cUtil.build_member_info(CallSign)]

            if CallSign in cSPOTS.last_spotted:
                FrequencyKHz, StartTime = cSPOTS.last_spotted[CallSign]

                Now = time.time()
                DeltaSeconds = max(int(Now - StartTime), 1)

                if DeltaSeconds > config.SPOT_PERSISTENCE_MINUTES * 60:
                    del cSPOTS.last_spotted[CallSign]
                elif DeltaSeconds > 60:
                    DeltaMinutes = DeltaSeconds // 60
                    Units = 'minutes' if DeltaMinutes > 1 else 'minute'
                    Report.append(f'Last spotted {DeltaMinutes} {Units} ago on {FrequencyKHz}')
                else:
                    Units = 'seconds' if DeltaSeconds > 1 else 'second'
                    Report.append(f'Last spotted {DeltaSeconds} {Units} ago on {FrequencyKHz}')

            GoalList = []

            if 'K3Y' in config.GOALS:
                def collect_station() -> tuple[str, str] | None:
                    K3Y_RegEx = r'\b(K3Y)/([0-9]|KP4|KH6|KL7)\b'
                    Matches = re.search(K3Y_RegEx, Status, re.IGNORECASE)

                    if Matches:
                        return Matches.group(1), Matches.group(2).upper()

                    SKM_RegEx = r'\b(SKM)[\/-](AF|AS|EU|NA|OC|SA)\b'
                    Matches = re.search(SKM_RegEx, Status, re.IGNORECASE)

                    if Matches:
                        return Matches.group(1), Matches.group(2).upper()

                    return None

                def collect_frequency_khz() -> float | None:
                    # Group 1 examples: 7.055.5 14.055.5
                    # Group 2 examples: 7.055   14.055
                    # Group 3 examples: 7055.5  14055.5
                    # Group 4 examples: 7055    14055
                    Freq_RegEx = re.compile(r"\b(\d{1,2}\.\d{3}\.\d{1,3})|(\d{1,2}\.\d{3})|(\d{4,5}\.\d{1,3})|(\d{4,5})\b\s*$")

                    if match := Freq_RegEx.search(Status):
                        FrequencyStr = match.group(1) or match.group(2) or match.group(3) or match.group(4)

                        if FrequencyStr:
                            return float(FrequencyStr.replace('.', '', 1)) if match.group(1) else float(FrequencyStr) * (1000 if match.group(2) else 1)

                    return None

                def combine(Type: str, Station: str):
                    if Type == 'SKM':
                        return f'SKM-{Station}'
                    else:
                        return f'K3Y/{Station}'

                if Status != '':
                    FullTuple = collect_station()

                    if FullTuple:
                        Type, Station = FullTuple
                        FrequencyKHz = collect_frequency_khz()

                        if FrequencyKHz:
                            Band = cSKCC.which_band(FrequencyKHz)

                            if Band:
                                if (not Station in cQSO.ContactsForK3Y) or (not Band in cQSO.ContactsForK3Y[Station]):
                                    GoalList.append(f'{combine(Type, Station)} ({Band}m)')
                        else:
                            GoalList.append(f'{combine(Type, Station)}')

            GoalList = GoalList + cQSO.get_goal_hits(CallSign)

            if GoalList:
                Report.append(f'YOU need them for {",".join(GoalList)}')

            TargetList = cQSO.get_target_hits(CallSign)

            if TargetList:
                Report.append(f'THEY need you for {",".join(TargetList)}')

            IsFriend = CallSign in config.FRIENDS

            if IsFriend:
                Report.append('friend')

            if Status:
                Report.append(f'STATUS: {cUtil.stripped(Status)}')

            if TargetList or GoalList or IsFriend:
                SkedHit[CallSign] = Report

        if SkedHit:
            GMT = time.gmtime()
            ZuluTime = time.strftime('%H%MZ', GMT)
            ZuluDate = time.strftime('%Y-%m-%d', GMT)

            if cls._FirstPass:
                NewLogins = []
            else:
                NewLogins = list(set(SkedHit)-set(cls._PreviousLogins))

            cDisplay.print('=========== '+Heading+' Sked Page '+'=' * (16-len(Heading)))

            for CallSign in sorted(SkedHit):
                if CallSign in NewLogins:
                    if config.NOTIFICATION.ENABLED:
                        if (CallSign in config.FRIENDS and 'friends' in config.NOTIFICATION.CONDITION) or (GoalList and 'goals' in config.NOTIFICATION.CONDITION) or (TargetList and 'targets' in config.NOTIFICATION.CONDITION):
                            cUtil.beep()

                    NewIndicator = '+'
                else:
                    NewIndicator = ' '

                Out = f'{ZuluTime}{NewIndicator}{CallSign:<6} {"; ".join(SkedHit[CallSign])}'
                cDisplay.print(Out)
                cUtil.log(f'{ZuluDate} {Out}')

        return SkedHit

    @classmethod
    def display_logins(cls) -> None:
        try:
            response = requests.get('http://sked.skccgroup.com/get-status.php', timeout=10)

            if response.status_code != 200:
                return

            Content = response.text
            Hits = {}

            if Content:
                try:
                    SkedLogins: list[tuple[str, str]] = json.loads(Content)
                    Hits = cls.handle_logins(SkedLogins, 'SKCC')
                except Exception as ex:
                    with open('DEBUG.txt', 'a', encoding='utf-8') as File:
                        File.write(Content + '\n')

                    print(f"*** Problem parsing data sent from the SKCC Sked Page: '{Content}'.  Details: '{ex}'.")

            cls._PreviousLogins = Hits
            cls._FirstPass = False

            if Hits:
                cDisplay.print('=======================================')
        except Exception as e:
            print(f"\nProblem retrieving information from the Sked Page: {e}. Skipping...")

    @classmethod
    async def sked_page_scraper_task(cls):
        while True:
            try:
                cls.display_logins()
            except Exception as e:
                print(f"Error in DisplayLogins: {e}")

            await asyncio.sleep(config.SKED.CHECK_SECONDS)

class cSPOTS:
    last_spotted: ClassVar[dict[str, tuple[float, float]]] = {}
    _Notified:    ClassVar[dict[str, float]] = {}

    _Zulu_RegEx:  ClassVar[re.Pattern[str]] = re.compile(r'^([01]?[0-9]|2[0-3])[0-5][0-9]Z$')
    _dB_RegEx:    ClassVar[re.Pattern[str]] = re.compile(r'^\s{0,1}\d{1,2} dB$')

    @classmethod
    async def handle_spots_task(cls):
        generator = cRBN.feed_generator(config.MY_CALLSIGN)

        async for data in generator:
            try:
                line = data.rstrip().decode("ascii", errors="replace")
                cSPOTS.handle_spot(line)
            except Exception as e:
                # Don't let processing errors crash the whole task
                print(f"Error processing spot: {e}")
                continue

    @staticmethod
    def parse_spot(Line: str) -> None | tuple[str, str, float, str, str, int, int]:
        # Using pattern matching to simplify the code
        if len(Line) != 75 or not Line.startswith('DX de '):
            cUtil.log_error(Line)
            return None

        try:
            # Basic extraction
            Spotter, FrequencyKHzStr = Line[6:24].split('-#:')
            CallSign = Line[26:35].rstrip()
            CW = Line[41:47].rstrip()
            Beacon = Line[62:68].rstrip()

            # Initial filtering
            if CW != 'CW' or Beacon == 'BEACON':
                return None

            Zulu = Line[70:75]

            # Validation
            if not (cSPOTS._Zulu_RegEx.match(Zulu) and cSPOTS._dB_RegEx.match(Line[47:52])):
                cUtil.log_error(Line)
                return None

            # Extract values
            dB = int(Line[47:49].strip())
            WPM = int(Line[53:56])
            FrequencyKHz = float(FrequencyKHzStr.lstrip())

            # Handle callsign suffix
            CallSignSuffix = ''
            if '/' in CallSign:
                CallSign, CallSignSuffix = CallSign.split('/', 1)
                CallSignSuffix = CallSignSuffix.upper()

            return Zulu, Spotter, FrequencyKHz, CallSign, CallSignSuffix, dB, WPM

        except (ValueError, IndexError):
            cUtil.log_error(Line)
            return None

    @classmethod
    def handle_notification(cls, CallSign: str, GoalList: list[str], TargetList: list[str]) -> Literal['+', ' ']:
        NotificationFlag = ' '

        Now = time.time()

        # Clean expired notifications
        for Call in list(cls._Notified.keys()):
            if Now > cls._Notified[Call]:
                del cls._Notified[Call]

        if CallSign not in cls._Notified:
            if config.NOTIFICATION.ENABLED:
                if (CallSign in config.FRIENDS and 'friends' in config.NOTIFICATION.CONDITION) or (GoalList and 'goals' in config.NOTIFICATION.CONDITION) or (TargetList and 'targets' in config.NOTIFICATION.CONDITION):
                    cUtil.beep()

            NotificationFlag = '+'
            cls._Notified[CallSign] = Now + config.NOTIFICATION.RENOTIFICATION_DELAY_SECONDS

        return NotificationFlag

    @classmethod
    def handle_spot(cls, Line: str) -> None:
        if config.VERBOSE:
            print(f'   {Line}')

        if not (Spot := cSPOTS.parse_spot(Line)):
            return

        Zulu, Spotter, FrequencyKHz, CallSign, CallSignSuffix, dB, WPM = Spot
        Report: list[str] = []

        # Extract callsign and validate
        if not (CallSign := cSKCC.extract_callsign(CallSign)) or CallSign in config.EXCLUSIONS:
            return

        # Check if frequency is in the configured bands
        if not cUtil.is_in_bands(FrequencyKHz):
            return

        # Process spotter information
        SpottedNearby = Spotter in SPOTTERS_NEARBY
        if SpottedNearby or CallSign == config.MY_CALLSIGN:
            if Spotter in Spotters.spotters:
                Miles = Spotters.get_distance(Spotter)
                Distance = cUtil.format_distance(Miles)
                Report.append(f'by {Spotter}({Distance}, {int(dB)}dB)')
            else:
                Report.append(f'by {Spotter}({int(dB)}dB)')

        # Check if this is the user's callsign
        if CallSign == config.MY_CALLSIGN:
            Report.append('(you)')

        # Check frequency
        if CallSign != 'K3Y':
            OnFrequency = cSKCC.is_on_skcc_frequency(FrequencyKHz, config.OFF_FREQUENCY.TOLERANCE)
            if not OnFrequency:
                if config.OFF_FREQUENCY.ACTION == 'warn':
                    Report.append('OFF SKCC FREQUENCY!')
                elif config.OFF_FREQUENCY.ACTION == 'suppress':
                    return

        # Handle WPM
        match config.HIGH_WPM.ACTION:
            case 'always-display':
                Report.append(f'{WPM} WPM')
            case 'warn' if WPM >= config.HIGH_WPM.THRESHOLD:
                Report.append(f'{WPM} WPM!')
            case 'suppress' if WPM >= config.HIGH_WPM.THRESHOLD:
                return
            case _:
                pass

        # Check if the callsign is in the friends list
        if CallSign in config.FRIENDS:
            Report.append('friend')

        # Get goal hits
        GoalList = []
        if 'K3Y' in config.GOALS and CallSign == 'K3Y' and CallSignSuffix:
            if Band := cSKCC.which_arrl_band(FrequencyKHz):
                if (CallSignSuffix not in cQSO.ContactsForK3Y) or (Band not in cQSO.ContactsForK3Y[CallSignSuffix]):
                    GoalList = [f'K3Y/{CallSignSuffix} ({Band}m)']

        GoalList.extend(cQSO.get_goal_hits(CallSign, FrequencyKHz))
        if GoalList:
            Report.append(f'YOU need them for {",".join(GoalList)}')

        # Get target hits
        TargetList = cQSO.get_target_hits(CallSign)
        if TargetList:
            Report.append(f'THEY need you for {",".join(TargetList)}')

        # Record and report spot if relevant
        if (SpottedNearby and (GoalList or TargetList)) or CallSign == config.MY_CALLSIGN or CallSign in config.FRIENDS:
            cSPOTS.last_spotted[CallSign] = (FrequencyKHz, time.time())
            ZuluDate = time.strftime('%Y-%m-%d', time.gmtime())
            FrequencyString = f'{FrequencyKHz:.1f}'

            if CallSign == 'K3Y':
                NotificationFlag = cls.handle_notification(f'K3Y/{CallSignSuffix}', GoalList, TargetList)
                Out = f'{Zulu}{NotificationFlag}K3Y/{CallSignSuffix} on {FrequencyString:>8} {"; ".join(Report)}'
            else:
                MemberInfo = cUtil.build_member_info(CallSign)
                NotificationFlag = cls.handle_notification(CallSign, GoalList, TargetList)
                Out = f'{Zulu}{NotificationFlag}{CallSign:<6} {MemberInfo} on {FrequencyString:>8} {"; ".join(Report)}'

            cDisplay.print(Out)
            cUtil.log(f'{ZuluDate} {Out}')

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
    ContactsForK3Y:   dict[str, dict[int, str]]

    Brag:             dict[str, tuple[str, str, str, float]]

    QSOsByMemberNumber: dict[str, list[str]]

    QSOs: list[tuple[str, str, str, float, str]]

    Prefix_RegEx = re.compile(r'(?:.*/)?([0-9]*[a-zA-Z]+\d+)')

    @classmethod
    def initialize(cls):
        cls.QSOs = []

        cls.Brag               = {}
        cls.ContactsForC       = {}
        cls.ContactsForT       = {}
        cls.ContactsForS       = {}
        cls.ContactsForWAS     = {}
        cls.ContactsForWAS_C   = {}
        cls.ContactsForWAS_T   = {}
        cls.ContactsForWAS_S   = {}
        cls.ContactsForP       = {}
        cls.ContactsForK3Y     = {}
        cls.QSOsByMemberNumber = {}

        cls.read_qsos()

        MyMemberEntry      = cSKCC.members[config.MY_CALLSIGN]
        cls.MyJoin_Date    = cUtil.effective(MyMemberEntry['join_date'])
        cls.MyC_Date       = cUtil.effective(MyMemberEntry['c_date'])
        cls.MyT_Date       = cUtil.effective(MyMemberEntry['t_date'])
        cls.MyS_Date       = cUtil.effective(MyMemberEntry['s_date'])
        cls.MyTX8_Date     = cUtil.effective(MyMemberEntry['tx8_date'])

        cls.MyMemberNumber = MyMemberEntry['plain_number']

    @classmethod
    async def watch_logfile_task(cls):
        while True:
            try:
                if os.path.exists(config.ADI_FILE) and os.path.getmtime(config.ADI_FILE) != cQSO.AdiFileReadTimeStamp:
                    cDisplay.print(f"'{config.ADI_FILE}' file is changing. Waiting for write to finish...")

                    # Wait until file size stabilizes
                    while True:
                        Size = os.path.getsize(config.ADI_FILE)
                        await asyncio.sleep(1)
                        if os.path.getsize(config.ADI_FILE) == Size:
                            break

                    cls.refresh()

            except FileNotFoundError:
                print(f"Warning: ADI file '{config.ADI_FILE}' not found or inaccessible")
            except Exception as e:
                print(f"Error watching log file: {e}")

            await asyncio.sleep(3)

    @classmethod
    def awards_check(cls) -> None:
        C_Level = len(cls.ContactsForC)  // Levels['C']
        T_Level = len(cls.ContactsForT)  // Levels['T']
        S_Level = len(cls.ContactsForS)  // Levels['S']
        P_Level = cls.calc_prefix_points() // Levels['P']

        ### C ###

        if cls.MyC_Date:
            Award_C_Level = cSKCC.centurion_level[cls.MyMemberNumber]

            while (C_Level > 10) and (C_Level % 5):
                C_Level -= 1

            if C_Level > Award_C_Level:
                C_or_Cx = 'C' if Award_C_Level == 1 else f'Cx{Award_C_Level}'
                print(f'FYI: You qualify for Cx{C_Level} but have only applied for {C_or_Cx}.')
        else:
            if C_Level == 1 and cls.MyMemberNumber not in cSKCC.centurion_level:
                print('FYI: You qualify for C but have not yet applied for it.')

        ### T ###

        if cls.MyT_Date:
            Award_T_Level = cSKCC.tribune_level[cls.MyMemberNumber]

            while (T_Level > 10) and (T_Level % 5):
                T_Level -= 1

            if T_Level > Award_T_Level:
                T_or_Tx = 'T' if Award_T_Level == 1 else f'Tx{Award_T_Level}'
                print(f'FYI: You qualify for Tx{T_Level} but have only applied for {T_or_Tx}.')
        else:
            if T_Level == 1 and cls.MyMemberNumber not in cSKCC.tribune_level:
                print('FYI: You qualify for T but have not yet applied for it.')

        ### S ###

        if cls.MyS_Date:
            Award_S_Level = cSKCC.senator_level[cls.MyMemberNumber]

            if S_Level > Award_S_Level:
                S_or_Sx = 'S' if Award_S_Level == 1 else f'Sx{Award_S_Level}'
                print(f'FYI: You qualify for Sx{S_Level} but have only applied for {S_or_Sx}.')
        else:
            if S_Level == 1 and cls.MyMemberNumber not in cSKCC.senator_level:
                print('FYI: You qualify for S but have not yet applied for it.')

        ### WAS and WAS-C and WAS-T and WAS-S ###

        if 'WAS' in config.GOALS:
            if len(cls.ContactsForWAS) == len(US_STATES) and config.MY_CALLSIGN not in cSKCC.was_level:
                print('FYI: You qualify for WAS but have not yet applied for it.')

        if 'WAS-C' in config.GOALS:
            if len(cls.ContactsForWAS_C) == len(US_STATES) and config.MY_CALLSIGN not in cSKCC.was_c_level:
                print('FYI: You qualify for WAS-C but have not yet applied for it.')

        if 'WAS-T' in config.GOALS:
            if len(cls.ContactsForWAS_T) == len(US_STATES) and config.MY_CALLSIGN not in cSKCC.was_t_level:
                print('FYI: You qualify for WAS-T but have not yet applied for it.')

        if 'WAS-S' in config.GOALS:
            if len(cls.ContactsForWAS_S) == len(US_STATES) and config.MY_CALLSIGN not in cSKCC.was_s_level:
                print('FYI: You qualify for WAS-S but have not yet applied for it.')

        if 'P' in config.GOALS:
            if config.MY_CALLSIGN in cSKCC.prefix_level:
                Award_P_Level = cSKCC.prefix_level[config.MY_CALLSIGN]

                if P_Level > Award_P_Level:
                    print(f'FYI: You qualify for Px{P_Level} but have only applied for Px{Award_P_Level}')
            elif P_Level >= 1:
                print(f'FYI: You qualify for Px{P_Level} but have not yet applied for it.')

    @staticmethod
    def calculate_numerics(Class: str, Total: int) -> tuple[int, int]:
        increment = Levels[Class]

        # Adjust increments after x10
        level = (Total // increment) + 1
        if level > 10:
            if level % 5 != 0:
                level -= (level % 5)
        return increment - (Total % increment), level

    @classmethod
    def read_qsos(cls) -> None:
        """Optimized QSO reading with chunked processing for better memory efficiency."""
        AdiFileAbsolute = os.path.abspath(config.ADI_FILE)
        cDisplay.print(f"\nReading QSOs for {config.MY_CALLSIGN} from '{AdiFileAbsolute}'...")

        cls.QSOs = []
        cls.AdiFileReadTimeStamp = os.path.getmtime(config.ADI_FILE)

        # Compile regex patterns once
        eoh_pattern = re.compile(r'<eoh>', re.I)
        eor_pattern = re.compile(r'<eor>', re.I)
        field_pattern = re.compile(r'<(\w+?):\d+(?::.*?)*>(.*?)\s*(?=<(?:\w+?):\d+(?::.*?)*>|$)', re.I | re.S)

        try:
            with open(AdiFileAbsolute, 'rb') as file:
                # Read the whole file - we could process in chunks for very large files
                content = file.read().decode('utf-8', 'ignore')

                # Split header from body
                parts = eoh_pattern.split(content, maxsplit=1)
                if len(parts) < 2:
                    print("Warning: Could not find EOH marker in ADIF file")
                    Body = content
                else:
                    Body = parts[1].strip(' \t\r\n\x1a')

                # Process each QSO record
                for record_text in filter(None, map(str.strip, eor_pattern.split(Body))):
                    # Extract fields
                    record = {k.upper(): v for k, v in field_pattern.findall(record_text)}

                    # Normalize QSO_DATE and TIME_ON fields
                    record.setdefault('QSO_DATE', record.pop('QSO_DATE_OFF', None))
                    record.setdefault('TIME_ON', record.pop('TIME_OFF', None))

                    # Skip non-CW QSOs and incomplete records
                    if not all(k in record for k in ('CALL', 'QSO_DATE', 'TIME_ON')) or record.get('MODE') != 'CW':
                        continue

                    # Frequency conversion to kHz
                    freq_str = record.get('FREQ', '')
                    fFrequency = 0.0
                    if freq_str and freq_str.replace('.', '', 1).isdigit():
                        fFrequency = float(freq_str) * 1000

                    # Append QSO data
                    cls.QSOs.append((
                        record['QSO_DATE'] + record['TIME_ON'],
                        record['CALL'],
                        record.get('STATE', ''),
                        fFrequency,
                        record.get('COMMENT', '')
                    ))

        except Exception as e:
            print(f"Error reading ADIF file: {e}")
            return

        # Sort QSOs by date
        cls.QSOs.sort(key=lambda qso: qso[0])

        # Process and map QSOs by member number with batched operations
        cls.QSOsByMemberNumber = {}
        for qso_date, call_sign, _, _, _ in cls.QSOs:
            call_sign = cSKCC.extract_callsign(call_sign)
            if not call_sign or call_sign == 'K3Y':
                continue

            member_number = cSKCC.members.get(call_sign, {}).get('plain_number')
            if member_number:
                if member_number not in cls.QSOsByMemberNumber:
                    cls.QSOsByMemberNumber[member_number] = []
                cls.QSOsByMemberNumber[member_number].append(qso_date)

    @classmethod
    def calc_prefix_points(cls) -> int:
        return sum(value[2] for value in cls.ContactsForP.values())

    @classmethod
    def print_progress(cls) -> None:
        def print_remaining(Class: str, Total: int):
            Remaining, X_Factor = cQSO.calculate_numerics(Class, Total)

            if Class in config.GOALS:
                Abbrev = cUtil.abbreviate_class(Class, X_Factor)
                print(f'{Class}: Have {Total:,} which qualifies for {Abbrev}. NEXT requires zzz ({Remaining:,} more)')

        print('')

        if config.GOALS:
            print(f'GOAL{"S" if len(config.GOALS) > 1 else ""}: {", ".join(config.GOALS)}')

        if config.TARGETS:
            print(f'TARGET{"S" if len(config.TARGETS) > 1 else ""}: {", ".join(config.TARGETS)}')

        print(f'BANDS: {", ".join(str(Band)  for Band in config.BANDS)}')


        print_remaining('C', len(cls.ContactsForC))

        if cQSO.MyC_Date:
            print_remaining('T', len(cls.ContactsForT))

        if cQSO.MyTX8_Date:
            print_remaining('S', len(cls.ContactsForS))

        print_remaining('P', cls.calc_prefix_points())

        def remaining_states(Class: str, QSOs: dict[str, tuple[str, str, str]]) -> None:
            if len(QSOs) == len(US_STATES):
                Need = 'none needed'
            else:
                RemainingStates = [State for State in US_STATES if State not in QSOs]

                if len(RemainingStates) > 14:
                    Need = f'only need {len(RemainingStates)} more'
                else:
                    Need = f'only need {",".join(RemainingStates)}'

            print(f'Total worked towards {Class}: {len(QSOs)}, {Need}.')

        if 'WAS' in config.GOALS:
            remaining_states('WAS', cls.ContactsForWAS)

        if 'WAS-C' in config.GOALS:
            remaining_states('WAS-C', cls.ContactsForWAS_C)

        if 'WAS-T' in config.GOALS:
            remaining_states('WAS-T', cls.ContactsForWAS_T)

        if 'WAS-S' in config.GOALS:
            remaining_states('WAS-S', cls.ContactsForWAS_S)

        if 'BRAG' in config.GOALS:
            NowGMT = cFastDateTime.now_gmt()
            MonthIndex = NowGMT.month()-1
            MonthName = cFastDateTime.MONTH_NAMES[MonthIndex]
            print(f'Total worked towards {MonthName} Brag: {len(cls.Brag)}')

    @classmethod
    def get_goal_hits(cls, TheirCallSign: str, fFrequency: float | None = None) -> list[str]:
        if TheirCallSign not in cSKCC.members or TheirCallSign == config.MY_CALLSIGN:
            return []

        TheirMemberEntry  = cSKCC.members[TheirCallSign]
        TheirC_Date       = cUtil.effective(TheirMemberEntry['c_date'])
        TheirT_Date       = cUtil.effective(TheirMemberEntry['t_date'])
        TheirS_Date       = cUtil.effective(TheirMemberEntry['s_date'])
        TheirMemberNumber = TheirMemberEntry['plain_number']

        GoalHitList: list[str] = []

        if 'BRAG' in config.GOALS and TheirMemberNumber not in cls.Brag:
            if (fFrequency and cSKCC.is_on_warc_frequency(fFrequency)) or not cSKCC.is_during_sprint(cFastDateTime.now_gmt()):
                GoalHitList.append('BRAG')

        if 'C' in config.GOALS and not cls.MyC_Date and TheirMemberNumber not in cls.ContactsForC:
            GoalHitList.append('C')

        if 'CXN' in config.GOALS and cls.MyC_Date and TheirMemberNumber not in cls.ContactsForC:
            _, x_factor = cQSO.calculate_numerics('C', len(cls.ContactsForC))
            GoalHitList.append(cUtil.abbreviate_class('C', x_factor))

        if 'T' in config.GOALS and cls.MyC_Date and not cls.MyT_Date and TheirC_Date and TheirMemberNumber not in cls.ContactsForT:
            GoalHitList.append('T')

        if 'TXN' in config.GOALS and cls.MyT_Date and TheirC_Date and TheirMemberNumber not in cls.ContactsForT:
            _, x_factor = cQSO.calculate_numerics('T', len(cls.ContactsForT))
            GoalHitList.append(cUtil.abbreviate_class('T', x_factor))

        if 'S' in config.GOALS and cls.MyTX8_Date and not cls.MyS_Date and TheirT_Date and TheirMemberNumber not in cls.ContactsForS:
            GoalHitList.append('S')

        if 'SXN' in config.GOALS and cls.MyS_Date and TheirT_Date and TheirMemberNumber not in cls.ContactsForS:
            _, x_factor = cQSO.calculate_numerics('S', len(cls.ContactsForS))
            GoalHitList.append(cUtil.abbreviate_class('S', x_factor))

        if 'WAS' in config.GOALS and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS:
            GoalHitList.append('WAS')

        if 'WAS-C' in config.GOALS and TheirC_Date and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS_C:
            GoalHitList.append('WAS-C')

        if 'WAS-T' in config.GOALS and TheirT_Date and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS_T:
            GoalHitList.append('WAS-T')

        if 'WAS-S' in config.GOALS and TheirS_Date and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS_S:
            GoalHitList.append('WAS-S')

        if 'P' in config.GOALS and (match := cQSO.Prefix_RegEx.match(TheirCallSign)):
            prefix = match.group(1)
            i_their_member_number = int(TheirMemberNumber)
            _, x_factor = cQSO.calculate_numerics('P', cls.calc_prefix_points())

            if (contact := cls.ContactsForP.get(prefix)):
                if i_their_member_number > contact[2]:
                    GoalHitList.append(f'{cUtil.abbreviate_class("P", x_factor)}(+{i_their_member_number - contact[2]})')
            else:
                GoalHitList.append(f'{cUtil.abbreviate_class("P", x_factor)}(new +{i_their_member_number})')

        return GoalHitList

    @classmethod
    def get_target_hits(cls, TheirCallSign: str) -> list[str]:
        if TheirCallSign not in cSKCC.members or TheirCallSign == config.MY_CALLSIGN:
            return []

        TheirMemberEntry  = cSKCC.members[TheirCallSign]
        TheirJoin_Date    = cUtil.effective(TheirMemberEntry['join_date'])
        TheirC_Date       = cUtil.effective(TheirMemberEntry['c_date'])
        TheirT_Date       = cUtil.effective(TheirMemberEntry['t_date'])
        TheirTX8_Date     = cUtil.effective(TheirMemberEntry['tx8_date'])
        TheirS_Date       = cUtil.effective(TheirMemberEntry['s_date'])
        TheirMemberNumber = TheirMemberEntry['plain_number']

        TargetHitList: list[str] = []

        if 'C' in config.TARGETS and not TheirC_Date:
            if TheirMemberNumber not in cls.QSOsByMemberNumber or all(
                qso_date <= TheirJoin_Date or qso_date <= cls.MyJoin_Date
                for qso_date in cls.QSOsByMemberNumber[TheirMemberNumber]
            ):
                TargetHitList.append('C')

        if 'CXN' in config.TARGETS and TheirC_Date:
            NextLevel = cSKCC.centurion_level[TheirMemberNumber] + 1

            if NextLevel <= 10 and (
                TheirMemberNumber not in cls.QSOsByMemberNumber or all(
                    qso_date <= TheirJoin_Date or qso_date <= cls.MyJoin_Date
                    for qso_date in cls.QSOsByMemberNumber[TheirMemberNumber]
                )
            ):
                TargetHitList.append(f'Cx{NextLevel}')


        if 'T' in config.TARGETS and TheirC_Date and not TheirT_Date and cls.MyC_Date:
            if TheirMemberNumber not in cls.QSOsByMemberNumber or all(
                qso_date <= TheirC_Date or qso_date <= cls.MyC_Date
                for qso_date in cls.QSOsByMemberNumber[TheirMemberNumber]
            ):
                TargetHitList.append('T')

        if 'TXN' in config.TARGETS and TheirT_Date and cls.MyC_Date:
            NextLevel = cSKCC.tribune_level[TheirMemberNumber] + 1

            if NextLevel <= 10 and (
                TheirMemberNumber not in cls.QSOsByMemberNumber or all(
                    qso_date <= TheirC_Date or qso_date <= cls.MyC_Date
                    for qso_date in cls.QSOsByMemberNumber[TheirMemberNumber]
                )
            ):
                TargetHitList.append(f'Tx{NextLevel}')

        if 'S' in config.TARGETS and TheirTX8_Date and not TheirS_Date and cls.MyT_Date:
            if TheirMemberNumber not in cls.QSOsByMemberNumber or all(
                qso_date <= TheirTX8_Date or qso_date <= cls.MyT_Date
                for qso_date in cls.QSOsByMemberNumber[TheirMemberNumber]
            ):
                TargetHitList.append('S')

        if 'SXN' in config.TARGETS and TheirS_Date and cls.MyT_Date:
            NextLevel = cSKCC.senator_level[TheirMemberNumber] + 1

            if NextLevel <= 10 and (
                TheirMemberNumber not in cls.QSOsByMemberNumber or all(
                    qso_date <= TheirTX8_Date or qso_date <= cls.MyT_Date
                    for qso_date in cls.QSOsByMemberNumber[TheirMemberNumber]
                )
            ):
                TargetHitList.append(f'Sx{NextLevel}')

        return TargetHitList

    @classmethod
    def refresh(cls) -> None:
        cls.read_qsos()
        cQSO.get_goal_qsos()
        cls.print_progress()

    @classmethod
    def get_brag_qsos(cls, PrevMonth: int = 0, Print: bool = False) -> None:
        cls.Brag = {}

        DateOfInterestGMT = cFastDateTime.now_gmt()

        if PrevMonth > 0:
            Year, Month, Day, _Hour, _Minute, _Second = DateOfInterestGMT.split_date_time()

            YearsBack  = int(PrevMonth  / 12)
            MonthsBack = PrevMonth % 12

            Year  -= YearsBack
            Month -= MonthsBack

            if Month <= 0:
                Year  -= 1
                Month += 12

            DateOfInterestGMT = cFastDateTime((Year, Month, Day))

        fastStartOfMonth = DateOfInterestGMT.start_of_month()
        fastEndOfMonth   = DateOfInterestGMT.end_of_month()

        for Contact in cls.QSOs:
            QsoDate, QsoCallSign, _QsoSPC, QsoFreq, _QsoComment = Contact

            if QsoCallSign in ('K9SKC'):
                continue

            QsoCallSign = cSKCC.extract_callsign(QsoCallSign)

            if not QsoCallSign or QsoCallSign == 'K3Y':
                continue

            MainCallSign = cSKCC.members[QsoCallSign]['main_call']

            TheirMemberEntry  = cSKCC.members[MainCallSign]
            TheirMemberNumber = TheirMemberEntry['plain_number']

            fastQsoDate = cFastDateTime(QsoDate)

            if fastStartOfMonth < fastQsoDate < fastEndOfMonth:
                TheirJoin_Date = cUtil.effective(TheirMemberEntry['join_date'])

                if TheirJoin_Date and TheirJoin_Date < QsoDate:
                    DuringSprint = cSKCC.is_during_sprint(fastQsoDate)

                    if not QsoFreq:
                        continue

                    OnWarcFreq   = cSKCC.is_on_warc_frequency(QsoFreq)

                    BragOkay = OnWarcFreq or (not DuringSprint)

                    #print(BragOkay, DuringSprint, OnWarcFreq, QsoFreq, QsoDate)

                    if TheirMemberNumber not in cls.Brag and BragOkay:
                        cls.Brag[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign, QsoFreq)
                        #print('Brag contact: {} on {} {}'.format(QsoCallSign, QsoDate, QsoFreq))
                    else:
                        #print('Not brag eligible: {} on {}  {}  warc: {}  sprint: {}'.format(QsoCallSign, QsoDate, QsoFreq, OnWarcFreq, DuringSprint))
                        pass

        if Print and 'BRAG' in config.GOALS:
            Year = DateOfInterestGMT.year()
            MonthIndex = DateOfInterestGMT.month()-1
            MonthAbbrev = cFastDateTime.MONTH_NAMES[MonthIndex][:3]
            print(f'Total Brag contacts in {MonthAbbrev} {Year}: {len(cls.Brag)}')

    @classmethod
    def get_goal_qsos(cls) -> None:
        """Optimized goal QSO processing with batched operations."""
        # Helper function to check date criteria
        def good(QsoDate: str, MemberDate: str, MyDate: str, EligibleDate: str | None = None):
            if MemberDate == '' or MyDate == '':
                return False

            if EligibleDate and QsoDate < EligibleDate:
                return False

            return QsoDate >= MemberDate and QsoDate >= MyDate

        # Initialize collections
        collections: dict[str, dict[str, Any]] = {
            'C': cls.ContactsForC,
            'T': cls.ContactsForT,
            'S': cls.ContactsForS,
            'WAS': cls.ContactsForWAS,
            'WAS_C': cls.ContactsForWAS_C,
            'WAS_T': cls.ContactsForWAS_T,
            'WAS_S': cls.ContactsForWAS_S,
            'P': cls.ContactsForP,
            'K3Y': cls.ContactsForK3Y,
        }

        for collection in collections.values():
            collection.clear()

        # Process BRAG QSOs
        if 'BRAG_MONTHS' in globals() and 'BRAG' in config.GOALS:
            for PrevMonth in range(abs(config.BRAG_MONTHS), 0, -1):
                cQSO.get_brag_qsos(PrevMonth=PrevMonth, Print=True)

        # Process current month as well
        cQSO.get_brag_qsos(PrevMonth=0, Print=False)

        # Define key dates once for efficiency
        eligible_dates = {
            'prefix': '20130101000000',
            'tribune': '20070301000000',
            'senator': '20130801000000',
            'was_c': '20110612000000',
            'was_ts': '20160201000000'
        }

        # Batch process all QSOs
        k3y_start = f'{config.K3Y_YEAR}0102000000'
        k3y_end = f'{config.K3Y_YEAR}0201000000'

        for Contact in cls.QSOs:
            QsoDate, QsoCallSign, QsoSPC, QsoFreq, QsoComment = Contact

            # Skip invalid callsigns
            if QsoCallSign in ('K9SKC', 'K3Y'):
                continue

            QsoCallSign = cSKCC.extract_callsign(QsoCallSign)
            if not QsoCallSign:
                continue

            # Get member data once
            MainCallSign = cSKCC.members[QsoCallSign]['main_call']
            TheirMemberEntry = cSKCC.members[MainCallSign]

            TheirJoin_Date = cUtil.effective(TheirMemberEntry['join_date'])
            TheirC_Date = cUtil.effective(TheirMemberEntry['c_date'])
            TheirT_Date = cUtil.effective(TheirMemberEntry['t_date'])
            TheirS_Date = cUtil.effective(TheirMemberEntry['s_date'])
            TheirMemberNumber = TheirMemberEntry['plain_number']

            # K3Y processing
            if 'K3Y' in config.GOALS and QsoDate >= k3y_start and QsoDate < k3y_end:
                if k3y_match := re.match(r'.*?(?:K3Y|SKM)[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)', QsoComment, re.IGNORECASE):
                    Suffix = k3y_match.group(1).upper()

                    if Band := cSKCC.which_arrl_band(QsoFreq):
                        if Suffix not in cls.ContactsForK3Y:
                            cls.ContactsForK3Y[Suffix] = {}
                        cls.ContactsForK3Y[Suffix][Band] = QsoCallSign

            # Prefix processing
            if good(QsoDate, TheirJoin_Date, cls.MyJoin_Date, eligible_dates['prefix']):
                if TheirMemberNumber != cls.MyMemberNumber:
                    if prefix_match := cQSO.Prefix_RegEx.match(QsoCallSign):
                        Prefix = prefix_match.group(1)
                        iTheirMemberNumber = int(TheirMemberNumber)

                        if Prefix not in cls.ContactsForP or iTheirMemberNumber > cls.ContactsForP[Prefix][2]:
                            FirstName = cSKCC.members[QsoCallSign]['name']
                            cls.ContactsForP[Prefix] = (QsoDate, Prefix, iTheirMemberNumber, FirstName)

            # Process C, T, S in one batch
            if good(QsoDate, TheirJoin_Date, cls.MyJoin_Date):
                if TheirMemberNumber not in cls.ContactsForC:
                    cls.ContactsForC[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

            if good(QsoDate, TheirC_Date, cls.MyC_Date, eligible_dates['tribune']):
                if TheirMemberNumber not in cls.ContactsForT:
                    cls.ContactsForT[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

            if good(QsoDate, TheirT_Date, cls.MyTX8_Date, eligible_dates['senator']):
                if TheirMemberNumber not in cls.ContactsForS:
                    cls.ContactsForS[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

            # Process WAS entries for states
            if QsoSPC in US_STATES:
                # Base WAS
                if TheirJoin_Date and QsoDate >= TheirJoin_Date and QsoDate >= cls.MyJoin_Date:
                    if QsoSPC not in cls.ContactsForWAS:
                        cls.ContactsForWAS[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

                # WAS variants
                if QsoDate >= eligible_dates['was_c']:
                    if TheirC_Date and QsoDate >= TheirC_Date:
                        if QsoSPC not in cls.ContactsForWAS_C:
                            cls.ContactsForWAS_C[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

                if QsoDate >= eligible_dates['was_ts']:
                    if TheirT_Date and QsoDate >= TheirT_Date:
                        if QsoSPC not in cls.ContactsForWAS_T:
                            cls.ContactsForWAS_T[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

                    if TheirS_Date and QsoDate >= TheirS_Date:
                        if QsoSPC not in cls.ContactsForWAS_S:
                            cls.ContactsForWAS_S[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

        # Generate output files
        QSOs_Dir = 'QSOs'
        if not os.path.exists(QSOs_Dir):
            os.makedirs(QSOs_Dir)

        # Award files
        cls.award_cts('C', cls.ContactsForC)
        cls.award_cts('T', cls.ContactsForT)
        cls.award_cts('S', cls.ContactsForS)
        cls.award_was('WAS', cls.ContactsForWAS)
        cls.award_was('WAS-C', cls.ContactsForWAS_C)
        cls.award_was('WAS-T', cls.ContactsForWAS_T)
        cls.award_was('WAS-S', cls.ContactsForWAS_S)
        cls.award_p(cls.ContactsForP)
        cls.track_brag(cls.Brag)

        # Print K3Y contacts if needed
        if 'K3Y' in config.GOALS:
            cls.print_k3y_contacts()

    @classmethod
    def award_p(cls, QSOs: dict[str, tuple[str, str, int, str]]) -> None:
        with open(f'QSOs/{config.MY_CALLSIGN}-P.txt', 'w', encoding='utf-8') as file:
            iPoints = 0
            for index, (_qso_date, prefix, member_number, first_name) in enumerate(
                sorted(QSOs.values(), key=lambda q: q[1]), start=1
            ):
                iPoints += member_number
                file.write(f"{index:>4} {member_number:>8} {first_name:<10.10} {prefix:<6} {iPoints:>12,}\n")

    @classmethod
    def award_cts(cls, Class: str, QSOs_dict: dict[str, tuple[str, str, str]]) -> None:
        QSOs = QSOs_dict.values()
        QSOs = sorted(QSOs, key=lambda QsoTuple: (QsoTuple[0], QsoTuple[2]))

        with open(f'QSOs/{config.MY_CALLSIGN}-{Class}.txt', 'w', encoding='utf-8') as File:
            for Count, (QsoDate, TheirMemberNumber, MainCallSign) in enumerate(QSOs):
                Date = f'{QsoDate[0:4]}-{QsoDate[4:6]}-{QsoDate[6:8]}'
                File.write(f'{Count+1:<4}  {Date}   {MainCallSign:<9}   {TheirMemberNumber:<7}\n')

    @classmethod
    def award_was(cls, Class: str, QSOs_dict: dict[str, tuple[str, str, str]]) -> None:
        QSOsByState = {spc: (spc, date, callsign) for spc, date, callsign in sorted(QSOs_dict.values(), key=lambda q: q[0])}

        with open(f'QSOs/{config.MY_CALLSIGN}-{Class}.txt', 'w', encoding='utf-8') as file:
            for state in US_STATES:
                if state in QSOsByState:
                    spc, date, callsign = QSOsByState[state]
                    file.write(f"{spc}    {callsign:<12}  {date[:4]}-{date[4:6]}-{date[6:8]}\n")
                else:
                    file.write(f"{state}\n")

    @classmethod
    def track_brag(cls, QSOs: dict[str, tuple[str, str, str, float]]) -> None:
        with open(f'QSOs/{config.MY_CALLSIGN}-BRAG.txt', 'w', encoding='utf-8') as file:
            for count, (qso_date, their_member_number, main_callsign, qso_freq) in enumerate(
                sorted(QSOs.values()), start=1
            ):
                date = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
                file.write(
                    f"{count:<4} {date}  {their_member_number:<6}  {main_callsign}  {qso_freq / 1000:.3f}\n"
                    if qso_freq else f"{count:<4} {date}  {their_member_number:<6}  {main_callsign}\n"
                )

    @classmethod
    def print_k3y_contacts(cls) -> None:
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

        def print_station(Station: str):
            _Prefix, Suffix = re.split('[/-]', Station)

            def print_band(Band: int):
                if (Suffix in cls.ContactsForK3Y) and (Band in cls.ContactsForK3Y[Suffix]):
                    print(f'{" " + cls.ContactsForK3Y[Suffix][Band]: <7}|', end = '')
                else:
                    print(f'{"": <7}|', end = '')

            print(f'{Station: <8}|', end = '')
            print_band(160)
            print_band(80)
            print_band(40)
            print_band(30)
            print_band(20)
            print_band(17)
            print_band(15)
            print_band(12)
            print_band(10)
            print_band(6)
            print()

        print_station('K3Y/0')
        print_station('K3Y/1')
        print_station('K3Y/2')
        print_station('K3Y/3')
        print_station('K3Y/4')
        print_station('K3Y/5')
        print_station('K3Y/6')
        print_station('K3Y/7')
        print_station('K3Y/8')
        print_station('K3Y/9')
        print_station('K3Y/KH6')
        print_station('K3Y/KL7')
        print_station('K3Y/KP4')
        print_station('SKM-AF')
        print_station('SKM-AS')
        print_station('SKM-EU')
        print_station('SKM-NA')
        print_station('SKM-OC')
        print_station('SKM-SA')

class cSpotters:
    spotters: ClassVar[dict[str, tuple[int, list[int]]]] = {}

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

    @classmethod
    def get_spotters(cls) -> None:
        """Get RBN spotters within the configured radius using parallel requests."""
        def parse_bands(band_csv: str) -> list[int]:
            valid_bands = {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"}
            return [int(b[:-1]) for b in band_csv.split(',') if b in valid_bands]

        print(f"\nFinding RBN spotters within {config.SPOTTER_RADIUS} miles of '{config.MY_GRIDSQUARE}'...")

        try:
            # Use a timeout to prevent hanging
            response = requests.get('https://reversebeacon.net/cont_includes/status.php?t=skt', timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f'*** Fatal Error: Unable to retrieve spotters from RBN: {e}')
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
                    cls.spotters[spotter] = (miles, parse_bands(csv_bands))
                except ValueError:
                    continue

    @classmethod
    def get_nearby_spotters(cls) -> list[tuple[str, int]]:
        spotters_sorted = sorted(cls.spotters.items(), key=lambda item: item[1][0])
        nearbySpotters = [(spotter, miles) for spotter, (miles, _) in spotters_sorted if miles <= config.SPOTTER_RADIUS]
        return nearbySpotters

    @classmethod
    def get_distance(cls, Spotter: str) -> int:
        Miles, _ = cls.spotters[Spotter]
        return Miles

class cSKCC:
    centurion_level: ClassVar[dict[str, int]] = {}
    tribune_level:   ClassVar[dict[str, int]] = {}
    senator_level:   ClassVar[dict[str, int]] = {}
    members:         ClassVar[dict[str, dict[str, str]]] = {}
    was_level:       ClassVar[dict[str, int]] = {}
    was_c_level:     ClassVar[dict[str, int]] = {}
    was_t_level:     ClassVar[dict[str, int]] = {}
    was_s_level:     ClassVar[dict[str, int]] = {}
    prefix_level:    ClassVar[dict[str, int]] = {}

    # Cache for frequently accessed member data
    _member_cache:   ClassVar[dict[str, dict[str, str]]] = {}

    _month_abbreviations: ClassVar[dict[str, int]] = {
        'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4,  'May':5,  'Jun':6,
        'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12
    }

    _calling_frequencies_khz: ClassVar[dict[int, list[float]]] = {
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

    @classmethod
    def initialize(cls):
        """Initialize SKCC data using parallel downloads for rosters."""
        # First, read the main SKCC data
        cls.read_skcc_data()

        # Download all rosters in parallel using thread pool
        print("Downloading award rosters...")
        with ThreadPoolExecutor(max_workers=8) as executor:
            # Submit all tasks
            centurion_future = executor.submit(cls.read_level_list, 'Centurion', 'centurionlist.txt')
            tribune_future = executor.submit(cls.read_level_list, 'Tribune', 'tribunelist.txt')
            senator_future = executor.submit(cls.read_level_list, 'Senator', 'senator.txt')
            was_future = executor.submit(cls.read_roster, 'WAS', 'operating_awards/was/was_roster.php')
            was_c_future = executor.submit(cls.read_roster, 'WAS-C', 'operating_awards/was-c/was-c_roster.php')
            was_t_future = executor.submit(cls.read_roster, 'WAS-T', 'operating_awards/was-t/was-t_roster.php')
            was_s_future = executor.submit(cls.read_roster, 'WAS-S', 'operating_awards/was-s/was-s_roster.php')
            prefix_future = executor.submit(cls.read_roster, 'PFX', 'operating_awards/pfx/prefix_roster.php')

            # Wait for completion with timeout to avoid hanging
            try:
                cls.centurion_level = centurion_future.result(timeout=30)
                cls.tribune_level = tribune_future.result(timeout=30)
                cls.senator_level = senator_future.result(timeout=30)
                cls.was_level = was_future.result(timeout=30)
                cls.was_c_level = was_c_future.result(timeout=30)
                cls.was_t_level = was_t_future.result(timeout=30)
                cls.was_s_level = was_s_future.result(timeout=30)
                cls.prefix_level = prefix_future.result(timeout=30)

                print("Successfully downloaded all award rosters.")
            except Exception as e:
                print(f"Error downloading rosters: {e}")
                sys.exit(1)

    @staticmethod
    def wes(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
        start_time = cFastDateTime((Year, Month, 1)).first_weekday_from_date('Sat').first_weekday_after_date('Sat') + timedelta(hours=12)
        return start_time, start_time + timedelta(hours=35, minutes=59, seconds=59)

    @staticmethod
    def sks(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
        start_date = cFastDateTime((Year, Month, 1))

        for _ in range(4):  # Loop exactly 4 times
            start_date = start_date.first_weekday_after_date('Wed')

        return start_date, start_date + timedelta(hours=2)

    @staticmethod
    def sksa(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
        start_time = cFastDateTime((Year, Month, 1)).first_weekday_from_date('Fri').first_weekday_after_date('Fri') + timedelta(hours=22)
        return start_time, start_time + timedelta(hours=1, minutes=59, seconds=59)

    @staticmethod
    def skse(Year: int, Month: int) -> tuple[cFastDateTime, cFastDateTime]:
        start_time = cFastDateTime((Year, Month, 1)).first_weekday_from_date('Thu') + timedelta(hours=20 if Month in {1, 2, 3, 11, 12} else 19)
        return start_time, start_time + timedelta(hours=1, minutes=59, seconds=59)

    @staticmethod
    def is_during_sprint(fastDateTime: cFastDateTime) -> bool:
        year, month = fastDateTime.year(), fastDateTime.month()

        return any(
            start <= fastDateTime <= end
            for start, end in (cSKCC.wes(year, month),  cSKCC.sks(year, month),
                               cSKCC.skse(year, month), cSKCC.sksa(year, month))
        )

    @staticmethod
    def block_during_update_window() -> None:
        def time_now_gmt():
            TimeNowGMT = time.strftime('%H%M00', time.gmtime())
            return int(TimeNowGMT)

        if time_now_gmt() % 20000 == 0:
            print('The SKCC website updates files every even UTC hour.')
            print('SKCC Skimmer will start when complete.  Please wait...')

            while time_now_gmt() % 20000 == 0:
                time.sleep(2)
                sys.stderr.write('.')
            else:
                print('')

    ''' The SKCC month abbreviations are always in US format.  We
            don't want to use the built in date routines because they are
            locale sensitive and could be misinterpreted in other countries.
    '''
    @staticmethod
    def normalize_skcc_date(Date: str) -> str:
        if not Date:
            return ""

        sDay, sMonthAbbrev, sYear = Date.split()
        return f"{int(sYear):04}{cSKCC._month_abbreviations[sMonthAbbrev]:02}{int(sDay):02}000000"

    @classmethod
    def extract_callsign(cls, CallSign: str) -> str | None:
        # Strip punctuation except '/'
        CallSign = CallSign.strip(string.punctuation.replace("/", ""))

        if CallSign in cls.members or CallSign == "K3Y":
            return CallSign

        if "/" in CallSign:
            parts = CallSign.split("/")
            if len(parts) in {2, 3}:  # Valid cases
                prefix, suffix = parts[:2]
                return prefix if prefix in cls.members else suffix if suffix in cls.members else None

        return None

    @staticmethod
    def read_level_list(Type: str, URL: str) -> dict[str, int] | NoReturn:
        """Read award level list with improved error handling."""
        print(f"Retrieving SKCC award info from {URL}...")

        try:
            # Use a timeout to prevent hanging
            response = requests.get(f"https://www.skccgroup.com/{URL}", timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error retrieving award info: {e}")
            return {}  # Return empty dict rather than exiting

        today_gmt = time.strftime("%Y%m%d000000", time.gmtime())
        level: dict[str, int] = {}

        for line in response.text.splitlines()[1:]:
            try:
                cert_number, call_sign, member_number, *_rest, effective_date, endorsements = line.split("|")
            except ValueError:
                continue  # Skip malformed lines

            x_factor = int(cert_number.split()[1][1:]) if " " in cert_number else 1
            level[member_number] = x_factor

            skcc_effective_date = cSKCC.normalize_skcc_date(effective_date)

            if today_gmt < skcc_effective_date:
                print(f"  FYI: Brand new {Type}, {call_sign}, will be effective 00:00Z {effective_date}")
            elif Type == "Tribune" and (match := re.search(r"\*Tx8: (.*?)$", endorsements)):
                skcc_effective_tx8_date = cSKCC.normalize_skcc_date(match.group(1))
                if today_gmt < skcc_effective_tx8_date:
                    print(f"  FYI: Brand new Tx8, {call_sign}, will be effective 00:00Z {match.group(1)}")

        return level

    @staticmethod
    def read_roster(Name: str, URL: str) -> dict[str, int] | NoReturn:
        """Read roster with improved error handling."""
        print(f"Retrieving SKCC {Name} roster...")

        try:
            # Use a timeout to prevent hanging
            response = requests.get(f"https://www.skccgroup.com/{URL}", timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error retrieving {Name} roster: {e}")
            return {}  # Return empty dict rather than exiting

        rows = re.findall(r"<tr.*?>(.*?)</tr>", response.text, re.I | re.S)
        columns_regex = re.compile(r"<td.*?>(.*?)</td>", re.I | re.S)

        return {
            (cols := columns_regex.findall(row))[1]: int(cols[0].split()[1][1:]) if " " in cols[0] else 1
            for row in rows[1:]
            if (cols := columns_regex.findall(row)) and len(cols) >= 2  # Ensure valid row data
        }

    @classmethod
    def read_skcc_data(cls) -> None | NoReturn:
        """Read SKCC member data with improved error handling."""
        print('Retrieving SKCC award dates...')

        try:
            # Use a timeout to prevent hanging
            response = requests.get('https://www.skccgroup.com/membership_data/skccdata.txt', timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error retrieving SKCC data: {e}")
            sys.exit(1)

        if response.status_code != 200:
            print(f"Unexpected response code {response.status_code} from SKCC website")
            sys.exit(1)

        SkccList = response.text
        lines = SkccList.splitlines()

        # Clear existing data
        cls.members.clear()
        cls._member_cache.clear()

        for line in lines[1:]:
            try:
                fields = line.split("|")
                (
                    _number, current_call, name, _city, spc, other_calls, plain_number,_, join_date, c_date, t_date, tx8_date, s_date, _country
                ) = fields
            except ValueError:
                print("Error parsing SKCC data line. Skipping.")
                continue

            all_calls = [current_call] + [x.strip() for x in other_calls.split(",")] if other_calls else [current_call]

            for call in all_calls:
                cls.members[call] = {
                    'name'         : name,
                    'plain_number' : plain_number,
                    'spc'          : spc,
                    'join_date'    : cSKCC.normalize_skcc_date(join_date),
                    'c_date'       : cSKCC.normalize_skcc_date(c_date),
                    't_date'       : cSKCC.normalize_skcc_date(t_date),
                    'tx8_date'     : cSKCC.normalize_skcc_date(tx8_date),
                    's_date'       : cSKCC.normalize_skcc_date(s_date),
                    'main_call'    : current_call,
                }

        print(f"Successfully loaded data for {len(cls.members)} member callsigns")

    @staticmethod
    def is_on_skcc_frequency(frequency_khz: float, tolerance_khz: int = 10) -> bool:
        return any(
            ((Band == 60) and ((5332 - 1.5) <= frequency_khz <= (5405 + 1.5))) or
            any((((MidPoint - tolerance_khz) <= frequency_khz) and (frequency_khz <= (MidPoint + tolerance_khz))) for MidPoint in MidPoints)
            for Band, MidPoints in cSKCC._calling_frequencies_khz.items()
        )

    @staticmethod
    def which_band(frequency_khz: float, tolerance_khz: float = 10) -> int | None:
        return next(
            (Band for Band, MidPointsKHz in cSKCC._calling_frequencies_khz.items()
            for MidPointKHz in MidPointsKHz
            if (MidPointKHz - tolerance_khz) <= frequency_khz <= (MidPointKHz + tolerance_khz)),
            None
        )

    @staticmethod
    def which_arrl_band(frequency_khz: float) -> int | None:
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
            if lower < frequency_khz < upper:
                return band

        return None

    @staticmethod
    def is_on_warc_frequency(frequency_khz: float, tolerance_khz: int = 10) -> bool:
        return any(
            (CallingFrequencyKHz - tolerance_khz) <= frequency_khz <= (CallingFrequencyKHz + tolerance_khz)
            for Band in (30, 17, 12)
            for CallingFrequencyKHz in cSKCC._calling_frequencies_khz[Band]
        )

    @staticmethod
    def get_full_member_number(CallSign: str) -> tuple[str, str]:
        Entry = cSKCC.members[CallSign]

        MemberNumber = Entry['plain_number']

        Suffix = ''
        Level  = 1

        if cUtil.effective(Entry['s_date']):
            Suffix = 'S'
            Level = cSKCC.senator_level.get(MemberNumber, 1)
        elif cUtil.effective(Entry['t_date']):
            Suffix = 'T'
            Level = cSKCC.tribune_level.get(MemberNumber, 1)

            if Level == 8 and not cUtil.effective(Entry['tx8_date']):
                Level = 7
        elif cUtil.effective(Entry['c_date']):
            Suffix = 'C'
            Level = cSKCC.centurion_level.get(MemberNumber, 1)

        if Level > 1:
            Suffix += f'x{Level}'

        return (MemberNumber, Suffix)

    @staticmethod
    def lookups(LookupString: str) -> None:
        def print_callsign(CallSign: str):
            Entry = cSKCC.members[CallSign]

            MyNumber = cSKCC.members[config.MY_CALLSIGN]['plain_number']

            Report = [cUtil.build_member_info(CallSign)]

            if Entry['plain_number'] == MyNumber:
                Report.append('(you)')
            else:
                # Get goal and target hits in one pass
                GoalList = cQSO.get_goal_hits(CallSign)
                TargetList = cQSO.get_target_hits(CallSign)
                IsFriend = CallSign in config.FRIENDS

                if GoalList:
                    Report.append(f'YOU need them for {",".join(GoalList)}')

                if TargetList:
                    Report.append(f'THEY need you for {",".join(TargetList)}')

                if IsFriend:
                    Report.append('friend')

                if not GoalList and not TargetList:
                    Report.append("You don't need to work each other.")

            print(f'  {CallSign} - {"; ".join(Report)}')

        LookupList = cUtil.split(LookupString.upper())

        for Item in LookupList:
            # Check for member number format
            if match := re.match(r'^([0-9]+)[CTS]{0,1}$', Item):
                Number = match.group(1)

                # Find the callsign for this member number
                found = False
                for CallSign, Value in cSKCC.members.items():
                    if Value['plain_number'] == Number and CallSign == Value['main_call']:
                        print_callsign(CallSign)
                        found = True
                        break

                if not found:
                    print(f'  No member with the number {Number}.')
            else:
                # Check if it's a valid callsign
                if CallSign := cSKCC.extract_callsign(Item):
                    print_callsign(CallSign)
                else:
                    print(f'  {Item} - not an SKCC member.')

        print('')

class cRBN:
    connected: bool = False
    dot_count: int = 0

    @staticmethod
    async def resolve_host(host: str, port: int) -> list[tuple[socket.AddressFamily, str]]:
        """Resolve the host and return a list of (family, address) tuples, preferring IPv6."""
        try:
            addr_info = await asyncio.get_event_loop().getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            # Sort addresses to prioritize IPv6 (AF_INET6 before AF_INET)
            return sorted(
                [(ai[0], ai[4][0]) for ai in addr_info],
                key=lambda x: x[0] != socket.AF_INET6  # Prioritize IPv6
            )
        except socket.gaierror:
            return []  # Silently fail if DNS resolution fails

    @classmethod
    async def feed_generator(cls, callsign: str) -> AsyncGenerator[bytes, None]:
        """Try to connect to the RBN server, preferring IPv6 but falling back to IPv4."""

        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None

        while True:
            # Resolve the hostname dynamically
            addresses: list[tuple[socket.AddressFamily, str]] = await cRBN.resolve_host(RBN_SERVER, RBN_PORT)
            if not addresses:
                print(f"Error: No valid IP addresses found for {RBN_SERVER}. Retrying in 5 seconds...")
                await asyncio.sleep(5)
                continue

            cls.connected = False

            for family, ip in addresses:
                protocol: str = "IPv6" if family == socket.AF_INET6 else "IPv4"
                try:
                    reader, writer = await asyncio.open_connection(ip, RBN_PORT, family=family)
                    print(f"Connected to '{RBN_SERVER}' using {protocol}.")
                    cls.connected = True

                    # Authenticate with the RBN server
                    await reader.readuntil(b"call: ")
                    writer.write(f"{callsign}\r\n".encode("ascii"))
                    await writer.drain()
                    await reader.readuntil(b">\r\n\r\n")

                    while True:
                        try:
                            data: bytes = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=1.0)
                            yield data  # Send data to caller
                        except asyncio.TimeoutError:
                            continue  # Timeout is fine, just continue

                except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
                    pass  # Silently ignore & retry
                except asyncio.CancelledError:
                    raise  # Ensure proper cancellation handling
                except Exception:
                    pass  # Silently ignore unexpected errors
                finally:
                    # Cleanup connections properly
                    if writer is not None:
                        writer.close()
                        try:
                            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
                        except (asyncio.TimeoutError, Exception):
                            pass

                if reader and writer:  # If connection succeeds, stop trying
                    break

            if not cls.connected:
                print(f"Connection to {RBN_SERVER} failed over both IPv6 and IPv4. Retrying in 5 seconds...")
            await asyncio.sleep(5)

        # Final cleanup if cancelled
        if writer is not None and not writer.is_closing():
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                pass
        raise  # Re-raise cancellation

    @classmethod
    async def write_dots_task(cls):
        while True:
            await asyncio.sleep(config.PROGRESS_DOTS.DISPLAY_SECONDS)

            if cls.connected:
                print('.', end='', flush=True)
                cls.dot_count += 1

                if cls.dot_count % config.PROGRESS_DOTS.DOTS_PER_LINE == 0:
                    print('', flush=True)

    @classmethod
    def dot_count_reset(cls):
        cls.dot_count = 0

async def get_version() -> str:
    """
    Creates or loads version information. Runs GenerateVersionStamp.py to
    generate cVersion.py containing the version stamp of the HEAD commit.
    While GenerateVersionStamp.py is excluded from releases, cVersion.py must be
    included to provide accurate version information to the user.
    """
    if os.path.isfile("GenerateVersionStamp.py"):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "GenerateVersionStamp.py",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"GenerateVersionStamp.py failed:\n{stderr.decode()}")

    VERSION = "<development>"

    try:
        from cVersion import VERSION
    except ImportError:
        pass

    return VERSION

async def main_loop():
    global config, SPOTTERS_NEARBY, Spotters

    print(f'SKCC Skimmer version {await get_version()}\n')

    # Set up shutdown handlers early
    if platform.system() == "Windows":
        # Windows needs a separate thread to handle KeyboardInterrupt
        ctrl_c_thread = threading.Thread(target=cUtil.watch_for_ctrl_c, daemon=True)
        ctrl_c_thread.start()
    else:
        # Unix-like systems can use signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, cUtil.handle_shutdown)

    ArgV = sys.argv[1:]

    config = cConfig(ArgV)

    cSKCC.block_during_update_window()

    if config.VERBOSE:
        config.PROGRESS_DOTS.ENABLED = False

    cUtil.file_check(config.ADI_FILE)

    # Initialize SKCC data with parallel downloads
    cSKCC.initialize()

    if config.MY_CALLSIGN not in cSKCC.members:
        print(f"'{config.MY_CALLSIGN}' is not a member of SKCC.")
        sys.exit()

    # Initialize QSO data
    cQSO.initialize()
    cQSO.get_goal_qsos()
    cQSO.print_progress()

    print('')
    cQSO.awards_check()

    # Handle interactive mode if enabled
    if config.INTERACTIVE:
        print('\nInteractive mode. Enter callsigns or "q" to quit, "r" to refresh.\n')

        while True:
            print('> ', end='', flush=True)

            try:
                match sys.stdin.readline().strip().lower():
                    case 'q' | 'quit':
                        print("\nExiting by user request...")
                        return
                    case 'r' | 'refresh':
                        cQSO.refresh()
                    case '':
                        continue
                    case cmd:
                        print('')
                        cSKCC.lookups(cmd)
            except KeyboardInterrupt:
                print("\nExiting immediately...")
                os._exit(0)

    # Get nearby spotters
    Spotters = cSpotters()
    Spotters.get_spotters()

    nearby_list_with_distance = Spotters.get_nearby_spotters()
    formatted_nearby_list_with_distance = [f'{Spotter}({cUtil.format_distance(Miles)})' for Spotter, Miles in nearby_list_with_distance]
    SPOTTERS_NEARBY = [Spotter for Spotter, _ in nearby_list_with_distance]

    print(f'  Found {len(formatted_nearby_list_with_distance)} nearby spotters:')

    wrapped_spotter_lines = textwrap.wrap(', '.join(formatted_nearby_list_with_distance), width=80)

    for spotter_line in wrapped_spotter_lines:
        print(f'    {spotter_line}')

    # Clear log file if needed
    if config.LOG_FILE.DELETE_ON_STARTUP:
        Filename = config.LOG_FILE.FILE_NAME
        if Filename is not None and os.path.exists(Filename):
            os.remove(Filename)

    print()
    print('Running...')
    print()

    # Create tasks and let them run until program exit
    tasks: list[asyncio.Task[None]] = []

    tasks.append(asyncio.create_task(cQSO.watch_logfile_task()))
    tasks.append(asyncio.create_task(cSPOTS.handle_spots_task()))

    if config.PROGRESS_DOTS.ENABLED:
        tasks.append(asyncio.create_task(cRBN.write_dots_task()))

    if config.SKED.ENABLED:
        tasks.append(asyncio.create_task(cSked.sked_page_scraper_task()))

    # Wait indefinitely until interrupted by Ctrl+C
    try:
        await asyncio.Future()  # This future never completes
    except asyncio.CancelledError:
        pass  # This won't happen since we exit with os._exit(0)

asyncio.run(main_loop())
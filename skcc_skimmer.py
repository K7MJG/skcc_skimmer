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



from datetime import timedelta, datetime
from typing import Any, NoReturn, Literal, get_args, AsyncGenerator, ClassVar, Final, Coroutine, TypedDict, Self, Iterator
from math import radians, sin, cos, atan2, sqrt
from dataclasses import dataclass, field

import asyncio
import aiohttp
from aiohttp import ClientTimeout
import aiofiles
import aiofiles.os
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
import platform

RBN_SERVER = "telnet.reversebeacon.net"
RBN_PORT   = 7000

# URL constants
SKED_STATUS_URL = 'http://sked.skccgroup.com/get-status.php'
RBN_STATUS_URL = 'https://reversebeacon.net/cont_includes/status.php?t=skt'
SKCC_DATA_URL = 'https://skccgroup.com/skimmer-data.txt'
SKCC_BASE_URL = 'https://www.skccgroup.com/'

# Global state for progress dot display
_progress_dot_count: int = 0

US_STATES: Final[set[str]] = {
    'AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD',
    'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH',
    'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY',
}

# Award level requirements
Levels: Final[dict[str, int]] = {
    'C'  :    100,
    'T'  :     50,
    'S'  :    200,
    'P'  : 250000,
}

# Award dates - when each award started
class AwardDates:
    PREFIX_START: Final[str] = '20130101000000'
    TRIBUNE_START: Final[str] = '20070301000000'
    SENATOR_START: Final[str] = '20130801000000'
    WAS_C_START: Final[str] = '20110612000000'
    WAS_TS_START: Final[str] = '20160201000000'

# Prefix award thresholds
class PrefixThresholds:
    INCREMENT: Final[int] = 500_000
    MILESTONE_10M: Final[int] = 10_000_000

class cUtil:
    @staticmethod
    def split(text: str, /) -> list[str]:
        return re.split(r'[,\s]+', text.strip())

    @staticmethod
    def effective(date: str) -> str:
        return date if time.strftime('%Y%m%d000000', time.gmtime()) >= date else ''

    @staticmethod
    def miles_to_km(miles: int) -> int:
        return round(miles * 1.609344)

    @staticmethod
    def stripped(text: str) -> str:
        return ''.join(c for c in text if 31 < ord(c) < 127)

    @staticmethod
    def beep() -> None:
        print('\a', end='', flush=True)

    @staticmethod
    def format_distance(miles: int) -> str:
        if cConfig.DISTANCE_UNITS == "mi":
            return f'{miles}mi'

        return f'{cUtil.miles_to_km(miles)}km'

    @staticmethod
    async def log_async(line: str) -> None:
        if cConfig.LOG_FILE.ENABLED and cConfig.LOG_FILE.FILE_NAME is not None:
            async with aiofiles.open(cConfig.LOG_FILE.FILE_NAME, 'a', encoding='utf-8') as file:
                await file.write(line + '\n')

    @staticmethod
    async def log_error_async(line: str) -> None:
        if cConfig.LOG_BAD_SPOTS:
            async with aiofiles.open('Bad_RBN_Spots.log', 'a', encoding='utf-8') as file:
                await file.write(line + '\n')

    @staticmethod
    def abbreviate_class(Class: str, X_Factor: int) -> str:
        if X_Factor > 1:
            return f'{Class}x{X_Factor}'

        return Class

    @staticmethod
    async def file_check_async(Filename: str) -> None | NoReturn:
        if await aiofiles.os.path.exists(Filename):
            return

        print()
        print(f"File '{Filename}' does not exist.")
        print()
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
            band in cConfig.BANDS and lowKHz <= FrequencyKHz <= highKHz
            for band, (lowKHz, highKHz) in bands.items()
        )

    @staticmethod
    def handle_shutdown(_signum: int, _frame: object | None = None) -> None:
        """Exits immediately when Ctrl+C is detected."""
        # Print a clean exit message and force immediate exit
        try:
            print("\n\nExiting...")
            sys.stdout.flush()
        except:
            pass
        # Force immediate exit without any cleanup or traceback
        os._exit(0)

    @staticmethod
    async def watch_for_ctrl_c_async() -> NoReturn:
        """Runs in the event loop to detect Ctrl+C on Windows."""
        try:
            # Just wait indefinitely until KeyboardInterrupt
            while True:
                await asyncio.sleep(0.1)
        except KeyboardInterrupt:
            # Print a clean exit message and force immediate exit
            try:
                print("\n\nExiting...")
                sys.stdout.flush()
            except:
                pass
            os._exit(0)

    @staticmethod
    def calculate_next_award_name(Class: str, current_x_factor: int) -> str:
        next_x_factor = current_x_factor + 1

        # Handle special cases for X_Factor progression
        if current_x_factor == 10:
            next_x_factor = 15
        elif current_x_factor > 10 and current_x_factor % 5 == 0:
            next_x_factor = current_x_factor + 5

        return cUtil.abbreviate_class(Class, next_x_factor)

class cConfig:
    @dataclass
    class cProgressDots:
        ENABLED:         bool = True
        DISPLAY_SECONDS: int  = 10
        DOTS_PER_LINE:   int  = 30
    @classmethod
    def init_progress_dots(cls) -> None:
        progress_config = cls.config_file.get("PROGRESS_DOTS", {})
        cls.PROGRESS_DOTS = cConfig.cProgressDots(
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
    @classmethod
    def init_logfile(cls) -> None:
        log_file_config = cls.config_file.get("LOG_FILE", {})
        cls.LOG_FILE = cConfig.cLogFile(
            ENABLED           = bool(log_file_config.get("ENABLED", cConfig.cLogFile.ENABLED)),
            FILE_NAME         = log_file_config.get("FILE_NAME", cConfig.cLogFile.FILE_NAME),
            DELETE_ON_STARTUP = bool(log_file_config.get("DELETE_ON_STARTUP", cConfig.cLogFile.DELETE_ON_STARTUP))
        )

    @dataclass
    class cHighWpm:
        tAction = Literal['suppress', 'warn', 'always-display']
        ACTION: tAction = 'always-display'
        THRESHOLD: int = 15
    @classmethod
    def init_high_wpm(cls) -> None:
        high_wpm_config = cls.config_file.get("HIGH_WPM", {})
        action: cConfig.cHighWpm.tAction = high_wpm_config.get("ACTION", cConfig.cHighWpm.ACTION)
        if action not in get_args(cConfig.cHighWpm.tAction):
            print(f"Invalid ACTION: {action}. Must be one of {get_args(cConfig.cHighWpm.tAction)}.")
            action = cConfig.cHighWpm.ACTION

        cls.HIGH_WPM = cConfig.cHighWpm(
            ACTION    = action,
            THRESHOLD = int(high_wpm_config.get("THRESHOLD", cConfig.cHighWpm.THRESHOLD))
        )

    @dataclass
    class cOffFrequency:
        ACTION:    Literal['suppress', 'warn'] = 'suppress'
        TOLERANCE: int = 0
    @classmethod
    def init_off_frequency(cls) -> None:
        off_frequency_config = cls.config_file.get("OFF_FREQUENCY", {})
        cls.OFF_FREQUENCY = cConfig.cOffFrequency(
            ACTION    =     off_frequency_config.get("ACTION",    cConfig.cOffFrequency.ACTION),
            TOLERANCE = int(off_frequency_config.get("TOLERANCE", cConfig.cOffFrequency.TOLERANCE))
        )

    @dataclass
    class cSked:
        ENABLED:       bool = True
        CHECK_SECONDS: int  = 60
    @classmethod
    def init_sked(cls) -> None:
        sked_config = cls.config_file.get("SKED", {})
        cls.SKED = cConfig.cSked(
            ENABLED       = sked_config.get("ENABLED",       cConfig.cSked.ENABLED),
            CHECK_SECONDS = sked_config.get("CHECK_SECONDS", cConfig.cSked.CHECK_SECONDS),
        )

    @dataclass
    class cNotification:
        DEFAULT_CONDITION = ['goals', 'targets', 'friends']  # Class-level default
        ENABLED: bool = True
        CONDITION: list[str] = field(default_factory=lambda: cConfig.cNotification.DEFAULT_CONDITION)
        RENOTIFICATION_DELAY_SECONDS: int = 30
    @classmethod
    def init_notifications(cls) -> None:
        notification_config = cls.config_file.get("NOTIFICATION", {})
        conditions = cUtil.split(notification_config.get("CONDITION", cConfig.cNotification.DEFAULT_CONDITION))  # Use DEFAULT_CONDITION
        invalid_conditions = [c for c in conditions if c not in ['goals', 'targets', 'friends']]
        if invalid_conditions:
            print(f"Invalid NOTIFICATION CONDITION(s): {invalid_conditions}. Must be 'goals', 'targets', or 'friends'.")
            sys.exit()
        cls.NOTIFICATION = cConfig.cNotification(
            ENABLED                      = bool(notification_config.get("ENABLED", cConfig.cNotification.ENABLED)),
            CONDITION                    = conditions,
            RENOTIFICATION_DELAY_SECONDS = int(notification_config.get("RENOTIFICATION_DELAY_SECONDS", cConfig.cNotification.RENOTIFICATION_DELAY_SECONDS))
        )

    MY_CALLSIGN:              str
    ADI_FILE:                 str
    MY_GRIDSQUARE:            str
    GOALS:                    set[str]
    TARGETS:                  set[str]
    BANDS:                    list[int]
    FRIENDS:                  set[str]
    EXCLUSIONS:               set[str]
    DISTANCE_UNITS:           str
    SPOT_PERSISTENCE_MINUTES: int
    VERBOSE:                  bool
    LOG_BAD_SPOTS:            bool
    SPOTTER_RADIUS:           int
    SPOTTERS_NEARBY:          set[str]
    K3Y_YEAR:                 int

    config_file:              dict[str, Any]

    @classmethod
    async def init(cls, argv_v: list[str]) -> None:
        async def read_skcc_skimmer_cfg_async() -> dict[str, Any]:
            config_vars: dict[str, Any] = {}

            ConfigFileAbsolute = os.path.abspath('skcc_skimmer.cfg')
            cDisplay.print(f"Reading skcc_skimmer.cfg from '{ConfigFileAbsolute}'...")

            async with aiofiles.open(ConfigFileAbsolute, 'r', encoding='utf-8') as config_file:
                ConfigFileString = await config_file.read()
                exec(ConfigFileString, {}, config_vars)

            return config_vars

        cls.config_file = await read_skcc_skimmer_cfg_async()

        cls.MY_CALLSIGN = cls.config_file.get('MY_CALLSIGN', '')
        cls.ADI_FILE = cls.config_file.get('ADI_FILE', '')
        cls.MY_GRIDSQUARE = cls.config_file.get('MY_GRIDSQUARE', '')
        cls.GOALS = set()
        cls.TARGETS = set()
        cls.BANDS = []
        cls.FRIENDS = set()
        cls.EXCLUSIONS = set()
        cls.SPOTTERS_NEARBY = set()

        if 'SPOTTERS_NEARBY' in cls.config_file:
            cls.SPOTTERS_NEARBY = {spotter for spotter in cUtil.split(cls.config_file['SPOTTERS_NEARBY'])}

        if 'SPOTTER_RADIUS' in cls.config_file:
            cls.SPOTTER_RADIUS = int(cls.config_file['SPOTTER_RADIUS'])

        if 'GOALS' in cls.config_file:
            cls.GOALS = set(cls.parse_goals(cls.config_file['GOALS'], 'C T S WAS WAS-C WAS-T WAS-S P BRAG K3Y QRP DX TKA', 'goal'))

        if 'TARGETS' in cls.config_file:
            cls.TARGETS = set(cls.parse_goals(cls.config_file['TARGETS'], 'C T S', 'target'))

        if 'BANDS' in cls.config_file:
            cls.BANDS = [int(Band) for Band in cUtil.split(cls.config_file['BANDS'])]

        if 'FRIENDS' in cls.config_file:
            cls.FRIENDS = {friend for friend in cUtil.split(cls.config_file['FRIENDS'])}

        if 'EXCLUSIONS' in cls.config_file:
            cls.EXCLUSIONS = {friend for friend in cUtil.split(cls.config_file['EXCLUSIONS'])}

        cls.init_logfile()
        cls.init_progress_dots()
        cls.init_sked()
        cls.init_notifications()
        cls.init_off_frequency()
        cls.init_high_wpm()

        cls.VERBOSE = bool(cls.config_file.get('VERBOSE', False))
        cls.LOG_BAD_SPOTS = bool(cls.config_file.get('LOG_BAD_SPOTS', False))

        cls.DISTANCE_UNITS = cls.config_file.get('DISTANCE_UNITS', 'mi')
        if cls.DISTANCE_UNITS not in ('mi', 'km'):
            cls.DISTANCE_UNITS = 'mi'

        if 'K3Y_YEAR' in cls.config_file:
            cls.K3Y_YEAR = cls.config_file['K3Y_YEAR']
        else:
            cls.K3Y_YEAR = datetime.now().year

        cls._parse_args(argv_v)
        cls._validate_config()

    @classmethod
    def _parse_args(cls, arg_v: list[str]) -> None:
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

        args = parser.parse_args(arg_v)

        cls.INTERACTIVE = args.interactive
        cls.VERBOSE = args.verbose

        if args.adi:
            cls.ADI_FILE = args.adi
        if args.bands:
            cls.BANDS = [int(band) for band in cUtil.split(args.bands)]
        if args.brag_months:
            cls.BRAG_MONTHS = args.brag_months
        if args.callsign:
            cls.MY_CALLSIGN = args.callsign.upper()
        if args.distance_units:
            cls.DISTANCE_UNITS = args.distance_units
        if args.goals:
            cls.GOALS = set(cls.parse_goals(args.goals, "C T S WAS WAS-C WAS-T WAS-S P BRAG K3Y QRP DX TKA", "goal"))
        if args.logfile:
            cls.LOG_FILE.ENABLED = True
            cls.LOG_FILE.DELETE_ON_STARTUP = True
            cls.LOG_FILE.FILE_NAME = args.logfile
        if args.maidenhead:
            cls.MY_GRIDSQUARE = args.maidenhead
        if args.notification:
            cls.NOTIFICATION.ENABLED = args.notification == "on"
        if args.radius:
            cls.SPOTTER_RADIUS = args.radius
        if args.sked:
            cls.SKED.ENABLED = args.sked == "on"
        if args.targets:
            cls.TARGETS = set(cls.parse_goals(args.targets, "C T S", "target"))

    @classmethod
    def _validate_config(cls) -> None:
        #
        # MY_CALLSIGN can be defined in skcc_skimmer.cfg.  It is not required
        # that it be supplied on the command line.
        #
        if not cls.MY_CALLSIGN:
            print("You must specify your callsign, either on the command line or in 'skcc_skimmer.cfg'.")
            print()
            cls.usage()

        if not cls.ADI_FILE:
            print("You must supply an ADI file, either on the command line or in 'skcc_skimmer.cfg'.")
            print()
            cls.usage()

        if not cls.GOALS and not cls.TARGETS:
            print('You must specify at least one goal or target.')
            sys.exit()

        if not cls.MY_GRIDSQUARE:
            print("'MY_GRIDSQUARE' in skcc_skimmer.cfg must be a 4 or 6 character maidenhead grid value.")
            sys.exit()

        if 'SPOTTER_RADIUS' not in cls.config_file:
            print("'SPOTTER_RADIUS' must be defined in skcc_skimmer.cfg.")
            sys.exit()

        if 'QUALIFIERS' in cls.config_file:
            print("'QUALIFIERS' is no longer supported and can be removed from 'skcc_skimmer.cfg'.")
            sys.exit()

        if 'NEARBY' in cls.config_file:
            print("'NEARBY' has been replaced with 'SPOTTERS_NEARBY'.")
            sys.exit()

        if 'SPOTTER_PREFIXES' in cls.config_file:
            print("'SPOTTER_PREFIXES' has been deprecated.")
            sys.exit()

        if 'SPOTTERS_NEARBY' in cls.config_file:
            print("'SPOTTERS_NEARBY' has been deprecated.")
            sys.exit()

        if 'SKCC_FREQUENCIES' in cls.config_file:
            print("'SKCC_FREQUENCIES' is now caluclated internally.  Remove it from 'skcc_skimmer.cfg'.")
            sys.exit()

        if 'HITS_FILE' in cls.config_file:
            print("'HITS_FILE' is no longer supported.")
            sys.exit()

        if 'HitCriteria' in cls.config_file:
            print("'HitCriteria' is no longer supported.")
            sys.exit()

        if 'StatusCriteria' in cls.config_file:
            print("'StatusCriteria' is no longer supported.")
            sys.exit()

        if 'SkedCriteria' in cls.config_file:
            print("'SkedCriteria' is no longer supported.")
            sys.exit()

        if 'SkedStatusCriteria' in cls.config_file:
            print("'SkedStatusCriteria' is no longer supported.")
            sys.exit()

        if 'SERVER' in cls.config_file:
            print('SERVER is no longer supported.')
            sys.exit()

        if 'SPOT_PERSISTENCE_MINUTES' not in cls.config_file:
            cls.SPOT_PERSISTENCE_MINUTES = 15

        if 'GOAL' in cls.config_file:
            print("'GOAL' has been replaced with 'GOALS' and has a different syntax and meaning.")
            sys.exit()

        if 'GOALS' not in cls.config_file:
            print("GOALS must be defined in 'skcc_skimmer.cfg'.")
            sys.exit()

        if 'TARGETS' not in cls.config_file:
            print("TARGETS must be defined in 'skcc_skimmer.cfg'.")
            sys.exit()

        if 'HIGH_WPM' not in cls.config_file:
            print("HIGH_WPM must be defined in 'skcc_skimmer.cfg'.")
            sys.exit()

        if cls.HIGH_WPM.ACTION not in ('suppress', 'warn', 'always-display'):
            print("HIGH_WPM['ACTION'] must be one of ('suppress', 'warn', 'always-display')")
            sys.exit()

        if 'OFF_FREQUENCY' not in cls.config_file:
            print("OFF_FREQUENCY must be defined in 'skcc_skimmer.cfg'.")
            sys.exit()

        if cls.OFF_FREQUENCY.ACTION not in ('suppress', 'warn'):
            print("OFF_FREQUENCY['ACTION'] must be one of ('suppress', 'warn')")
            sys.exit()

        if 'NOTIFICATION' not in cls.config_file:
            print("'NOTIFICATION' must be defined in skcc_skimmer.cfg.")
            sys.exit()

    @staticmethod
    def usage() -> NoReturn:
        print('Usage:')
        print()
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
        print()
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
        print()
        sys.exit()

    @staticmethod
    def parse_goals(string: str, all_str: str, type_str: str) -> list[str]:
        all: list[str] = all_str.split()
        parsed: list[str] = cUtil.split(string.upper())

        # Using pattern matching simplifies the logic
        match parsed:
            case ['ALL']: return all
            case ['NONE']: return []
            case items:
                # Handle deprecation warnings and convert CXN/TXN/SXN to C/T/S
                deprecated_mappings = {'CXN': 'C', 'TXN': 'T', 'SXN': 'S'}
                for deprecated, replacement in deprecated_mappings.items():
                    if deprecated in items:
                        print(f"WARNING: '{deprecated}' is deprecated. Use '{replacement}' instead.")
                        print( "         The system will automatically handle both initial awards and multipliers.")
                        items.remove(deprecated)
                        if replacement not in items:
                            items.append(replacement)

                # Handle negation syntax (e.g., ALL,-BRAG)
                # Negation only applies when ALL is specified
                result: list[str] = []
                negated: list[str] = []
                has_all: bool = False

                for item in items:
                    if item.startswith('-'):
                        # Remove the '-' prefix and add to negated list
                        negated_item: str = item[1:]
                        if negated_item in all:
                            negated.append(negated_item)
                        else:
                            print(f"Unrecognized {type_str} '{item}' (negated item '{negated_item}' not found).")
                            sys.exit()
                    else:
                        # Regular item
                        if item == 'ALL':
                            has_all = True
                            result.extend(all)
                        elif item in all:
                            result.append(item)
                        else:
                            print(f"Unrecognized {type_str} '{item}'.")
                            sys.exit()

                # Check if negation was used without ALL
                if negated and not has_all:
                    print("Negation syntax (e.g., '-BRAG') can only be used with 'ALL'. Example: 'ALL,-BRAG'")
                    sys.exit()

                # Remove duplicates and apply negations
                result = list(set(result))  # Remove duplicates
                for negated_item in negated:
                    if negated_item in result:
                        result.remove(negated_item)

                return result

class cFastDateTime:
    FastDateTime: str

    MONTH_NAMES: Final = 'January February March April May June July August September October November December'.split()

    def __init__(self, Object: datetime | time.struct_time | tuple[int, int, int] | tuple[int, int, int, int, int, int] | str | None) -> None:
        if isinstance(Object, datetime):
            self.FastDateTime = Object.strftime('%Y%m%d%H%M%S')

        elif isinstance(Object, time.struct_time):
            self.FastDateTime = time.strftime('%Y%m%d%H%M%S', Object)

        elif isinstance(Object, tuple):
            if len(Object) == 3:
                year, month, day = Object
                self.FastDateTime = f'{year:0>4}{month:0>2}{day:0>2}000000'
            elif len(Object) == 6:
                year, month, day, hour, minute, second = Object
                self.FastDateTime = f"{year:04}{month:02}{day:02}{hour:02}{minute:02}{second:02}"

        elif isinstance(Object, str):
            self.FastDateTime = Object

        else:
            self.FastDateTime = ''

    def split_date_time(self) -> list[int]:
        return list(map(int, [self.FastDateTime[:4],   self.FastDateTime[4:6],   self.FastDateTime[6:8],
                              self.FastDateTime[8:10], self.FastDateTime[10:12], self.FastDateTime[12:14]]))

    def start_of_month(self) -> Self:
        Year, Month, _Day, _Hour, _Minute, _Second = self.split_date_time()
        return type(self)(f'{Year:0>4}{Month:0>2}{1:0>2}000000')

    def end_of_month(self) -> Self:
        Year, Month, _Day, _Hour, _Minute, _Second = self.split_date_time()
        _, DaysInMonth = calendar.monthrange(Year, Month)
        return type(self)(f'{Year:0>4}{Month:0>2}{DaysInMonth:0>2}235959')

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

    def first_weekday_after_date(self, target_weekday: str) -> 'cFastDateTime':
        target_weekday_number = time.strptime(target_weekday, '%a').tm_wday
        date_time = self.to_datetime()

        while True:
            date_time += timedelta(days=1)

            if date_time.weekday() == target_weekday_number:
                return cFastDateTime(date_time)

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
    def print(text: str) -> None:
        global _progress_dot_count
        if _progress_dot_count > 0:
            print()

        print(text)
        _progress_dot_count = 0

class cSked:
    _RegEx:          ClassVar[re.Pattern[str]] = re.compile('<span class="callsign">(.*?)<span>(?:.*?<span class="userstatus">(.*?)</span>)?')
    _Freq_RegEx:     ClassVar[re.Pattern[str]] = re.compile(r"\b(\d{1,2}\.\d{3}\.\d{1,3})|(\d{1,2}\.\d{3})|(\d{4,5}\.\d{1,3})|(\d{4,5})\b\s*$")
    _SkedSite:       ClassVar[str | None] = None

    _PreviousLogins: ClassVar[dict[str, list[str]]] = {}
    _FirstPass:      ClassVar[bool] = True

    @classmethod
    async def handle_logins_async(cls, SkedLogins: list[tuple[str, str]], Heading: str) -> dict[str, list[str]]:
        SkedHit: dict[str, list[str]] = {}

        # Create tasks for processing all logins in parallel
        processing_tasks: list[Coroutine[Any, Any, None]]  = []

        for orig_call, status in SkedLogins:
            if orig_call == cConfig.MY_CALLSIGN:
                continue

            call_sign = cSKCC.extract_callsign(orig_call)
            if not call_sign or call_sign in cConfig.EXCLUSIONS:
                continue

            processing_tasks.append(cls._process_login_async(call_sign, status, SkedHit))

        # Wait for all processing to complete
        await asyncio.gather(*processing_tasks)

        if SkedHit:
            GMT = time.gmtime()
            ZuluTime = time.strftime('%H%MZ', GMT)
            ZuluDate = time.strftime('%Y-%m-%d', GMT)

            if cls._FirstPass:
                NewLogins: list[str] = []
            else:
                NewLogins = list(set(SkedHit) - set(cls._PreviousLogins))

            cDisplay.print('=========== ' + Heading + ' Sked Page ' + '=' * (16-len(Heading)))

            for CallSign in sorted(SkedHit):
                GoalList = list(hit for hit in SkedHit[CallSign] if hit.startswith("YOU need them for"))
                TargetList = list(hit for hit in SkedHit[CallSign] if hit.startswith("THEY need you for"))
                IsFriend = "friend" in SkedHit[CallSign]

                if CallSign in NewLogins:
                    if cConfig.NOTIFICATION.ENABLED:
                        if (IsFriend and 'friends' in cConfig.NOTIFICATION.CONDITION) or \
                        (GoalList and 'goals' in cConfig.NOTIFICATION.CONDITION) or \
                        (TargetList and 'targets' in cConfig.NOTIFICATION.CONDITION):
                            cUtil.beep()

                    NewIndicator = '+'
                else:
                    NewIndicator = ' '

                Out = f'{ZuluTime}{NewIndicator}{CallSign:<6} {"; ".join(SkedHit[CallSign])}'
                cDisplay.print(Out)
                await cUtil.log_async(f'{ZuluDate} {Out}')

            # Only add the separator here, not at the end
            cDisplay.print('=======================================')

            cls._PreviousLogins = SkedHit
            cls._FirstPass = False

        return SkedHit

    @classmethod
    async def _process_login_async(cls, CallSign: str, Status: str, SkedHit: dict[str, list[str]]) -> None:
        """Process a single sked login asynchronously and add to SkedHit if relevant."""
        Report: list[str] = [cSKCC.build_member_info(CallSign)]

        if CallSign in cSPOTS.last_spotted:
            FrequencyKHz, StartTime = cSPOTS.last_spotted[CallSign]

            Now = time.time()
            DeltaSeconds = max(int(Now - StartTime), 1)

            if DeltaSeconds > cConfig.SPOT_PERSISTENCE_MINUTES * 60:
                del cSPOTS.last_spotted[CallSign]
            elif DeltaSeconds > 60:
                DeltaMinutes = DeltaSeconds // 60
                Units = 'minutes' if DeltaMinutes > 1 else 'minute'
                Report.append(f'Last spotted {DeltaMinutes} {Units} ago on {FrequencyKHz}')
            else:
                Units = 'seconds' if DeltaSeconds > 1 else 'second'
                Report.append(f'Last spotted {DeltaSeconds} {Units} ago on {FrequencyKHz}')

        GoalList: list[str] = []

        if 'K3Y' in cConfig.GOALS and Status:
            # K3Y processing logic here...
            K3Y_RegEx = r'\b(K3Y)/([0-9]|KP4|KH6|KL7)\b'
            SKM_RegEx = r'\b(SKM)[\/-](AF|AS|EU|NA|OC|SA)\b'
            # Use hoisted regex pattern
            Freq_RegEx = cls._Freq_RegEx

            Matches = re.search(K3Y_RegEx, Status, re.IGNORECASE)
            if Matches:
                Type, Station = Matches.group(1), Matches.group(2).upper()
            else:
                Matches = re.search(SKM_RegEx, Status, re.IGNORECASE)
                if Matches:
                    Type, Station = Matches.group(1), Matches.group(2).upper()
                else:
                    Type, Station = None, None

            if Type and Station:
                match = Freq_RegEx.search(Status)
                if match:
                    FrequencyStr = match.group(1) or match.group(2) or match.group(3) or match.group(4)
                    if FrequencyStr:
                        FrequencyKHz = float(FrequencyStr.replace('.', '', 1)) if match.group(1) else float(FrequencyStr) * (1000 if match.group(2) else 1)
                        Band = cSKCC.which_band(FrequencyKHz)
                        if Band:
                            if (not Station in cQSO.ContactsForK3Y) or (not Band in cQSO.ContactsForK3Y[Station]):
                                GoalList.append(f'{"SKM-" + Station if Type == "SKM" else "K3Y/" + Station} ({Band}m)')
                else:
                    GoalList.append(f'{"SKM-" + Station if Type == "SKM" else "K3Y/" + Station}')

        # Add regular goal hits
        GoalList.extend(cQSO.get_goal_hits(CallSign))

        if GoalList:
            Report.append(f'YOU need them for {",".join(GoalList)}')

        TargetList = cQSO.get_target_hits(CallSign)

        if TargetList:
            Report.append(f'THEY need you for {",".join(TargetList)}')

        IsFriend = CallSign in cConfig.FRIENDS

        if IsFriend:
            Report.append('friend')

        if Status:
            Report.append(f'STATUS: {cUtil.stripped(Status)}')

        if TargetList or GoalList or IsFriend:
            SkedHit[CallSign] = Report

    @classmethod
    async def display_logins_async(cls) -> None:
        """Async version of display_logins."""
        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=10)) as session:
                async with session.get(SKED_STATUS_URL) as response:
                    if response.status != 200:
                        return

                    Content = await response.text()
                    Hits = {}

                    if Content:
                        try:
                            SkedLogins: list[tuple[str, str]] = json.loads(Content)
                            Hits = await cls.handle_logins_async(SkedLogins, 'SKCC')
                        except Exception as ex:
                            print(f"*** Problem parsing data sent from the SKCC Sked Page: '{Content}'.  Details: '{ex}'.")

                    cls._PreviousLogins = Hits
                    cls._FirstPass = False
        except Exception as e:
            print(f"\nProblem retrieving information from the Sked Page: {e}. Skipping...")

    @classmethod
    async def sked_page_scraper_task_async(cls) -> NoReturn:
        """Updated async task for the sked page scraper."""
        while True:
            try:
                await cls.display_logins_async()
            except Exception as e:
                print(f"Error in DisplayLogins: {e}")

            await asyncio.sleep(cConfig.SKED.CHECK_SECONDS)

class cSPOTS:
    last_spotted: ClassVar[dict[str, tuple[float, float]]] = {}
    _Notified:    ClassVar[dict[str, float]] = {}

    _Zulu_RegEx:  ClassVar[re.Pattern[str]] = re.compile(r'^([01]?[0-9]|2[0-3])[0-5][0-9]Z$')
    _dB_RegEx:    ClassVar[re.Pattern[str]] = re.compile(r'^\s{0,1}\d{1,2} dB$')

    @classmethod
    async def handle_spots_task(cls) -> None:
        generator = cRBN.feed_generator(cConfig.MY_CALLSIGN)

        async for data in generator:
            try:
                line = data.rstrip().decode("ascii", errors="replace")
                await cSPOTS.handle_spot_async(line)
            except Exception as e:
                # Don't let processing errors crash the whole task
                print(f"Error processing spot: {e}")
                continue

    @staticmethod
    async def parse_spot_async(Line: str) -> None | tuple[str, str, float, str, str, int, int]:
        # Using pattern matching to simplify the code
        if len(Line) != 75 or not Line.startswith('DX de '):
            await cUtil.log_error_async(Line)
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
                await cUtil.log_error_async(Line)
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
            await cUtil.log_error_async(Line)
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
            if cConfig.NOTIFICATION.ENABLED:
                if (CallSign in cConfig.FRIENDS and 'friends' in cConfig.NOTIFICATION.CONDITION) or (GoalList and 'goals' in cConfig.NOTIFICATION.CONDITION) or (TargetList and 'targets' in cConfig.NOTIFICATION.CONDITION):
                    cUtil.beep()

            NotificationFlag = '+'
            cls._Notified[CallSign] = Now + cConfig.NOTIFICATION.RENOTIFICATION_DELAY_SECONDS

        return NotificationFlag

    @classmethod
    async def handle_spot_async(cls, Line: str) -> None:
        if cConfig.VERBOSE:
            print(f'   {Line}')

        if not (Spot := await cSPOTS.parse_spot_async(Line)):
            await cUtil.log_error_async(Line)  # Use the async log_error method
            return

        Zulu, Spotter, FrequencyKHz, CallSign, CallSignSuffix, dB, WPM = Spot
        Report: list[str] = []

        # Extract callsign and validate
        if not (CallSign := cSKCC.extract_callsign(CallSign)) or CallSign in cConfig.EXCLUSIONS:
            return

        # Check if frequency is in the configured bands
        if not cUtil.is_in_bands(FrequencyKHz):
            return

        # Check if spotter is nearby
        SpottedNearby = Spotter in cConfig.SPOTTERS_NEARBY
        
        # Process spotter information
        if SpottedNearby or CallSign == cConfig.MY_CALLSIGN:
            if Spotter in cSpotters.spotters:
                Miles = cSpotters.get_distance(Spotter)
                Distance = cUtil.format_distance(Miles)
                Report.append(f'by {Spotter}({Distance}, {int(dB)}dB)')
            else:
                Report.append(f'by {Spotter}({int(dB)}dB)')

        # Check if this is the user's callsign
        if CallSign == cConfig.MY_CALLSIGN:
            Report.append('(you)')

        # Check frequency
        if CallSign != 'K3Y':
            OnFrequency = cSKCC.is_on_skcc_frequency(FrequencyKHz, cConfig.OFF_FREQUENCY.TOLERANCE)
            if not OnFrequency:
                match cConfig.OFF_FREQUENCY.ACTION:
                    case 'warn':
                        Report.append('OFF SKCC FREQUENCY!')
                    case 'suppress':
                        return

        # Handle WPM
        match cConfig.HIGH_WPM.ACTION:
            case 'always-display':
                Report.append(f'{WPM} WPM')
            case 'warn' if WPM >= cConfig.HIGH_WPM.THRESHOLD:
                Report.append(f'{WPM} WPM!')
            case 'suppress' if WPM >= cConfig.HIGH_WPM.THRESHOLD:
                return
            case _:
                pass

        # Check if the callsign is in the friends list
        if CallSign in cConfig.FRIENDS:
            Report.append('friend')

        # Get goal hits
        GoalList: list[str] = []
        if 'K3Y' in cConfig.GOALS and CallSign == 'K3Y' and CallSignSuffix:
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
        # Only show spots from nearby spotters for goals/targets, but always show user's callsign and friends
        if ((SpottedNearby and (GoalList or TargetList)) or 
            CallSign == cConfig.MY_CALLSIGN or 
            CallSign in cConfig.FRIENDS):
            cSPOTS.last_spotted[CallSign] = (FrequencyKHz, time.time())
            ZuluDate = time.strftime('%Y-%m-%d', time.gmtime())
            FrequencyString = f'{FrequencyKHz:.1f}'

            if CallSign == 'K3Y':
                NotificationFlag = cls.handle_notification(f'K3Y/{CallSignSuffix}', GoalList, TargetList)
                Out = f'{Zulu}{NotificationFlag}K3Y/{CallSignSuffix} on {FrequencyString:>8} {"; ".join(Report)}'
            else:
                MemberInfo = cSKCC.build_member_info(CallSign)
                NotificationFlag = cls.handle_notification(CallSign, GoalList, TargetList)
                Out = f'{Zulu}{NotificationFlag}{CallSign:<6} {MemberInfo} on {FrequencyString:>8} {"; ".join(Report)}'

            cDisplay.print(Out)
            await cUtil.log_async(f'{ZuluDate} {Out}')

class QRPQSOData(TypedDict):
    """Type definition for QRP-qualified QSO data."""
    date: str
    member_number: str
    callsign: str
    band: str
    qrp_1x: bool
    qrp_2x: bool

class cQSO:
    MyMemberNumber: str
    MyDXCC_Code: str

    # Compiled regex patterns for ADI parsing (hoisted for efficiency)
    _EOH_PATTERN = re.compile(r'<eoh>', re.I)
    _EOR_PATTERN = re.compile(r'<eor>', re.I)
    _FIELD_PATTERN = re.compile(r'<(\w+?):\d+(?::.*?)*>(.*?)\s*(?=<(?:\w+?):\d+(?::.*?)*>|$)', re.I | re.S)

    # QRP band point values (hoisted for efficiency) - includes both upper/lowercase for ADI compatibility
    _QRP_BAND_POINTS_AWARDS: ClassVar[dict[str, float]] = {
        "160M": 4.0, "160m": 4.0, "80M": 3.0, "80m": 3.0, "60M": 2.0, "60m": 2.0,
        "40M": 2.0, "40m": 2.0, "30M": 2.0, "30m": 2.0, "20M": 1.0, "20m": 1.0,
        "17M": 1.0, "17m": 1.0, "15M": 1.0, "15m": 1.0, "12M": 1.0, "12m": 1.0,
        "10M": 3.0, "10m": 3.0, "6M": 0.5, "6m": 0.5, "2M": 0.5, "2m": 0.5
    }

    ContactsForC:     dict[str, tuple[str, str, str]]
    ContactsForT:     dict[str, tuple[str, str, str]]
    ContactsForS:     dict[str, tuple[str, str, str]]

    ContactsForWAS:   dict[str, tuple[str, str, str]]
    ContactsForWAS_C: dict[str, tuple[str, str, str]]
    ContactsForWAS_T: dict[str, tuple[str, str, str]]
    ContactsForWAS_S: dict[str, tuple[str, str, str]]
    ContactsForP:     dict[str, tuple[str, str, int, str]]
    ContactsForK3Y:   dict[str, dict[int, str]]
    ContactsForQRP:   dict[str, tuple[str, str, str, int]]  # (date, call, band, qrp_type): qrp_type: 1=1xQRP, 2=2xQRP
    QRPQualifiedQSOs: list[QRPQSOData]  # Phase 1: QRP-qualified QSOs for band-by-band processing
    ContactsForDXC:   dict[str, tuple[str, str, str]]  # Key: dxcc_code, Value: (date, member_number, call)
    ContactsForDXQ:   dict[str, tuple[str, str, str]]  # Key: member_number, Value: (date, member_number, call)
    DXC_HomeCountryUsed: bool = False  # Track if home country slot has been used
    ContactsForTKA_SK:  dict[str, tuple[str, str, str]]  # Key: member_number, Value: (date, member_number, call) - Straight Key
    ContactsForTKA_BUG: dict[str, tuple[str, str, str]]  # Key: member_number, Value: (date, member_number, call) - Bug
    ContactsForTKA_SS:  dict[str, tuple[str, str, str]]  # Key: member_number, Value: (date, member_number, call) - Sideswiper


    Brag:             dict[str, tuple[str, str, str, float]]

    QSOsByMemberNumber: dict[str, list[str]]

    QSOs: list[tuple[str, str, str, float, str, str, str, str, str, str, str]]  # (date, call, state, freq, comment, skcc, tx_pwr, rx_pwr, dxcc, band, key_type)

    Prefix_RegEx = re.compile(r'(?:.*/)?([0-9]*[a-zA-Z]+\d+)')

    @classmethod
    def _frequency_to_band(cls, frequency_khz: float) -> str | None:
        """Convert frequency in kHz to band name for QRP award calculations."""
        if 1800 <= frequency_khz <= 2000:
            return "160m"
        elif 3500 <= frequency_khz <= 4000:
            return "80m"
        elif 5330.5 <= frequency_khz <= 5403.5:
            return "60m"
        elif 7000 <= frequency_khz <= 7300:
            return "40m"
        elif 10100 <= frequency_khz <= 10150:
            return "30m"
        elif 14000 <= frequency_khz <= 14350:
            return "20m"
        elif 18068 <= frequency_khz <= 18168:
            return "17m"
        elif 21000 <= frequency_khz <= 21450:
            return "15m"
        elif 24890 <= frequency_khz <= 24990:
            return "12m"
        elif 28000 <= frequency_khz <= 29700:
            return "10m"
        elif 50000 <= frequency_khz <= 50100:
            return "6m"
        elif 144000 <= frequency_khz <= 148000:
            return "2m"
        else:
            return None

    @classmethod
    def _lookup_member_from_qso(cls, qso_skcc: str | None, qso_callsign: str, skcc_number_to_call: dict[str, str]) -> tuple[str | None, str | None, bool]:
        """Helper to lookup member information from QSO data.

        Returns: (member_skcc_number, found_callsign, is_historical_member)
        """
        mbr_skcc_nr: str | None = None
        found_call: str | None = None
        is_historical_member = False

        if qso_skcc and qso_skcc != "NONE":
            # Try to find member by SKCC number first
            if qso_skcc in skcc_number_to_call:
                mbr_skcc_nr = qso_skcc
                found_call = skcc_number_to_call[qso_skcc]
            else:
                # Historical member number case
                extracted_call = cSKCC.extract_callsign(qso_callsign)
                if extracted_call and extracted_call in cSKCC.members:
                    mbr_skcc_nr = qso_skcc  # Keep historical number
                    found_call = extracted_call
                    is_historical_member = True

        if not mbr_skcc_nr:
            # Fall back to callsign lookup
            found_call = cSKCC.extract_callsign(qso_callsign)
            if found_call and found_call in cSKCC.members:
                mbr_skcc_nr = cSKCC.members[found_call]['plain_number']

        return mbr_skcc_nr, found_call, is_historical_member

    @classmethod
    async def initialize_async(cls) -> None:
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
        cls.ContactsForQRP     = {}
        cls.ContactsForDXC     = {}
        cls.ContactsForDXQ     = {}
        cls.DXC_HomeCountryUsed = False
        cls.ContactsForTKA_SK  = {}
        cls.ContactsForTKA_BUG = {}
        cls.ContactsForTKA_SS  = {}
        cls.QSOsByMemberNumber = {}

        await cls.read_qsos_async()

        MyMemberEntry      = cSKCC.members[cConfig.MY_CALLSIGN]
        cls.MyJoin_Date    = cUtil.effective(MyMemberEntry['join_date'])
        cls.MyC_Date       = cUtil.effective(MyMemberEntry['c_date'])
        cls.MyT_Date       = cUtil.effective(MyMemberEntry['t_date'])
        cls.MyS_Date       = cUtil.effective(MyMemberEntry['s_date'])
        cls.MyTX8_Date     = cUtil.effective(MyMemberEntry['tx8_date'])

        cls.MyMemberNumber = MyMemberEntry['plain_number']
        cls.MyDXCC_Code = MyMemberEntry['dxcode']

    @classmethod
    async def watch_logfile_task(cls) -> NoReturn:
        while True:
            try:
                if await aiofiles.os.path.exists(cConfig.ADI_FILE) and os.path.getmtime(cConfig.ADI_FILE) != cQSO.AdiFileReadTimeStamp:
                    cDisplay.print(f"'{cConfig.ADI_FILE}' file is changing. Waiting for write to finish...")

                    # Wait until file size stabilizes
                    while True:
                        Size = os.path.getsize(cConfig.ADI_FILE)
                        await asyncio.sleep(1)
                        if os.path.getsize(cConfig.ADI_FILE) == Size:
                            break

                    await cls.refresh_async()

            except FileNotFoundError:
                print(f"Warning: ADI file '{cConfig.ADI_FILE}' not found or inaccessible")
            except Exception as e:
                print(f"Error watching log file: {e}")

            await asyncio.sleep(3)

    @classmethod
    def calculate_current_award_level(cls, Class: str, Total: int) -> int:
        """
        Calculate what award level someone currently qualifies for.
        Updated to match official SKCC rules.
        """
        match Class:
            case 'C':
                if Total < 100:
                    return 0  # No award yet
                elif Total < 1000:
                    return Total // 100
                elif Total < 1500:
                    return 10  # Cx10
                else:
                    # Cx15, Cx20, Cx25, etc.
                    increments_past_1500 = (Total - 1500) // 500
                    return 15 + (increments_past_1500 * 5)

            case 'T':
                # Tribune: Must be Centurion first, then 50 contacts with C/T/S for Tx1
                # Tx1=50, Tx2=100, ..., Tx10=500, then Tx15=750, Tx20=1000, etc.
                if not cls.MyC_Date:
                    return 0  # Must be Centurion first
                if Total < 50:
                    return 0  # No Tribune award yet
                elif Total < 500:
                    return Total // 50  # Tx1 through Tx10
                elif Total < 750:
                    return 10  # Between Tx10 and Tx15
                elif Total < 1000:
                    return 15  # Tx15
                else:
                    # Tx20 and beyond (250-contact increments)
                    increments_past_1000 = (Total - 1000) // 250
                    return 20 + (increments_past_1000 * 5)

            case 'S':
                # Senator: Must have Tribune x8 (400 Tribune contacts) first, then 200 contacts with T/S for Sx1
                tribune_contacts = len(cls.ContactsForT)
                if tribune_contacts < 400:
                    return 0  # Must have Tribune x8 (400 contacts) first
                if Total < 200:
                    return 0  # No Senator award yet
                else:
                    # Sx1, Sx2, etc. - each level requires 200 more contacts
                    return min(Total // 200, 10)  # Cap at Sx10 per official rules

            case 'P':
                # Prefix progression per SKCC rules:
                # Px1-Px10: Each level requires an additional 500,000 points
                # Px1 at >500k, Px2 at >1M, ..., Px10 at >5M
                # Beyond Px10: Px15 at >7.5M, Px20 at >10M, Px25 at >12.5M (2.5M increments)
                if Total <= 500_000:
                    return 0  # No P award yet
                elif Total <= 5_000_000:
                    # Px1 through Px10 - each 500k increment adds 1 level
                    return (Total - 1) // 500_000 + 1
                else:
                    # After 5M (Px10): levels jump by 5, thresholds by 2.5M
                    # Px10: >5M, Px15: >7.5M, Px20: >10M, Px25: >12.5M
                    if Total <= 7_500_000:
                        return 10  # Still at Px10
                    else:
                        # Calculate how many 2.5M increments past 7.5M
                        increments_past_7_5m = (Total - 7_500_001) // 2_500_000 + 1
                        return 10 + (increments_past_7_5m * 5)

            case _:
                # Default simple division
                return Total // Levels[Class]

    @classmethod
    def awards_check(cls) -> None:
        """
        Updated awards check that properly handles official SKCC award requirements.
        """
        C_Level = cls.calculate_current_award_level('C', len(cls.ContactsForC))
        T_Level = cls.calculate_current_award_level('T', len(cls.ContactsForT))
        S_Level = cls.calculate_current_award_level('S', len(cls.ContactsForS))
        P_Level = cls.calculate_current_award_level('P', cls.calc_prefix_points())

        ### C ###
        if cls.MyC_Date:
            Award_C_Level = cSKCC.centurion_level.get(cls.MyMemberNumber, 1)

            if C_Level > Award_C_Level:
                C_or_Cx = 'C' if Award_C_Level == 1 else f'Cx{Award_C_Level}'
                next_level_name = 'C' if C_Level == 1 else f'Cx{C_Level}'
                print(f'FYI: You qualify for {next_level_name} but have only applied for {C_or_Cx}.')
        else:
            if C_Level >= 1 and cls.MyMemberNumber not in cSKCC.centurion_level:
                print('FYI: You qualify for C but have not yet applied for it.')

        ### T ###
        if not cls.MyC_Date:
            if T_Level > 0:
                print('NOTE: Tribune award requires Centurion first. Apply for C before T.')
        elif cls.MyT_Date:
            Award_T_Level = cSKCC.tribune_level.get(cls.MyMemberNumber, 1)

            if T_Level > Award_T_Level:
                T_or_Tx = 'T' if Award_T_Level == 1 else f'Tx{Award_T_Level}'
                next_level_name = 'T' if T_Level == 1 else f'Tx{T_Level}'
                print(f'FYI: You qualify for {next_level_name} but have only applied for {T_or_Tx}.')
        else:
            if T_Level >= 1 and cls.MyMemberNumber not in cSKCC.tribune_level:
                print('FYI: You qualify for T but have not yet applied for it.')

        ### S ###
        tribune_contacts = len(cls.ContactsForT)
        if tribune_contacts < 400:
            if S_Level > 0:
                print(f'NOTE: Senator award requires Tribune x8 (400 contacts) first. Currently have {tribune_contacts} Tribune contacts.')
        elif cls.MyS_Date:
            Award_S_Level = cSKCC.senator_level.get(cls.MyMemberNumber, 1)

            if S_Level > Award_S_Level:
                S_or_Sx = 'S' if Award_S_Level == 1 else f'Sx{Award_S_Level}'
                next_level_name = 'S' if S_Level == 1 else f'Sx{S_Level}'
                print(f'FYI: You qualify for {next_level_name} but have only applied for {S_or_Sx}.')
        else:
            if S_Level >= 1 and cls.MyMemberNumber not in cSKCC.senator_level:
                print('FYI: You qualify for S but have not yet applied for it.')

        ### WAS and WAS-C and WAS-T and WAS-S ###
        if 'WAS' in cConfig.GOALS:
            if len(cls.ContactsForWAS) == len(US_STATES) and cConfig.MY_CALLSIGN not in cSKCC.was_level:
                print('FYI: You qualify for WAS but have not yet applied for it.')

        if 'WAS-C' in cConfig.GOALS:
            if len(cls.ContactsForWAS_C) == len(US_STATES) and cConfig.MY_CALLSIGN not in cSKCC.was_c_level:
                print('FYI: You qualify for WAS-C but have not yet applied for it.')

        if 'WAS-T' in cConfig.GOALS:
            if len(cls.ContactsForWAS_T) == len(US_STATES) and cConfig.MY_CALLSIGN not in cSKCC.was_t_level:
                print('FYI: You qualify for WAS-T but have not yet applied for it.')

        if 'WAS-S' in cConfig.GOALS:
            if len(cls.ContactsForWAS_S) == len(US_STATES) and cConfig.MY_CALLSIGN not in cSKCC.was_s_level:
                print('FYI: You qualify for WAS-S but have not yet applied for it.')

        if 'P' in cConfig.GOALS:
            if cConfig.MY_CALLSIGN in cSKCC.prefix_level:
                Award_P_Level = cSKCC.prefix_level[cConfig.MY_CALLSIGN]

                if P_Level > Award_P_Level:
                    print(f'FYI: You qualify for Px{P_Level} but have only applied for Px{Award_P_Level}.')
            elif P_Level >= 1:
                print(f'FYI: You qualify for Px{P_Level} but have not yet applied for it.')

        ### DX ###
        if 'DX' in cConfig.GOALS:
            # DXC
            DXC_count = len(cls.ContactsForDXC)
            if DXC_count >= 10:  # First level is 10
                DXC_Level, _, _ = cls.get_dx_award_level_and_next(DXC_count)
                if cls.MyMemberNumber in cSKCC.dxc_level:
                    Award_DXC_Level = cSKCC.dxc_level[cls.MyMemberNumber]
                    if DXC_Level > Award_DXC_Level:
                        print(f'FYI: You qualify for DXCx{DXC_Level} but have only applied for DXCx{Award_DXC_Level}.')
                else:
                    print(f'FYI: You qualify for DXCx{DXC_Level} but have not yet applied for it.')

            # DXQ
            DXQ_count = len(cls.ContactsForDXQ)
            if DXQ_count >= 10:  # First level is 10
                DXQ_Level, _, _ = cls.get_dx_award_level_and_next(DXQ_count)
                if cls.MyMemberNumber in cSKCC.dxq_level:
                    Award_DXQ_Level = cSKCC.dxq_level[cls.MyMemberNumber]
                    if DXQ_Level > Award_DXQ_Level:
                        print(f'FYI: You qualify for DXQx{DXQ_Level} but have only applied for DXQx{Award_DXQ_Level}.')
                else:
                    print(f'FYI: You qualify for DXQx{DXQ_Level} but have not yet applied for it.')

        ### QRP ###
        if 'QRP' in cConfig.GOALS:
            # Calculate QRP points using correct hoisted constant
            band_points = cls._QRP_BAND_POINTS_AWARDS

            # Calculate points for 1xQRP (all contacts) and 2xQRP (only 2x contacts)
            points_1x = 0.0
            points_2x = 0.0

            for qso_key, (_, _, _, qrp_type) in cls.ContactsForQRP.items():
                key_parts = qso_key.split('_')
                if len(key_parts) >= 3:
                    band = key_parts[1]
                    points = band_points.get(band, 0.0)
                    points_1x += points  # All contacts count for 1xQRP
                    if qrp_type == 2:
                        points_2x += points  # Only 2xQRP contacts count for 2xQRP

            # Check 1xQRP
            if points_1x >= 300:
                QRP_1x_Level = int(points_1x // 300)
                if cls.MyMemberNumber in cSKCC.qrp_1x_level:
                    Award_QRP_1x_Level = cSKCC.qrp_1x_level[cls.MyMemberNumber]
                    if QRP_1x_Level > Award_QRP_1x_Level:
                        print(f'FYI: You qualify for 1xQRP x{QRP_1x_Level} but have only applied for 1xQRP x{Award_QRP_1x_Level}.')
                else:
                    print(f'FYI: You qualify for 1xQRP x{QRP_1x_Level} but have not yet applied for it.')

            # Check 2xQRP
            if points_2x >= 150:
                QRP_2x_Level = int(points_2x // 150)
                if cls.MyMemberNumber in cSKCC.qrp_2x_level:
                    Award_QRP_2x_Level = cSKCC.qrp_2x_level[cls.MyMemberNumber]
                    if QRP_2x_Level > Award_QRP_2x_Level:
                        print(f'FYI: You qualify for 2xQRP x{QRP_2x_Level} but have only applied for 2xQRP x{Award_QRP_2x_Level}.')
                else:
                    print(f'FYI: You qualify for 2xQRP x{QRP_2x_Level} but have not yet applied for it.')

        ### TKA ###
        if 'TKA' in cConfig.GOALS:
            # Check if they have achieved all 300 unique QSOs (100 of each key type)
            sk_count = len(cls.ContactsForTKA_SK)
            bug_count = len(cls.ContactsForTKA_BUG)
            ss_count = len(cls.ContactsForTKA_SS)
            
            # Calculate unique members across all key types
            all_members: set[str] = set()
            all_members.update(cls.ContactsForTKA_SK.keys())
            all_members.update(cls.ContactsForTKA_BUG.keys())
            all_members.update(cls.ContactsForTKA_SS.keys())
            unique_total = len(all_members)
            
            # Check if they qualify (100 of each type and 300 unique total)
            if sk_count >= 100 and bug_count >= 100 and ss_count >= 100 and unique_total >= 300:
                if cls.MyMemberNumber not in cSKCC.tka_level:
                    print('FYI: You qualify for TKA but have not yet applied for it.')

    @staticmethod
    def calculate_numerics(Class: str, Total: int) -> tuple[int, int]:
        """
        Calculate remaining contacts needed and X-factor for next award level.
        Now correctly handles the special progression rules for C and T after level 10.
        """
        base_increment = Levels[Class]

        match Class:
            case 'C':
                # Centurion: 100, 200, 300... up to 1000 (Cx10)
                # Then Cx15 (1500), Cx20 (2000), Cx25 (2500), etc. in increments of 500
                if Total < 1000:  # Cx1 through Cx10
                    since_last = Total % base_increment
                    remaining = base_increment - since_last
                    x_factor = (Total + base_increment) // base_increment
                else:  # Cx15, Cx20, Cx25, etc.
                    # After 1000: Cx15=1500, Cx20=2000, Cx25=2500, Cx30=3000, Cx35=3500, Cx40=4000...
                    # Pattern: Cx(10+5n) = 1000 + 500n where n >= 1

                    # Calculate current level
                    if Total >= 1500:
                        # How many 500-increments past 1500?
                        increments_past_1500 = (Total - 1500) // 500
                        current_x_factor = 15 + (increments_past_1500 * 5)

                        # Next level
                        next_x_factor = current_x_factor + 5
                        next_target = 1000 + ((next_x_factor - 10) // 5) * 500
                    else:
                        # Between 1000 and 1500, working toward Cx15
                        next_x_factor = 15
                        next_target = 1500

                    remaining = next_target - Total
                    x_factor = next_x_factor

            case 'T':
                # Tribune: Must be Centurion first
                # Tx1=50, Tx2=100, ..., Tx10=500, then Tx15=750, Tx20=1000, etc.
                if not cQSO.MyC_Date:
                    # Must be Centurion first
                    remaining = 999999  # Large number to indicate not eligible
                    x_factor = 0
                elif Total < 50:
                    # Working toward Tx1
                    remaining = 50 - Total
                    x_factor = 1
                elif Total < 500:
                    # Tx1 through Tx10 (each level requires 50 contacts)
                    current_level = Total // 50
                    next_level = current_level + 1
                    next_target = next_level * 50
                    remaining = next_target - Total
                    x_factor = next_level
                elif Total < 750:
                    # Between Tx10 and Tx15
                    remaining = 750 - Total
                    x_factor = 15
                elif Total < 1000:
                    # At Tx15, working toward Tx20
                    remaining = 1000 - Total
                    x_factor = 20
                else:
                    # Tx20 and beyond (250-contact increments)
                    increments_past_1000 = (Total - 1000) // 250
                    current_x_factor = 20 + (increments_past_1000 * 5)
                    next_x_factor = current_x_factor + 5
                    next_target = 1000 + ((next_x_factor - 20) // 5) * 250
                    remaining = next_target - Total
                    x_factor = next_x_factor

            case 'S':
                # Senator: Must have Tribune x8 (400 Tribune contacts) first
                # Sx1=200, Sx2=400, Sx3=600, ..., Sx10=2000 (each requires 200 contacts)
                tribune_contacts = len(cQSO.ContactsForT)
                if tribune_contacts < 400:
                    # Must have Tribune x8 (400 contacts) first
                    remaining = 999999  # Large number to indicate not eligible
                    x_factor = 0
                elif Total < 200:
                    # Working toward Sx1
                    remaining = 200 - Total
                    x_factor = 1
                else:
                    # Sx1 through Sx10 (each level requires 200 contacts)
                    current_level = min(Total // 200, 10)
                    if current_level >= 10:
                        # Already at max Senator level
                        remaining = 0
                        x_factor = 10
                    else:
                        next_level = current_level + 1
                        next_target = next_level * 200
                        remaining = next_target - Total
                        x_factor = next_level

            case 'P':
                # Prefix progression per SKCC rules
                if Total <= 500_000:
                    remaining = 500_001 - Total  # Need >500,000 for Px1
                    x_factor = 1
                elif Total <= 5_000_000:
                    # Px1 through Px10 - calculate next level
                    current_level = (Total - 1) // 500_000 + 1
                    next_level = current_level + 1
                    next_threshold = next_level * 500_000
                    remaining = next_threshold + 1 - Total
                    x_factor = next_level
                else:
                    # After 5M (Px10): levels go 15, 20, 25... with 2.5M increments
                    # Calculate current level using same logic as calculate_current_award_level
                    if Total <= 7_500_000:
                        current_level = 10
                        next_level = 15
                        next_threshold = 7_500_000
                    else:
                        increments_past_7_5m = (Total - 7_500_001) // 2_500_000 + 1
                        current_level = 10 + (increments_past_7_5m * 5)
                        next_level = current_level + 5

                        # Calculate threshold for next level
                        # Px15: >7.5M, Px20: >10M, Px25: >12.5M
                        levels_past_15 = (next_level - 15) // 5
                        next_threshold = 7_500_000 + (levels_past_15 * 2_500_000)

                    # For round numbers (10M, etc), don't add 1
                    if next_threshold == PrefixThresholds.MILESTONE_10M:
                        remaining = next_threshold - Total
                    else:
                        remaining = next_threshold + 1 - Total
                    x_factor = next_level

            case _:
                # Default logic
                since_last = Total % base_increment
                remaining = base_increment - since_last
                x_factor = (Total + base_increment) // base_increment

        return remaining, x_factor

    @classmethod
    def _parse_adi_generator(cls, file_path: str) -> Iterator[tuple[str, str, str, float, str, str, str, str, str, str, str]]:
        """Elegant regex-based ADI parser using generator."""
        with open(file_path, 'rb') as f:
            content = f.read().decode('utf-8', 'ignore')

        # Split header from body using hoisted pattern
        parts = cls._EOH_PATTERN.split(content, maxsplit=1)
        body = parts[1].strip() if len(parts) > 1 else content

        # Process each QSO record using hoisted patterns
        for record_text in filter(None, map(str.strip, cls._EOR_PATTERN.split(body))):
            # Extract fields using hoisted regex pattern
            fields = {k.upper(): v.strip() for k, v in cls._FIELD_PATTERN.findall(record_text)}

            # Handle alternate field names
            if 'QSO_DATE_OFF' in fields and 'QSO_DATE' not in fields:
                fields['QSO_DATE'] = fields['QSO_DATE_OFF']
            if 'TIME_OFF' in fields and 'TIME_ON' not in fields:
                fields['TIME_ON'] = fields['TIME_OFF']

            # Skip non-CW QSOs and incomplete records
            if (fields.get('MODE', '').upper() != 'CW' or
                not all(k in fields for k in ('CALL', 'QSO_DATE', 'TIME_ON'))):
                continue

            # Parse frequency
            frequency = 0.0
            if freq_str := fields.get('FREQ', ''):
                try:
                    frequency = float(freq_str) * 1000
                except ValueError:
                    pass

            # Clean SKCC number
            skcc_number = ''.join(filter(str.isdigit, fields.get('SKCC', '')))

            # Yield QSO tuple
            yield (
                fields['QSO_DATE'] + fields['TIME_ON'],
                fields['CALL'].upper(),
                fields.get('STATE', '').upper(),
                frequency,
                fields.get('COMMENT', ''),
                skcc_number,
                fields.get('TX_PWR', ''),
                fields.get('RX_PWR', ''),
                fields.get('DXCC', ''),
                fields.get('BAND', ''),  # Add BAND field from ADI file
                fields.get('APP_SKCCLOGGER_KEYTYPE', '')  # Add KEY_TYPE field for TKA
            )

    @classmethod
    async def read_qsos_async(cls) -> None:
        """Fast, simple QSO reading using generator."""
        AdiFileAbsolute = os.path.abspath(cConfig.ADI_FILE)
        cDisplay.print(f"\nReading QSOs for {cConfig.MY_CALLSIGN} from '{AdiFileAbsolute}'...")

        cls.QSOs = []
        cls.AdiFileReadTimeStamp = os.path.getmtime(cConfig.ADI_FILE)

        try:
            # Use generator in thread pool for async operation
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                cls.QSOs = await loop.run_in_executor(
                    executor,
                    lambda: list(cls._parse_adi_generator(AdiFileAbsolute))
                )

        except Exception as e:
            cDisplay.print(f"Error reading ADIF file: {e}")
            return

        # Sort QSOs by date
        cls.QSOs.sort(key=lambda qso: qso[0])

        # Process and map QSOs by member number
        cls.QSOsByMemberNumber = {}
        for qso_date, call_sign, _, _, _, _, _, _, _, _, _ in cls.QSOs:
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


    @staticmethod
    def get_dx_award_level_and_next(count: int) -> tuple[int, int, int]:
        """Calculate DX award level and next target based on count.
        
        DX award progression: 10, 25, 50, then increment by 25 (75, 100, 125, 150, etc.)
        
        Returns:
            Tuple of (current_level, next_level, next_target)
        """
        if count < 10:
            return 0, 10, 10
        elif count < 25:
            return 10, 25, 25
        elif count < 50:
            return 25, 50, 50
        else:
            # After 50, levels increment by 25
            # 50 -> 75, 75 -> 100, 100 -> 125, etc.
            current_level = 50 + ((count - 50) // 25) * 25
            next_level = current_level + 25
            return current_level, next_level, next_level

    @classmethod
    def print_dx_awards_progress(cls) -> None:
        """Print DX award progress in the main awards progress section."""
        # DXC: Unique countries
        dxc_count = len(cls.ContactsForDXC)
        if dxc_count == 0:
            print('DXC: Have 0 countries. Need DXCC codes in ADI file or member data.')
        else:
            current_level, next_level, next_target = cls.get_dx_award_level_and_next(dxc_count)
            
            if current_level == 0:
                # Working toward initial DXC
                remaining = next_target - dxc_count
                print(f'DXC: Have {dxc_count}. DXCx{next_level} requires {next_target} ({remaining} more)')
            else:
                remaining = next_target - dxc_count
                if remaining == 0:
                    # Exactly at a level
                    print(f'DXC: Have {dxc_count} which qualifies for DXCx{current_level}.')
                else:
                    print(f'DXC: Have {dxc_count} which qualifies for DXCx{current_level}. DXCx{next_level} requires {next_target} ({remaining} more)')

        # DXQ: Unique member QSOs from foreign countries
        dxq_count = len(cls.ContactsForDXQ)
        if dxq_count == 0:
            print('DXQ: Have 0 foreign member QSOs.')
        else:
            current_level, next_level, next_target = cls.get_dx_award_level_and_next(dxq_count)
            
            if current_level == 0:
                # Working toward initial DXQ
                remaining = next_target - dxq_count
                print(f'DXQ: Have {dxq_count}. DXQx{next_level} requires {next_target} ({remaining} more)')
            else:
                remaining = next_target - dxq_count
                if remaining == 0:
                    # Exactly at a level
                    print(f'DXQ: Have {dxq_count} which qualifies for DXQx{current_level}.')
                else:
                    print(f'DXQ: Have {dxq_count} which qualifies for DXQx{current_level}. DXQx{next_level} requires {next_target} ({remaining} more)')

    @classmethod
    def print_tka_award_progress(cls) -> None:
        """Print TKA (Triple Key Award) progress."""
        sk_count = len(cls.ContactsForTKA_SK)
        bug_count = len(cls.ContactsForTKA_BUG)
        ss_count = len(cls.ContactsForTKA_SS)
        
        # Calculate unique members across all key types (for the 300 unique requirement)
        all_members: set[str] = set()
        all_members.update(cls.ContactsForTKA_SK.keys())
        all_members.update(cls.ContactsForTKA_BUG.keys())
        all_members.update(cls.ContactsForTKA_SS.keys())
        unique_total = len(all_members)
        
        # Simple, clear format showing progress toward requirements
        print(f'TKA: SK:{sk_count}/100 BUG:{bug_count}/100 SS:{ss_count}/100. Unique:{unique_total}/300')

    @classmethod
    def process_qrp_awards_xojo_style(cls) -> None:
        """Phase 2: Process QRP awards using Xojo's exact band-by-band logic"""
        if 'QRP' not in cConfig.GOALS or not hasattr(cls, 'QRPQualifiedQSOs'):
            return

        # Define Xojo's band array (AP_Bands) - exactly matching Xojo source
        xojo_bands = ["6M", "10M", "12M", "15M", "17M", "20M", "30M", "40M", "60M", "80M", "160M"]

        # Clear existing QRP contacts to rebuild with Xojo logic
        cls.ContactsForQRP = {}

        # Process each band separately (matching Xojo's for loop)
        for xojo_band in xojo_bands:
            # Select all QRP QSOs for this band using UPPER(Log_BAND) = xojo_band logic
            band_qsos: list[QRPQSOData] = []

            for qso in cls.QRPQualifiedQSOs:
                if qso['band'].upper() == xojo_band:
                    band_qsos.append(qso)

            # Process QSOs for this band - one entry per member per band
            # But we need to ensure 2xQRP contacts are properly identified
            for qso in band_qsos:
                member_number: str = qso['member_number']
                dup_key = f"{member_number}_{xojo_band}"

                if dup_key not in cls.ContactsForQRP:
                    # Add the QSO - it will be counted correctly by the display logic
                    qrp_type = 2 if qso['qrp_2x'] else 1
                    cls.ContactsForQRP[dup_key] = (
                        qso['date'],
                        qso['member_number'],
                        qso['callsign'],
                        qrp_type
                    )
                else:
                    # If we already have this member-band, upgrade to 2xQRP if this QSO qualifies
                    existing_qso = cls.ContactsForQRP[dup_key]
                    if qso['qrp_2x'] and existing_qso[3] != 2:
                        cls.ContactsForQRP[dup_key] = (
                            qso['date'],
                            qso['member_number'],
                            qso['callsign'],
                            2  # Upgrade to 2xQRP
                        )

    @classmethod
    def print_qrp_awards_progress(cls) -> None:
        """Print QRP award progress in the main awards progress section."""
        if not cls.ContactsForQRP:
            print('QRP: Have 0 contacts. Need QRP power (≤5W) logged in ADI file.')
            return

        # QRP point values by band (using hoisted constant)
        band_points = cls._QRP_BAND_POINTS_AWARDS

        # Calculate points for ALL QRP contacts (both 1x and 2x count toward 1xQRP)
        points_all: float = 0.0
        points_2x_only: float = 0.0
        count_all: int = 0
        count_2x_only: int = 0

        for qso_key, (_qso_date, _member_number, _callsign, qrp_type) in cls.ContactsForQRP.items():
            # Extract band from key format: "member_band" (matching Xojo duplicate detection)
            key_parts = qso_key.split('_')
            if len(key_parts) >= 2:
                band: str = key_parts[1]
            else:
                band = ""
            points: float = band_points.get(band, 0.0)

            # All QRP contacts count toward 1xQRP
            points_all += points
            count_all += 1

            # Only 2xQRP contacts count toward 2xQRP
            if qrp_type == 2:
                points_2x_only += points
                count_2x_only += 1


        # Display progress in awards progress format
        # For 1xQRP: Show ALL QRP contacts (matching gold standard)
        if count_all > 0:
            current_level = int(points_all // 300)
            next_level = current_level + 1
            next_target = next_level * 300
            remaining_next = next_target - points_all
            if current_level > 0:
                print(f'QRP 1x: Have {count_all} contacts, {points_all:.1f} points which qualifies for 1xQRP x{current_level}. 1xQRP x{next_level} requires {next_target:.1f} points ({remaining_next:.1f} more)')
            else:
                print(f'QRP 1x: Have {count_all} contacts, {points_all:.1f} points. 1xQRP x1 requires {next_target:.1f} points ({remaining_next:.1f} more)')

        # For 2xQRP: Show only 2xQRP contacts
        if count_2x_only > 0:
            current_level = int(points_2x_only // 150)
            next_level = current_level + 1
            next_target = next_level * 150
            remaining_next = next_target - points_2x_only
            if current_level > 0:
                print(f'QRP 2x: Have {count_2x_only} contacts, {points_2x_only:.1f} points which qualifies for 2xQRP x{current_level}. 2xQRP x{next_level} requires {next_target:.1f} points ({remaining_next:.1f} more)')
            else:
                print(f'QRP 2x: Have {count_2x_only} contacts, {points_2x_only:.1f} points. 2xQRP x1 requires {next_target:.1f} points ({remaining_next:.1f} more)')

        # If we have no qualifying contacts, show what's needed
        if count_all == 0:
            print('QRP 1x: Have 0 contacts. Need QRP power (≤5W) logged in ADI file.')

    @classmethod
    def print_qrp_progress(cls) -> None:
        """Print QRP award progress."""
        if not cls.ContactsForQRP:
            print('QRP: No qualifying contacts found (TX power must be <= 5W)')
            return

        # QRP point values by band (using hoisted constant)
        band_points = cls._QRP_BAND_POINTS_AWARDS

        # Calculate points for each QRP type
        points_1x: float = 0.0
        points_2x: float = 0.0
        count_1x: int = 0
        count_2x: int = 0

        for qso_key, (_qso_date, _member_number, _callsign, qrp_type) in cls.ContactsForQRP.items():
            # Extract band from key format: "member_band" (matching Xojo duplicate detection)
            key_parts = qso_key.split('_')
            if len(key_parts) >= 2:
                band: str = key_parts[1]
            else:
                band = ""
            points: float = band_points.get(band, 0.0)

            if qrp_type == 1:
                points_1x += points
                count_1x += 1
            else:
                points_2x += points
                count_2x += 1

        # Display progress
        if count_1x > 0:
            progress_1x: float = (points_1x / 300.0) * 100.0
            print(f'QRP 1x: {count_1x} contacts, {points_1x:.1f} points ({progress_1x:.1f}% of 300 required)')

        if count_2x > 0:
            progress_2x: float = (points_2x / 150.0) * 100.0
            print(f'QRP 2x: {count_2x} contacts, {points_2x:.1f} points ({progress_2x:.1f}% of 150 required)')

    @classmethod
    def print_progress(cls) -> None:
        def print_remaining(Class: str, Total: int) -> None:
            Remaining, X_Factor = cQSO.calculate_numerics(Class, Total)

            if Class in cConfig.GOALS:
                # Calculate current qualifying level
                current_level = cls.calculate_current_award_level(Class, Total)
                next_x_factor = X_Factor

                # Format in requested style
                # Use current qualifying level for display
                display_level = current_level

                match Class:
                    case 'C':
                        if display_level >= 1:
                            current_abbrev = cUtil.abbreviate_class(Class, display_level)
                            next_abbrev = cUtil.abbreviate_class(Class, next_x_factor)
                            print(f'{Class}: Have {Total:,} which qualifies for {current_abbrev}. {next_abbrev} requires {Total + Remaining:,} ({Remaining:,} more)')
                        else:
                            # Not yet qualified for C
                            print(f'{Class}: Have {Total:,}. C requires 100 ({Remaining:,} more)')
                    case 'T':
                        if not cls.MyC_Date:
                            print(f'{Class}: Tribune award requires Centurion first. Apply for C before working toward T.')
                        elif display_level >= 1:
                            current_abbrev = cUtil.abbreviate_class(Class, display_level)
                            next_abbrev = cUtil.abbreviate_class(Class, next_x_factor)
                            print(f'{Class}: Have {Total:,} which qualifies for {current_abbrev}. {next_abbrev} requires {Total + Remaining:,} ({Remaining:,} more)')
                        else:
                            # Working toward T
                            print(f'{Class}: Have {Total:,}. T requires 50 ({Remaining:,} more)')
                    case 'S':
                        tribune_contacts = len(cls.ContactsForT)
                        if tribune_contacts < 400:
                            print(f'{Class}: Senator award requires Tribune x8 (400 contacts) first. Currently have {tribune_contacts} Tribune contacts.')
                        elif display_level >= 1:
                            current_abbrev = cUtil.abbreviate_class(Class, display_level)
                            next_abbrev = cUtil.abbreviate_class(Class, next_x_factor)
                            print(f'{Class}: Have {Total:,} which qualifies for {current_abbrev}. {next_abbrev} requires {Total + Remaining:,} ({Remaining:,} more)')
                        else:
                            # Working toward S
                            print(f'{Class}: Have {Total:,}. S requires 200 ({Remaining:,} more)')
                    case 'P':
                        if display_level >= 1:
                            current_abbrev = cUtil.abbreviate_class(Class, display_level)
                            next_abbrev = cUtil.abbreviate_class(Class, next_x_factor)
                            print(f'{Class}: Have {Total:,} which qualifies for {current_abbrev}. {next_abbrev} requires {Total + Remaining:,} ({Remaining:,} more)')
                        else:
                            # Working toward P
                            print(f'{Class}: Have {Total:,}. Px1 requires >500,000 ({Remaining:,} more)')
                    case _:
                        print(f'{Class}: Have {Total:,}. Need {Remaining:,} more for next level.')

        print('')

        if cConfig.GOALS:
            # Sort goals in preferred display order
            goal_order = ['C', 'T', 'S', 'P', 'DX', 'QRP', 'WAS', 'WAS-C', 'WAS-T', 'WAS-S', 'BRAG', 'K3Y']
            sorted_goals = sorted(cConfig.GOALS, key=lambda x: goal_order.index(x) if x in goal_order else len(goal_order))
            print(f'GOAL{"S" if len(cConfig.GOALS) > 1 else ""}: {", ".join(sorted_goals)}')

        if cConfig.TARGETS:
            # Sort targets in preferred display order (same as goals)
            target_order = ['C', 'T', 'S']  # Only C, T, S are valid targets
            sorted_targets = sorted(cConfig.TARGETS, key=lambda x: target_order.index(x) if x in target_order else len(target_order))
            print(f'TARGET{"S" if len(cConfig.TARGETS) > 1 else ""}: {", ".join(sorted_targets)}')

        print(f'BANDS: {", ".join(str(Band) for Band in sorted(cConfig.BANDS, reverse=True))}')

        print('')
        print('*** Awards Progress ***')

        print_remaining('C', len(cls.ContactsForC))

        if cls.MyC_Date:
            print_remaining('T', len(cls.ContactsForT))

        if cls.MyTX8_Date:
            print_remaining('S', len(cls.ContactsForS))

        print_remaining('P', cls.calc_prefix_points())

        if 'QRP' in cConfig.GOALS:
            cls.print_qrp_awards_progress()

        if 'DX' in cConfig.GOALS:
            cls.print_dx_awards_progress()

        if 'TKA' in cConfig.GOALS:
            cls.print_tka_award_progress()

        def remaining_states(Class: str, QSOs: dict[str, tuple[str, str, str]]) -> None:
            if len(QSOs) == len(US_STATES):
                Need = 'none needed'
            else:
                RemainingStates = [State for State in US_STATES if State not in QSOs]

                if len(RemainingStates) > 14:
                    Need = f'only need {len(RemainingStates)} more'
                else:
                    Need = f'only need {",".join(RemainingStates)}'

            print(f'{Class}: Have {len(QSOs)}, {Need}')

        if 'WAS' in cConfig.GOALS:
            remaining_states('WAS', cls.ContactsForWAS)

        if 'WAS-C' in cConfig.GOALS:
            remaining_states('WAS-C', cls.ContactsForWAS_C)

        if 'WAS-T' in cConfig.GOALS:
            remaining_states('WAS-T', cls.ContactsForWAS_T)

        if 'WAS-S' in cConfig.GOALS:
            remaining_states('WAS-S', cls.ContactsForWAS_S)

        if 'BRAG' in cConfig.GOALS:
            NowGMT = cFastDateTime.now_gmt()
            MonthIndex = NowGMT.month()-1
            MonthName = cFastDateTime.MONTH_NAMES[MonthIndex]
            print(f'{MonthName} Brag: Have {len(cls.Brag)}')


    @classmethod
    def _check_cts_goal(cls, award_type: str, member_number: str, contacts_dict: dict[str, Any],
                        my_award_date: str) -> str | None:
        """Helper method to check C/T/S award goals - reduces code duplication."""
        if member_number not in contacts_dict:
            if not my_award_date:
                # Working toward initial award
                return award_type
            else:
                # Already have award, working toward multipliers
                _, x_factor = cQSO.calculate_numerics(award_type, len(contacts_dict))
                return cUtil.abbreviate_class(award_type, x_factor)
        return None

    @classmethod
    def _check_cts_target(cls, award_type: str, member_number: str, their_award_date: str,
                          level_dict: dict[str, int], date1: str, date2: str) -> str | None:
        """Helper method to check C/T/S target awards - reduces code duplication."""
        if not their_award_date:
            # They're working toward initial award
            if member_number not in cls.QSOsByMemberNumber or all(
                qso_date <= date1 or qso_date <= date2
                for qso_date in cls.QSOsByMemberNumber[member_number]
            ):
                return award_type
        else:
            # They already have award, working toward multipliers
            next_level = level_dict[member_number] + 1
            if next_level <= 10 and (
                member_number not in cls.QSOsByMemberNumber or all(
                    qso_date <= date1 or qso_date <= date2
                    for qso_date in cls.QSOsByMemberNumber[member_number]
                )
            ):
                return f'{award_type}x{next_level}'
        return None

    @classmethod
    def get_goal_hits(cls, TheirCallSign: str, fFrequency: float | None = None) -> list[str]:
        if TheirCallSign not in cSKCC.members or TheirCallSign == cConfig.MY_CALLSIGN:
            return []

        TheirMemberEntry  = cSKCC.members[TheirCallSign]

        # Don't spot inactive members (IA=Inactive, SK=Silent Key)
        if TheirMemberEntry.get('mbr_status') != 'A':
            return []
        TheirC_Date       = cUtil.effective(TheirMemberEntry['c_date'])
        TheirT_Date       = cUtil.effective(TheirMemberEntry['t_date'])
        TheirS_Date       = cUtil.effective(TheirMemberEntry['s_date'])
        TheirMemberNumber = TheirMemberEntry['plain_number']

        GoalHitList: list[str] = []

        if 'BRAG' in cConfig.GOALS and TheirMemberNumber not in cls.Brag:
            if (fFrequency and cSKCC.is_on_warc_frequency(fFrequency)) or not cSKCC.is_during_sprint(cFastDateTime.now_gmt()):
                GoalHitList.append('BRAG')

        # C award processing - handles both initial C and multipliers intelligently
        if 'C' in cConfig.GOALS:
            result = cls._check_cts_goal('C', TheirMemberNumber, cls.ContactsForC, cls.MyC_Date)
            if result:
                GoalHitList.append(result)

        # T award processing - handles both initial T and multipliers intelligently
        if 'T' in cConfig.GOALS and cls.MyC_Date and TheirC_Date:
            result = cls._check_cts_goal('T', TheirMemberNumber, cls.ContactsForT, cls.MyT_Date)
            if result:
                GoalHitList.append(result)

        # S award processing - handles both initial S and multipliers intelligently
        if 'S' in cConfig.GOALS and cls.MyTX8_Date and TheirT_Date:
            result = cls._check_cts_goal('S', TheirMemberNumber, cls.ContactsForS, cls.MyS_Date)
            if result:
                GoalHitList.append(result)

        if 'WAS' in cConfig.GOALS and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS:
            GoalHitList.append('WAS')

        if 'WAS-C' in cConfig.GOALS and TheirC_Date and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS_C:
            GoalHitList.append('WAS-C')

        if 'WAS-T' in cConfig.GOALS and TheirT_Date and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS_T:
            GoalHitList.append('WAS-T')

        if 'WAS-S' in cConfig.GOALS and TheirS_Date and (spc := TheirMemberEntry['spc']) in US_STATES and spc not in cls.ContactsForWAS_S:
            GoalHitList.append('WAS-S')

        if 'P' in cConfig.GOALS and (match := cQSO.Prefix_RegEx.match(TheirCallSign)):
            prefix = match.group(1)
            i_their_member_number = int(TheirMemberNumber)
            _, x_factor = cQSO.calculate_numerics('P', cls.calc_prefix_points())

            if (contact := cls.ContactsForP.get(prefix)):
                if i_their_member_number > contact[2]:
                    GoalHitList.append(f'{cUtil.abbreviate_class("P", x_factor)}(+{i_their_member_number - contact[2]})')
            else:
                GoalHitList.append(f'{cUtil.abbreviate_class("P", x_factor)}(new +{i_their_member_number})')

        if 'DX' in cConfig.GOALS:
            # Get DXCC code from member data
            dxcc_code = TheirMemberEntry.get('dxcode', '').strip()
            if dxcc_code and dxcc_code.isdigit():
                home_dxcc = cls.MyDXCC_Code

                # Check DXC (unique countries)
                if dxcc_code not in cls.ContactsForDXC:
                    # Get current DXC count and next level
                    dxc_count = len(cls.ContactsForDXC)
                    _, next_level, _ = cls.get_dx_award_level_and_next(dxc_count + 1)
                    GoalHitList.append(f'DXCx{next_level}')

                # Check DXQ (foreign member QSOs)
                if dxcc_code != home_dxcc and TheirMemberNumber not in cls.ContactsForDXQ:
                    # Get current DXQ count and next level
                    dxq_count = len(cls.ContactsForDXQ)
                    _, next_level, _ = cls.get_dx_award_level_and_next(dxq_count + 1)
                    GoalHitList.append(f'DXQx{next_level}')

        # QRP award processing
        if 'QRP' in cConfig.GOALS and fFrequency:
            # For QRP, we need to check if we've worked this member on this band
            # QRP contacts are stored with key: membernumber_band
            band = cSKCC.which_arrl_band(fFrequency)
            if band:
                qrp_key = f"{TheirMemberNumber}_{band}"
                if qrp_key not in cls.ContactsForQRP:
                    # Calculate current QRP points to determine which level we're working toward
                    # QRP awards are points-based: 300 points per level for 1xQRP, 150 for 2xQRP
                    
                    # Calculate current points for both 1x and 2x
                    points_1x = 0.0
                    points_2x = 0.0
                    band_points = cls._QRP_BAND_POINTS_AWARDS
                    
                    for qso_key, (_, _, _, qrp_type) in cls.ContactsForQRP.items():
                        key_parts = qso_key.split('_')
                        if len(key_parts) >= 2:
                            qso_band = key_parts[1]
                            if qso_band in band_points:
                                points = band_points[qso_band]
                                points_1x += points
                                if qrp_type == 2:  # 2 means 2xQRP
                                    points_2x += points
                    
                    # Determine which QRP level we're working toward
                    # 1xQRP: 300 points per level
                    current_1x_level = int(points_1x // 300)
                    next_1x_level = current_1x_level + 1
                    
                    # 2xQRP: 150 points per level (but only if they've made 2x contacts)
                    if points_2x > 0:
                        current_2x_level = int(points_2x // 150)
                        next_2x_level = current_2x_level + 1
                        GoalHitList.append(f'1xQRP x{next_1x_level},2xQRP x{next_2x_level}')
                    else:
                        GoalHitList.append(f'1xQRP x{next_1x_level}')

        return GoalHitList

    @classmethod
    def get_target_hits(cls, TheirCallSign: str) -> list[str]:
        if TheirCallSign not in cSKCC.members or TheirCallSign == cConfig.MY_CALLSIGN:
            return []

        TheirMemberEntry  = cSKCC.members[TheirCallSign]

        # Don't spot inactive members (IA=Inactive, SK=Silent Key)
        if TheirMemberEntry.get('mbr_status') != 'A':
            return []
        TheirJoin_Date    = cUtil.effective(TheirMemberEntry['join_date'])
        TheirC_Date       = cUtil.effective(TheirMemberEntry['c_date'])
        TheirT_Date       = cUtil.effective(TheirMemberEntry['t_date'])
        TheirTX8_Date     = cUtil.effective(TheirMemberEntry['tx8_date'])
        TheirS_Date       = cUtil.effective(TheirMemberEntry['s_date'])
        TheirMemberNumber = TheirMemberEntry['plain_number']

        TargetHitList: list[str] = []

        # C target processing - handles both initial C and multipliers intelligently
        if 'C' in cConfig.TARGETS:
            result = cls._check_cts_target('C', TheirMemberNumber, TheirC_Date,
                                         cSKCC.centurion_level, TheirJoin_Date, cls.MyJoin_Date)
            if result:
                TargetHitList.append(result)

        # T target processing - handles both initial T and multipliers intelligently
        if 'T' in cConfig.TARGETS and TheirC_Date and cls.MyC_Date:
            result = cls._check_cts_target('T', TheirMemberNumber, TheirT_Date,
                                         cSKCC.tribune_level, TheirC_Date, cls.MyC_Date)
            if result:
                TargetHitList.append(result)

        # S target processing - handles both initial S and multipliers intelligently
        if 'S' in cConfig.TARGETS and TheirTX8_Date and cls.MyT_Date:
            result = cls._check_cts_target('S', TheirMemberNumber, TheirS_Date,
                                         cSKCC.senator_level, TheirTX8_Date, cls.MyT_Date)
            if result:
                TargetHitList.append(result)

        return TargetHitList

    @classmethod
    async def refresh_async(cls) -> None:
        await cls.read_qsos_async()
        await cQSO.get_goal_qsos_async()
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
            QsoDate, QsoCallSign, _QsoSPC, QsoFreq, _QsoComment, _QsoSKCC, _QsoTxPwr, _QsoRxPwr, _QsoDXCC, _QsoBand, _QsoKeyType = Contact

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

                    if TheirMemberNumber not in cls.Brag and BragOkay:
                        cls.Brag[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign, QsoFreq)

        if Print and 'BRAG' in cConfig.GOALS:
            Year = DateOfInterestGMT.year()
            MonthIndex = DateOfInterestGMT.month()-1
            MonthAbbrev = cFastDateTime.MONTH_NAMES[MonthIndex][:3]
            print(f'Total Brag contacts in {MonthAbbrev} {Year}: {len(cls.Brag)}')

    @classmethod
    async def get_goal_qsos_async(cls) -> None:
        """Optimized goal QSO processing with batched operations."""
        # Helper function to check date criteria
        def good(QsoDate: str, MemberDate: str, MyDate: str, EligibleDate: str | None = None) -> bool:
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
        if 'BRAG_MONTHS' in globals() and 'BRAG' in cConfig.GOALS:
            for PrevMonth in range(abs(cConfig.BRAG_MONTHS), 0, -1):
                cQSO.get_brag_qsos(PrevMonth=PrevMonth, Print=True)

        # Process current month as well
        cQSO.get_brag_qsos(PrevMonth=0, Print=False)

        # Define key dates once for efficiency
        eligible_dates = {
            'prefix': AwardDates.PREFIX_START,
            'tribune': AwardDates.TRIBUNE_START,
            'senator': AwardDates.SENATOR_START,
            'was_c': AwardDates.WAS_C_START,
            'was_ts': AwardDates.WAS_TS_START
        }

        # Create reverse lookup for SKCC numbers to callsigns (for GetSKCCFromCall efficiency)
        skcc_number_to_call: dict[str, str] = {}
        for call, member_data in cSKCC.members.items():
            skcc_nr = member_data['plain_number']
            # Use the actual callsign (not main_call) for direct member number lookup
            # This handles cases where a callsign has its own member number
            skcc_number_to_call[skcc_nr] = call

        # Batch process all QSOs
        k3y_start = f'{cConfig.K3Y_YEAR}0102000000'
        k3y_end = f'{cConfig.K3Y_YEAR}0201000000'

        for Contact in cls.QSOs:
            QsoDate, QsoCallSign, QsoSPC, QsoFreq, QsoComment, QsoSKCC, QsoTxPwr, QsoRxPwr, QsoDXCC, QsoBand, QsoKeyType = Contact


            # Skip invalid callsigns
            if QsoCallSign in ('K9SKC', 'K3Y'):
                continue

            # Lookup member using helper method
            mbr_skcc_nr, found_call, is_historical_member = cls._lookup_member_from_qso(QsoSKCC, QsoCallSign, skcc_number_to_call)

            if not mbr_skcc_nr or not found_call:
                continue
            # For prefix processing, we need to use the ORIGINAL logged callsign, not the main_call
            # Store the found_call for member data lookup but keep QsoCallSign as logged
            MemberLookupCall = found_call

            # Get member data using the determined SKCC number (matches Xojo line 315)
            # For member number lookup matches, use the found call's data directly
            if MemberLookupCall in cSKCC.members and cSKCC.members[MemberLookupCall]['plain_number'] == mbr_skcc_nr:
                # Direct member number match - use this member's data
                TheirMemberEntry = cSKCC.members[MemberLookupCall]
                MainCallSign = MemberLookupCall
            else:
                # Fall back to main_call lookup
                MainCallSign = cSKCC.members[MemberLookupCall]['main_call']
                TheirMemberEntry = cSKCC.members[MainCallSign]

            TheirJoin_Date = cUtil.effective(TheirMemberEntry['join_date'])
            TheirC_Date = cUtil.effective(TheirMemberEntry['c_date'])
            TheirT_Date = cUtil.effective(TheirMemberEntry['t_date'])
            TheirS_Date = cUtil.effective(TheirMemberEntry['s_date'])
            # Use the determined member number from GetSKCCFromCall, not recalculated
            TheirMemberNumber = mbr_skcc_nr

            # Main validation: QSO date >= member join date AND not working yourself (matches Xojo line 318)
            # For historical members, we assume join date validation passes since QSO explicitly references that member
            date_validation_passes = (is_historical_member or good(QsoDate, TheirJoin_Date, cls.MyJoin_Date))

            if date_validation_passes and TheirMemberNumber != cls.MyMemberNumber:

                # K3Y processing
                if 'K3Y' in cConfig.GOALS and QsoDate >= k3y_start and QsoDate < k3y_end:
                    if k3y_match := re.match(r'.*?(?:K3Y|SKM)[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)', QsoComment, re.IGNORECASE):
                        Suffix = k3y_match.group(1).upper()

                        if Band := cSKCC.which_arrl_band(QsoFreq):
                            if Suffix not in cls.ContactsForK3Y:
                                cls.ContactsForK3Y[Suffix] = {}
                            cls.ContactsForK3Y[Suffix][Band] = QsoCallSign

                # Prefix processing - exact Xojo logic from AwardProcessorThreadWindow lines 485-511
                # Xojo only checks if QSO date >= 20130101 (line 485)
                if QsoDate >= eligible_dates['prefix']:
                    # Split callsign by "/" and process each segment (Xojo logic)
                    call_segments = QsoCallSign.split('/')

                    for pfx_call in call_segments:
                        # GetSKCCFromCall(pfx_call, mbr_skcc_nr) logic from Xojo
                        # Returns mbr_skcc_nr if pfx_call is found in member database, else empty string
                        pfx_skcc_nr = ""  # Default to empty string like Xojo

                        # Check if this segment exists in the member database
                        if pfx_call in cSKCC.members:
                            # Segment found in database - return the logged SKCC number
                            pfx_skcc_nr = TheirMemberNumber

                        # Xojo only processes if GetSKCCFromCall returned non-empty string
                        if pfx_skcc_nr != "":
                            # Extract prefix using exact Xojo logic from line 493-497
                            if len(pfx_call) >= 3 and pfx_call[2].isdigit():
                                Prefix = pfx_call[:3]  # First 3 characters
                            else:
                                Prefix = pfx_call[:2]  # First 2 characters

                            iTheirMemberNumber = int(TheirMemberNumber)

                            # Update if this is a new prefix or higher SKCC number (line 499-503)
                            if Prefix not in cls.ContactsForP or iTheirMemberNumber > cls.ContactsForP[Prefix][2]:
                                # Use the name from the segment's member data if found
                                seg_name = cSKCC.members[pfx_call].get('name', '') if pfx_call in cSKCC.members else ''
                                cls.ContactsForP[Prefix] = (QsoDate, Prefix, iTheirMemberNumber, seg_name)

                            break  # Only process first valid segment (line 510)

                # Process C, T, S in one batch
                # For Centurion award: basic validation already done above
                # Always update (last QSO wins, matching potential reference behavior)
                cls.ContactsForC[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

                if good(QsoDate, TheirC_Date, cls.MyC_Date, eligible_dates['tribune']):
                    cls.ContactsForT[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

                if good(QsoDate, TheirT_Date, cls.MyTX8_Date, eligible_dates['senator']):
                    cls.ContactsForS[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

                # Process WAS entries for states
                if QsoSPC in US_STATES:
                    # Base WAS - basic validation already done above
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

                # Phase 1: Mark QRP QSOs during processing (matching Xojo AwardProcessorThreadWindow logic)
                if QsoTxPwr and QsoFreq > 0:
                    try:
                        tx_power = float(QsoTxPwr.strip())
                        if 0.0 < tx_power <= 5.0:
                            # This QSO qualifies for QRP 1x
                            qrp_1x_qualified = True
                            qrp_2x_qualified = False

                            # Check for QRP 2x (both TX and RX <= 5W)
                            if QsoRxPwr and QsoRxPwr.strip():
                                try:
                                    rx_power = float(QsoRxPwr.strip())
                                    if 0.0 < rx_power <= 5.0:
                                        qrp_2x_qualified = True
                                except (ValueError, TypeError):
                                    pass

                            # Store QRP-qualified QSO with all needed data for later band-by-band processing
                            if qrp_1x_qualified or qrp_2x_qualified:
                                band = QsoBand.strip() if QsoBand else ''
                                if band:
                                    # Store with original band name (before normalization)
                                    qrp_qso_data: QRPQSOData = {
                                        'date': QsoDate,
                                        'member_number': TheirMemberNumber,
                                        'callsign': MainCallSign,
                                        'band': band,
                                        'qrp_1x': qrp_1x_qualified,
                                        'qrp_2x': qrp_2x_qualified
                                    }
                                    if not hasattr(cls, 'QRPQualifiedQSOs'):
                                        cls.QRPQualifiedQSOs = []
                                    cls.QRPQualifiedQSOs.append(qrp_qso_data)
                    except (ValueError, TypeError):
                        pass

                # Process DX contacts if DX is a goal
                if 'DX' in cConfig.GOALS:
                    # Get DXCC code - prioritize ADI file DXCC, fallback to member data
                    dxcc_code = QsoDXCC.strip() if QsoDXCC else ''
                    if not dxcc_code:
                        # Try to get from member data
                        dxcc_code = TheirMemberEntry.get('dxcode', '').strip()

                    if dxcc_code and dxcc_code.isdigit():
                        # Normalize DXCC code by converting to integer to remove leading zeros
                        dxcc_code = str(int(dxcc_code))

                        # Use user's DXCC code from membership data
                        home_dxcc = cls.MyDXCC_Code

                        # DXC: Count unique countries (date >= 20091219, allows one home country contact)
                        if QsoDate >= '20091219':
                            if dxcc_code == home_dxcc:
                                # Home country - only allow one contact
                                if not cls.DXC_HomeCountryUsed:
                                    cls.ContactsForDXC[dxcc_code] = (QsoDate, TheirMemberNumber, MainCallSign)
                                    cls.DXC_HomeCountryUsed = True
                            else:
                                # Foreign country - count all unique DXCC entities
                                if dxcc_code not in cls.ContactsForDXC:
                                    cls.ContactsForDXC[dxcc_code] = (QsoDate, TheirMemberNumber, MainCallSign)

                        # DXQ: Count unique member QSOs from foreign countries (date >= 20090614, no home country)
                        if QsoDate >= '20090614' and dxcc_code != home_dxcc:
                            if TheirMemberNumber not in cls.ContactsForDXQ:
                                cls.ContactsForDXQ[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

                if 'TKA' in cConfig.GOALS:
                    # TKA: Triple Key Award - need 100 each of SK, BUG, SS from unique members
                    # Only count QSOs on or after November 10, 2018
                    if QsoDate >= '20181110' and QsoKeyType:
                        # QsoKeyType should contain 'SK', 'BUG', or 'SS' from APP_SKCCLOGGER_KEYTYPE field
                        key_type_upper = QsoKeyType.upper().strip()
                        
                        if key_type_upper == 'SK' and TheirMemberNumber not in cls.ContactsForTKA_SK:
                            cls.ContactsForTKA_SK[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)
                        elif key_type_upper == 'BUG' and TheirMemberNumber not in cls.ContactsForTKA_BUG:
                            cls.ContactsForTKA_BUG[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)
                        elif key_type_upper == 'SS' and TheirMemberNumber not in cls.ContactsForTKA_SS:
                            cls.ContactsForTKA_SS[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

        # Generate output files
        QSOs_Dir = 'QSOs'
        if not await aiofiles.os.path.exists(QSOs_Dir):
            os.makedirs(QSOs_Dir)

        # Award files
        await cls.award_cts_async('C', cls.ContactsForC)
        await cls.award_cts_async('T', cls.ContactsForT)
        await cls.award_cts_async('S', cls.ContactsForS)
        await cls.award_was_async('WAS', cls.ContactsForWAS)
        await cls.award_was_async('WAS-C', cls.ContactsForWAS_C)
        await cls.award_was_async('WAS-T', cls.ContactsForWAS_T)
        await cls.award_was_async('WAS-S', cls.ContactsForWAS_S)
        await cls.award_p_async(cls.ContactsForP)

        # Phase 2: Process QRP awards using Xojo's exact band-by-band logic
        cls.process_qrp_awards_xojo_style()


        await cls.award_qrp_async(cls.ContactsForQRP)
        await cls.award_dx_async()
        await cls.award_tka_async()
        await cls.track_brag_async(cls.Brag)

        # Print K3Y contacts if needed
        if 'K3Y' in cConfig.GOALS:
            cls.print_k3y_contacts()

    @classmethod
    async def award_dx_async(cls) -> None:
        """Write DXC and DXQ award files."""
        # Write DXC file (unique countries)
        if cls.ContactsForDXC:
            async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-DXC.txt', 'w', encoding='utf-8') as file:
                await file.write(f"DXC Award Progress for {cConfig.MY_CALLSIGN}\n")
                await file.write("=" * 50 + "\n\n")
                await file.write("DXCC  Date        CallSign     Member#\n")
                await file.write("-" * 40 + "\n")

                for dxcc_code, (qso_date, member_number, callsign) in sorted(cls.ContactsForDXC.items()):
                    date_str = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
                    await file.write(f"{dxcc_code:>4}  {date_str}  {callsign:<12} {member_number}\n")

                await file.write(f"\nTotal Countries: {len(cls.ContactsForDXC)} (Need: 100)\n")
                await file.write(f"Progress: {len(cls.ContactsForDXC):.1f}%\n")

        # Write DXQ file (foreign member QSOs)
        if cls.ContactsForDXQ:
            async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-DXQ.txt', 'w', encoding='utf-8') as file:
                await file.write(f"DXQ Award Progress for {cConfig.MY_CALLSIGN}\n")
                await file.write("=" * 50 + "\n\n")
                await file.write("Date        CallSign     Member#\n")
                await file.write("-" * 35 + "\n")

                for member_number, (qso_date, _, callsign) in sorted(cls.ContactsForDXQ.items(), key=lambda x: x[1][0]):
                    date_str = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
                    await file.write(f"{date_str}  {callsign:<12} {member_number}\n")

                await file.write(f"\nTotal Foreign Member QSOs: {len(cls.ContactsForDXQ)} (Need: 100)\n")
                await file.write(f"Progress: {len(cls.ContactsForDXQ):.1f}%\n")

    @classmethod
    async def award_tka_async(cls) -> None:
        """Write TKA (Triple Key Award) files."""
        import aiofiles
        
        # Only generate files if we have TKA contacts
        if not (cls.ContactsForTKA_SK or cls.ContactsForTKA_BUG or cls.ContactsForTKA_SS):
            return
            
        async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-TKA.txt', 'w', encoding='utf-8') as file:
            await file.write(f"TKA Award Progress for {cConfig.MY_CALLSIGN}\n")
            await file.write(f"Triple Key Award - Need 100 each of SK, BUG, SS from 300 unique members\n")
            await file.write("=" * 70 + "\n\n")
            
            # Write SK contacts
            await file.write("STRAIGHT KEY (SK) CONTACTS\n")
            await file.write("-" * 30 + "\n")
            for member_number, (qso_date, _, callsign) in sorted(cls.ContactsForTKA_SK.items(), key=lambda x: x[1][0]):
                date_str = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
                await file.write(f"{date_str}  {callsign:<12} {member_number}\n")
            await file.write(f"Total SK: {len(cls.ContactsForTKA_SK)}\n\n")
            
            # Write BUG contacts
            await file.write("BUG CONTACTS\n")
            await file.write("-" * 30 + "\n")
            for member_number, (qso_date, _, callsign) in sorted(cls.ContactsForTKA_BUG.items(), key=lambda x: x[1][0]):
                date_str = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
                await file.write(f"{date_str}  {callsign:<12} {member_number}\n")
            await file.write(f"Total BUG: {len(cls.ContactsForTKA_BUG)}\n\n")
            
            # Write SS contacts
            await file.write("SIDESWIPER/COOTIE (SS) CONTACTS\n")
            await file.write("-" * 30 + "\n")
            for member_number, (qso_date, _, callsign) in sorted(cls.ContactsForTKA_SS.items(), key=lambda x: x[1][0]):
                date_str = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
                await file.write(f"{date_str}  {callsign:<12} {member_number}\n")
            await file.write(f"Total SS: {len(cls.ContactsForTKA_SS)}\n\n")
            
            # Calculate unique members
            all_members: set[str] = set()
            all_members.update(cls.ContactsForTKA_SK.keys())
            all_members.update(cls.ContactsForTKA_BUG.keys())
            all_members.update(cls.ContactsForTKA_SS.keys())
            unique_total = len(all_members)
            
            await file.write("=" * 70 + "\n")
            await file.write(f"SUMMARY: SK:{len(cls.ContactsForTKA_SK)} BUG:{len(cls.ContactsForTKA_BUG)} SS:{len(cls.ContactsForTKA_SS)} Total unique:{unique_total}/300\n")

    @classmethod
    async def award_qrp_async(cls, QSOs: dict[str, tuple[str, str, str, int]]) -> None:
        """Generate QRP award files with point calculations using generator-based streaming."""
        import aiofiles

        if not QSOs:
            return

        # QRP point values by band (using hoisted constant)
        band_points = cls._QRP_BAND_POINTS_AWARDS

        def qrp_2x_contacts_generator() -> Iterator[tuple[str, str, str, str, float]]:
            """Generator that yields QRP 2x contacts (TX and RX <= 5W), sorted by date."""
            contacts: list[tuple[str, str, str, str, float]] = []
            for qso_key, (qso_date, member_number, callsign, qrp_type) in QSOs.items():
                if qrp_type == 2:  # QRP 2x: TX power <= 5W AND RX power <= 5W
                    # Extract band from the key (format: "member_band_date")
                    key_parts = qso_key.split('_')
                    band: str = key_parts[1] if len(key_parts) >= 3 else ""
                    points: float = band_points.get(band, 0.0)
                    contacts.append((qso_date, member_number, callsign, band, points))

            # Sort by date and yield
            yield from sorted(contacts, key=lambda x: x[0])

        # Write 1xQRP file (ALL QRP contacts count toward 1xQRP)
        def all_qrp_contacts_generator() -> Iterator[tuple[str, str, str, str, float]]:
            """Generator that yields ALL QRP contacts (both 1x and 2x), sorted by date."""
            contacts: list[tuple[str, str, str, str, float]] = []
            for qso_key, (qso_date, member_number, callsign, _) in QSOs.items():
                # ALL QRP contacts count toward 1xQRP award
                key_parts = qso_key.split('_')
                band: str = key_parts[1] if len(key_parts) >= 3 else ""
                points: float = band_points.get(band, 0.0)
                contacts.append((qso_date, member_number, callsign, band, points))

            # Sort by date and yield
            yield from sorted(contacts, key=lambda x: x[0])

        qrp_1x_generator = all_qrp_contacts_generator()
        qrp_1x_first = next(qrp_1x_generator, None)
        if qrp_1x_first is not None:
            async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-QRP-1x.txt', 'w', encoding='utf-8') as file:
                await file.write(f"1xQRP Award Progress for {cConfig.MY_CALLSIGN}\n")
                await file.write("=" * 50 + "\n\n")

                total_points: float = 0.0
                index = 1

                # Process first contact
                _, member_number, callsign, band, points = qrp_1x_first
                total_points += points
                await file.write(f"{index:>4} {member_number:>8} {callsign:<12} {band:<6} {points:>6.1f} {total_points:>8.1f}\n")
                index += 1

                # Process remaining contacts from generator
                for _, member_number, callsign, band, points in qrp_1x_generator:
                    total_points += points
                    await file.write(f"{index:>4} {member_number:>8} {callsign:<12} {band:<6} {points:>6.1f} {total_points:>8.1f}\n")
                    index += 1

                await file.write(f"\nTotal Points: {total_points:.1f} (Need: 300)\n")
                await file.write(f"Progress: {total_points/3:.1f}%\n")

        # Write 2xQRP file
        qrp_2x_generator = qrp_2x_contacts_generator()
        qrp_2x_first = next(qrp_2x_generator, None)
        if qrp_2x_first is not None:
            async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-QRP-2x.txt', 'w', encoding='utf-8') as file:
                await file.write(f"2xQRP Award Progress for {cConfig.MY_CALLSIGN}\n")
                await file.write("=" * 50 + "\n\n")

                total_points: float = 0.0
                index = 1

                # Process first contact
                _, member_number, callsign, band, points = qrp_2x_first
                total_points += points
                await file.write(f"{index:>4} {member_number:>8} {callsign:<12} {band:<6} {points:>6.1f} {total_points:>8.1f}\n")
                index += 1

                # Process remaining contacts from generator
                for _, member_number, callsign, band, points in qrp_2x_generator:
                    total_points += points
                    await file.write(f"{index:>4} {member_number:>8} {callsign:<12} {band:<6} {points:>6.1f} {total_points:>8.1f}\n")
                    index += 1

                await file.write(f"\nTotal Points: {total_points:.1f} (Need: 150)\n")
                await file.write(f"Progress: {total_points*2/3:.1f}%\n")

    @classmethod
    async def award_p_async(cls, QSOs: dict[str, tuple[str, str, int, str]]) -> None:
        """Async version of award_p to write files using aiofiles"""
        import aiofiles  # You'll need to add this to your imports

        async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-P.txt', 'w', encoding='utf-8') as file:
            iPoints = 0
            for index, (_qso_date, prefix, member_number, first_name) in enumerate(
                sorted(QSOs.values(), key=lambda q: q[1]), start=1
            ):
                iPoints += member_number
                await file.write(f"{index:>4} {member_number:>8} {first_name:<10.10} {prefix:<6} {iPoints:>12,}\n")

    @classmethod
    async def award_cts_async(cls, Class: str, QSOs_dict: dict[str, tuple[str, str, str]]) -> None:
        """Async version of award_cts to write files using aiofiles"""
        import aiofiles

        QSOs = QSOs_dict.values()
        QSOs = sorted(QSOs, key=lambda QsoTuple: (QsoTuple[0], QsoTuple[2]))

        async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-{Class}.txt', 'w', encoding='utf-8') as File:
            for Count, (QsoDate, TheirMemberNumber, MainCallSign) in enumerate(QSOs):
                Date = f'{QsoDate[0:4]}-{QsoDate[4:6]}-{QsoDate[6:8]}'
                await File.write(f'{Count+1:<4}  {Date}   {MainCallSign:<9}   {TheirMemberNumber:<7}\n')

    @classmethod
    async def award_was_async(cls, Class: str, QSOs_dict: dict[str, tuple[str, str, str]]) -> None:
        """Async version of award_was to write files using aiofiles"""
        import aiofiles

        QSOsByState = {spc: (spc, date, callsign) for spc, date, callsign in sorted(QSOs_dict.values(), key=lambda q: q[0])}

        async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-{Class}.txt', 'w', encoding='utf-8') as file:
            for state in US_STATES:
                if state in QSOsByState:
                    spc, date, callsign = QSOsByState[state]
                    await file.write(f"{spc}    {callsign:<12}  {date[:4]}-{date[4:6]}-{date[6:8]}\n")
                else:
                    await file.write(f"{state}\n")

    @classmethod
    async def track_brag_async(cls, QSOs: dict[str, tuple[str, str, str, float]]) -> None:
        """Async version of track_brag to write files using aiofiles"""
        import aiofiles

        async with aiofiles.open(f'QSOs/{cConfig.MY_CALLSIGN}-BRAG.txt', 'w', encoding='utf-8') as file:
            for count, (qso_date, their_member_number, main_callsign, qso_freq) in enumerate(
                sorted(QSOs.values()), start=1
            ):
                date = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
                if qso_freq:
                    await file.write(f"{count:<4} {date}  {their_member_number:<6}  {main_callsign}  {qso_freq / 1000:.3f}\n")
                else:
                    await file.write(f"{count:<4} {date}  {their_member_number:<6}  {main_callsign}\n")

    @classmethod
    def print_k3y_contacts(cls) -> None:
        # Could be cleaner, but want to match order on the SKCC K3Y website.
        print('')
        print(f'K3Y {cConfig.K3Y_YEAR}')
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

        def print_station(Station: str) -> None:
            _Prefix, Suffix = re.split('[/-]', Station)

            def print_band(Band: int) -> None:
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
    _columns_regex: ClassVar[re.Pattern[str]] = re.compile(
        r'<td.*?><a href="/dxsd1.php\?f=.*?>\s*(.*?)\s*</a>.*?</td>\s*'
        r'<td.*?>\s*(.*?)</a></td>\s*<td.*?>(.*?)</td>',
        re.S
    )

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
    async def get_spotters_async(cls) -> None:
        """Get RBN spotters within the configured radius using parallel async requests."""
        print(f"\nFinding RBN spotters within {cConfig.SPOTTER_RADIUS} miles of '{cConfig.MY_GRIDSQUARE}'...")

        try:
            # Use aiohttp instead of requests for async HTTP
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=10)) as session:
                async with session.get(RBN_STATUS_URL) as response:
                    if response.status != 200:
                        print(f'*** Fatal Error: Unable to retrieve spotters from RBN: HTTP {response.status}')
                        sys.exit()
                    html = await response.text()
        except aiohttp.ClientError as e:
            print(f'*** Fatal Error: Unable to retrieve spotters from RBN: {e}')
            sys.exit()

        rows = re.findall(r'<tr.*?online24h online7d total">(.*?)</tr>', html, re.S)

        # Use hoisted regex pattern
        columns_regex = cls._columns_regex

        # Process spotters in parallel
        processing_tasks: list[Coroutine[Any, Any, None]]  = []

        for row in rows:
            for spotter, csv_bands, grid in columns_regex.findall(row):
                if grid in ["XX88LL"]:
                    continue

                processing_tasks.append(cls._process_spotter(spotter, csv_bands, grid))

        # Wait for all processing tasks to complete
        await asyncio.gather(*processing_tasks)

    @classmethod
    async def _process_spotter(cls, spotter: str, csv_bands: str, grid: str) -> None:
        """Process a single spotter entry asynchronously."""
        try:
            miles = int(cSpotters.calculate_distance(cConfig.MY_GRIDSQUARE, grid) * 0.62137)

            # Parse bands from csv string
            valid_bands = {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"}
            bands = list(int(b[:-1]) for b in csv_bands.split(',') if b in valid_bands)

            cls.spotters[spotter] = (miles, bands)
        except ValueError:
            pass

    @classmethod
    def get_nearby_spotters(cls) -> list[tuple[str, int]]:
        spotters_sorted = sorted(cls.spotters.items(), key=lambda item: item[1][0])
        nearbySpotters = list((spotter, miles) for spotter, (miles, _) in spotters_sorted if miles <= cConfig.SPOTTER_RADIUS)
        return nearbySpotters

    @classmethod
    def get_distance(cls, Spotter: str) -> int:
        Miles, _ = cls.spotters[Spotter]
        return Miles

class cSKCC:
    _roster_columns_regex: ClassVar[re.Pattern[str]] = re.compile(r"<td.*?>(.*?)</td>", re.I | re.S)

    class cMemberEntry(TypedDict):
        name: str
        plain_number: str
        spc: str
        dxcode: str
        join_date: str
        c_date: str
        t_date: str
        tx8_date: str
        s_date: str
        main_call: str
        mbr_status: str

    members:         ClassVar[dict[str, cMemberEntry]] = {}

    centurion_level: ClassVar[dict[str, int]] = {}

    tribune_level:   ClassVar[dict[str, int]] = {}
    senator_level:   ClassVar[dict[str, int]] = {}
    was_level:       ClassVar[dict[str, int]] = {}
    was_c_level:     ClassVar[dict[str, int]] = {}

    was_t_level:     ClassVar[dict[str, int]] = {}
    was_s_level:     ClassVar[dict[str, int]] = {}
    prefix_level:    ClassVar[dict[str, int]] = {}
    dxq_level:       ClassVar[dict[str, int]] = {}
    dxc_level:       ClassVar[dict[str, int]] = {}
    qrp_1x_level:    ClassVar[dict[str, int]] = {}
    qrp_2x_level:    ClassVar[dict[str, int]] = {}
    tka_level:       ClassVar[dict[str, int]] = {}  # Triple Key Award roster


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
    async def initialize_async(cls) -> None:
        """Initialize SKCC data using parallel downloads for rosters."""
        # First, read the main SKCC data
        await cls.read_skcc_data_async()

        # Convert the synchronous methods to async
        print("Downloading award rosters...")

        try:
            # Create a list of coroutines for all downloads
            tasks = [
                cls.read_level_list_async('Centurion', 'centurionlist.txt'),
                cls.read_level_list_async('Tribune', 'tribunelist.txt'),
                cls.read_level_list_async('Senator', 'senator.txt'),
                cls.read_roster_async('WAS', 'operating_awards/was/was_roster.php'),
                cls.read_roster_async('WAS-C', 'operating_awards/was-c/was-c_roster.php'),
                cls.read_roster_async('WAS-T', 'operating_awards/was-t/was-t_roster.php'),
                cls.read_roster_async('WAS-S', 'operating_awards/was-s/was-s_roster.php'),
                cls.read_roster_async('PFX', 'operating_awards/pfx/prefix_roster.php'),
                cls.read_roster_async('DXQ', 'operating_awards/dx/dxq_roster.php'),
                cls.read_roster_async('DXC', 'operating_awards/dx/dxc_roster.php'),
                cls.read_roster_async('QRP 1x', 'operating_awards/qrp_awards/qrp_x1_roster.php'),
                cls.read_roster_async('QRP 2x', 'operating_awards/qrp_awards/qrp_x2_roster.php'),
                cls.read_roster_async('TKA', 'operating_awards/triplekey/triplekey_roster.php')
            ]

            try:
                results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
            except asyncio.TimeoutError:
                print("Timeout loading rosters")
                return

            # Unpack results
            cls.centurion_level, cls.tribune_level, cls.senator_level, \
            cls.was_level, cls.was_c_level, cls.was_t_level, \
            cls.was_s_level, cls.prefix_level, cls.dxq_level, \
            cls.dxc_level, cls.qrp_1x_level, cls.qrp_2x_level, cls.tka_level = results

            print("Successfully downloaded all award rosters.")
        except asyncio.TimeoutError:
            print("Timeout error downloading rosters.")
            sys.exit(1)
        except Exception as e:
            print(f"Error downloading rosters: {e}")
            sys.exit(1)

    @classmethod
    def build_member_info(cls, CallSign: str) -> str:
        entry = cls.members[CallSign]
        number, suffix = cls.get_full_member_number(CallSign)

        return f'({number:>5} {suffix:<4} {entry["name"]:<9.9} {entry["spc"]:>3})'

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
    async def block_during_update_window_async() -> None:
        def time_now_gmt() -> int:
            TimeNowGMT = time.strftime('%H%M00', time.gmtime())
            return int(TimeNowGMT)

        if time_now_gmt() % 20000 == 0:
            print('The SKCC website updates files every even UTC hour.')
            print('SKCC Skimmer will start when complete.  Please wait...')

            while time_now_gmt() % 20000 == 0:
                await asyncio.sleep(2)  # Non-blocking sleep
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
    async def read_level_list_async(Type: str, URL: str) -> dict[str, int] | NoReturn:
        """Read award level list with async HTTP request."""
        print(f"Retrieving SKCC award info from {URL}...")

        try:
            # Use aiohttp instead of requests for async HTTP
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(f"{SKCC_BASE_URL}{URL}") as response:
                    if response.status != 200:
                        print(f"Error retrieving award info: HTTP {response.status}")
                        return {}
                    text = await response.text()
        except Exception as e:
            print(f"Error retrieving award info: {e}")
            return {}

        today_gmt = time.strftime("%Y%m%d000000", time.gmtime())
        level: dict[str, int] = {}

        for line in text.splitlines()[1:]:
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
    async def read_roster_async(Name: str, URL: str) -> dict[str, int] | NoReturn:
        """Read roster with async HTTP request."""
        print(f"Retrieving SKCC {Name} roster...")

        try:
            # Use aiohttp instead of requests for async HTTP
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(f"{SKCC_BASE_URL}{URL}") as response:
                    if response.status != 200:
                        print(f"Error retrieving {Name} roster: HTTP {response.status}")
                        return {}
                    text = await response.text()
        except Exception as e:
            print(f"Error retrieving {Name} roster: {e}")
            return {}

        rows = re.findall(r"<tr.*?>(.*?)</tr>", text, re.I | re.S)
        # Use hoisted regex pattern
        columns_regex = cSKCC._roster_columns_regex

        # For DX and QRP rosters, use SKCC number (column 2) as key
        if Name in ['DXC', 'DXQ', 'QRP 1x', 'QRP 2x']:
            return {
                (cols := columns_regex.findall(row))[2]: int(cols[0].split()[1][1:]) if " " in cols[0] else 1
                for row in rows[1:]
                if (cols := columns_regex.findall(row)) and len(cols) >= 3  # Ensure valid row data with SKCC number
            }
        else:
            # For other rosters, use callsign (column 1) as key
            return {
                (cols := columns_regex.findall(row))[1]: int(cols[0].split()[1][1:]) if " " in cols[0] else 1
                for row in rows[1:]
                if (cols := columns_regex.findall(row)) and len(cols) >= 2  # Ensure valid row data
            }

    @classmethod
    async def read_skcc_data_async(cls) -> None | NoReturn:
        """Read SKCC member data asynchronously with improved error handling."""
        print('Retrieving SKCC award dates...')

        url = SKCC_DATA_URL

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        print(f"Unexpected response code {response.status} from SKCC website")
                        sys.exit(1)
                    text = await response.text()
        except aiohttp.ClientError as e:
            print(f"Error retrieving SKCC data: {e}")
            sys.exit(1)

        lines = text.splitlines()

        # Clear existing data
        cls.members.clear()
        cls._member_cache.clear()

        for line in lines[1:]:
            try:
                fields = line.split("|")
                (
                    number, current_call, name, spc, other_calls, dxcode, join_date, c_date, t_date, tx8_date, s_date, mbr_status, *_
                ) = fields
            except ValueError:
                print("Error parsing SKCC data line. Skipping.")
                continue

            all_calls = [current_call] + list(x.strip() for x in other_calls.split(",")) if other_calls else [current_call]

            # Derive plain number by removing suffix letters from SKCCNR
            plain_number = re.sub(r'[A-Z]+$', '', number)

            for call in all_calls:
                cls.members[call] = {
                    'name'         : name,
                    'plain_number' : plain_number,
                    'spc'          : spc,
                    'dxcode'       : dxcode,
                    'join_date'    : cls.normalize_skcc_date(join_date),
                    'c_date'       : cls.normalize_skcc_date(c_date),
                    't_date'       : cls.normalize_skcc_date(t_date),
                    'tx8_date'     : cls.normalize_skcc_date(tx8_date),
                    's_date'       : cls.normalize_skcc_date(s_date),
                    'main_call'    : current_call,
                    'mbr_status'   : mbr_status,
                }

        print(f"Successfully loaded data for {len(cls.members):,} member callsigns")

    @classmethod
    def is_on_skcc_frequency(cls, frequency_khz: float, tolerance_khz: int = 10) -> bool:
        return any(
            ((Band == 60) and ((5332 - 1.5) <= frequency_khz <= (5405 + 1.5))) or
            any((((MidPoint - tolerance_khz) <= frequency_khz) and (frequency_khz <= (MidPoint + tolerance_khz))) for MidPoint in MidPoints)
            for Band, MidPoints in cls._calling_frequencies_khz.items()
        )

    @classmethod
    def which_band(cls, frequency_khz: float, tolerance_khz: float = 10) -> int | None:
        return next(
            (Band for Band, MidPointsKHz in cls._calling_frequencies_khz.items()
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

    @classmethod
    def is_on_warc_frequency(cls, frequency_khz: float, tolerance_khz: int = 10) -> bool:
        return any(
            (CallingFrequencyKHz - tolerance_khz) <= frequency_khz <= (CallingFrequencyKHz + tolerance_khz)
            for Band in (30, 17, 12)
            for CallingFrequencyKHz in cls._calling_frequencies_khz[Band]
        )

    @classmethod
    def get_full_member_number(cls, CallSign: str) -> tuple[str, str]:
        """Get a member's full number including suffix."""
        Entry = cls.members[CallSign]
        MemberNumber = Entry['plain_number']

        Suffix = ''
        Level = 1

        # Simple synchronous calls - no need for threading
        c_date = cUtil.effective(Entry['c_date'])
        t_date = cUtil.effective(Entry['t_date'])
        s_date = cUtil.effective(Entry['s_date'])

        if s_date:
            Suffix = 'S'
            Level = cls.senator_level.get(MemberNumber, 1)
        elif t_date:
            Suffix = 'T'
            Level = cls.tribune_level.get(MemberNumber, 1)

            if Level == 8 and not cUtil.effective(Entry['tx8_date']):
                Level = 7
        elif c_date:
            Suffix = 'C'
            Level = cls.centurion_level.get(MemberNumber, 1)

        if Level > 1:
            Suffix += f'x{Level}'

        return (MemberNumber, Suffix)

    @classmethod
    async def lookups_async(cls, LookupString: str) -> None:
        """Async version of lookups to allow for concurrent processing."""
        async def print_callsign_async(CallSign: str) -> None:
            Entry = cls.members[CallSign]
            MyNumber = cls.members[cConfig.MY_CALLSIGN]['plain_number']
            Report = [cls.build_member_info(CallSign)]

            if Entry['plain_number'] == MyNumber:
                Report.append('(you)')
            else:
                # Get goal and target hits in one pass, could be made async if these methods are updated
                GoalList = cQSO.get_goal_hits(CallSign)
                TargetList = cQSO.get_target_hits(CallSign)
                IsFriend = CallSign in cConfig.FRIENDS

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

        # Process each lookup in parallel
        tasks: list[Coroutine[Any, Any, None]] = []

        for Item in LookupList:
            # Check for member number format
            if match := re.match(r'^([0-9]+)[CTS]{0,1}$', Item):
                Number = match.group(1)

                # Find the callsign for this member number
                found = False
                for CallSign, Value in cls.members.items():
                    if Value['plain_number'] == Number and CallSign == Value['main_call']:
                        tasks.append(print_callsign_async(CallSign))
                        found = True
                        break

                if not found:
                    print(f'  No member with the number {Number}.')
            else:
                # Check if it's a valid callsign
                if CallSign := cls.extract_callsign(Item):
                    tasks.append(print_callsign_async(CallSign))
                else:
                    print(f'  {Item} - not an SKCC member.')

        # Execute all tasks concurrently
        if tasks:
            await asyncio.gather(*tasks)

        print('')

class cRBN:

    _connected: ClassVar[bool] = False

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
        """Try to connect to the RBN server, preferring IPv6 but falling back to IPv4.
        Includes robust connection handling with keepalive and timeout management."""

        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        retry_count = 0

        while True:
            # Resolve the hostname dynamically
            addresses: list[tuple[socket.AddressFamily, str]] = await cRBN.resolve_host(RBN_SERVER, RBN_PORT)
            if not addresses:
                retry_count += 1
                backoff_time = min(5 * (2 ** min(retry_count - 1, 4)), 60)  # Exponential backoff, max 60s
                print(f"Error: No valid IP addresses found for {RBN_SERVER}. Retrying in {backoff_time} seconds...")
                await asyncio.sleep(backoff_time)
                continue

            cls._connected = False
            connection_succeeded = False
            attempted_protocols: list[str] = []
            error_messages: list[str] = []

            for family, ip in addresses:
                protocol: str = "IPv6" if family == socket.AF_INET6 else "IPv4"
                attempted_protocols.append(protocol)

                try:
                    # Add connection timeout
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(ip, RBN_PORT, family=family),
                        timeout=30.0  # 30 second connection timeout
                    )

                    # Enable TCP keepalive
                    sock = writer.get_extra_info('socket')
                    if sock:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        # Set keepalive parameters if available (Linux/Unix)
                        if hasattr(socket, 'TCP_KEEPIDLE'):
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 300)  # 5 minutes
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60)  # 1 minute
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)    # 3 probes

                    print(f"Connected to '{RBN_SERVER}' using {protocol}.")
                    cls._connected = True
                    retry_count = 0  # Reset retry count on successful connection

                    # Authenticate with the RBN server
                    await asyncio.wait_for(reader.readuntil(b"call: "), timeout=10.0)
                    writer.write(f"{callsign}\r\n".encode("ascii"))
                    await writer.drain()
                    await asyncio.wait_for(reader.readuntil(b">\r\n\r\n"), timeout=10.0)

                    # Main data reading loop with connection health monitoring
                    while True:
                        try:
                            # Read data with timeout to detect stale connections
                            data = await asyncio.wait_for(reader.read(8192), timeout=600.0)  # 10 minute timeout
                            if not data:  # EOF received
                                print("RBN connection closed by server.")
                                break

                            yield data

                        except asyncio.TimeoutError:
                            print("No data received from RBN for 10 minutes. Connection may be stale.")
                            # Send a simple keepalive (empty line) to test connection
                            try:
                                writer.write(b"\r\n")
                                await asyncio.wait_for(writer.drain(), timeout=5.0)
                                print("Sent keepalive to RBN server.")
                                continue
                            except Exception:
                                print("Keepalive failed. Reconnecting...")
                                break

                    connection_succeeded = True

                except asyncio.TimeoutError:
                    # Silent failure for IPv6, log for IPv4
                    if protocol == "IPv4":
                        error_messages.append(f"Connection timeout ({protocol})")
                except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError) as e:
                    # Silent failure for IPv6, log for IPv4
                    if protocol == "IPv4":
                        error_messages.append(f"Connection error ({protocol}): {type(e).__name__}")
                except asyncio.CancelledError:
                    raise  # Ensure proper cancellation handling
                except Exception as e:
                    # Silent failure for IPv6, log for IPv4
                    if protocol == "IPv4":
                        error_messages.append(f"Unexpected error ({protocol}): {e}")
                finally:
                    # Cleanup connections properly
                    cls._connected = False
                    if writer is not None:
                        writer.close()
                        try:
                            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
                        except (asyncio.TimeoutError, Exception):
                            pass

                if connection_succeeded:  # If connection worked, stop trying other IPs
                    break

            if not connection_succeeded:
                retry_count += 1
                backoff_time = min(5 * (2 ** min(retry_count - 1, 4)), 60)  # Exponential backoff, max 60s

                # Show specific error messages, or generic message if no IPv4 errors
                if error_messages:
                    error_detail = "; ".join(error_messages)
                    protocols_tried = " and ".join(attempted_protocols)
                    print(f"Connection to {RBN_SERVER} failed over {protocols_tried}. {error_detail}. Retrying in {backoff_time} seconds...")
                else:
                    # Only IPv6 was attempted and failed silently, or no specific errors
                    protocols_tried = " and ".join(attempted_protocols)
                    print(f"Connection to {RBN_SERVER} failed over {protocols_tried}. Retrying in {backoff_time} seconds...")

                await asyncio.sleep(backoff_time)

    @classmethod
    async def write_dots_task(cls) -> NoReturn:
        while True:
            await asyncio.sleep(cConfig.PROGRESS_DOTS.DISPLAY_SECONDS)

            if cls._connected:
                global _progress_dot_count
                print('.', end='', flush=True)
                _progress_dot_count += 1

                if _progress_dot_count % cConfig.PROGRESS_DOTS.DOTS_PER_LINE == 0:
                    print('', flush=True)

    @classmethod
    def dot_count_reset(cls) -> None:
        global _progress_dot_count
        _progress_dot_count = 0

async def get_version_async() -> str:
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

async def main_loop() -> None:
    global config, Spotters

    print(f'SKCC Skimmer version {await get_version_async()}\n')

    # New implementation using asyncio:
    if platform.system() == "Windows":
        # Add a task to the event loop to watch for keyboard interrupts
        asyncio.create_task(cUtil.watch_for_ctrl_c_async())
    else:
        # Unix-like systems can use signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, cUtil.handle_shutdown)

    ArgV = sys.argv[1:]

    config = await cConfig.init(ArgV)

    await cSKCC.block_during_update_window_async()

    if cConfig.VERBOSE:
        cConfig.PROGRESS_DOTS.ENABLED = False

    await cUtil.file_check_async(cConfig.ADI_FILE)

    # Initialize SKCC data with parallel downloads
    await cSKCC.initialize_async()

    if cConfig.MY_CALLSIGN not in cSKCC.members:
        print(f"'{cConfig.MY_CALLSIGN}' is not a member of SKCC.")
        sys.exit()

    # Initialize QSO data
    await cQSO.initialize_async()
    await cQSO.get_goal_qsos_async()
    cQSO.print_progress()

    print('')
    cQSO.awards_check()

    # Handle interactive mode if enabled
    if cConfig.INTERACTIVE:
        print('\nInteractive mode. Enter callsigns or "q" to quit, "r" to refresh.\n')

        while True:
            print('> ', end='', flush=True)

            try:
                match sys.stdin.readline().strip().lower():
                    case 'q' | 'quit':
                        print("\nExiting by user request...")
                        return
                    case 'r' | 'refresh':
                        await cQSO.refresh_async()
                    case '':
                        continue
                    case cmd:
                        print('')
                        await cSKCC.lookups_async(cmd)
            except KeyboardInterrupt:
                os._exit(0)

    # Get nearby spotters
    await cSpotters.get_spotters_async()

    nearby_list_with_distance = cSpotters.get_nearby_spotters()
    formatted_nearby_list_with_distance = list(f'{Spotter}({cUtil.format_distance(Miles)})' for Spotter, Miles in nearby_list_with_distance)
    cConfig.SPOTTERS_NEARBY = {Spotter for Spotter, _ in nearby_list_with_distance}

    print(f'  Found {len(formatted_nearby_list_with_distance)} nearby spotters:')

    wrapped_spotter_lines = textwrap.wrap(', '.join(formatted_nearby_list_with_distance), width=80)

    for spotter_line in wrapped_spotter_lines:
        print(f'    {spotter_line}')

    # Clear log file if needed
    if cConfig.LOG_FILE.DELETE_ON_STARTUP:
        Filename = cConfig.LOG_FILE.FILE_NAME
        if Filename is not None and await aiofiles.os.path.exists(Filename):
            os.remove(Filename)

    print()
    print('Running...')
    print()

    try:
        # Create tasks for concurrent execution
        tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(cQSO.watch_logfile_task()),
            asyncio.create_task(cSPOTS.handle_spots_task()),
        ]

        if cConfig.PROGRESS_DOTS.ENABLED:
            tasks.append(asyncio.create_task(cRBN.write_dots_task()))
        if cConfig.SKED.ENABLED:
            tasks.append(asyncio.create_task(cSked.sked_page_scraper_task_async()))

        # Run all tasks concurrently
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        return
    except Exception:
        return

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Clean exit on Ctrl+C - no traceback
        try:
            print("\n\nExiting...")
            sys.stdout.flush()
        except:
            pass
        os._exit(0)
    except SystemExit:
        # Allow normal sys.exit() calls to proceed
        raise
    except Exception as e:
        # Show unexpected errors but exit cleanly
        try:
            print(f"\nUnexpected error: {e}")
            sys.stdout.flush()
        except:
            pass
        os._exit(1)
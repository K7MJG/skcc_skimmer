# SKCC Skimmer

SKCC Skimmer connects to the Reverse Beacon Network (RBN) to help you find SKCC stations you haven't worked yet for various award levels.

## Prerequisites

### Windows Executable Version
- No prerequisites - just extract and run!

### Source Code Version
1. **Python 3.11 or higher** (will be installed automatically if missing)
2. **uv** - Modern Python package manager
   - Windows: Download from https://github.com/astral-sh/uv
   - Linux/Mac: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Quick Start

### Step 1: Configure

Edit the `skcc_skimmer.cfg` configuration file and replace these
parameters with your own information:

```
MY_CALLSIGN =  'x6xxx'
ADI_FILE    = r'MasterLog.adi'
GOALS       =  'all'
TARGETS     =  'C,T,S'
```

`MY_CALLSIGN`: Replace `x6xxx` with your callsign. (Leave the
quotes -- they are important.)

`ADI_FILE`: Replace 'MasterLog.adi' with a log file in ADI format.
It should be your complete master ADI file that contains all SKCC
contacts that you've ever made. It can include non SKCC members, which
will be ignored.  The small 'r' before the string is important
and should not be removed.


`GOALS`: Replace 'all' with one or more of the following, space
or comma separated (but not both). When in doubt, leave it as 'all'.

```
C     - You are working toward your C (intelligently handles both initial C and multipliers).
T     - You are working toward your T (intelligently handles both initial T and multipliers).
S     - You are working toward your S (intelligently handles both initial S and multipliers).
CXn   - (DEPRECATED) Use 'C' instead - handles both initial and advanced awards.
TXn   - (DEPRECATED) Use 'T' instead - handles both initial and advanced awards.
SXn   - (DEPRECATED) Use 'S' instead - handles both initial and advanced awards.
WAS   - You are working toward your Worked All States.
WAS-C - You are working toward your Worked All States, Centurion.
WAS-T - You are working toward your Worked All States, Tribune.
WAS-S - You are working toward your Worked All States, Senator.
P     - You are attempting to accumulate prefix points.
DXC   - You are working toward DX Countries award.
DXQ   - You are working toward DX Member QSOs award.
QRP   - You are working toward QRP awards (1xQRP and 2xQRP).
all   - All of the above.
none  - None of the above.

GOALS Examples:
   GOALS = 'T'
   GOALS = 'T,S,P'
   GOALS = 'T,S,P,WAS,WAS-C'
   GOALS = 'C,P,DXC,QRP'
   GOALS = 'ALL'
   GOALS = 'ALL,-BRAG'          # All awards except BRAG
   GOALS = 'ALL,-BRAG,-K3Y'     # All awards except BRAG and K3Y

Note: Negation (using minus sign) only works with 'ALL'.
Examples like 'C,T,-BRAG' are invalid.
```

`TARGETS`: Replace 'C,T,S' with your preferences. When in doubt, just use the default value of 'C,T,S'.

```
C     - You are helping others achieve their C (intelligently handles both initial and advanced).
T     - You are helping others achieve their T (intelligently handles both initial and advanced).
S     - You are helping others achieve their S (intelligently handles both initial and advanced).
CXn   - (DEPRECATED) Use 'C' instead - handles both initial and advanced awards.
TXn   - (DEPRECATED) Use 'T' instead - handles both initial and advanced awards.
SXn   - (DEPRECATED) Use 'S' instead - handles both initial and advanced awards.
ALL   - All of the above.
NONE  - None of the above

TARGETS Examples:
   TARGETS = 'T,C'
   TARGETS = 'C,T,S'
   TARGETS = 'all'
   TARGETS = 'ALL'
   TARGETS = 'None'
```

### Step 2: Run

Once you've changed these configuration parameters, you
can run skcc_skimmer:

#### Windows Executable Version
Double-click `skcc_skimmer.exe`

#### Windows Source Code Version
Double-click `run.bat` or open a command prompt and type:
```
run.bat
```

#### Linux/Mac Source Code Version
Open a terminal and type:
```
./run
```

The first time you run the source code version, it will:
1. Check if Python 3.11+ is installed (install if needed)
2. Create a virtual environment
3. Install dependencies
4. Start SKCC Skimmer

## Command Line Options

You can override configuration file settings with command line options:

```
run.bat [options]  # Windows
./run [options]    # Linux/Mac

Options:
  -c, --callsign CALL     Your amateur radio callsign
  -a, --adi FILE          ADI log file path
  -g, --goals GOALS       Awards you're working toward
  -t, --targets TARGETS   Awards you're helping others achieve
  -m, --maidenhead GRID   Your grid square location
  -i, --interactive       Enable interactive mode
  -v, --verbose           Enable verbose mode
```

## Interactive Commands

While running, press:
- `c` - Display worked member counts
- `g` - Display goal progress
- `l` - List recent spots
- `f` - List spots nearby (requires maidenhead grid)
- `q` - Quit

## More Information

Visit the SKCC Skimmer web page for the most up-to-date info:

https://k7mjg.com/pages/SKCC_Skimmer/


73,
Mark
K7MJG

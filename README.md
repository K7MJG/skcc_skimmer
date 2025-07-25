## Quick Start

Edit the skcc_skimmer.cfg configuration file and replace these
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

Once you've changed these three configuration parameters, you
can run skcc_skimmer:

On Windows:
  `run skcc_skimmer.py`

On Linux:
  `./run skcc_skimmer.py`

Visit the SKCC Skimmer web page for the most up-to-date info:

https://www.k7mjg.com/SKCC_Skimmer


73,<br>
Mark<br>
K7MJG<br>

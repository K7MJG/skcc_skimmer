## Quick Start
***

Edit the skcc_skimmer.cfg configuration file and replace these
parameters with your own information:

```
MY_CALLSIGN =  'x6xxx'
ADI_FILE    = r'MasterLog.adi'
GOALS       =  'all'
TARGETS     =  'c,TXn,SXn'
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
C     - You are working toward your C.
T     - You are working toward your T.
S     - You are working toward your S.
CXn   - You are working toward your an advanced Cx- awards.
TXn   - You are working toward your an advanced Tx- awards.
SXn   - You are working toward your an advanced Sx- awards.
WAS   - You are working toward your Worked All States.
WAS-C - You are working toward your Worked All States, Centurion.
WAS-T - You are working toward your Worked All States, Tribune.
WAS-S - You are working toward your Worked All States, Senator.
P     - You are attempting to accumulate prefix points.
all   - All of the above.
none  - None of the above.

GOALS Examples:
   GOALS = 'txn'
   GOALS = 'txn,sxn,p'
   GOALS = 'txn,sxn,p,was,was-c'
   GOALS = 'C,P'
   GOALS = 'all'
```

`TARGETS`: Replace 'C,TXn,SXn' with your preferences. When in doubt,
         use the default value of 'c,TXn,SXn'.

```
C     - You are helping others achieve their C.
T     - You are helping others achieve their T.
S     - You are helping others achieve their S.
CXn   - You are helping others achieve their advanced Cx- awards.
TXn   - You are helping others achieve their advanced Tx- awards.
SXn   - You are helping others achieve their advanced Sx- awards.
all   - All of the above.
none  - None of the above

TARGETS Examples:
   TARGETS = 'TXn,CXn'
   TARGETS = 'all'
   TARGETS = 'ALL'
   TARGETS = 'None'
```

Once you've changed these three configuration parameters, you
can run skcc_skimmer:

  `python skcc_skimmer.py`

Visit the SKCC Skimmer web page for the most up-to-date info:

https://www.k7mjg.com/SKCC_Skimmer


73,<br>
Mark<br>
K7MJG<br>

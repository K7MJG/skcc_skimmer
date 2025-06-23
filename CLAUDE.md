# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SKCC Skimmer is a Python application that uses the Reverse Beacon Network (RBN) to locate unique, unworked SKCC (Straight Key Century Club) members for ham radio operators working toward SKCC awards. The application connects to telnet.reversebeacon.net:7000 and filters spots based on user-defined goals and targets.

## Development Environment Setup

### Virtual Environment Setup
Use one of these scripts to set up the development environment:

**Linux/macOS:**
```bash
./venv_setup.sh
```

**Windows:**
```batch
venv_setup.bat
```

**Cross-platform Python:**
```bash
python venv_setup.py [--force]
```

All scripts create a `.venv` directory, install dependencies from requirements.txt, and provide activation instructions.

### Dependencies
- Python 3.13+ required
- Key dependencies: aiohttp, aiofiles, requests
- All dependencies listed in requirements.txt

## Running the Application

### Basic Usage
```bash
python skcc_skimmer.py
```

### Command Line Options
```bash
python skcc_skimmer.py [options]
  -c, --callsign <callsign>     Your amateur radio callsign
  -a, --adi <file>              ADI log file path
  -g, --goals <goals>           Goals: C,T,S,CXN,TXN,SXN,WAS,WAS-C,WAS-T,WAS-S,P,BRAG,K3Y,ALL,NONE
  -t, --targets <targets>       Targets: C,T,S,CXN,TXN,SXN,ALL,NONE
  -b, --bands <bands>           Comma-separated bands: 160,80,60,40,30,20,17,15,12,10,6
  -m, --maidenhead <grid>       4 or 6 character grid square
  -r, --radius <miles>          Spotter radius in miles
  -v, --verbose                 Enable verbose mode
  -i, --interactive             Enable interactive mode
  -l, --logfile <file>          Log file name
  -n, --notification <on|off>   Enable notifications
  -s, --sked <on|off>           Enable SKCC Sked monitoring
```

## Configuration

### Primary Configuration File: skcc_skimmer.cfg
Must be configured before first run with these required parameters:
- `MY_CALLSIGN`: Your amateur radio callsign
- `MY_GRIDSQUARE`: Your grid square (4 or 6 characters)
- `ADI_FILE`: Path to your ADI log file (raw string with 'r' prefix)
- `GOALS`: Awards you're working toward
- `TARGETS`: Awards you're helping others achieve
- `SPOTTER_RADIUS`: Maximum distance from your location for spotters (miles)

### Configuration Sections
- `BANDS`: Which amateur radio bands to monitor
- `PROGRESS_DOTS`: Progress indicator settings
- `SKED`: SKCC Sked page monitoring
- `LOG_FILE`: Spot logging configuration
- `HIGH_WPM`: High speed CW handling
- `OFF_FREQUENCY`: Off-frequency spot handling
- `NOTIFICATION`: Audio notification settings

## Architecture

### Core Components
- **Configuration Management**: Class-based config system with command-line override support
- **RBN Connection**: Async telnet connection to Reverse Beacon Network
- **ADI Log Processing**: Parses Amateur Data Interchange format log files
- **SKCC Database**: Maintains member database and award tracking
- **Spot Filtering**: Filters RBN spots based on goals, targets, and worked status
- **Real-time Processing**: Async event loop for concurrent RBN monitoring and log file watching

### Key Files
- `skcc_skimmer.py`: Main application (single large file ~34k tokens)
- `skcc_skimmer.cfg`: Configuration file (Python syntax)
- `GenerateVersionStamp.py`: Version management utility
- `cVersion.py`: Version information
- `QSOs/`: Directory containing sample QSO data files

### Data Flow
1. Loads configuration from skcc_skimmer.cfg and command-line args
2. Parses ADI log file to determine worked stations
3. Downloads SKCC member database
4. Connects to RBN via telnet
5. Filters incoming spots against worked log and goals/targets
6. Displays relevant spots with award progress information

## Development Notes

### No Test Framework
This project does not include automated tests. Manual testing is done by running the application with various configurations.

### Single File Architecture
The main application logic resides in a single large Python file (skcc_skimmer.py) rather than being modularized. When making changes, be aware that classes and functions may have dependencies throughout the file.

### Async Architecture
The application uses asyncio extensively for concurrent operations:
- RBN telnet connection monitoring
- ADI log file watching for changes
- SKCC Sked page monitoring
- HTTP requests for member data

### Configuration Validation
The application performs extensive configuration validation on startup and will exit with descriptive error messages for invalid configurations.
#!/bin/bash
# Build script for SKCC Skimmer Go version

set -e

echo "Building SKCC Skimmer Go version..."

# Build for current platform
go build -o skcc_skimmer skcc_skimmer.go

echo "Build complete: ./skcc_skimmer"
echo ""
echo "Usage:"
echo "  Awards only:    ./skcc_skimmer -c CALLSIGN -a logfile.adi -g ALL -m GRID --awards-only"
echo "  Interactive:    ./skcc_skimmer -c CALLSIGN -a logfile.adi -g ALL -m GRID -i"
echo ""

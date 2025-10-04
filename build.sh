#!/bin/bash
#
# Build SKCC Skimmer for all platforms
#

set -e

VERSION="9.0.0"
BUILD_DIR="releases/${VERSION}"

echo "Building SKCC Skimmer v${VERSION}"
echo "================================"
echo ""

# Create build directory
mkdir -p "${BUILD_DIR}"

# Build for Windows (64-bit)
echo "Building for Windows (amd64)..."
GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o "${BUILD_DIR}/skcc_skimmer.exe" skcc_skimmer.go
echo "  ✓ Windows build complete: ${BUILD_DIR}/skcc_skimmer.exe"

# Build for Linux (64-bit)
echo "Building for Linux (amd64)..."
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o "${BUILD_DIR}/skcc_skimmer_linux" skcc_skimmer.go
echo "  ✓ Linux build complete: ${BUILD_DIR}/skcc_skimmer_linux"

# Build for macOS (Intel)
echo "Building for macOS (amd64)..."
GOOS=darwin GOARCH=amd64 go build -ldflags="-s -w" -o "${BUILD_DIR}/skcc_skimmer_macos_intel" skcc_skimmer.go
echo "  ✓ macOS Intel build complete: ${BUILD_DIR}/skcc_skimmer_macos_intel"

# Build for macOS (Apple Silicon)
echo "Building for macOS (arm64)..."
GOOS=darwin GOARCH=arm64 go build -ldflags="-s -w" -o "${BUILD_DIR}/skcc_skimmer_macos_arm64" skcc_skimmer.go
echo "  ✓ macOS ARM64 build complete: ${BUILD_DIR}/skcc_skimmer_macos_arm64"

# Build for Linux ARM (Raspberry Pi)
echo "Building for Linux ARM (arm64)..."
GOOS=linux GOARCH=arm64 go build -ldflags="-s -w" -o "${BUILD_DIR}/skcc_skimmer_linux_arm64" skcc_skimmer.go
echo "  ✓ Linux ARM64 build complete: ${BUILD_DIR}/skcc_skimmer_linux_arm64"

echo ""
echo "All builds complete!"
echo ""
echo "Binaries created in: ${BUILD_DIR}/"
ls -lh "${BUILD_DIR}/"

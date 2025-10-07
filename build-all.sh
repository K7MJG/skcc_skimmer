#!/bin/bash
# Cross-platform build script for SKCC Skimmer Go version

set -e

VERSION=${1:-"9.0.0"}
OUTPUT_DIR="builds"

echo "Building SKCC Skimmer Go version ${VERSION} for all platforms..."
echo ""

# Clean and create output directory
rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

# Build for each platform
PLATFORMS=(
    "linux/amd64"
    "linux/arm64"
    "darwin/amd64"
    "darwin/arm64"
    "windows/amd64"
    "windows/arm64"
)

for platform in "${PLATFORMS[@]}"; do
    GOOS=${platform%/*}
    GOARCH=${platform#*/}

    OUTPUT_NAME="skcc_skimmer-${VERSION}-${GOOS}-${GOARCH}"
    if [ "$GOOS" = "windows" ]; then
        OUTPUT_NAME="${OUTPUT_NAME}.exe"
    fi

    echo "Building for ${GOOS}/${GOARCH}..."
    GOOS=$GOOS GOARCH=$GOARCH go build -o "${OUTPUT_DIR}/${OUTPUT_NAME}" skcc_skimmer.go

    if [ $? -eq 0 ]; then
        echo "  ✓ ${OUTPUT_NAME}"
    else
        echo "  ✗ Failed to build for ${GOOS}/${GOARCH}"
    fi
done

echo ""
echo "Build complete! Executables in ./${OUTPUT_DIR}/"
echo ""
ls -lh "${OUTPUT_DIR}/"

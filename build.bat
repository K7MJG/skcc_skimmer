@echo off
REM Build SKCC Skimmer for all platforms (Windows batch version)

setlocal

set VERSION=9.0.0
set BUILD_DIR=releases\%VERSION%

echo Building SKCC Skimmer v%VERSION%
echo ================================
echo.

REM Create build directory
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

REM Build for Windows (64-bit)
echo Building for Windows (amd64)...
set GOOS=windows
set GOARCH=amd64
go build -ldflags="-s -w" -o "%BUILD_DIR%\skcc_skimmer.exe" skcc_skimmer.go
echo   [OK] Windows build complete: %BUILD_DIR%\skcc_skimmer.exe

REM Build for Linux (64-bit)
echo Building for Linux (amd64)...
set GOOS=linux
set GOARCH=amd64
go build -ldflags="-s -w" -o "%BUILD_DIR%\skcc_skimmer_linux" skcc_skimmer.go
echo   [OK] Linux build complete: %BUILD_DIR%\skcc_skimmer_linux

REM Build for macOS (Intel)
echo Building for macOS (amd64)...
set GOOS=darwin
set GOARCH=amd64
go build -ldflags="-s -w" -o "%BUILD_DIR%\skcc_skimmer_macos_intel" skcc_skimmer.go
echo   [OK] macOS Intel build complete: %BUILD_DIR%\skcc_skimmer_macos_intel

REM Build for macOS (Apple Silicon)
echo Building for macOS (arm64)...
set GOOS=darwin
set GOARCH=arm64
go build -ldflags="-s -w" -o "%BUILD_DIR%\skcc_skimmer_macos_arm64" skcc_skimmer.go
echo   [OK] macOS ARM64 build complete: %BUILD_DIR%\skcc_skimmer_macos_arm64

REM Build for Linux ARM (Raspberry Pi)
echo Building for Linux ARM (arm64)...
set GOOS=linux
set GOARCH=arm64
go build -ldflags="-s -w" -o "%BUILD_DIR%\skcc_skimmer_linux_arm64" skcc_skimmer.go
echo   [OK] Linux ARM64 build complete: %BUILD_DIR%\skcc_skimmer_linux_arm64

echo.
echo All builds complete!
echo.
echo Binaries created in: %BUILD_DIR%\
dir "%BUILD_DIR%"

endlocal

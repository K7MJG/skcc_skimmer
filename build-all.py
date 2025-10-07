#!/usr/bin/env python3
"""
Cross-platform build script for SKCC Skimmer Go version
Builds for all supported platforms concurrently
"""

import asyncio
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from build import get_version_from_git, substitute_version


PLATFORMS = [
    ("linux", "amd64"),
    ("linux", "arm64"),
    ("darwin", "amd64"),
    ("darwin", "arm64"),
    ("windows", "amd64"),
    ("windows", "arm64"),
]


async def build_for_platform(goos: str, goarch: str, temp_source: Path, output_dir: Path) -> tuple[str, bool, str]:
    """Build for a specific platform. Returns (platform_name, success, message)"""
    platform_name = f"{goos}/{goarch}"
    output_name = f"skcc_skimmer-{goos}-{goarch}"

    if goos == "windows":
        output_name += ".exe"

    output_path = output_dir / output_name

    try:
        # Build with environment variables for cross-compilation
        env = os.environ.copy()
        env['GOOS'] = goos
        env['GOARCH'] = goarch

        proc = await asyncio.create_subprocess_exec(
            'go', 'build', '-o', str(output_path), str(temp_source),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            return platform_name, True, output_name
        else:
            error_msg = stderr.decode().strip() or stdout.decode().strip()
            return platform_name, False, error_msg
    except Exception as e:
        return platform_name, False, str(e)


async def build_all_platforms() -> None:
    """Build for all supported platforms"""
    source_file = Path("skcc_skimmer.go")

    if not source_file.exists():
        print(f"Error: {source_file} not found")
        return

    # Get version from git
    version = await get_version_from_git()

    # Create output directory with version in name
    output_dir = Path(f"skcc_skimmer_{version}")

    print(f"Building SKCC Skimmer Go version {version} for all platforms...")
    print()

    # Clean and create output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir()

    # Read and modify source code
    source_code = source_file.read_text()
    modified_code = substitute_version(source_code, version)

    # Write modified source temporarily
    temp_source = Path("skcc_skimmer_temp.go")
    temp_source.write_text(modified_code)

    try:
        # Build all platforms concurrently
        tasks = [
            build_for_platform(goos, goarch, temp_source, output_dir)
            for goos, goarch in PLATFORMS
        ]

        results = await asyncio.gather(*tasks)

        # Display build results
        build_failed = False
        for platform_name, success, message in results:
            if success:
                print(f"Building for {platform_name}...")
                print(f"  ✓ {message}")
            else:
                print(f"Building for {platform_name}...")
                print(f"  ✗ Failed: {message}")
                build_failed = True

        if build_failed:
            print()
            print("Some builds failed. Skipping archive creation.")
            return

        print()
        print(f"Build complete! Executables in ./{output_dir}/")
        print()

        # List the output files
        files = sorted(output_dir.iterdir())
        for file in files:
            size = file.stat().st_size
            size_mb = size / (1024 * 1024)
            print(f"  {file.name:50} {size_mb:6.2f} MB")

        print()
        print("Creating archives...")

        # Create zip archive
        zip_name = f"{output_dir}.zip"
        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                zipf.write(file, f"{output_dir.name}/{file.name}")
        zip_size = Path(zip_name).stat().st_size / (1024 * 1024)
        print(f"  ✓ {zip_name} ({zip_size:.2f} MB)")

        # Create tar.gz archive
        tar_name = f"{output_dir}.tar.gz"
        with tarfile.open(tar_name, 'w:gz') as tarf:
            for file in files:
                tarf.add(file, arcname=f"{output_dir.name}/{file.name}")
        tar_size = Path(tar_name).stat().st_size / (1024 * 1024)
        print(f"  ✓ {tar_name} ({tar_size:.2f} MB)")

        print()
        print("Archives created successfully!")

    finally:
        # Clean up temporary source file
        temp_source.unlink(missing_ok=True)


async def main() -> None:
    """Main entry point"""
    await build_all_platforms()


if __name__ == "__main__":
    asyncio.run(main())

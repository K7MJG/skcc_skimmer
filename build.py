#!/usr/bin/env python3
"""
Build script for SKCC Skimmer Go version
Automatically detects version from Git and embeds it in the binary
"""

import asyncio
import re
import subprocess
import tempfile
from pathlib import Path


async def run_git_command(*args: str) -> tuple[bool, str]:
    """Run a git command and return (success, output)"""
    try:
        proc = await asyncio.create_subprocess_exec(
            'git', *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return proc.returncode == 0, stdout.decode().strip()
    except Exception:
        return False, ""


async def is_worktree_dirty() -> bool:
    """Check if the git worktree has uncommitted changes"""
    success, output = await run_git_command('status', '--porcelain')
    return success and bool(output)


async def get_version_from_git() -> str:
    """
    Detect version from Git:
    - If HEAD has an annotated tag, use that
    - Otherwise, use 7-character abbreviated SHA
    - Append '-' if worktree is dirty
    """
    # Try to get annotated tag on HEAD
    success, tag = await run_git_command('describe', '--exact-match', '--tags', 'HEAD')

    if success and tag:
        version = tag
    else:
        # No tag, use abbreviated SHA
        success, sha = await run_git_command('rev-parse', '--short=7', 'HEAD')
        version = sha if success and sha else "unknown"

    # Check if worktree is dirty
    if await is_worktree_dirty():
        version += "-"

    return version


def substitute_version(source_code: str, version: str) -> str:
    """Replace 'const Version = "development"' with actual version"""
    pattern = r'const Version = "development"'
    replacement = f'const Version = "{version}"'
    return re.sub(pattern, replacement, source_code)


async def build_for_current_platform() -> bool:
    """Build skcc_skimmer for the current platform"""
    source_file = Path("skcc_skimmer.go")
    output_file = Path("skcc_skimmer")

    if not source_file.exists():
        print(f"Error: {source_file} not found")
        return False

    # Get version from git
    version = await get_version_from_git()
    print(f"Building SKCC Skimmer Go version {version}...")

    # Read source code
    source_code = source_file.read_text()

    # Substitute version
    modified_code = substitute_version(source_code, version)

    # Write to temporary file and build
    with tempfile.NamedTemporaryFile(mode='w', suffix='.go', delete=False) as tmp:
        tmp.write(modified_code)
        tmp_path = tmp.name

    try:
        # Build using the temporary file
        proc = await asyncio.create_subprocess_exec(
            'go', 'build', '-o', str(output_file), tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode == 0:
            print(f"Build complete: ./{output_file}")
            print()
            print("Usage:")
            print("  Awards only:    ./skcc_skimmer -c CALLSIGN -a logfile.adi -g ALL -m GRID --awards-only")
            print("  Interactive:    ./skcc_skimmer -c CALLSIGN -a logfile.adi -g ALL -m GRID -i")
            print()
            return True
        else:
            print(f"Build failed:")
            print(stderr.decode())
            return False
    finally:
        # Clean up temporary file
        Path(tmp_path).unlink(missing_ok=True)


async def main() -> None:
    """Main entry point"""
    success = await build_for_current_platform()
    exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())

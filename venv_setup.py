#!/usr/bin/env python3

import asyncio
import platform
import shutil
import sys
import venv
from pathlib import Path

ROOT: Path = Path(__file__).parent.resolve()
VENV_DIR: Path = ROOT / ".venv"
REQUIREMENTS: Path = ROOT / "requirements.txt"
FORCE: bool = "--force" in sys.argv

def get_venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"

def ensure_venv_exists() -> None:
    if FORCE and VENV_DIR.exists():
        print("Removing existing virtual environment")
        shutil.rmtree(VENV_DIR)

    if not VENV_DIR.exists() or not get_venv_python().exists():
        print("Bootstrapping Python project...")
        print("Creating virtual environment at", VENV_DIR)
        venv.create(str(VENV_DIR), with_pip=True)
    else:
        print("Virtual environment already exists at", VENV_DIR)

async def run_async(cmd: list[str]) -> None:
    print("Running:", " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    stdout, _ = await proc.communicate()

    if stdout:
        print(stdout.decode("utf-8").strip())
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {proc.returncode}")

async def install_all_async() -> None:
    python: str = str(get_venv_python())

    await run_async([python, "-m", "pip", "install", "--upgrade", "pip"])

    if (ROOT / "pyproject.toml").exists() or (ROOT / "setup.py").exists():
        await run_async([python, "-m", "pip", "install", "-e", str(ROOT)])
    else:
        print("No pyproject.toml or setup.py found. Skipping editable install.")

    if REQUIREMENTS.exists():
        await run_async([python, "-m", "pip", "install", "--requirement", str(REQUIREMENTS)])

async def main_async() -> None:
    ensure_venv_exists()
    await install_all_async()
    print()
    print("Setup complete.")
    print("To activate the virtual environment:")

    if platform.system() == "Windows":
        print(r".venv\Scripts\activate")
    else:
        print("source .venv/bin/activate")

if __name__ == "__main__":
    asyncio.run(main_async())
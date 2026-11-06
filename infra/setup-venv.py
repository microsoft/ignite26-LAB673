"""Prepare the shared Python environment for lab setup and notebooks."""

import subprocess
import sys
from pathlib import Path


repo_root = Path(__file__).resolve().parents[1]
venv_dir = repo_root / ".venv"
venv_python = (
    venv_dir.joinpath("Scripts", "python.exe")
    if sys.platform == "win32" else venv_dir.joinpath("bin", "python")
)
if not venv_python.is_file():
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
subprocess.run(
    [
        str(venv_python), "-m", "pip", "install", "--disable-pip-version-check",
        "-r", str(repo_root / "src" / "notebooks" / "requirements.txt"),
    ],
    check=True,
)

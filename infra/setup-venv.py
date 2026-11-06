"""Prepare the shared Python environment for lab setup and notebooks."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    requirements = repo_root.joinpath("src", "notebooks", "requirements.txt")
    if not requirements.is_file():
        raise RuntimeError(f"Notebook requirements not found: {requirements}")
    venv_dir = repo_root / ".venv"
    venv_python = (
        venv_dir.joinpath("Scripts", "python.exe")
        if sys.platform == "win32" else venv_dir.joinpath("bin", "python")
    )
    if not venv_python.is_file():
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            cwd=repo_root,
        )
    subprocess.run(
        [
            str(venv_python), "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(requirements),
        ],
        check=True,
        cwd=repo_root,
    )
    print(f"Lab Python environment is ready: {venv_python}")


if __name__ == "__main__":
    main()

"""Create local config and optionally install project dependencies."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from devtools.environment import PROJECT_ROOT, SERVICES, service_python
from devtools.initialization import initialize


def install(root: Path) -> None:
    for name in SERVICES:
        directory = root / "services" / name
        executable = service_python(directory)
        if not executable.exists():
            venv.EnvBuilder(with_pip=True).create(directory / ".venv")
        subprocess.run([str(executable), "-m", "pip", "install", "-r", "requirements.txt"],
                       cwd=directory, check=True)
    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
    if not pnpm:
        raise RuntimeError("pnpm is not available")
    subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=root / "web", check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="create per-service .venv and install dependencies")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Run initialization with Python 3.12")
    try:
        for path, created in initialize(PROJECT_ROOT):
            print(f"{'CREATED' if created else 'PRESERVED'} {path.relative_to(PROJECT_ROOT)}")
        print("Secret values were not printed. Existing configuration was preserved.")
        if args.install:
            install(PROJECT_ROOT)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Initialization failed ({type(error).__name__}); check local configuration and dependencies.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run the leader's components with an explicit catalog integration mode."""
import argparse
import os
import subprocess
import sys
from devtools.environment import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["gateway", "ai-chat-service", "web"])
    parser.add_argument("--catalog-mode", choices=["internal", "market"], default="internal")
    args = parser.parse_args()
    environment = {**os.environ, "CAPABILITY_CATALOG_MODE": args.catalog_mode,
                   "PYTHONIOENCODING": "utf-8"}
    print(f"Catalog mode: {args.catalog_mode}; existing configuration files are preserved.", flush=True)
    try:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts/start_pro_local.py"), args.component],
            cwd=PROJECT_ROOT, env=environment, check=False,
        ).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

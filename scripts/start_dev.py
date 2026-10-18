"""Run a single development component in the current terminal."""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys

from devtools.environment import PROJECT_ROOT, SERVICES, component_environment, read_env, service_python


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["gateway", "web", "middleware", *SERVICES])
    args = parser.parse_args()
    root = PROJECT_ROOT
    environment = component_environment(root)
    name = args.component
    if name == "middleware":
        command, directory, port = ["docker", "compose", "up", "-d", "mysql", "nacos", "sentinel"], root / "deploy", None
    elif name == "gateway":
        if len(environment.get("JWT_SECRET", "").encode("utf-8")) < 32:
            parser.error("Initialize the shared .env with python scripts/init_dev.py first")
        command, directory, port = ["mvn", "spring-boot:run"], root / "gateway", int(environment.get("GATEWAY_PORT", "8080"))
    elif name == "web":
        directory = root / "web"
        values = {**read_env(directory / ".env"), **environment}
        command, port = ["pnpm", "dev", "--strictPort"], int(values.get("VITE_PORT", "5173"))
    else:
        directory = root / "services" / name
        executable = service_python(directory)
        if not executable.exists():
            parser.error("Install service environments with python scripts/init_dev.py --install")
        values = {**read_env(directory / ".env"), **environment}
        port = int(values.get("SERVICE_PORT", str(SERVICES[name][1])))
        command = [str(executable), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    if port:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                parser.error(f"Port {port} is occupied; existing processes were preserved")
    resolved = shutil.which(command[0] + ".cmd") or shutil.which(command[0])
    if not resolved:
        parser.error(f"Missing executable for {name}")
    command[0] = resolved
    print(f"Starting {name} in {directory}; Ctrl+C stops this process.")
    try:
        return subprocess.run(command, cwd=directory, env=environment, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

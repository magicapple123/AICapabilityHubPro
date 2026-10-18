"""Start Pro on separate middleware ports while preserving existing .env files."""

from __future__ import annotations

import argparse
import subprocess
import sys
from urllib.parse import quote

from devtools.environment import PROJECT_ROOT, SERVICES, component_environment, read_env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["middleware", "gateway", "web", *SERVICES])
    args = parser.parse_args()
    root = PROJECT_ROOT
    shared = read_env(root / ".env")
    deploy = read_env(root / "deploy" / ".env")
    user = read_env(root / "services" / "user-service" / ".env")
    password = shared.get("MYSQL_ROOT_PASSWORD", "")
    jwt_secret = shared.get("JWT_SECRET", "")
    if not password or len(jwt_secret.encode("utf-8")) < 32:
        parser.error("Run python scripts/init_dev.py first; existing files are preserved")
    if password != deploy.get("MYSQL_ROOT_PASSWORD"):
        parser.error("Shared/deploy database passwords differ; no files changed")
    if jwt_secret != user.get("JWT_SECRET"):
        parser.error("Shared/user JWT secrets differ; no files changed")

    environment = component_environment(root)
    environment.update(
        MYSQL_ROOT_PASSWORD=password,
        JWT_SECRET=jwt_secret,
        JWT_ISSUER=shared.get("JWT_ISSUER", "ai-capability-hub"),
        NACOS_ADDR="127.0.0.1:8849",
        SENTINEL_DASHBOARD="127.0.0.1:8859",
        PYTHONUNBUFFERED="1",
    )
    if args.component in SERVICES:
        database, _ = SERVICES[args.component]
        environment["DB_URL"] = (
            f"mysql+pymysql://root:{quote(password, safe='')}"
            f"@127.0.0.1:3307/{database}?charset=utf8mb4"
        )
    if args.component == "middleware":
        command = [
            "docker", "compose", "--env-file", str(root / "deploy" / ".env"),
            "-f", str(root / "deploy" / "docker-compose.yml"),
            "-f", str(root / "deploy" / "docker-compose.pro-local.yml"),
            "up", "-d", "--wait", "--wait-timeout", "120", "mysql", "nacos", "sentinel",
        ]
    else:
        command = [sys.executable, str(root / "scripts" / "start_dev.py"), args.component]
    print(f"Pro local profile: {args.component}; MySQL 3307, Nacos 8849, Sentinel 8859", flush=True)
    try:
        return subprocess.run(command, cwd=root, env=environment, check=False).returncode
    except FileNotFoundError:
        parser.error("Missing executable; check the Docker/Python installation")
    except KeyboardInterrupt:
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())

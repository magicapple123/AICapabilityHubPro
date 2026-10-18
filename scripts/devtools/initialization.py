"""Create missing local configuration consistently, with no overwrites."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote

from devtools.environment import SERVICES, read_env


def write_once(path: Path, content: str) -> bool:
    """Exclusive creation protects an existing file even in a concurrent run."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError:
        return False
    return True


def render_template(path: Path, replacements: dict[str, str]) -> str:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    found: set[str] = set()
    for index, line in enumerate(lines):
        key, separator, _ = line.partition("=")
        if separator and key.strip() in replacements:
            key = key.strip()
            lines[index] = f"{key}={replacements[key]}"
            found.add(key)
    lines.extend(f"{key}={value}" for key, value in replacements.items() if key not in found)
    return "\n".join(lines) + "\n"


def initialize(root: Path) -> list[tuple[Path, bool]]:
    shared_path = root / ".env"
    shared = read_env(shared_path)
    deploy = read_env(root / "deploy" / ".env")
    user = read_env(root / "services" / "user-service" / ".env")
    # Prefer already configured values; partial setups must not silently split
    # the gateway/user signing key or the database password.
    jwt_secret = shared.get("JWT_SECRET") or user.get("JWT_SECRET") or secrets.token_hex(32)
    password = shared.get("MYSQL_ROOT_PASSWORD") or deploy.get("MYSQL_ROOT_PASSWORD") or secrets.token_hex(24)
    if len(jwt_secret.encode("utf-8")) < 32:
        raise ValueError("Existing JWT_SECRET is shorter than 32 bytes; preserved unchanged")
    if user.get("JWT_SECRET", jwt_secret) != jwt_secret:
        raise ValueError("Existing user JWT_SECRET differs from shared config; no files changed")
    if deploy.get("MYSQL_ROOT_PASSWORD", password) != password:
        raise ValueError("Existing deploy password differs from shared config; no files changed")
    issuer = shared.get("JWT_ISSUER") or user.get("JWT_ISSUER") or "ai-capability-hub"
    shared_values = {
        "JWT_SECRET": jwt_secret,
        "JWT_ISSUER": issuer,
        "MYSQL_ROOT_PASSWORD": password,
    }
    if shared_path.exists() and any(not shared.get(key) for key in shared_values):
        raise ValueError("Shared .env is incomplete; preserved unchanged, complete its required keys first")
    plans = [(shared_path, "# Local values only. Never commit this file.\n" + "".join(
        f"{key}={value}\n" for key, value in shared_values.items()
    ))]
    plans.append((root / "deploy" / ".env", render_template(
        root / "deploy" / ".env.example", {"MYSQL_ROOT_PASSWORD": password}
    )))
    plans.append((root / "web" / ".env", render_template(
        root / "web" / ".env.example", {"VITE_USE_MOCK_LOGIN": "false"}
    )))
    for name, (database, _) in SERVICES.items():
        directory = root / "services" / name
        replacements = {
            "DB_URL": f"mysql+pymysql://root:{quote(password, safe='')}@127.0.0.1:3306/{database}?charset=utf8mb4",
        }
        if name == "user-service":
            replacements.update(JWT_SECRET=jwt_secret, JWT_ISSUER=issuer)
        plans.append((directory / ".env", render_template(directory / ".env.example", replacements)))
    return [(path, write_once(path, content)) for path, content in plans]

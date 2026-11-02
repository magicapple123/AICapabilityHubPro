"""Regenerate the MySQL first-boot baseline from the per-service SQL scripts.

`deploy/mysql/init/*.sql` is what the MySQL container executes on first boot
(docker compose and the leader E2E both load it). It is a *copy* of
`services/<service>/sql/*.sql`, concatenated in filename order, as the header
comment in each file states. Whenever a service adds a migration, the baseline
must be regenerated, otherwise a freshly created database is missing the new
columns/tables and the real services fail at runtime (for example
`Unknown column 'daily_points_limit' in 'field list'`).

Usage:
    python scripts/devtools/sync_mysql_baseline.py           # rewrite the files
    python scripts/devtools/sync_mysql_baseline.py --check   # exit 1 when stale

The script is idempotent: running it twice produces byte identical output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = PROJECT_ROOT / "deploy/mysql/init"

#: Baseline file stem -> service directory name owning the migrations.
BASELINE_SOURCES: dict[str, str] = {
    "02_user_service": "user-service",
    "03_capability_service": "capability-service",
    "04_billing_service": "billing-service",
    "05_ai_chat_service": "ai-chat-service",
}

HEADER = (
    "SET NAMES utf8mb4;\n"
    "-- 本文件由服务目录的 sql 脚本复制生成，供 MySQL 容器首次初始化时自动建表。\n"
    "-- 修改请以 services/<服务名>/sql/*.sql 为准，并同步本文件。\n"
)


def _body(script: Path) -> str:
    """Read one migration, normalising line endings and the charset preamble.

    Every script starts with ``SET NAMES utf8mb4;``; the baseline already sets it
    once at the top, so the duplicated preamble is dropped to keep the generated
    file close to the one that was hand-maintained before.

    Args:
        script: Absolute path of a service SQL migration.

    Returns:
        File content with LF endings, no leading ``SET NAMES`` and a final ``\\n``.
    """
    text = script.read_bytes().decode("utf-8").replace("\r\n", "\n")
    if text.startswith("SET NAMES utf8mb4;\n"):
        text = text[len("SET NAMES utf8mb4;\n"):]
    return text if text.endswith("\n") else text + "\n"


def render(service: str) -> str:
    """Return the full baseline text for ``service``.

    Args:
        service: Service directory name, e.g. ``user-service``.

    Returns:
        Header followed by every migration, each prefixed with a source marker.

    Raises:
        FileNotFoundError: When the service ships no SQL migration at all.
    """
    scripts = sorted((PROJECT_ROOT / "services" / service / "sql").glob("*.sql"))
    if not scripts:
        raise FileNotFoundError(f"no SQL scripts found for {service}")
    sections = [f"-- 来源: {script.relative_to(PROJECT_ROOT).as_posix()}\n{_body(script)}"
                for script in scripts]
    return HEADER + "\n" + "\n\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    """Regenerate or verify every baseline file.

    Args:
        argv: Command line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` on success (or when ``--check`` finds no drift), ``1`` on drift.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="only report stale baselines; never write")
    args = parser.parse_args(argv)

    stale: list[str] = []
    for stem, service in BASELINE_SOURCES.items():
        target = BASELINE_DIR / f"{stem}.sql"
        expected = render(service)
        current = target.read_bytes().decode("utf-8").replace("\r\n", "\n") if target.exists() else ""
        if current == expected:
            print(f"up to date: {target.relative_to(PROJECT_ROOT).as_posix()}", flush=True)
            continue
        stale.append(target.name)
        if args.check:
            print(f"STALE: {target.relative_to(PROJECT_ROOT).as_posix()}", flush=True)
            continue
        # Files in this directory use CRLF endings (they are edited on Windows).
        target.write_bytes(expected.replace("\n", "\r\n").encode("utf-8"))
        print(f"regenerated: {target.relative_to(PROJECT_ROOT).as_posix()}", flush=True)

    if args.check and stale:
        print("Run `python scripts/devtools/sync_mysql_baseline.py` to refresh: "
              + ", ".join(stale), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

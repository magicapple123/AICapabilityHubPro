"""校验 deploy/mysql/init 基线与各服务建表脚本的列是否一致。

背景（G2 实测踩过的坑）：`deploy/mysql/init/*.sql` 是空库首启时执行的基线，
而 `services/<svc>/sql/01_init.sql` 才是模型对应的"最新建表"。
只要有增量迁移（例如 `04_add_images.sql`）没同步回基线，空库起来就会缺列，
表现为调用直接 `4003 系统内部错误`，日志里是 `Unknown column ...`。
单服务 pytest 用的是模型建表或已有库，永远发现不了。

用法：
    python scripts/devtools/check_init_drift.py          # 有差异返回 1
    python scripts/devtools/check_init_drift.py --json   # 机器可读
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAIRS = {
    "user": (ROOT / "deploy/mysql/init/02_user_service.sql", ROOT / "services/user-service/sql/01_init.sql"),
    "capability": (
        ROOT / "deploy/mysql/init/03_capability_service.sql",
        ROOT / "services/capability-service/sql/01_init.sql",
    ),
    "billing": (
        ROOT / "deploy/mysql/init/04_billing_service.sql",
        ROOT / "services/billing-service/sql/01_init.sql",
    ),
    "ai_chat": (
        ROOT / "deploy/mysql/init/05_ai_chat_service.sql",
        ROOT / "services/ai-chat-service/sql/01_init.sql",
    ),
}

_TABLE = re.compile(r"CREATE TABLE(?: IF NOT EXISTS)?\s+`?(\w+)`?\s*\((.*?)\n\)\s*ENGINE", re.S | re.I)
_SKIP = ("PRIMARY", "UNIQUE", "KEY", "INDEX", "CONSTRAINT", "FOREIGN")
_COLUMN = re.compile(r"`?(\w+)`?\s+[A-Za-z]")


def parse_tables(path: Path) -> dict[str, set[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    tables: dict[str, set[str]] = {}
    for match in _TABLE.finditer(text):
        name, body = match.group(1), match.group(2)
        columns: set[str] = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith(_SKIP):
                continue
            column = _COLUMN.match(line)
            if column:
                columns.add(column.group(1))
        tables[name] = columns
    return tables


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    problems: list[dict[str, object]] = []
    for label, (init_path, service_path) in PAIRS.items():
        if not init_path.exists() or not service_path.exists():
            problems.append({"service": label, "kind": "missing_file", "detail": str(init_path if not init_path.exists() else service_path)})
            continue
        init_tables = parse_tables(init_path)
        service_tables = parse_tables(service_path)
        for table in sorted(set(service_tables) - set(init_tables)):
            problems.append({"service": label, "kind": "missing_table", "table": table})
        for table in sorted(set(init_tables) & set(service_tables)):
            missing = sorted(service_tables[table] - init_tables[table])
            if missing:
                problems.append({"service": label, "kind": "missing_column", "table": table, "columns": missing})
            extra = sorted(init_tables[table] - service_tables[table])
            if extra:
                problems.append({"service": label, "kind": "stale_column", "table": table, "columns": extra})

    if args.json:
        print(json.dumps({"passed": not problems, "problems": problems}, ensure_ascii=False, indent=2))
    elif problems:
        for item in problems:
            print("[DRIFT]", json.dumps(item, ensure_ascii=False))
    else:
        print("[OK] deploy/mysql/init 与四个服务的建表脚本列一致")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())

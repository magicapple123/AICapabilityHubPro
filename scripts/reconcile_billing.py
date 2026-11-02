"""账单与积分流水对账（B4）。

为什么是独立运维脚本而不是服务接口：
`billing_db` 与 `user_db` 物理隔离，服务层**禁止跨库查询**（contract_lint 会拒绝）。
对账天然要同时读两个库，因此放在运维脚本里，用独立连接、只读查询完成。

三类差异：
1. `billing_without_log`：有账单、无同 requestId 的积分流水（少扣/漏扣）；
2. `log_without_billing`：有积分流水、无同 requestId 的账单（多扣）；
3. `request_id_mismatch`：同一用户、同一金额、5 分钟内成对出现但 requestId 不同，
   典型是"账单用了 requestId A、流水用了 requestId B"的错配。

幂等：差异项按 `kind:request_id` 记进状态文件，只有首次出现才算"新增告警"；
连续跑两次，第二次 `new=0`，不会重复告警。

用法：
    <python with pymysql> scripts/reconcile_billing.py \
        --billing-url "mysql+pymysql://.../billing_db" \
        --user-url "mysql+pymysql://.../user_db" \
        --days 7 [--state artifacts/reconcile/state.json] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

# 金额配对的时间窗：同一次调用的账单与流水通常在同一秒内，5 分钟足够容忍时钟漂移。
PAIR_WINDOW = timedelta(minutes=5)

KIND_BILLING_WITHOUT_LOG = "billing_without_log"
KIND_LOG_WITHOUT_BILLING = "log_without_billing"
KIND_REQUEST_ID_MISMATCH = "request_id_mismatch"


@dataclass(frozen=True)
class Discrepancy:
    kind: str
    request_id: str
    user_id: int
    billing_cost: int | None = None
    log_amount: int | None = None
    detail: str = ""
    occurred_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.request_id}"


def _billing_rows(engine, since: datetime, until: datetime) -> list[dict[str, Any]]:
    statement = text(
        """
        SELECT request_id, user_id, cost, call_status, create_time
        FROM t_call_record
        WHERE is_deleted = 0 AND create_time >= :since AND create_time < :until
        """
    )
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(
            statement, {"since": since, "until": until}
        )]


def _points_rows(engine, since: datetime, until: datetime) -> list[dict[str, Any]]:
    statement = text(
        """
        SELECT request_id, user_id, amount, biz_type, create_time
        FROM t_points_log
        WHERE is_deleted = 0 AND biz_type = 'call'
          AND create_time >= :since AND create_time < :until
        """
    )
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(
            statement, {"since": since, "until": until}
        )]


def find_discrepancies(
    billing_engine, user_engine, *, since: datetime, until: datetime
) -> tuple[list[Discrepancy], dict[str, int]]:
    """返回 (差异列表, 扫描计数)。不做任何写操作。"""

    bills = _billing_rows(billing_engine, since, until)
    # 流水窗口左右各放宽一个配对窗，避免边界上的"成对但被切断"。
    logs = _points_rows(user_engine, since - PAIR_WINDOW, until + PAIR_WINDOW)

    bill_by_request = {row["request_id"]: row for row in bills}
    log_by_request = {row["request_id"]: row for row in logs}

    found: dict[str, Discrepancy] = {}

    # 1) 有账单无流水（只对**实际扣费**的账单有意义；0 元账单本来就不产生流水）
    for request_id, bill in bill_by_request.items():
        if bill["cost"] <= 0 or request_id in log_by_request:
            continue
        found[f"{KIND_BILLING_WITHOUT_LOG}:{request_id}"] = Discrepancy(
            kind=KIND_BILLING_WITHOUT_LOG,
            request_id=request_id,
            user_id=int(bill["user_id"]),
            billing_cost=int(bill["cost"]),
            occurred_at=str(bill["create_time"]),
            detail="账单已扣费但积分流水缺失",
        )

    # 2) 有流水无账单
    for request_id, log in log_by_request.items():
        if request_id in bill_by_request:
            continue
        found[f"{KIND_LOG_WITHOUT_BILLING}:{request_id}"] = Discrepancy(
            kind=KIND_LOG_WITHOUT_BILLING,
            request_id=request_id,
            user_id=int(log["user_id"]),
            log_amount=int(log["amount"]),
            occurred_at=str(log["create_time"]),
            detail="积分流水已扣分但账单缺失",
        )

    # 3) requestId 错配：同用户同金额、5 分钟内，但 requestId 不同
    paired: set[str] = set()
    for request_id, bill in bill_by_request.items():
        if bill["cost"] <= 0 or request_id in log_by_request:
            continue
        for log_id, log in log_by_request.items():
            if log_id in bill_by_request or log_id in paired:
                continue
            if int(log["user_id"]) != int(bill["user_id"]):
                continue
            if int(log["amount"]) != int(bill["cost"]):
                continue
            if abs(log["create_time"] - bill["create_time"]) > PAIR_WINDOW:
                continue
            paired.add(log_id)
            found[f"{KIND_REQUEST_ID_MISMATCH}:{request_id}"] = Discrepancy(
                kind=KIND_REQUEST_ID_MISMATCH,
                request_id=request_id,
                user_id=int(bill["user_id"]),
                billing_cost=int(bill["cost"]),
                log_amount=int(log["amount"]),
                occurred_at=str(bill["create_time"]),
                detail=f"账单 requestId={request_id} 与流水 requestId={log_id} 疑似同一次调用",
            )
            # 已经找到配对，就不再重复报"有账单无流水"
            found.pop(f"{KIND_BILLING_WITHOUT_LOG}:{request_id}", None)
            found.pop(f"{KIND_LOG_WITHOUT_BILLING}:{log_id}", None)
            break

    counts = {
        "billing_rows": len(bills),
        "points_rows": len(logs),
        "checked_cost_rows": sum(1 for row in bills if row["cost"] > 0),
    }
    return sorted(found.values(), key=lambda item: (item.kind, item.request_id)), counts


def load_state(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_state(
    discrepancies: list[Discrepancy], state: dict[str, dict[str, str]], now: datetime
) -> list[dict[str, Any]]:
    """给每条差异标注 is_new；新增项写入状态，已存在的只更新 last_seen。"""

    stamped = now.strftime("%Y-%m-%d %H:%M:%S")
    result: list[dict[str, Any]] = []
    for item in discrepancies:
        payload = asdict(item)
        existing = state.get(item.key)
        payload["is_new"] = existing is None
        payload["first_seen"] = existing["first_seen"] if existing else stamped
        payload["last_seen"] = stamped
        state[item.key] = {"first_seen": payload["first_seen"], "last_seen": stamped}
        result.append(payload)
    return result


def build_report(
    *, items: list[dict[str, Any]], counts: dict[str, int],
    since: datetime, until: datetime, now: datetime,
) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for item in items:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "window": {"since": str(since), "until": str(until)},
        "counts": counts,
        "summary": {
            "total": len(items),
            "new": sum(1 for item in items if item["is_new"]),
            "by_kind": by_kind,
        },
        "items": items,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="账单与积分流水对账（只读）")
    parser.add_argument("--billing-url", default=os.environ.get("BILLING_DB_URL", ""))
    parser.add_argument("--user-url", default=os.environ.get("USER_DB_URL", ""))
    parser.add_argument("--days", type=int, default=7, help="回看天数，默认 7")
    parser.add_argument(
        "--state", default="artifacts/reconcile/state.json", help="去重状态文件"
    )
    parser.add_argument(
        "--out-dir", default="artifacts/reconcile", help="报告输出目录"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印，不落状态与报告")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.billing_url or not args.user_url:
        print(json.dumps({
            "passed": False,
            "error": "missing --billing-url / --user-url (or BILLING_DB_URL / USER_DB_URL)",
        }, ensure_ascii=False))
        return 2

    now = datetime.now().replace(microsecond=0)
    since = now - timedelta(days=max(1, args.days))
    billing_engine = create_engine(args.billing_url)
    user_engine = create_engine(args.user_url)

    discrepancies, counts = find_discrepancies(
        billing_engine, user_engine, since=since, until=now
    )
    state_path = Path(args.state)
    state = {} if args.dry_run else load_state(state_path)
    items = apply_state(discrepancies, state, now)
    report = build_report(
        items=items, counts=counts, since=since, until=now, now=now
    )

    print(json.dumps({
        "passed": True,
        "scanned": counts,
        "total": report["summary"]["total"],
        "new": report["summary"]["new"],
        "by_kind": report["summary"]["by_kind"],
        "window": report["window"],
    }, ensure_ascii=False, indent=2))

    if args.dry_run:
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"reconcile-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_state(state_path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

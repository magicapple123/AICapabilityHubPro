"""B4 对账脚本的行为测试。

用真实 MySQL 的两张表构造三类差异，验证：
- 三类差异都能被检出；
- 连续跑两次不重复告警（`is_new` 第二次为 False）；
- 只看窗口内数据、不改任何业务数据（脚本是只读的，测试自己负责清理）。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import DB_READY, DB_REASON, TEST_USER_ID_BASE

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "reconcile_billing.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("reconcile_billing", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclass 需要通过 sys.modules 找到所属模块，否则 __qualname__ 解析失败。
    sys.modules.setdefault("reconcile_billing", module)
    spec.loader.exec_module(module)
    return module


def _user_db_url(billing_url: str) -> str:
    """四个库同实例同凭据，把库名换掉即可，避免再引入一个环境变量。"""

    return billing_url.replace("/billing_db", "/user_db")


@pytest.fixture()
def reconcile(monkeypatch):
    if not DB_READY:
        pytest.skip(f"需要可用的 billing_db：{DB_REASON}")
    import os

    billing_url = os.environ["DB_URL"]
    module = _load_script()
    billing_engine = create_engine(billing_url)
    user_engine = create_engine(_user_db_url(billing_url))
    token = uuid4().hex[:8]
    user_id = TEST_USER_ID_BASE + 77
    created: list[str] = []

    def add_bill(request_id: str, cost: int, when: datetime) -> None:
        with billing_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO t_call_record "
                    "(request_id, user_id, capability_id, service_name, cost, call_status, "
                    " duration_ms, model_name, billing_mode, create_time) "
                    "VALUES (:rid, :uid, 1, 'ai-chat-service', :cost, 'success', 10, 'm', "
                    "        'per_call', :ts)"
                ),
                {"rid": request_id, "uid": user_id, "cost": cost, "ts": when},
            )
        created.append(request_id)

    def add_log(request_id: str, amount: int, when: datetime) -> None:
        with user_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO t_points_log "
                    "(user_id, direction, amount, balance_after, biz_type, request_id, create_time) "
                    "VALUES (:uid, 'out', :amount, 0, 'call', :rid, :ts)"
                ),
                {"uid": user_id, "amount": amount, "rid": request_id, "ts": when},
            )
        created.append(request_id)

    def cleanup() -> None:
        with billing_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM t_call_record WHERE user_id = :uid"), {"uid": user_id}
            )
        with user_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM t_points_log WHERE user_id = :uid"), {"uid": user_id}
            )

    cleanup()
    yield {
        "module": module, "billing": billing_engine, "user": user_engine,
        "add_bill": add_bill, "add_log": add_log, "token": token,
        "user_id": user_id, "cleanup": cleanup,
    }
    cleanup()


def test_billing_without_log_is_detected(reconcile):
    now = datetime.now().replace(microsecond=0)
    request_id = f"qa-reconcile-{reconcile['token']}-1"
    reconcile["add_bill"](request_id, 5, now)

    items, counts = reconcile["module"].find_discrepancies(
        reconcile["billing"], reconcile["user"],
        since=now - timedelta(minutes=10), until=now + timedelta(minutes=10),
    )
    kinds = {(item.kind, item.request_id) for item in items}
    assert ("billing_without_log", request_id) in kinds
    assert counts["checked_cost_rows"] >= 1


def test_log_without_billing_is_detected(reconcile):
    now = datetime.now().replace(microsecond=0)
    request_id = f"qa-reconcile-{reconcile['token']}-2"
    reconcile["add_log"](request_id, 3, now)

    items, _ = reconcile["module"].find_discrepancies(
        reconcile["billing"], reconcile["user"],
        since=now - timedelta(minutes=10), until=now + timedelta(minutes=10),
    )
    kinds = {(item.kind, item.request_id) for item in items}
    assert ("log_without_billing", request_id) in kinds


def test_request_id_mismatch_is_detected_as_pair(reconcile):
    now = datetime.now().replace(microsecond=0)
    bill_id = f"qa-reconcile-{reconcile['token']}-3a"
    log_id = f"qa-reconcile-{reconcile['token']}-3b"
    reconcile["add_bill"](bill_id, 7, now)
    reconcile["add_log"](log_id, 7, now + timedelta(seconds=20))

    items, _ = reconcile["module"].find_discrepancies(
        reconcile["billing"], reconcile["user"],
        since=now - timedelta(minutes=10), until=now + timedelta(minutes=10),
    )
    kinds = {(item.kind, item.request_id) for item in items}
    assert ("request_id_mismatch", bill_id) in kinds
    # 错配已经成对解释，不应再重复报"有账单无流水"
    assert ("billing_without_log", bill_id) not in kinds


def test_zero_cost_billing_is_not_reported_as_missing_log(reconcile):
    """降级调用 cost=0，本来就不产生流水，不能算差异。"""

    now = datetime.now().replace(microsecond=0)
    request_id = f"qa-reconcile-{reconcile['token']}-4"
    reconcile["add_bill"](request_id, 0, now)

    items, _ = reconcile["module"].find_discrepancies(
        reconcile["billing"], reconcile["user"],
        since=now - timedelta(minutes=10), until=now + timedelta(minutes=10),
    )
    assert all(item.request_id != request_id for item in items)


def test_second_run_does_not_repeat_alerts(reconcile):
    now = datetime.now().replace(microsecond=0)
    request_id = f"qa-reconcile-{reconcile['token']}-5"
    reconcile["add_bill"](request_id, 9, now)

    module = reconcile["module"]
    items, _ = module.find_discrepancies(
        reconcile["billing"], reconcile["user"],
        since=now - timedelta(minutes=10), until=now + timedelta(minutes=10),
    )
    state: dict = {}
    first = module.apply_state(items, state, now)
    second = module.apply_state(items, state, now + timedelta(minutes=1))

    target = [item for item in first if item["request_id"] == request_id][0]
    again = [item for item in second if item["request_id"] == request_id][0]
    assert target["is_new"] is True
    assert again["is_new"] is False
    assert again["first_seen"] == target["first_seen"]


def test_report_summary_splits_by_kind(reconcile):
    module = reconcile["module"]
    now = datetime.now().replace(microsecond=0)
    report = module.build_report(
        items=[
            {"kind": "billing_without_log", "is_new": True, "request_id": "a"},
            {"kind": "log_without_billing", "is_new": False, "request_id": "b"},
        ],
        counts={"billing_rows": 2, "points_rows": 1, "checked_cost_rows": 2},
        since=now, until=now, now=now,
    )
    assert report["summary"]["total"] == 2
    assert report["summary"]["new"] == 1
    assert report["summary"]["by_kind"]["billing_without_log"] == 1

"""P6 Key 归因 + P5 全量用户聚合的数据库回归测试。

覆盖三件事：
1. `api_key_id` / `entrypoint` 真的落进 `t_call_record`，并能从对外明细读回；
2. 没有 Key 身份的调用不会被硬塞进某把 Key（按 Key 聚合必须 `IS NOT NULL`）；
3. P5 的全量用户聚合来自 `t_usage_daily`，跨用户都能看到。
"""

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.db.session import engine
from app.schemas import BillingRecordRequest
from tests.conftest import QaBilling, TEST_USER_ID_BASE

TODAY = date.today()


def _admin(client, index: int = 0) -> QaBilling:
    """桩里只有 `TEST_USER_ID_BASE` 是 admin，索引 0 即管理员身份。"""

    return QaBilling(client, index=index)


# ---------------------------------------------------------------- 纯内存校验


def test_api_key_id_zero_is_rejected() -> None:
    """0 不是"未知"的合法写法：写库会让按 Key 聚合多出一个假 Key。"""

    with pytest.raises(ValidationError):
        BillingRecordRequest(
            request_id="qa-p6-invalid", user_id=1, points=0, api_key_id=0
        )


def test_api_key_id_defaults_to_none() -> None:
    payload = BillingRecordRequest(request_id="qa-p6-default", user_id=1, points=0)
    assert payload.api_key_id is None
    assert payload.entrypoint == ""


# ---------------------------------------------------------------- 落库与读回


def test_api_key_attribution_is_persisted_and_filterable(
    qa: QaBilling, fake_user_service
) -> None:
    key_a, key_b = 901001, 901002
    first = qa.next_request_id()
    second = qa.next_request_id()

    assert qa.record(request_id=first, api_key_id=key_a, entrypoint="openai_compat")["code"] == 0
    assert qa.record(request_id=second, api_key_id=key_b, entrypoint="openai_compat")["code"] == 0

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT request_id, api_key_id, entrypoint FROM t_call_record "
                "WHERE request_id IN (:a, :b) ORDER BY api_key_id"
            ),
            {"a": first, "b": second},
        ).all()
    assert [(row[1], row[2]) for row in rows] == [
        (key_a, "openai_compat"),
        (key_b, "openai_compat"),
    ]

    # 用户自己的明细里也能看到归因字段（前端"这是哪把 Key 调的"）。
    listed = qa.records(start_date=TODAY.isoformat(), end_date=TODAY.isoformat())
    by_request = {item["request_id"]: item for item in listed["data"]["list"]}
    assert by_request[first]["api_key_id"] == key_a
    assert by_request[second]["entrypoint"] == "openai_compat"

    # 管理员按 Key 筛选：只命中那一把。
    admin = _admin(qa.client)
    body = qa.client.get(
        "/api/billing/admin/records",
        headers=admin.headers(),
        params={
            "user_id": qa.user_id,
            "api_key_id": key_a,
            "start_date": TODAY.isoformat(),
            "end_date": TODAY.isoformat(),
        },
    ).json()
    assert body["code"] == 0
    assert [item["request_id"] for item in body["data"]["list"]] == [first]


def test_key_usage_ignores_calls_without_key(qa: QaBilling, fake_user_service) -> None:
    key_id = 901101
    attributed = qa.next_request_id()
    assert qa.record(request_id=attributed, points=5, api_key_id=key_id)["code"] == 0
    # 网页调试台（无 Key 身份）与历史数据同样为 NULL。
    assert qa.record(request_id=qa.next_request_id(), points=5)["code"] == 0

    admin = _admin(qa.client)
    body = qa.client.get(
        f"/api/billing/admin/users/{qa.user_id}/keys-usage",
        headers=admin.headers(),
        params={"start_date": TODAY.isoformat(), "end_date": TODAY.isoformat()},
    ).json()
    assert body["code"] == 0
    items = body["data"]["list"]
    assert [item["api_key_id"] for item in items] == [key_id]
    assert items[0]["call_count"] >= 1
    assert items[0]["total_cost"] >= 5
    assert items[0]["last_call_at"].startswith(TODAY.isoformat())


def test_user_aggregates_cover_users_from_usage_daily(
    qa: QaBilling, fake_user_service
) -> None:
    other = QaBilling(qa.client, index=3)
    assert qa.record(points=5)["code"] == 0
    assert other.record(points=7)["code"] == 0

    admin = _admin(qa.client)
    body = qa.client.get(
        "/api/billing/admin/users/usage",
        headers=admin.headers(),
        params={"start_date": TODAY.isoformat(), "end_date": TODAY.isoformat()},
    ).json()
    assert body["code"] == 0
    aggregates = {item["user_id"]: item for item in body["data"]["list"]}

    assert TEST_USER_ID_BASE >= 1  # 桩里的管理员本身也在聚合范围里
    assert aggregates[qa.user_id]["total_cost"] >= 5
    assert aggregates[other.user_id]["total_cost"] >= 7
    assert aggregates[other.user_id]["call_count"] >= 1


def test_user_aggregates_requires_admin(api, fake_user_service) -> None:
    normal = QaBilling(api, index=9)
    body = api.get(
        "/api/billing/admin/users/usage", headers=normal.headers()
    ).json()
    assert body["code"] == 2007

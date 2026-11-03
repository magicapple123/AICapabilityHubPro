"""F1 管理端跨用户查询：权限归一（普通用户 2007）与数据口径。

数据库行为复用 `tests/conftest.py` 的真实 MySQL 基座；user-service 用内存桩。
"""

from datetime import date

import pytest

from tests.conftest import DB_READY, QaBilling, TEST_USER_ID_BASE

TODAY = date.today().isoformat()


def _normal_user(client) -> QaBilling:
    """默认角色为 user 的测试身份（桩里只有 TEST_USER_ID_BASE 是 admin）。"""

    return QaBilling(client, index=9)


# ---------------------------------------------------------------- 权限


def test_admin_records_requires_identity(api) -> None:
    body = api.get("/api/billing/admin/records", params={"user_id": 1}).json()
    assert body["code"] == 1001


def test_admin_usage_requires_identity(api) -> None:
    body = api.get("/api/billing/admin/users/1/usage").json()
    assert body["code"] == 1001


def test_admin_records_requires_user_id(api, fake_user_service) -> None:
    """目标用户是必填参数：缺省按 2001 处理，不能退化成"查全部"。"""

    caller = QaBilling(api, index=0)
    body = api.get("/api/billing/admin/records", headers=caller.headers()).json()
    assert body["code"] == 2001


def test_normal_user_is_rejected_with_2007(api, fake_user_service) -> None:
    caller = _normal_user(api)
    records = api.get(
        "/api/billing/admin/records",
        headers=caller.headers(),
        params={"user_id": TEST_USER_ID_BASE},
    ).json()
    usage = api.get(
        f"/api/billing/admin/users/{TEST_USER_ID_BASE}/usage",
        headers=caller.headers(),
    ).json()

    for body in (records, usage):
        assert body["code"] == 2007
        assert body["data"] is None
        assert "仅管理员" in body["message"]
    # 授权失败后不得继续查库
    assert fake_user_service.paths == [
        "/internal/user/authorization",
        "/internal/user/authorization",
    ]


def test_authorization_dependency_failure_stays_4002(api, fake_user_service) -> None:
    from app.core.exceptions import BizException

    fake_user_service.error = BizException(4002, "授权服务暂不可用")
    caller = QaBilling(api, index=0)
    body = api.get(
        "/api/billing/admin/records",
        headers=caller.headers(),
        params={"user_id": TEST_USER_ID_BASE},
    ).json()
    assert body["code"] == 4002


# ---------------------------------------------------------------- 数据口径


@pytest.mark.skipif(not DB_READY, reason="需要可用的 billing_db")
def test_admin_records_filter_by_user_id(api, qa: QaBilling, fake_user_service) -> None:
    admin = qa  # index=0 → TEST_USER_ID_BASE，桩里是 admin
    target = QaBilling(api, index=5)

    qa.record(points=3)  # 管理员自己的记录，不应出现在目标用户结果里
    for points in (5, 7):
        body = target.record(points=points)
        assert body["code"] == 0

    result = api.get(
        "/api/billing/admin/records",
        headers=admin.headers(),
        params={"user_id": target.user_id, "page_size": 50},
    ).json()

    assert result["code"] == 0
    data = result["data"]
    assert data["total"] == 2
    assert {item["user_id"] for item in data["list"]} == {target.user_id}
    assert [item["cost"] for item in data["list"]] == [7, 5]  # 按 id 倒序


@pytest.mark.skipif(not DB_READY, reason="需要可用的 billing_db")
def test_admin_usage_returns_30_day_summary(api, qa: QaBilling, fake_user_service) -> None:
    admin = qa
    target = QaBilling(api, index=6)
    qa.record(points=3)
    target.record(points=5)
    target.record(points=7)

    body = api.get(
        f"/api/billing/admin/users/{target.user_id}/usage",
        headers=admin.headers(),
    ).json()

    assert body["code"] == 0
    data = body["data"]
    assert data["summary"] == {
        "call_count": 2, "total_cost": 12,
        "success_count": 2, "degraded_count": 0, "failed_count": 0,
    }
    assert data["by_day"] == [
        {"stat_date": TODAY, "call_count": 2, "total_cost": 12}
    ]
    assert data["by_service"] == [
        {"service_name": "ai-chat-service", "call_count": 2, "total_cost": 12}
    ]
    assert data["end_date"] == TODAY

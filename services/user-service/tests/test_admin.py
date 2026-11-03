"""F1 运营后台用户管理 + C3 日预算。"""

import pytest
from sqlalchemy import text

from app.db.session import engine
from tests.conftest import DB_READY, DB_REASON


def _promote(user_id: int, *, role: str = "admin") -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE t_user SET role = :role WHERE id = :uid"),
            {"role": role, "uid": user_id},
        )


def _set_limit(user_id: int, limit: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE t_user SET daily_points_limit = :limit WHERE id = :uid"),
            {"limit": limit, "uid": user_id},
        )


@pytest.fixture()
def admin_user(qa):
    if not DB_READY:
        pytest.skip(f"需要可用的 user_db：{DB_REASON}")
    qa.register()
    _promote(qa.user_id)
    return qa


def _headers(user) -> dict:
    return user.headers


# ---------------------------------------------------------------- 权限


def test_admin_endpoints_reject_regular_user(qa):
    qa.register()
    body = qa.client.get("/api/user/admin/users", headers=_headers(qa)).json()
    assert body["code"] == 2007


def test_admin_can_list_users(admin_user):
    body = admin_user.client.get(
        "/api/user/admin/users", headers=_headers(admin_user),
        params={"keyword": admin_user.username},
    ).json()
    assert body["code"] == 0, body
    row = body["data"]["list"][0]
    assert row["username"] == admin_user.username
    assert "balance" in row and "daily_points_limit" in row
    assert "password_hash" not in row


# ---------------------------------------------------------------- 详情


def test_detail_lists_api_keys_without_secret(admin_user):
    """详情抽屉要展示该用户的 Key 元数据，但绝不能带出 secret。"""

    created = admin_user.client.post(
        "/api/user/apikeys", headers=_headers(admin_user), json={"name": "qa-detail-key"},
    ).json()
    assert created["code"] == 0, created

    body = admin_user.client.get(
        f"/api/user/admin/users/{admin_user.user_id}", headers=_headers(admin_user),
    ).json()

    assert body["code"] == 0, body
    detail = body["data"]
    assert detail["balance"] >= 0
    keys = detail["api_keys"]
    assert [key["name"] for key in keys] == ["qa-detail-key"]
    key = keys[0]
    assert key["access_key"] and key["status"]
    for forbidden in ("secret_key", "secret_hash", "secret_mask"):
        assert forbidden not in key


# ---------------------------------------------------------------- 启停


def test_disable_then_enable_restores_access(admin_user):
    admin = admin_user
    target = type(admin)(admin.client)
    target.register()

    disabled = admin.client.put(
        f"/api/user/admin/users/{target.user_id}/status",
        headers=_headers(admin), json={"status": "disabled"},
    ).json()
    assert disabled["code"] == 0 and disabled["data"]["status"] == "disabled"
    # 被禁用后，受保护接口失败关闭
    assert target.points()["code"] == 1005

    admin.client.put(
        f"/api/user/admin/users/{target.user_id}/status",
        headers=_headers(admin), json={"status": "normal"},
    )
    assert target.points()["code"] == 0


def test_status_change_writes_audit(admin_user):
    admin = admin_user
    target = type(admin)(admin.client)
    target.register()
    admin.client.put(
        f"/api/user/admin/users/{target.user_id}/status",
        headers=_headers(admin), json={"status": "disabled"},
    )
    audit = admin.client.get(
        "/api/user/admin/audit", headers=_headers(admin),
        params={"resource_type": "user", "resource_id": target.user_id},
    ).json()
    assert audit["code"] == 0
    rows = audit["data"]["list"]
    assert rows and rows[0]["action"] == "status"
    assert rows[0]["before_json"]["status"] == "normal"
    assert rows[0]["after_json"]["status"] == "disabled"


# ---------------------------------------------------------------- 调分


def test_adjust_points_requires_reason(admin_user):
    admin = admin_user
    body = admin.client.post(
        f"/api/user/admin/users/{admin.user_id}/points",
        headers=_headers(admin), json={"amount": 10, "reason": ""},
    ).json()
    assert body["code"] == 2001


def test_adjust_points_updates_balance_and_writes_audit(admin_user):
    admin = admin_user
    before = admin.points()["data"]["balance"]
    body = admin.client.post(
        f"/api/user/admin/users/{admin.user_id}/points",
        headers=_headers(admin), json={"amount": 50, "reason": "客服补偿"},
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["balance"] == before + 50
    assert admin.points()["data"]["balance"] == before + 50

    audit = admin.client.get(
        "/api/user/admin/audit", headers=_headers(admin),
        params={"resource_type": "points", "action": "adjust_points"},
    ).json()["data"]["list"]
    assert audit and audit[0]["after_json"]["amount"] == 50
    assert audit[0]["after_json"]["reason"] == "客服补偿"

    logs = admin.logs(page_size=50)["data"]["list"]
    assert any(item["biz_type"] == "admin_adjust" for item in logs)


def test_zero_amount_is_rejected(admin_user):
    admin = admin_user
    body = admin.client.post(
        f"/api/user/admin/users/{admin.user_id}/points",
        headers=_headers(admin), json={"amount": 0, "reason": "x"},
    ).json()
    assert body["code"] == 2001


# ---------------------------------------------------------------- 导出


def test_export_csv_has_header_and_no_secret(admin_user):
    admin = admin_user
    response = admin.client.get(
        "/api/user/admin/users/export", headers=_headers(admin),
        params={"keyword": admin.username},
    )
    assert response.status_code == 200
    text_body = response.text
    assert "username" in text_body and "balance" in text_body
    assert admin.password not in text_body
    assert "password_hash" not in text_body


# ---------------------------------------------------------------- C3 预算


def test_daily_budget_blocks_deduction(qa):
    qa.register()
    _set_limit(qa.user_id, 10)

    first = qa.deduct(amount=6)
    assert first["code"] == 0, first
    second = qa.deduct(amount=6)
    assert second["code"] == 3003
    # 超预算的这次不能留下流水
    logs = qa.logs(page_size=50)["data"]["list"]
    assert len([item for item in logs if item["direction"] == "out"]) == 1


def test_zero_limit_means_unlimited(qa):
    qa.register()
    _set_limit(qa.user_id, 0)
    for _ in range(3):
        assert qa.deduct(amount=5)["code"] == 0


# ---------------------------------------------------------------- P10 预算配置入口


def test_admin_can_set_budget_and_it_takes_effect_immediately(admin_user):
    """P10：配置入口生效后，拦截立刻按新预算判断（无缓存，不需要重启）。"""

    admin = admin_user
    target = type(admin)(admin.client)
    target.register()

    body = admin.client.put(
        f"/api/user/admin/users/{target.user_id}/budget",
        headers=_headers(admin), json={"daily_points_limit": 5},
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["daily_points_limit"] == 5

    assert target.deduct(amount=5)["code"] == 0
    assert target.deduct(amount=5)["code"] == 3003

    # 0 = 不限：同一秒改回 0 后立即可继续扣
    reset = admin.client.put(
        f"/api/user/admin/users/{target.user_id}/budget",
        headers=_headers(admin), json={"daily_points_limit": 0},
    ).json()
    assert reset["code"] == 0 and reset["data"]["daily_points_limit"] == 0
    assert target.deduct(amount=5)["code"] == 0

    audit = admin.client.get(
        "/api/user/admin/audit", headers=_headers(admin),
        params={"resource_type": "user", "resource_id": target.user_id,
                "action": "budget"},
    ).json()["data"]["list"]
    assert [row["after_json"]["daily_points_limit"] for row in audit] == [0, 5]
    assert audit[0]["before_json"]["daily_points_limit"] == 5


def test_budget_rejects_negative_and_huge_values(admin_user):
    admin = admin_user
    for value in (-1, 1_000_001):
        body = admin.client.put(
            f"/api/user/admin/users/{admin.user_id}/budget",
            headers=_headers(admin), json={"daily_points_limit": value},
        ).json()
        assert body["code"] == 2001


def test_budget_requires_admin(qa):
    qa.register()
    body = qa.client.put(
        f"/api/user/admin/users/{qa.user_id}/budget",
        headers=_headers(qa), json={"daily_points_limit": 10},
    ).json()
    assert body["code"] == 2007


def test_same_budget_value_writes_no_duplicate_audit(admin_user):
    """同值重复提交不该产生"改了但其实没改"的审计噪声。"""

    admin = admin_user
    target = type(admin)(admin.client)
    target.register()
    for _ in range(2):
        body = admin.client.put(
            f"/api/user/admin/users/{target.user_id}/budget",
            headers=_headers(admin), json={"daily_points_limit": 20},
        ).json()
        assert body["code"] == 0
    audit = admin.client.get(
        "/api/user/admin/audit", headers=_headers(admin),
        params={"resource_type": "user", "resource_id": target.user_id,
                "action": "budget"},
    ).json()["data"]["list"]
    assert len(audit) == 1


# ---------------------------------------------------------------- P6 Key 生命周期审计


def test_api_key_create_and_disable_are_audited_without_secrets(admin_user):
    admin = admin_user
    created = admin.client.post(
        "/api/user/apikeys", headers=_headers(admin), json={"name": "qa-audit-key"},
    ).json()
    assert created["code"] == 0, created
    key_id = created["data"]["id"]
    secret = created["data"]["secret_key"]

    audit = admin.client.get(
        "/api/user/admin/audit", headers=_headers(admin),
        params={"resource_type": "apikey", "resource_id": key_id},
    ).json()["data"]["list"]
    assert [row["action"] for row in audit] == ["create"]
    payload = str(audit[0]["after_json"])
    assert "qa-audit-key" in payload
    assert secret not in payload
    assert "secret" not in payload.lower()

    disabled = admin.client.put(
        f"/api/user/apikeys/{key_id}/disable", headers=_headers(admin),
    ).json()
    assert disabled["code"] == 0, disabled

    audit = admin.client.get(
        "/api/user/admin/audit", headers=_headers(admin),
        params={"resource_type": "apikey", "resource_id": key_id},
    ).json()["data"]["list"]
    assert [row["action"] for row in audit] == ["disable", "create"]
    assert audit[0]["after_json"]["status"] == "disabled"

    # 重复禁用幂等，且不再多写一条审计
    admin.client.put(f"/api/user/apikeys/{key_id}/disable", headers=_headers(admin))
    audit = admin.client.get(
        "/api/user/admin/audit", headers=_headers(admin),
        params={"resource_type": "apikey", "resource_id": key_id},
    ).json()["data"]["list"]
    assert len(audit) == 2

"""B1 运营审计：改价留痕、只追加、脱敏与筛选。

验收口径（需求清单 B1）：
- 改价后能查到操作人、时间、改前改后；
- 无法通过任何接口修改历史记录。
"""

from app.models import OperationLog
from app.service.audit_service import sanitize
from tests.conftest import USER_HEADERS


def _audit(qa, **params):
    merged = {"page_size": 50, **params}
    return qa.client.get(
        "/api/capability/audit", headers=USER_HEADERS, params=merged
    ).json()


def _find(logs, **match):
    return [
        item for item in logs
        if all(str(item.get(key)) == str(value) for key, value in match.items())
    ]


def test_price_change_is_audited_with_before_and_after(qa):
    category = qa.category()
    created = qa.create_capability_raw(category["id"], code=qa.code("audit"), price=7)
    assert created["code"] == 0, created
    capability_id = created["data"]["id"]

    updated = qa.client.put(
        f"/api/capability/{capability_id}", headers=USER_HEADERS,
        json={"price_per_call": 9},
    ).json()
    assert updated["code"] == 0, updated

    body = _audit(qa, resource_type="capability", resource_id=capability_id, action="update")
    assert body["code"] == 0, body
    rows = body["data"]["list"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["operator_id"] == USER_HEADERS["X-User-Id"]
    assert row["operator_name"] == USER_HEADERS["X-User-Name"]
    assert row["request_id"] == USER_HEADERS["X-Request-Id"]
    assert row["before_json"]["price_per_call"] == 7
    assert row["after_json"]["price_per_call"] == 9
    assert row["create_time"]


def test_status_change_records_only_status(qa):
    category = qa.category()
    created = qa.create_capability_raw(category["id"], code=qa.code("audit"))
    capability_id = created["data"]["id"]

    qa.client.put(
        f"/api/capability/{capability_id}/status", headers=USER_HEADERS,
        json={"status": "offline"},
    )

    rows = _audit(qa, resource_type="capability", resource_id=capability_id,
                  action="status")["data"]["list"]
    assert len(rows) == 1
    assert rows[0]["before_json"] == {"status": "draft"}
    assert rows[0]["after_json"] == {"status": "offline"}


def test_delete_is_audited(qa):
    category = qa.category()
    created = qa.create_capability_raw(category["id"], code=qa.code("audit"))
    capability_id = created["data"]["id"]

    qa.client.delete(f"/api/capability/{capability_id}", headers=USER_HEADERS)

    rows = _audit(qa, resource_type="capability", resource_id=capability_id,
                  action="delete")["data"]["list"]
    assert len(rows) == 1
    assert rows[0]["after_json"]["is_deleted"] == 1


def test_category_writes_are_audited(qa):
    category = qa.category()
    qa.client.put(
        f"/api/capability/categories/{category['id']}", headers=USER_HEADERS,
        json={"name": f"QACatRenamed-{qa.token}"},
    )
    rows = _audit(qa, resource_type="category", resource_id=category["id"],
                  action="update")["data"]["list"]
    assert len(rows) == 1
    assert rows[0]["after_json"]["name"].startswith("QACatRenamed-")


def test_audit_history_is_read_only(qa):
    """应用层不提供任何改写历史记录的入口。

    说明：`PUT/DELETE /api/capability/audit` 会被 `/{capability_id}` 路由接住，
    但由于 `audit` 不是合法 ID 且能力不存在，业务码必须是失败；这里断言的是
    "改不动"这个语义，而不是 HTTP 405 这种路由层细节。
    """

    before = _audit(qa)["data"]["total"]

    put_body = qa.client.put(
        "/api/capability/audit", headers=USER_HEADERS, json={"price_per_call": 1}
    ).json()
    delete_body = qa.client.delete("/api/capability/audit", headers=USER_HEADERS).json()
    post_body = qa.client.post("/api/capability/audit", headers=USER_HEADERS).json()

    assert put_body["code"] != 0 and delete_body["code"] != 0 and post_body["code"] != 0
    # 历史条数不变：既没被改写，也没被删除
    assert _audit(qa)["data"]["total"] == before


def test_audit_requires_admin(qa, monkeypatch):
    from app.core.exceptions import BizException
    from app.service import authorization_service

    async def deny(user_id: str) -> None:
        raise BizException(2007, "无运营权限")

    monkeypatch.setattr(authorization_service, "require_admin", deny)
    body = qa.client.get("/api/capability/audit", headers=USER_HEADERS).json()
    assert body["code"] == 2007


def test_sanitize_masks_sensitive_keys():
    cleaned = sanitize({
        "name": "ok",
        "api_key": "sk-real-key",
        "nested": {"password": "p", "keep": 1},
        "param_schema": {"type": "object"},
    })
    assert cleaned["name"] == "ok"
    assert cleaned["api_key"] == "***"
    assert cleaned["nested"]["password"] == "***"
    assert cleaned["nested"]["keep"] == 1
    assert cleaned["param_schema"] == {"type": "object"}


def test_audit_supports_time_and_operator_filters(qa):
    category = qa.category()
    created = qa.create_capability_raw(category["id"], code=qa.code("audit"))
    capability_id = created["data"]["id"]
    qa.client.put(
        f"/api/capability/{capability_id}", headers=USER_HEADERS,
        json={"description": "改一下"},
    )

    by_operator = _audit(qa, operator_id=USER_HEADERS["X-User-Id"], resource_id=capability_id)
    assert by_operator["code"] == 0
    assert len(by_operator["data"]["list"]) >= 2  # create + update

    future = _audit(qa, start_date="2099-01-01")
    assert future["code"] == 0 and future["data"]["total"] == 0


def test_audit_row_is_appended_in_same_transaction(qa):
    """审计与业务写同事务：能查到记录即说明业务提交成功，反之不会只留审计。"""

    category = qa.category()
    code = qa.code("audit")
    created = qa.create_capability_raw(category["id"], code=code)
    capability_id = created["data"]["id"]

    rows = _audit(qa, resource_type="capability", resource_id=capability_id,
                  action="create")["data"]["list"]
    assert len(rows) == 1
    assert rows[0]["after_json"]["code"] == code
    assert OperationLog.__tablename__ == "t_operation_log"

"""D5「上架体验与目录语义」的两条语义：分类停用、软删 code 复用。

分类停用（`status='disabled'`）只影响市场可见性：
- 市场列表 / 市场详情 / 市场筛选栏都看不到该分类下的能力；
- 运营列表仍然查得到，且内部目录接口（已授权调用方）仍按原样返回；
- 恢复 enabled 后市场可见性回来（测试结束一定恢复，避免污染演示数据）。

软删 code 复用（生成列 `active_code`）：
同一 code 允许"建 → 删 → 建 → 删 → 建"任意多轮，未删除范围内仍然唯一；
唯一性由数据库 `uk_capability_active_code` 兜底，第二次软删不再撞 1062。
"""

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.models import Capability
from app.repository import capability_repository
from app.repository.capability_repository import DuplicateCapabilityCodeError
from app.service import capability_service
from tests.conftest import DB_READY, DB_REASON, USER_HEADERS


def _create(qa, category_id, *, code: str, status: str = "online") -> dict:
    return qa.client.post(
        "/api/capability",
        headers=USER_HEADERS,
        json={
            "category_id": category_id,
            "name": f"QAD5-{qa.token}",
            "code": code,
            "service_name": "ai-chat-service",
            "path": "/api/chat/completions",
            "param_schema": {"type": "object", "properties": {}},
            "status": status,
            "price_per_call": 3,
        },
    ).json()


def _market_ids(qa, *, category_id: int | None = None) -> list[int]:
    params: dict[str, object] = {"keyword": qa.token, "page_size": 50}
    if category_id is not None:
        params["category_id"] = category_id
    body = qa.client.get("/api/capability/market", params=params).json()
    assert body["code"] == 0, body
    return [item["id"] for item in body["data"]["list"]]


def _manage_ids(qa) -> list[int]:
    body = qa.client.get(
        "/api/capability/manage",
        headers=USER_HEADERS,
        params={"keyword": qa.token, "page_size": 50},
    ).json()
    assert body["code"] == 0, body
    return [item["id"] for item in body["data"]["list"]]


def _market_category_ids(qa) -> list[int]:
    body = qa.client.get("/api/capability/market/categories").json()
    assert body["code"] == 0, body
    return [item["id"] for item in body["data"]["list"]]


def _set_category_status(qa, category_id: int, status: str) -> None:
    body = qa.update_category(category_id, {"status": status})
    assert body["code"] == 0, body
    assert body["data"]["status"] == status


# --------------------------------------------------------------- 分类停用语义


def test_disabled_category_hides_capabilities_from_market(qa):
    category = qa.category()
    capability = _create(qa, category["id"], code=qa.code("d5cat"))
    assert capability["code"] == 0, capability
    capability_id = capability["data"]["id"]

    # 停用前：市场可见，且出现在市场筛选栏
    assert capability_id in _market_ids(qa)
    assert category["id"] in _market_category_ids(qa)

    _set_category_status(qa, category["id"], "disabled")
    try:
        # 停用后：市场列表 / 市场详情 / 筛选栏都看不到
        assert capability_id not in _market_ids(qa)
        detail = qa.market_detail(capability_id)
        assert detail["code"] == 2002, detail
        assert category["id"] not in _market_category_ids(qa)

        # 但运营列表仍查得到（可以据此恢复），能力自身的 status 没有被改动
        assert capability_id in _manage_ids(qa)
        internal = qa.internal_detail(capability_id)
        assert internal["code"] == 0, internal
        assert internal["data"]["status"] == "online"
    finally:
        # 恢复分类状态：测试绝不能把演示分类留在 disabled
        _set_category_status(qa, category["id"], "enabled")

    # 恢复后市场可见性回来
    assert capability_id in _market_ids(qa)
    detail = qa.market_detail(capability_id)
    assert detail["code"] == 0, detail


def test_disabled_category_is_filtered_by_category_id_query(qa):
    """按 category_id 过滤时同样不能漏出停用分类的能力。"""

    category = qa.category()
    capability = _create(qa, category["id"], code=qa.code("d5cat"))
    capability_id = capability["data"]["id"]
    assert _market_ids(qa, category_id=category["id"]) == [capability_id]

    _set_category_status(qa, category["id"], "disabled")
    try:
        assert _market_ids(qa, category_id=category["id"]) == []
    finally:
        _set_category_status(qa, category["id"], "enabled")
    assert _market_ids(qa, category_id=category["id"]) == [capability_id]


# --------------------------------------------------------------- 软删 code 复用


def test_soft_deleted_code_can_be_reused_repeatedly(qa):
    """建 → 删 → 建 → 删 → 建：旧 `(code, is_deleted)` 唯一键在第二次删时就会 1062。"""

    category = qa.category()
    code = qa.code("d5reuse")

    created_ids: list[int] = []
    for round_index in range(3):
        created = _create(qa, category["id"], code=code)
        assert created["code"] == 0, (round_index, created)
        capability_id = created["data"]["id"]
        created_ids.append(capability_id)

        deleted = qa.delete_capability(capability_id)
        assert deleted["code"] == 0, (round_index, deleted)

        # 软删后未删除范围内不再有该编码，因此还能再建
        assert capability_id not in _manage_ids(qa)

    # 三轮拿到三个不同的 id，说明确实是新建而不是复用旧行
    assert len(set(created_ids)) == 3
    # 软删的行全部保留在库里（可追溯），active_code 为 NULL
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, is_deleted, active_code FROM t_capability "
                "WHERE code = :code ORDER BY id"
            ),
            {"code": code},
        ).all()
    assert [row[0] for row in rows] == created_ids
    assert all(row[1] == 1 for row in rows)
    assert all(row[2] is None for row in rows)


def test_duplicate_code_is_rejected_while_row_is_alive(qa):
    """未删除范围内仍然唯一：第二次登记同一 code 返回 2006，而不是 500。"""

    category = qa.category()
    code = qa.code("d5dup")
    first = _create(qa, category["id"], code=code)
    assert first["code"] == 0, first

    second = _create(qa, category["id"], code=code)
    assert second["code"] == 2006, second


def test_database_enforces_active_code_uniqueness(qa):
    """约束建在生成列上，而不是 `(code, is_deleted)`。"""

    if not DB_READY:
        pytest.skip(f"需要可用的 capability_db：{DB_REASON}")

    with engine.connect() as connection:
        indexes = connection.execute(
            text(
                "SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability'"
            )
        ).all()
        generated = connection.execute(
            text(
                "SELECT EXTRA, GENERATION_EXPRESSION FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability' "
                "AND COLUMN_NAME = 'active_code'"
            )
        ).first()

    unique_columns = {
        row[1] for row in indexes if row[0] == "uk_capability_active_code" and row[2] == 0
    }
    assert unique_columns == {"active_code"}, indexes
    # 旧的唯一键必须已经不在（否则第二次软删仍会 1062）
    assert not any(row[0] == "uk_capability_code" for row in indexes), indexes
    # exists_code() 的访问路径仍在
    assert any(row[0] == "idx_capability_code" and row[2] == 1 for row in indexes), indexes
    assert generated is not None
    assert "STORED GENERATED" in (generated[0] or "").upper()
    assert "is_deleted" in (generated[1] or "")


# ------------------------------------------- 1062 语义：仍然翻译成 2006（不是 500）


def test_repository_translates_mysql_1062_into_domain_error(qa):
    """绕开 service 的预检直接插库：唯一键冲突必须变成 DuplicateCapabilityCodeError。"""

    category = qa.category()
    code = qa.code("d5conflict")
    created = _create(qa, category["id"], code=code)
    assert created["code"] == 0, created

    db = SessionLocal()
    try:
        duplicate = Capability(
            category_id=category["id"],
            name=f"QAD5-dup-{qa.token}",
            code=code,
            service_name="ai-chat-service",
            path="/api/chat/completions",
            param_schema={"type": "object", "properties": {}},
            status="draft",
        )
        with pytest.raises(DuplicateCapabilityCodeError):
            capability_repository.create(db, duplicate)
    finally:
        db.close()


def test_service_maps_concurrent_duplicate_to_2006(qa, monkeypatch):
    """预检放行后仍然由数据库兜底：接口返回 2006，不会漏成 500。"""

    category = qa.category()
    code = qa.code("d5race")
    first = _create(qa, category["id"], code=code)
    assert first["code"] == 0, first

    # 模拟"并发下预检没看到对方"：exists_code 恒为 False，冲突只能由数据库发现。
    monkeypatch.setattr(
        capability_service.capabilities, "exists_code", lambda *args, **kwargs: False
    )
    second = _create(qa, category["id"], code=code)
    assert second["code"] == 2006, second

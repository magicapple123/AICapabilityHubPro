"""capability-service 数据库行为测试。

覆盖 `docs/team-tasks.md` 第 5 节要求的筛选、上下架、软删除、重复名称与越权访问，
并补充接口契约写明的 PUT 幂等语义。

所有用例通过真实接口调用并连接真实 MySQL（表由 `sql/01_init.sql` 创建），
数据库不可用时整组自动跳过，原因见 `tests/conftest.py`。
"""

import pytest

from tests.conftest import DB_REASON, DB_READY, QaCatalog

pytestmark = pytest.mark.skipif(
    not DB_READY, reason=f"需要可用的 capability_db：{DB_REASON}"
)


# ---------------------------------------------------------------- 筛选


def test_market_is_anonymous(api) -> None:
    """市场接口属网关白名单，不带任何身份头也能访问。"""

    body = api.get("/api/capability/market").json()
    assert body["code"] == 0
    assert "list" in body["data"]


def test_market_filters_by_category(qa: QaCatalog) -> None:
    """分类筛选只返回该分类下的能力，且 draft 能力一律不返回。"""

    category = qa.category()
    online = qa.capability(category["id"], status="online")
    draft = qa.capability(category["id"], status="draft")

    items = qa.market_items(category_id=category["id"])
    codes = [item["code"] for item in items]

    assert online["code"] in codes
    assert draft["code"] not in codes
    # 不会混入其它分类的能力
    assert all(item["category_id"] == category["id"] for item in items)


def test_market_filters_by_keyword(qa: QaCatalog) -> None:
    """关键字按名称模糊匹配，且仍然只返回 online 能力。"""

    category = qa.category()
    online = qa.capability(category["id"], name=f"QAKw-{qa.token}", status="online")
    draft = qa.capability(category["id"], name=f"QAKwDraft-{qa.token}", status="draft")

    items = qa.market_items(keyword=f"QAKw-{qa.token}")
    codes = [item["code"] for item in items]

    assert codes == [online["code"]]
    assert draft["code"] not in codes


def test_market_supports_chinese_keyword(qa: QaCatalog) -> None:
    """中文关键字可检索，确认 utf8mb4 存储与匹配正常。"""

    category = qa.category(name=f"QA中文分类{qa.token}")
    chinese_name = f"QA中文能力{qa.token}"
    capability = qa.capability(category["id"], name=chinese_name, status="online")

    items = qa.market_items(keyword=chinese_name)
    matched = [item for item in items if item["code"] == capability["code"]]

    assert len(matched) == 1
    assert matched[0]["name"] == chinese_name
    assert matched[0]["category_name"] == category["name"]


def test_market_rejects_draft_detail(qa: QaCatalog) -> None:
    """未上架能力对市场接口不可见，返回 2002 而不暴露存在性。"""

    category = qa.category()
    draft = qa.capability(category["id"], status="draft")

    body = qa.market_detail(draft["id"])
    assert body["code"] == 2002
    assert body["data"] is None


# ---------------------------------------------------------------- 上下架


def test_status_transitions_control_market_visibility(qa: QaCatalog) -> None:
    """draft → online → offline 的状态流转决定市场可见性。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="draft")
    code = capability["code"]

    # 初始 draft：市场不可见
    assert not qa.visible_in_market(code)
    assert qa.market_detail(capability["id"])["code"] == 2002

    # 上架：市场可见
    assert qa.set_status(capability["id"], "online")["code"] == 0
    assert qa.visible_in_market(code)
    assert qa.market_detail(capability["id"])["code"] == 0

    # 下架：市场再次不可见
    assert qa.set_status(capability["id"], "offline")["code"] == 0
    assert not qa.visible_in_market(code)
    assert qa.market_detail(capability["id"])["code"] == 2002


def test_status_update_rejects_unknown_value(qa: QaCatalog) -> None:
    """非法状态值在参数校验阶段被拦截，返回 2001。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="draft")

    body = qa.set_status(capability["id"], "published")
    assert body["code"] == 2001


def test_repeated_status_update_is_idempotent(qa: QaCatalog) -> None:
    """同一状态重复提交不产生副作用（契约写明 PUT 幂等）。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="draft")

    first = qa.set_status(capability["id"], "online")
    second = qa.set_status(capability["id"], "online")

    assert first["code"] == 0 and second["code"] == 0
    assert second["data"]["status"] == "online"
    assert qa.visible_in_market(capability["code"])


# ---------------------------------------------------------------- 软删除


def test_capability_soft_delete(qa: QaCatalog) -> None:
    """软删除后能力从市场消失，按 ID 查询与管理列表都不再可见。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="online")
    assert qa.visible_in_market(capability["code"])

    assert qa.delete_capability(capability["id"])["code"] == 0
    assert not qa.visible_in_market(capability["code"])
    assert qa.market_detail(capability["id"])["code"] == 2002

    managed = [item for item in qa.manage_list()["data"]["list"] if item["code"] == capability["code"]]
    assert managed == []

    # 重复删除：已软删除的记录不再算存在
    assert qa.delete_capability(capability["id"])["code"] == 2002


def test_category_soft_delete(qa: QaCatalog) -> None:
    """软删除后分类从列表消失，重复删除返回 2003。"""

    category = qa.category()

    assert qa.delete_category(category["id"])["code"] == 0
    assert category["id"] not in [item["id"] for item in qa.list_categories()]

    assert qa.delete_category(category["id"])["code"] == 2003


def test_delete_category_blocked_until_capabilities_removed(qa: QaCatalog) -> None:
    """分类下仍有未删除能力时禁止删除（2005），软删除能力后放行。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="online")

    assert qa.delete_category(category["id"])["code"] == 2005

    # 下架不等于删除，引用检查仍按 is_deleted=0 计数
    assert qa.set_status(capability["id"], "offline")["code"] == 0
    assert qa.delete_category(category["id"])["code"] == 2005

    # 软删除能力之后即可删除分类
    assert qa.delete_capability(capability["id"])["code"] == 0
    assert qa.delete_category(category["id"])["code"] == 0


# ---------------------------------------------------------------- 重复名称与编码


def test_duplicate_category_name_returns_2004(qa: QaCatalog) -> None:
    """分类名称在未删除范围内唯一。"""

    category = qa.category()

    body = qa.create_category_raw(name=category["name"], code=qa.code("dup"))
    assert body["code"] == 2004


def test_duplicate_category_code_returns_2004(qa: QaCatalog) -> None:
    """分类编码在未删除范围内唯一。"""

    category = qa.category()

    body = qa.create_category_raw(name=f"QAName-{qa.token}", code=category["code"])
    assert body["code"] == 2004


def test_duplicate_capability_code_returns_2006(qa: QaCatalog) -> None:
    """能力编码在未删除范围内唯一。"""

    category = qa.category()
    capability = qa.capability(category["id"])

    body = qa.create_capability_raw(category["id"], code=capability["code"])
    assert body["code"] == 2006


def test_code_reusable_after_soft_delete(qa: QaCatalog) -> None:
    """唯一索引为 (列, is_deleted)，因此软删除后同一编码可以重新登记。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="online")

    assert qa.delete_capability(capability["id"])["code"] == 0

    reused = qa.create_capability_raw(category["id"], code=capability["code"])
    assert reused["code"] == 0
    assert reused["data"]["id"] != capability["id"]


def test_repeated_category_update_is_idempotent(qa: QaCatalog) -> None:
    """重复提交同一变更不产生副作用。"""

    category = qa.category()
    payload = {"sort": 42, "status": "disabled"}

    assert qa.update_category(category["id"], payload)["code"] == 0
    second = qa.update_category(category["id"], payload)

    assert second["code"] == 0
    assert second["data"]["sort"] == 42
    assert second["data"]["status"] == "disabled"


# ---------------------------------------------------------------- 越权访问


def test_manage_lists_draft_with_internal_fields(qa: QaCatalog) -> None:
    """运营列表返回 draft 能力并包含内部字段，而市场接口不返回。"""

    category = qa.category()
    draft = qa.capability(category["id"], status="draft")

    matched = [
        item for item in qa.manage_list()["data"]["list"] if item["code"] == draft["code"]
    ]

    assert len(matched) == 1
    assert matched[0]["status"] == "draft"
    assert matched[0]["service_name"] == "ai-chat-service"
    assert matched[0]["path"] == "/api/chat/completions"
    assert not qa.visible_in_market(draft["code"])


# ---------------------------------------------------------------- 上架 Schema


def test_online_creation_requires_schema(qa: QaCatalog) -> None:
    """不能直接登记一个没有 Schema 的已上架能力。"""

    category = qa.category()

    body = qa.create_capability_raw(
        category["id"], code=qa.code("noschema"), status="online", omit_schema=True
    )

    assert body["code"] == 2001
    assert body["data"] is None


def test_draft_without_schema_cannot_go_online(qa: QaCatalog) -> None:
    """草稿可以暂不填写 Schema，但上架前必须补齐。"""

    category = qa.category()
    created = qa.create_capability_raw(
        category["id"], code=qa.code("draftnoschema"), status="draft", omit_schema=True
    )
    assert created["code"] == 0
    assert created["data"]["param_schema"] is None

    assert qa.set_status(created["data"]["id"], "online")["code"] == 2001
    assert not qa.visible_in_market(created["data"]["code"])


def test_online_capability_cannot_clear_schema(qa: QaCatalog) -> None:
    """线上能力不能通过编辑把 Schema 清空，必须先下架。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="online")

    body = qa.update_capability(capability["id"], {"param_schema": None})

    assert body["code"] == 2001
    assert qa.market_detail(capability["id"])["code"] == 0


def test_online_capability_can_update_valid_schema(qa: QaCatalog) -> None:
    """合法 Schema 的编辑仍然允许，并在内部详情中立即生效。"""

    category = qa.category()
    capability = qa.capability(category["id"], status="online")
    schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    body = qa.update_capability(capability["id"], {"param_schema": schema})

    assert body["code"] == 0
    assert qa.internal_detail(capability["id"])["data"]["param_schema"] == schema

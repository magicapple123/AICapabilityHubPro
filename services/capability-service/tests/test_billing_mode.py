"""C2 双轨计费的目录侧约束：计价字段组合校验、旧能力零变化、内部/市场出参。

这些用例走真实接口与真实 MySQL（表由 sql 脚本创建），不 mock service。
"""

import pytest

from tests.conftest import USER_HEADERS

DEFAULT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _create(qa, category_id: int, **overrides) -> dict:
    payload = {
        "category_id": category_id,
        "name": f"QABilling-{qa.token}",
        "code": qa.code("billing"),
        "service_name": "ai-chat-service",
        "path": "/api/chat/completions",
        "param_schema": DEFAULT_SCHEMA,
        "status": "draft",
        "price_per_call": 0,
    }
    payload.update(overrides)
    return qa.client.post(
        "/api/capability", headers=USER_HEADERS, json=payload
    ).json()


# ---------------------------------------------------------------- 创建校验


def test_per_token_capability_requires_token_price(qa):
    category = qa.category()
    body = _create(qa, category["id"], billing_mode="per_token")
    assert body["code"] == 2001


def test_per_token_capability_rejects_double_pricing(qa):
    """同时给 price_per_call 和 token 单价属于双重计价，必须在保存阶段拒绝。"""

    category = qa.category()
    body = _create(
        qa, category["id"], billing_mode="per_token", price_per_call=5,
        price_per_1k_input=1,
    )
    assert body["code"] == 2001


def test_per_unit_capability_requires_unit_label(qa):
    category = qa.category()
    body = _create(qa, category["id"], billing_mode="per_unit", price_per_unit=4)
    assert body["code"] == 2001


def test_per_unit_capability_is_stored_with_unit(qa):
    category = qa.category()
    body = _create(
        qa, category["id"], billing_mode="per_unit", price_per_unit=4, unit="张",
    )
    assert body["code"] == 0, body
    listed = qa.client.get(
        "/api/capability/manage", headers=USER_HEADERS,
        params={"keyword": qa.token, "page_size": 50},
    ).json()["data"]["list"]
    row = [item for item in listed if item["id"] == body["data"]["id"]][0]
    assert row["billing_mode"] == "per_unit"
    assert row["price_per_unit"] == 4 and row["unit"] == "张"


def test_per_token_capability_is_stored(qa):
    category = qa.category()
    body = _create(
        qa, category["id"], billing_mode="per_token",
        price_per_1k_input=2, price_per_1k_output=8,
    )
    assert body["code"] == 0, body
    # 运营侧没有单条详情接口，用列表（按 token 过滤）核对落库结果。
    listed = qa.client.get(
        "/api/capability/manage", headers=USER_HEADERS,
        params={"keyword": qa.token, "page_size": 50},
    ).json()["data"]["list"]
    row = [item for item in listed if item["id"] == body["data"]["id"]][0]
    assert row["billing_mode"] == "per_token"
    assert row["price_per_1k_input"] == 2
    assert row["price_per_1k_output"] == 8


# ---------------------------------------------------------------- 编辑校验


def test_switching_to_per_token_requires_clearing_per_call_price(qa):
    category = qa.category()
    created = _create(qa, category["id"], price_per_call=5)
    assert created["code"] == 0

    only_mode = qa.client.put(
        f"/api/capability/{created['data']['id']}", headers=USER_HEADERS,
        json={"billing_mode": "per_token", "price_per_1k_input": 1},
    ).json()
    assert only_mode["code"] == 2001

    fixed = qa.client.put(
        f"/api/capability/{created['data']['id']}", headers=USER_HEADERS,
        json={"billing_mode": "per_token", "price_per_call": 0, "price_per_1k_input": 1},
    ).json()
    assert fixed["code"] == 0, fixed
    assert fixed["data"]["billing_mode"] == "per_token"
    assert fixed["data"]["price_per_call"] == 0


def test_partial_update_on_per_call_capability_rejects_token_price(qa):
    """按次能力不能被只加一个 token 单价"偷偷"变成双轨计价。"""

    category = qa.category()
    created = _create(qa, category["id"], price_per_call=5)
    body = qa.client.put(
        f"/api/capability/{created['data']['id']}", headers=USER_HEADERS,
        json={"price_per_1k_input": 3},
    ).json()
    assert body["code"] == 2001


# ---------------------------------------------------------------- 旧能力零变化


def test_demo_capabilities_stay_per_call_after_migration(qa):
    """红线 3：迁移后旧两行必须仍是 per_call，单价仍是 5 / 3。"""

    for capability_id, price in ((1, 5), (2, 3)):
        detail = qa.client.get(
            f"/internal/capability/{capability_id}", headers=USER_HEADERS
        ).json()
        assert detail["code"] == 0, detail
        data = detail["data"]
        assert data["billing_mode"] == "per_call"
        assert data["price_per_call"] == price
        assert data["price_per_1k_input"] == 0
        assert data["price_per_1k_output"] == 0


def test_market_list_exposes_billing_mode_without_internal_fields(qa):
    category = qa.category()
    created = _create(
        qa, category["id"], status="online", billing_mode="per_unit",
        price_per_unit=6, unit="张",
    )
    assert created["code"] == 0, created

    listed = qa.client.get(
        "/api/capability/market", params={"keyword": qa.token, "page_size": 50}
    ).json()
    assert listed["code"] == 0
    row = [item for item in listed["data"]["list"] if item["id"] == created["data"]["id"]][0]
    assert row["billing_mode"] == "per_unit" and row["unit"] == "张"
    # 市场侧仍然不能暴露内部配置
    assert "service_name" not in row and "path" not in row

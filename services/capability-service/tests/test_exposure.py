"""E4 市场展示开关：与 status 独立，隐藏不影响可调用性。"""

from tests.conftest import USER_HEADERS


def _create(qa, category_id, **overrides):
    payload = {
        "category_id": category_id,
        "name": f"QAExpose-{qa.token}",
        "code": qa.code("expose"),
        "service_name": "ai-chat-service",
        "path": "/api/chat/completions",
        "param_schema": {"type": "object", "properties": {}},
        "status": "online",
        "price_per_call": 3,
    }
    payload.update(overrides)
    return qa.client.post("/api/capability", headers=USER_HEADERS, json=payload).json()


def test_hidden_capability_is_not_in_market_but_still_executable(qa):
    category = qa.category()
    created = _create(qa, category["id"], exposed_to_market=False)
    assert created["code"] == 0, created
    capability_id = created["data"]["id"]

    market = qa.client.get(
        "/api/capability/market", params={"keyword": qa.token, "page_size": 50}
    ).json()["data"]["list"]
    assert all(item["id"] != capability_id for item in market)

    internal = qa.client.get(
        f"/internal/capability/{capability_id}", headers=USER_HEADERS
    ).json()
    assert internal["code"] == 0
    assert internal["data"]["status"] == "online"


def test_manage_list_exposes_the_switch(qa):
    category = qa.category()
    created = _create(qa, category["id"])
    rows = qa.client.get(
        "/api/capability/manage", headers=USER_HEADERS,
        params={"keyword": qa.token, "page_size": 50},
    ).json()["data"]["list"]
    row = [item for item in rows if item["id"] == created["data"]["id"]][0]
    assert row["exposed_to_market"] is True


def test_toggle_hides_and_restores(qa):
    category = qa.category()
    created = _create(qa, category["id"])
    capability_id = created["data"]["id"]

    hidden = qa.client.put(
        f"/api/capability/{capability_id}", headers=USER_HEADERS,
        json={"exposed_to_market": False},
    ).json()
    assert hidden["code"] == 0 and hidden["data"]["exposed_to_market"] is False
    market = qa.client.get(
        "/api/capability/market", params={"keyword": qa.token, "page_size": 50}
    ).json()["data"]["list"]
    assert all(item["id"] != capability_id for item in market)

    shown = qa.client.put(
        f"/api/capability/{capability_id}", headers=USER_HEADERS,
        json={"exposed_to_market": True},
    ).json()
    assert shown["data"]["exposed_to_market"] is True
    market = qa.client.get(
        "/api/capability/market", params={"keyword": qa.token, "page_size": 50}
    ).json()["data"]["list"]
    assert any(item["id"] == capability_id for item in market)

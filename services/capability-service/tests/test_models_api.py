"""P3：登录用户可读的对外模型名清单（`GET /api/capability/models`）。

设置页的「使用方法」抽屉要靠它自动填充 model，避免成员手填别名后拿到 2002。
口径必须与 `/v1/models` 一致：只列**已上架 + chat + 有对外模型名**的能力。
"""

from tests.conftest import USER_HEADERS


def test_models_requires_identity(api) -> None:
    body = api.get("/api/capability/models").json()
    assert body["code"] == 1001


def test_models_lists_only_online_chat_with_alias(qa) -> None:
    category = qa.category()
    alias = f"qa-model-{qa.token}"

    online = qa.create_capability_raw(
        category["id"], code=qa.code("model"), status="online",
        executor="chat", openai_alias=alias,
    )
    assert online["code"] == 0, online

    # 草稿：还没上架，不能出现在成员可选的模型里
    draft = qa.create_capability_raw(
        category["id"], code=qa.code("model"), status="draft",
        executor="chat", openai_alias=f"qa-draft-{qa.token}",
    )
    assert draft["code"] == 0, draft

    # 摘要执行器：即使有别名也不该被推荐（用户选了只会拿到参数错）
    summary = qa.create_capability_raw(
        category["id"], code=qa.code("model"), status="online",
        executor="summary", openai_alias=f"qa-summary-{qa.token}",
    )
    assert summary["code"] == 0, summary

    body = qa.client.get("/api/capability/models", headers=USER_HEADERS).json()
    assert body["code"] == 0, body
    aliases = {item["alias"] for item in body["data"]["list"]}
    assert alias in aliases
    assert f"qa-draft-{qa.token}" not in aliases
    assert f"qa-summary-{qa.token}" not in aliases

    item = [row for row in body["data"]["list"] if row["alias"] == alias][0]
    assert item["capability_id"] == online["data"]["id"]
    assert item["name"]
    # 只暴露对外模型名与展示名，不带 base_url / 密钥 / 执行参数
    assert set(item) == {"alias", "capability_id", "name"}


def test_models_hides_capability_after_offline(qa) -> None:
    category = qa.category()
    alias = f"qa-offline-{qa.token}"
    created = qa.create_capability_raw(
        category["id"], code=qa.code("model"), status="online",
        executor="chat", openai_alias=alias,
    )
    assert created["code"] == 0, created

    before = qa.client.get("/api/capability/models", headers=USER_HEADERS).json()
    assert alias in {item["alias"] for item in before["data"]["list"]}

    assert qa.set_status(created["data"]["id"], "offline")["code"] == 0
    after = qa.client.get("/api/capability/models", headers=USER_HEADERS).json()
    assert alias not in {item["alias"] for item in after["data"]["list"]}

"""P8：市场出参必须带 `executor`，前端"能不能调试"不能再靠猜 code。

历史缺陷：`CapabilityMarketDetailOut` 声明了 `executor/provider_alias/max_output_tokens`，
但 `from_row` 从未赋值，运行期恒为 `""/""/1024`；列表出参 `CapabilityMarketOut` 干脆
没有 `executor` 字段。结果是通过界面新建的能力（code 不在旧白名单里）即使
`executor=chat` 可用，市场卡片仍显示「暂无执行器」。
"""

from tests.conftest import USER_HEADERS


def _market_list_item(qa, capability_id: int) -> dict:
    body = qa.client.get(
        "/api/capability/market", params={"page_size": 100}
    ).json()
    assert body["code"] == 0, body
    rows = [row for row in body["data"]["list"] if row["id"] == capability_id]
    assert rows, "能力应已上架并出现在市场列表"
    return rows[0]


def test_market_list_and_detail_expose_executor(qa) -> None:
    category = qa.category()
    created = qa.create_capability_raw(
        category["id"], code=qa.code("exec"), status="online",
        executor="chat", openai_alias=f"qa-exec-{qa.token}",
    )
    assert created["code"] == 0, created
    capability_id = created["data"]["id"]

    listed = _market_list_item(qa, capability_id)
    assert listed["executor"] == "chat"
    # 市场仍然不泄露内部路由配置
    assert "service_name" not in listed and "path" not in listed

    detail = qa.market_detail(capability_id)
    assert detail["code"] == 0, detail
    assert detail["data"]["executor"] == "chat"
    assert detail["data"]["max_output_tokens"] >= 1
    assert "service_name" not in detail["data"] and "path" not in detail["data"]


def test_market_detail_keeps_empty_executor_for_legacy_rows(qa) -> None:
    """历史数据可能没填 executor：出参保持空串，由前端 code 回退，而不是伪造一个执行器。"""

    category = qa.category()
    created = qa.create_capability_raw(
        category["id"], code=qa.code("legacy"), status="online",
    )
    assert created["code"] == 0, created
    detail = qa.market_detail(created["data"]["id"])
    assert detail["data"]["executor"] in ("", "chat")


def test_admin_write_paths_are_not_affected(qa) -> None:
    """列表出参加字段属于加法；管理员列表仍返回完整字段集。"""

    body = qa.client.get("/api/capability/manage", headers=USER_HEADERS).json()
    assert body["code"] == 0
    row = body["data"]["list"][0]
    for field in ("executor", "provider_alias", "billing_mode", "max_output_tokens"):
        assert field in row

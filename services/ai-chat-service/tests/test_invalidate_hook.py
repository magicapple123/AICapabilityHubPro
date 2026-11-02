"""A3 快速失效路径：管理接口改价后 ai-chat 必须立刻读到新价，不等 TTL。

为什么单独守护：`scripts/leader_e2e/checks.py` 走裸 SQL 改目录，天然绕过失效钩子
（只能靠 5s TTL 兜底），所以"capability 写操作 → POST
/internal/capability-cache/invalidate → 缓存真的被清"这条链路在别处没有任何覆盖。
钩子一旦接错，运营改价就会静默地继续按旧价结算。

断言的三步与"能区分好坏实现"的关键：
1. 预热缓存，并确认第二次读取不再打下游（证明真的命中缓存）；
2. 走真实 HTTP 端点发失效通知（capability-service 的管理接口就是这么调的）；
3. **不 sleep** 再读一次，必须是新价。TTL 还没过，只有"缓存被清"才能拿到新价。
另外用负向守护证明第 3 步的断言不是空转：失效端点回 200 但不清缓存时，同一断言必须失败。
"""

import asyncio

import pytest

from app.schemas.capability import CapabilityDefinition
from app.service.capability_client import CapabilityClient
from app.service.catalog_cache import catalog_cache
from tests.conftest import USER_HEADERS

CAPABILITY_ID = 4242
PRICE_BEFORE = 5
PRICE_AFTER = 9

# 负向守护与正向用例共用同一条文案，才能证明"同一条断言"会失败。
FRESH_PRICE_MESSAGE = "管理接口改价后必须立刻读到新价格（不得依赖 TTL 过期）"


def _definition(price: int) -> CapabilityDefinition:
    """构造一条在线能力的目录快照，只有价格随下标变化。"""

    return CapabilityDefinition(
        id=CAPABILITY_ID,
        code="chat-completions",
        status="online",
        param_schema={"type": "object"},
        price_per_call=price,
    )


class _CatalogStub:
    """扮演 capability-service 的目录：返回它当前持有的价格，并记录取快照次数。"""

    def __init__(self) -> None:
        self.price = PRICE_BEFORE
        self.downstream_fetches = 0

    async def fetch(self, capability_id: int) -> CapabilityDefinition:
        assert capability_id == CAPABILITY_ID
        self.downstream_fetches += 1
        return _definition(self.price)


def _served_price_after_management_change(
    api, monkeypatch, *, break_hook: bool = False
) -> tuple[int, int]:
    """预热 → 管理接口改价 → 立刻再读，返回 (ai-chat 拿到的价格, 下游取快照次数)。

    Args:
        api: FastAPI 测试客户端。
        monkeypatch: pytest 的 monkeypatch，用于替换下游取快照与失效实现。
        break_hook: 为 ``True`` 时把失效实现换成"回 200 但不清缓存"，
            用来验证断言具备区分能力。
    """

    catalog = _CatalogStub()
    client = CapabilityClient()
    monkeypatch.setattr(client, "_fetch_uncached", catalog.fetch)

    # 1. 预热：首次取快照后进入缓存，第二次读取不再打下游。
    assert asyncio.run(client.fetch(CAPABILITY_ID)).price_per_call == PRICE_BEFORE
    assert asyncio.run(client.fetch(CAPABILITY_ID)).price_per_call == PRICE_BEFORE
    assert catalog.downstream_fetches == 1

    # 2. 改价落库后，capability-service 会调到这里；端点必须回 200 且报告清掉了 1 条。
    catalog.price = PRICE_AFTER
    if break_hook:
        # 最像"钩子接错"的真实故障：端点成功返回，但缓存根本没动。
        monkeypatch.setattr(catalog_cache, "invalidate", lambda capability_id=None: 1)
    body = api.post(
        "/internal/capability-cache/invalidate",
        headers=USER_HEADERS,
        json={"capability_id": CAPABILITY_ID},
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["removed"] == 1, body

    # 3. 不等待：TTL 尚未过期，只有缓存真被清才可能拿到新价。
    return asyncio.run(client.fetch(CAPABILITY_ID)).price_per_call, catalog.downstream_fetches


def test_management_price_change_is_visible_without_waiting_for_the_ttl(api, monkeypatch):
    """改价后**立刻**（≤1ms，无 sleep）读到新价，且确实重新取了一次快照。"""

    price, fetches = _served_price_after_management_change(api, monkeypatch)
    assert price == PRICE_AFTER, FRESH_PRICE_MESSAGE
    assert fetches == 2, "缓存被清后必须重新取一次快照，而不是继续复用旧行"


def test_the_same_assertion_fails_when_invalidation_does_not_clear_the_cache(
    api, monkeypatch
):
    """负向守护：钩子只回 200 不清缓存时，上面那条断言必须失败。"""

    price, fetches = _served_price_after_management_change(api, monkeypatch, break_hook=True)
    # 故障态下的可观察事实：仍在 TTL 内提供旧价，且没有重新取快照。
    assert (price, fetches) == (PRICE_BEFORE, 1)
    with pytest.raises(AssertionError, match="立刻读到新价格"):
        assert price == PRICE_AFTER, FRESH_PRICE_MESSAGE


def test_endpoint_without_capability_id_clears_every_cached_entry(api):
    """不带 capability_id 时清空全部快照（运营批量改价后的兜底路径）。"""

    catalog_cache.put(1, "cached-one")
    catalog_cache.put(2, "cached-two")
    body = api.post(
        "/internal/capability-cache/invalidate", headers=USER_HEADERS, json={}
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["removed"] == 2
    assert catalog_cache.get(1) is None and catalog_cache.get(2) is None


def test_endpoint_rejects_a_request_without_a_trusted_identity(api):
    """内部接口不接受匿名失效请求：缺少 X-User-Id 时回 1001，且不清缓存。"""

    catalog_cache.put(1, "cached-one")
    body = api.post(
        "/internal/capability-cache/invalidate", json={"capability_id": 1}
    ).json()
    assert body["code"] == 1001, body
    assert catalog_cache.get(1) == "cached-one"

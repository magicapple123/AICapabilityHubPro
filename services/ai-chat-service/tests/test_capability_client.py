import asyncio
import importlib
import pytest
import httpx
from app.core.capability_config import capability_settings
from app.core.exceptions import BizException
from app.service.capability_client import CapabilityClient
from app.service.catalog_cache import OpenAIModelCatalog

module = importlib.import_module("app.service.capability_client")


def payload(**changes):
    return {"id": 1, "code": "chat-completions", "status": "online",
            "price_per_call": 5, "param_schema": {"type": "object"}, **changes}


def test_internal_read_caches_for_five_seconds_then_refreshes(monkeypatch):
    calls = []
    async def read(service, method, path):
        calls.append((service, method, path))
        return payload(price_per_call=len(calls))
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "internal")
    monkeypatch.setattr(module, "call_internal", read)
    client = CapabilityClient()
    # A3：5 秒内命中缓存（只打一次目录服务），主动失效后重新读取。
    from app.service.catalog_cache import catalog_cache

    assert asyncio.run(client.fetch(1)).price_per_call == 1
    assert asyncio.run(client.fetch(1)).price_per_call == 1
    assert calls == [("capability-service", "GET", "/internal/capability/1")]
    catalog_cache.invalidate(1)
    assert asyncio.run(client.fetch(1)).price_per_call == 2
    assert calls == [("capability-service", "GET", "/internal/capability/1")] * 2


def test_openai_model_directory_uses_shared_cache_and_invalidation(monkeypatch):
    calls = []

    async def read(service, method, path):
        calls.append((service, method, path))
        return [
            {"id": 42, "openai_alias": "qa-live-model"},
            {"id": 7, "openai_alias": None},
        ]

    from app.service.catalog_cache import catalog_cache

    catalog_cache.clear()
    monkeypatch.setattr(module, "call_internal", read)
    client = CapabilityClient()

    assert asyncio.run(client.openai_model_catalog()) == OpenAIModelCatalog(
        {"qa-live-model": 42}, frozenset({42, 7})
    )
    assert asyncio.run(client.openai_model_catalog()) == OpenAIModelCatalog(
        {"qa-live-model": 42}, frozenset({42, 7})
    )
    assert calls == [(
        "capability-service", "GET", "/internal/capability/openai-models"
    )]

    catalog_cache.invalidate(42)
    assert asyncio.run(client.openai_model_catalog()) == OpenAIModelCatalog(
        {"qa-live-model": 42}, frozenset({42, 7})
    )
    assert len(calls) == 2
    catalog_cache.clear()


def test_openai_model_directory_single_flight_on_concurrent_cache_miss(monkeypatch):
    calls = []

    async def read(service, method, path):
        calls.append((service, method, path))
        await asyncio.sleep(0.01)
        return [{"id": 42, "openai_alias": "qa-live-model"}]

    from app.service.catalog_cache import catalog_cache

    catalog_cache.clear()
    monkeypatch.setattr(module, "call_internal", read)
    client = CapabilityClient()

    async def resolve_many():
        return await asyncio.gather(*(client.openai_model_catalog() for _ in range(10)))

    results = asyncio.run(resolve_many())

    assert all(item.aliases == {"qa-live-model": 42} for item in results)
    assert calls == [(
        "capability-service", "GET", "/internal/capability/openai-models"
    )]
    catalog_cache.clear()


@pytest.mark.parametrize("changes,code", [({"status": "offline"}, 2002), ({"status": "draft"}, 2002),
    ({"is_deleted": 1}, 2002), ({"id": 2}, 4002), ({"price_per_call": -1}, 4002),
    ({"price_per_call": True}, 4002), ({"price_per_call": "5"}, 4002), ({"param_schema": None}, 4002)])
def test_bad_catalog_snapshot_fails_closed(monkeypatch, changes, code):
    async def read(*args): return payload(**changes)
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "internal")
    monkeypatch.setattr(module, "call_internal", read)
    with pytest.raises(BizException) as error: asyncio.run(CapabilityClient().fetch(1))
    assert error.value.code == code


def test_internal_failure_does_not_fallback_to_market(monkeypatch):
    async def fail(*args): raise BizException(4003, "missing internal interface")
    async def forbidden(*args): raise AssertionError("Must not auto-fallback")
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "internal")
    monkeypatch.setattr(module, "call_internal", fail)
    monkeypatch.setattr(CapabilityClient, "_market_detail", forbidden)
    with pytest.raises(BizException) as error: asyncio.run(CapabilityClient().fetch(1))
    assert error.value.code == 4002


def patch_client(monkeypatch, handler):
    """把共享 client 换成挂 MockTransport 的替身：只验请求形状，不打真网络。"""

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def get_client():
        return client

    monkeypatch.setattr(module, "get_http_client", get_client)
    return client


def test_explicit_market_compatibility_reads_only_published_detail(monkeypatch):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"code": 0, "data": {
            key: value for key, value in payload().items() if key != "status"},
            "message": "ok", "requestId": "catalog"})
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "market")
    monkeypatch.setattr(module.nacos_register, "discover_one", lambda name: "http://catalog.test")
    patch_client(monkeypatch, handler)
    result = asyncio.run(CapabilityClient().fetch(1))
    assert result.status == "online" and result.catalog_source == "market"
    assert seen == ["http://catalog.test/api/capability/market/1"]


def test_market_not_found_is_not_executable(monkeypatch):
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "market")
    monkeypatch.setattr(module.nacos_register, "discover_one", lambda name: "http://catalog.test")
    patch_client(monkeypatch, lambda req: httpx.Response(
        200, json={"code": 2002, "data": None}))
    with pytest.raises(BizException) as error: asyncio.run(CapabilityClient().fetch(1))
    assert error.value.code == 2002

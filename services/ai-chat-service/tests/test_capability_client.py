import asyncio
import importlib
import pytest
import httpx
from app.core.capability_config import capability_settings
from app.core.exceptions import BizException
from app.service.capability_client import CapabilityClient

module = importlib.import_module("app.service.capability_client")


def payload(**changes):
    return {"id": 1, "code": "chat-completions", "status": "online",
            "price_per_call": 5, "param_schema": {"type": "object"}, **changes}


def test_internal_read_is_fresh_and_uses_only_fixed_service_path(monkeypatch):
    calls = []
    async def read(service, method, path):
        calls.append((service, method, path))
        return payload(price_per_call=len(calls))
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "internal")
    monkeypatch.setattr(module, "call_internal", read)
    client = CapabilityClient()
    assert asyncio.run(client.fetch(1)).price_per_call == 1
    assert asyncio.run(client.fetch(1)).price_per_call == 2
    assert calls == [("capability-service", "GET", "/internal/capability/1")] * 2


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


def test_explicit_market_compatibility_reads_only_published_detail(monkeypatch):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"code": 0, "data": {
            key: value for key, value in payload().items() if key != "status"},
            "message": "ok", "requestId": "catalog"})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "market")
    monkeypatch.setattr(module.nacos_register, "discover_one", lambda name: "http://catalog.test")
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    result = asyncio.run(CapabilityClient().fetch(1))
    assert result.status == "online" and result.catalog_source == "market"
    assert seen == ["http://catalog.test/api/capability/market/1"]


def test_market_not_found_is_not_executable(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(capability_settings, "capability_catalog_mode", "market")
    monkeypatch.setattr(module.nacos_register, "discover_one", lambda name: "http://catalog.test")
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"code": 2002, "data": None}))))
    with pytest.raises(BizException) as error: asyncio.run(CapabilityClient().fetch(1))
    assert error.value.code == 2002

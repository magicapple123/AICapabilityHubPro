"""进程级 HTTP 连接复用（`app/core/http_client.py`）的行为约束。

覆盖四个必须成立的断言：
1. 同一事件循环内多次 `get_http_client()` 返回**同一个**对象（连接池只有一份）；
2. `close_http_client()` 之后重建新对象，旧对象确实被关闭；
3. 事件循环变化时自动重建（跨循环复用连接池会抛 `Event loop is closed`）；
4. `call_internal` 在多次调用中**只建一个 client**，且不会把它关掉
   —— 这一条直接防"call site 用完就 close 共享 client"的回归。
"""

import asyncio

import httpx
import pytest

from app.core import http_client, service_call


@pytest.fixture(autouse=True)
def _reset_singleton():
    """单例是模块级全局，用例之间必须复位，否则顺序会影响结果。"""

    http_client._client = None
    http_client._client_loop = None
    http_client._lock = None
    http_client._lock_loop = None
    yield
    http_client._client = None
    http_client._client_loop = None
    http_client._lock = None
    http_client._lock_loop = None


def test_same_loop_returns_same_client():
    async def run():
        first = await http_client.get_http_client()
        second = await http_client.get_http_client()
        assert first is second
        assert not first.is_closed
        assert first.trust_env is False
        await http_client.close_http_client()

    asyncio.run(run())


def test_close_then_get_builds_a_new_client():
    async def run():
        first = await http_client.get_http_client()
        await http_client.close_http_client()
        assert first.is_closed
        second = await http_client.get_http_client()
        assert second is not first
        assert not second.is_closed
        await http_client.close_http_client()

    asyncio.run(run())


def test_close_is_idempotent():
    async def run():
        await http_client.get_http_client()
        await http_client.close_http_client()
        # 第二次关闭不应抛错（lifespan 与测试兜底可能各调一次）。
        await http_client.close_http_client()

    asyncio.run(run())


def test_new_event_loop_rebuilds_the_client():
    async def build():
        return await http_client.get_http_client()

    first = asyncio.run(build())
    second = asyncio.run(build())
    assert first is not second
    assert http_client._client is second


def test_call_internal_builds_and_keeps_one_client(monkeypatch):
    built = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"ok": True}})

    def fake_new_client() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        built.append(client)
        return client

    monkeypatch.setattr(http_client, "_new_client", fake_new_client)
    monkeypatch.setattr(
        service_call.nacos_register, "discover_one", lambda name: "http://downstream.test"
    )

    async def run():
        for _ in range(3):
            assert await service_call.call_internal(
                "demo-service", "GET", "/internal/demo"
            ) == {"ok": True}
        client = await http_client.get_http_client()
        # 共享 client 必须仍然可用：call site 一旦 close 它，下一次调用就要重新握手。
        assert not client.is_closed
        await http_client.close_http_client()

    asyncio.run(run())
    assert len(built) == 1


def test_call_internal_passes_per_request_timeout(monkeypatch):
    """超时按调用点逐请求传，不被 client 上的兜底值覆盖。"""

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"code": 0, "data": None})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(http_client, "_client", client)
    monkeypatch.setattr(
        service_call.nacos_register, "discover_one", lambda name: "http://downstream.test"
    )

    async def run():
        # _client_loop 必须指向当前循环，get_http_client 才会直接复用这个替身。
        http_client._client_loop = asyncio.get_running_loop()
        await service_call.call_internal(
            "demo-service", "POST", "/internal/demo", timeout=2.5
        )

    asyncio.run(run())
    assert seen["timeout"]["read"] == 2.5

"""A3 目录缓存：TTL 5 秒、命中复用、主动失效。"""

import time

import pytest

from app.service import catalog_cache as module
from app.service.catalog_cache import CatalogCache


def test_hit_within_ttl():
    cache = CatalogCache(ttl=5.0)
    cache.put(1, {"price": 5})
    assert cache.get(1) == {"price": 5}


def test_miss_when_absent():
    assert CatalogCache().get(99) is None


def test_expires_after_ttl(monkeypatch):
    cache = CatalogCache(ttl=5.0)
    cache.put(1, "v1")
    real = time.monotonic
    monkeypatch.setattr(module.time, "monotonic", lambda: real() + 6)
    assert cache.get(1) is None


def test_invalidate_single_and_all():
    cache = CatalogCache()
    cache.put(1, "a")
    cache.put(2, "b")
    assert cache.invalidate(1) == 1
    assert cache.get(1) is None and cache.get(2) == "b"
    assert cache.invalidate() == 1
    assert cache.get(2) is None


def test_invalidate_unknown_is_noop():
    assert CatalogCache().invalidate(404) == 0


@pytest.mark.anyio if False else pytest.mark.usefixtures()
def _noop():
    return None


def test_fetch_populates_the_shared_cache(monkeypatch):
    """第一次 fetch 后，共享缓存里就有这条能力；再次 get 直接命中。"""

    from app.schemas.capability import CapabilityDefinition
    from app.service.capability_client import CapabilityClient
    from app.service.catalog_cache import catalog_cache

    catalog_cache.clear()
    client = CapabilityClient()
    calls: list[int] = []

    async def fake(_capability_id):
        calls.append(_capability_id)
        return CapabilityDefinition(
            id=7, code="chat-completions", status="online",
            param_schema={"type": "object"}, price_per_call=5,
        )

    monkeypatch.setattr(client, "_fetch_uncached", fake)
    import asyncio

    asyncio.run(client.fetch(7))
    assert calls == [7]
    assert catalog_cache.get(7) is not None
    catalog_cache.clear()

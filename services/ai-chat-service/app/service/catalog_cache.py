"""目录快照缓存（A3）：TTL 5 秒 + 主动失效。

为什么不缓存更久：改价后必须尽快生效。5 秒是"扛住突发 QPS"与"改价窗口可接受"
之间的折中；运营改价/上下架时 capability 会调失效接口，把窗口压到接近 0。

失效是**尽力而为**：通知失败只记日志，靠 TTL 兜底，绝不让写操作因为
ai-chat 不可用而失败。
"""

import time
from dataclasses import dataclass

from loguru import logger

from app.core.observability import CATALOG_CACHE_EVENTS

TTL_SECONDS = 5.0


@dataclass
class _Entry:
    expires_at: float
    value: object


@dataclass(frozen=True)
class OpenAIModelCatalog:
    aliases: dict[str, int]
    capability_ids: frozenset[int]


class CatalogCache:
    def __init__(self, ttl: float = TTL_SECONDS) -> None:
        self._ttl = ttl
        self._store: dict[int, _Entry] = {}
        self._openai_models: _Entry | None = None

    def get(self, capability_id: int):
        entry = self._store.get(capability_id)
        if entry is None:
            CATALOG_CACHE_EVENTS.labels(service="ai-chat-service", result="miss").inc()
            return None
        if entry.expires_at <= time.monotonic():
            self._store.pop(capability_id, None)
            CATALOG_CACHE_EVENTS.labels(service="ai-chat-service", result="expired").inc()
            return None
        CATALOG_CACHE_EVENTS.labels(service="ai-chat-service", result="hit").inc()
        return entry.value

    def put(self, capability_id: int, value: object) -> None:
        self._store[capability_id] = _Entry(time.monotonic() + self._ttl, value)

    def get_openai_models(self) -> OpenAIModelCatalog | None:
        entry = self._openai_models
        if entry is None:
            CATALOG_CACHE_EVENTS.labels(service="ai-chat-service", result="models-miss").inc()
            return None
        if entry.expires_at <= time.monotonic():
            self._openai_models = None
            CATALOG_CACHE_EVENTS.labels(service="ai-chat-service", result="models-expired").inc()
            return None
        CATALOG_CACHE_EVENTS.labels(service="ai-chat-service", result="models-hit").inc()
        return entry.value  # type: ignore[return-value]

    def put_openai_models(self, value: OpenAIModelCatalog) -> None:
        self._openai_models = _Entry(time.monotonic() + self._ttl, value)

    def invalidate(self, capability_id: int | None = None) -> int:
        """失效单个能力或全部；返回清掉的条数。"""

        if self._openai_models is not None:
            self._openai_models = None
            CATALOG_CACHE_EVENTS.labels(
                service="ai-chat-service", result="models-invalidated"
            ).inc()

        if capability_id is None:
            removed = len(self._store)
            self._store.clear()
        else:
            removed = 1 if self._store.pop(capability_id, None) is not None else 0
        if removed:
            CATALOG_CACHE_EVENTS.labels(service="ai-chat-service", result="invalidated").inc(
                removed
            )
            logger.info("目录缓存已失效 capability_id={} removed={}", capability_id, removed)
        return removed

    def clear(self) -> None:
        self._store.clear()
        self._openai_models = None


catalog_cache = CatalogCache()

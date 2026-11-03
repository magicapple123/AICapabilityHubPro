"""按用户的令牌桶限流（A4）。

为什么放在 ai-chat 而不是网关：网关只认识 IP 与全局 QPS，只有执行层知道
"这个请求属于哪个平台用户、要花多少积分"。放在这里才能做到按用户的公平性。

设计取舍：
- **进程内内存**：本服务是多 worker 部署，实际是"每 worker 一份桶"，
  真实速率 ≈ 配置值 × worker 数。这是有意的近似——要精确全局限流需要 Redis，
  当前规模引入外部依赖不值当，已在此注明。
- **令牌桶而非固定窗口**：允许短时突发（burst），避免"整点一到全部拒绝"。
- 拒绝码用 `4001`（平台错误码总表里的"限流"，与网关 Sentinel 限流同一口径）。
  早期实现用过 `2009`，但 2xxx 属于目录/参数类，客户端会误判为业务参数错误；
  A4 需求也明确"超限 4001"，故已纠正（见 `docs/api-contract/pro-shared.md` 错误码总表）。
- 响应体是标准 Result（HTTP 200 + `code=4001`），消息里带"稍后再试"的指引；
  网关对外仍按 429 语义翻译（见 `openai_compat.py` 的 `4001 → 429`）。
"""

import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.exceptions import BizException
from app.core.observability import RATE_LIMITED

#: 平台错误码总表：4001 = 触发限流（客户端应退避重试，不应视为参数错误）。
RATE_LIMIT_CODE = 4001
RATE_LIMIT_MESSAGE = "请求过于频繁，请稍后再试"


@dataclass
class _Bucket:
    tokens: float
    updated_at: float = field(default_factory=time.monotonic)


class UserRateLimiter:
    """每个用户一个桶；空闲用户会被惰性清理，避免长期运行内存膨胀。"""

    def __init__(self, qps: float = 5.0, burst: int = 10, idle_seconds: float = 300.0) -> None:
        self._qps = max(0.1, qps)
        self._capacity = max(1.0, float(burst))
        self._idle = idle_seconds
        self._buckets: dict[str, _Bucket] = {}

    def configure(self, qps: float, burst: int) -> None:
        self._qps = max(0.1, qps)
        self._capacity = max(1.0, float(burst))

    def _evict(self, now: float) -> None:
        if len(self._buckets) < 1000:
            return
        stale = [k for k, b in self._buckets.items() if now - b.updated_at > self._idle]
        for key in stale:
            self._buckets.pop(key, None)

    def acquire(self, user_id: str, cost: float = 1.0) -> None:
        """消耗一个令牌；不足则抛 4001。`cost` 预留给按 token 计费的场景。"""

        if not settings.rate_limit_enabled:
            return
        now = time.monotonic()
        self._evict(now)
        bucket = self._buckets.get(user_id)
        if bucket is None:
            bucket = _Bucket(tokens=self._capacity)
            self._buckets[user_id] = bucket
        else:
            elapsed = now - bucket.updated_at
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._qps)
            bucket.updated_at = now
        if bucket.tokens < cost:
            RATE_LIMITED.labels(service="ai-chat-service").inc()
            raise BizException(RATE_LIMIT_CODE, RATE_LIMIT_MESSAGE)
        bucket.tokens -= cost

    def reset(self) -> None:
        self._buckets.clear()


rate_limiter = UserRateLimiter()

"""按供应商 alias 的最简熔断（P16）。

状态机：`closed` →（连续 N 次失败）→ `open` →（冷却 M 秒）→ `half_open`
→（探测成功）`closed` /（探测失败）重新 `open`。

只统计"上游真的坏了"的失败：5xx、超时、连接/协议错误。429（限流）与
401/402/403（鉴权/欠费）**不计入**——一把过期 Key 不该把整个供应商永久熔断，
这类故障本就有独立错误码（5003/5004）与告警路径。

被熔断拒绝的调用抛 `BizException(5005)`：它走既有失败语义（写 `failed` 占位消息、
不产生账单、不扣分），因此**一次调用仍然只有一条账单、一次扣分**。

已知限制（口径与实现一致，勿再夸大）：

1. **状态只在进程内**：`UVICORN_WORKERS=N` 时每个 worker 各自计数，真实的打开阈值
   ≈ N × `PROVIDER_BREAKER_FAILURE_THRESHOLD`，冷却也各自计时。要跨 worker 共享需要
   Redis 之类的共享存储（与 A4 令牌桶同一局限），不在本轮范围。
2. **不做指数退避**：每次打开都把冷却重置为 M 秒，反复失败会持续续期。
3. **半开只放一个探测**：同一 alias 在探测进行中时，其余请求继续被拒绝，
   避免恢复瞬间被并发打满。

指标：`provider_breaker_state`（Gauge，0=closed 1=half_open 2=open）、
`provider_breaker_trips_total`（Counter）、`provider_breaker_rejected_total`（Counter），
均注册在 `app.core.observability.REGISTRY`，由 `/metrics` 直接暴露。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from loguru import logger
from prometheus_client import Counter, Gauge

from app.core.config import settings
from app.core.exceptions import BizException
from app.core.observability import REGISTRY

CLOSED = "closed"
HALF_OPEN = "half_open"
OPEN = "open"

#: 熔断拒绝使用的错误码；与"上游故障"同码，客户端已有对应话术。
BREAKER_CODE = 5005

#: 计入熔断的失败错误码：上游 5xx、超时、响应不可解析（多为连接被中断）。
_COUNTED_ERROR_CODES = frozenset({5001, 5002, 5005})

_SERVICE = settings.service_name

STATE_GAUGE = Gauge(
    "provider_breaker_state",
    "供应商熔断状态（0=closed 1=half_open 2=open）",
    ["service", "provider"],
    registry=REGISTRY,
)
TRIPS = Counter(
    "provider_breaker_trips_total", "供应商熔断打开次数", ["service", "provider"], registry=REGISTRY,
)
REJECTED = Counter(
    "provider_breaker_rejected_total", "被熔断直接拒绝的调用数",
    ["service", "provider"], registry=REGISTRY,
)

_STATE_VALUE = {CLOSED: 0, HALF_OPEN: 1, OPEN: 2}


@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float | None = None
    probing: bool = False


class ProviderBreaker:
    """进程内熔断器；所有状态操作都在同一把同步锁里，不做 await。"""

    def __init__(self) -> None:
        self._states: dict[str, _BreakerState] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 配置读取
    @staticmethod
    def _enabled() -> bool:
        return bool(getattr(settings, "provider_breaker_enabled", True))

    @staticmethod
    def _threshold() -> int:
        return int(getattr(settings, "provider_breaker_failure_threshold", 5) or 5)

    @staticmethod
    def _cooldown() -> float:
        return float(getattr(settings, "provider_cooldown_seconds", 30.0) or 30.0)

    # ---------------------------------------------------------------- 对外接口
    def guard(self, key: str | None) -> None:
        """调用前检查；放行返回 None，处于熔断状态时抛 `BizException(5005)`。

        `key` 为空表示"没有绑定供应商"（走全局配置），不参与熔断。
        """

        if not key or not self._enabled():
            return
        rejected_seconds = 0.0
        with self._lock:
            state = self._states.get(key)
            if state is None or state.opened_at is None:
                return
            elapsed = time.monotonic() - state.opened_at
            cooldown = self._cooldown()
            if elapsed < cooldown:
                rejected_seconds = cooldown - elapsed
            elif state.probing:
                # 半开期间已有探测在跑，其余请求继续快速失败。
                rejected_seconds = cooldown
            else:
                state.probing = True
                self._set_gauge(key, HALF_OPEN)
                logger.info("供应商熔断进入半开探测 provider={}", key)
                return
            self._set_gauge(key, OPEN)

        REJECTED.labels(service=_SERVICE, provider=key).inc()
        raise BizException(
            BREAKER_CODE,
            f"供应商 {key} 近期连续失败，已熔断，请在 {max(1, int(rejected_seconds))} 秒后重试",
        )

    def record_success(self, key: str | None) -> None:
        """一次成功的上游调用：清空计数并关闭熔断。"""

        if not key or not self._enabled():
            return
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return
            was_open = state.opened_at is not None
            state.failures = 0
            state.opened_at = None
            state.probing = False
            self._set_gauge(key, CLOSED)
        if was_open:
            logger.info("供应商熔断恢复 provider={}", key)

    def record_failure(self, key: str | None, error_code: int | None = None) -> None:
        """一次失败的上游调用：只有 5xx/超时/连接错计入（`error_code` 为空则计入）。"""

        if not key or not self._enabled():
            return
        if error_code is not None and int(error_code) not in _COUNTED_ERROR_CODES:
            # 限流与鉴权不是"供应商坏了"，只解除探测标记，不累加失败数。
            with self._lock:
                state = self._states.get(key)
                if state is not None:
                    state.probing = False
            return
        tripped = False
        with self._lock:
            state = self._states.setdefault(key, _BreakerState())
            state.probing = False
            if state.opened_at is not None:
                # 半开探测失败：重新打开并续期冷却。
                state.opened_at = time.monotonic()
                tripped = True
            else:
                state.failures += 1
                if state.failures >= self._threshold():
                    state.opened_at = time.monotonic()
                    tripped = True
            if tripped:
                self._set_gauge(key, OPEN)
        if tripped:
            TRIPS.labels(service=_SERVICE, provider=key).inc()
            logger.warning(
                "供应商熔断打开 provider={} threshold={} cooldown={}s",
                key, self._threshold(), self._cooldown(),
            )

    def state(self, key: str | None) -> str:
        """当前状态（用于测试与排障）；冷却已过但未探测时视为 half_open。"""

        if not key:
            return CLOSED
        with self._lock:
            state = self._states.get(key)
            if state is None or state.opened_at is None:
                return CLOSED
            if time.monotonic() - state.opened_at >= self._cooldown():
                return HALF_OPEN
            return OPEN

    def snapshot(self) -> dict[str, str]:
        """所有已知 alias 的状态快照，便于排障接口/日志使用。"""

        with self._lock:
            keys = list(self._states)
        return {key: self.state(key) for key in keys}

    def reset(self) -> None:
        """清空全部状态（测试与运维手工恢复用）。"""

        with self._lock:
            keys = list(self._states)
            self._states.clear()
        for key in keys:
            STATE_GAUGE.labels(service=_SERVICE, provider=key).set(0)

    # ---------------------------------------------------------------- 内部
    def _set_gauge(self, key: str, state: str) -> None:
        # 指标写入绝不能影响业务：prometheus 客户端本身不会抛业务异常，
        # 但多进程/重复注册的历史问题值得一层保护。
        try:
            STATE_GAUGE.labels(service=_SERVICE, provider=key).set(_STATE_VALUE[state])
        except Exception:  # noqa: BLE001 - 观测失败不阻断调用
            pass


provider_breaker = ProviderBreaker()

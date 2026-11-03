"""P16：按供应商 alias 的熔断 + 整体超时预算。

断言三件事：
1. 连续 N 次 5xx/超时 → 打开；打开期间调用在毫秒级失败（`BizException(5005)`），不打上游；
2. 冷却后半开探测：成功即恢复，失败继续打开；限流/鉴权不算"供应商坏了"；
3. 整体预算把单次尝试超时压到"剩余预算"，预算耗尽后不再发起上游请求。
"""

import asyncio
import time
from importlib import import_module

import pytest
from prometheus_client import generate_latest

from app.core.deadline import Deadline
from app.core.exceptions import BizException
from app.core.observability import REGISTRY
from app.core.provider_breaker import provider_breaker

# 模块级 monkeypatch 必须拿到模块对象（包导出的同名属性是单例实例）。
model_client_module = import_module("app.service.model_client")

ALIAS = "qa-breaker"


@pytest.fixture(autouse=True)
def fast_breaker(monkeypatch):
    """阈值调小、冷却调短，避免用例变慢；每个用例前后清空状态。"""

    monkeypatch.setattr(model_client_module.settings, "provider_breaker_enabled", True)
    monkeypatch.setattr(model_client_module.settings, "provider_breaker_failure_threshold", 3)
    monkeypatch.setattr(model_client_module.settings, "provider_cooldown_seconds", 1)
    provider_breaker.reset()
    yield
    provider_breaker.reset()


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class _Client:
    """记录调用次数与超时，用于断言"熔断后不再打上游"与"预算压缩超时"。"""

    calls = 0
    timeouts: list[float] = []

    async def post(self, url, **kwargs):
        _Client.calls += 1
        _Client.timeouts.append(kwargs.get("timeout"))
        body = {
            "model": "m",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        return _Response(200, body)


@pytest.fixture()
def fake_http(monkeypatch):
    _Client.calls = 0
    _Client.timeouts = []

    async def get_client():
        return _Client()

    monkeypatch.setattr(model_client_module, "get_http_client", get_client)
    monkeypatch.setattr(model_client_module, "RETRY_BACKOFF_SECONDS", 0)
    return _Client


def _complete(**kwargs):
    return asyncio.run(model_client_module.model_client.complete(
        [{"role": "user", "content": "hi"}], model="m", temperature=0.1,
        base_url="https://api.example.com/v1", api_key="k", **kwargs,
    ))


# ---------------------------------------------------------------- 状态机


def test_consecutive_failures_open_the_breaker():
    for _ in range(3):
        provider_breaker.record_failure(ALIAS, 5005)

    assert provider_breaker.state(ALIAS) == "open"
    with pytest.raises(BizException) as error:
        provider_breaker.guard(ALIAS)
    assert error.value.code == 5005
    assert ALIAS in error.value.message


def test_success_resets_failure_count():
    provider_breaker.record_failure(ALIAS, 5005)
    provider_breaker.record_failure(ALIAS, 5005)
    provider_breaker.record_success(ALIAS)
    provider_breaker.record_failure(ALIAS, 5005)

    assert provider_breaker.state(ALIAS) == "closed"
    provider_breaker.guard(ALIAS)


def test_rate_limit_and_auth_failures_do_not_trip_breaker():
    """429/401 不是"供应商坏了"，否则一把过期 Key 会把供应商永久熔断。"""

    for _ in range(10):
        provider_breaker.record_failure(ALIAS, 5003)
        provider_breaker.record_failure(ALIAS, 5004)

    assert provider_breaker.state(ALIAS) == "closed"


def test_cooldown_opens_half_open_then_success_closes(monkeypatch):
    monkeypatch.setattr(model_client_module.settings, "provider_cooldown_seconds", 0.01)
    for _ in range(3):
        provider_breaker.record_failure(ALIAS, 5005)
    assert provider_breaker.state(ALIAS) == "open"

    time.sleep(0.02)
    assert provider_breaker.state(ALIAS) == "half_open"
    # 半开放行一个探测。
    provider_breaker.guard(ALIAS)
    provider_breaker.record_success(ALIAS)
    assert provider_breaker.state(ALIAS) == "closed"


def test_half_open_probe_blocks_concurrent_requests(monkeypatch):
    monkeypatch.setattr(model_client_module.settings, "provider_cooldown_seconds", 0.01)
    for _ in range(3):
        provider_breaker.record_failure(ALIAS, 5005)
    time.sleep(0.02)

    provider_breaker.guard(ALIAS)  # 第一个请求成为探测
    with pytest.raises(BizException) as error:
        provider_breaker.guard(ALIAS)
    assert error.value.code == 5005


def test_failed_probe_reopens_breaker(monkeypatch):
    monkeypatch.setattr(model_client_module.settings, "provider_cooldown_seconds", 0.01)
    for _ in range(3):
        provider_breaker.record_failure(ALIAS, 5005)
    time.sleep(0.02)
    provider_breaker.guard(ALIAS)
    provider_breaker.record_failure(ALIAS, 5005)

    assert provider_breaker.state(ALIAS) == "open"


def test_open_breaker_exposed_in_metrics():
    for _ in range(3):
        provider_breaker.record_failure(ALIAS, 5005)

    metrics = generate_latest(REGISTRY).decode("utf-8")
    assert "provider_breaker_state" in metrics
    line = next(
        item for item in metrics.splitlines()
        if item.startswith("provider_breaker_state") and ALIAS in item
    )
    assert line.rstrip().endswith(" 2.0")  # 2 = open
    assert "provider_breaker_trips_total" in metrics


# ---------------------------------------------------------------- 与调用链的配合


def test_open_breaker_fails_fast_without_calling_upstream(fake_http):
    for _ in range(3):
        provider_breaker.record_failure(ALIAS, 5005)

    started = time.perf_counter()
    with pytest.raises(BizException) as error:
        _complete(breaker_key=ALIAS)
    elapsed = time.perf_counter() - started

    assert error.value.code == 5005
    assert fake_http.calls == 0
    assert elapsed < 0.5  # 毫秒级，不是 30s × 2


def test_execute_prepared_short_circuits_when_breaker_open(fake_http):
    """执行器层同样在毫秒级失败：抛 5005，交给既有失败路径（写 failed 占位、不计费）。"""

    from types import SimpleNamespace

    from app.schemas.capability import CapabilityDefinition
    from app.schemas.chat import ChatCompletionRequest
    from app.service import capability_adapters

    definition = CapabilityDefinition(
        id=1, code="chat-completions", status="online",
        param_schema={"type": "object"}, price_per_call=5,
        executor="chat", provider_alias=ALIAS,
    )
    request = ChatCompletionRequest(
        capability_id=1, input={"messages": [{"role": "user", "content": "hi"}]},
    )
    execution = capability_adapters.prepare_execution(definition, request)
    provider = SimpleNamespace(
        alias=ALIAS, protocol="openai-chat", base_url="https://api.example.com/v1",
        api_key="k", model="m", timeout=5.0, target=None,
    )
    for _ in range(3):
        provider_breaker.record_failure(ALIAS, 5005)

    with pytest.raises(BizException) as error:
        asyncio.run(capability_adapters.execute_prepared(
            execution, runtime=SimpleNamespace(use_mock=False),
            model_client=model_client_module.model_client, provider=provider,
            definition=definition,
        ))
    assert error.value.code == 5005
    assert fake_http.calls == 0


def test_upstream_failures_trip_breaker_through_call_path(fake_http, monkeypatch):
    class _Always500(_Client):
        async def post(self, url, **kwargs):
            _Client.calls += 1
            return _Response(500)

    async def get_client():
        return _Always500()

    monkeypatch.setattr(model_client_module, "get_http_client", get_client)

    for _ in range(3):
        reply = _complete(breaker_key=ALIAS)
        assert reply.degraded and reply.error_code == 5005

    assert provider_breaker.state(ALIAS) == "open"


def test_success_through_call_path_keeps_breaker_closed(fake_http):
    reply = _complete(breaker_key=ALIAS)
    assert reply.content == "ok"
    assert provider_breaker.state(ALIAS) == "closed"


# ---------------------------------------------------------------- 超时预算


def test_deadline_clamps_and_reports_exhaustion():
    deadline = Deadline.start(5.0)
    assert 0 < deadline.remaining() <= 5.0
    assert deadline.clamp(30.0) <= 5.0
    assert deadline.clamp(1.0) <= 1.0

    expired = Deadline(budget=1.0, expires_at=time.monotonic() - 1)
    assert expired.exhausted()
    assert expired.remaining() == 0.0


def test_model_timeout_is_capped_by_remaining_budget(fake_http):
    deadline = Deadline.start(2.0)
    _complete(deadline=deadline)

    assert fake_http.calls == 1
    assert fake_http.timeouts[0] is not None and fake_http.timeouts[0] <= 2.0


def test_exhausted_budget_skips_upstream(fake_http):
    expired = Deadline(budget=1.0, expires_at=time.monotonic() - 1)

    reply = _complete(deadline=expired)

    assert reply.degraded and reply.error_code == 5001
    assert fake_http.calls == 0

"""D2 执行器抽象 / D4 参数白名单与容错。"""

import pytest
from types import SimpleNamespace
import asyncio

from app.core.config import settings
from app.core.constants import ModelErrorCode
from app.core.exceptions import BizException
from app.schemas.capability import CapabilityDefinition
from app.schemas.chat import ChatCompletionRequest
from importlib import import_module

# 包里导出了同名实例，`import ... as` 会拿到实例；这里显式取模块对象。
mc = import_module("app.service.model_client")
from app.service.capability_adapters import (
    EXECUTORS,
    resolve_upstream_model,
    execute_prepared,
    effective_max_tokens,
    prepare_execution,
    resolve_executor,
)


def definition(**changes):
    data = {
        "id": 1, "code": "chat-completions", "status": "online",
        "param_schema": {"type": "object"}, "price_per_call": 5,
    }
    return CapabilityDefinition(**{**data, **changes})


def request(payload=None, **changes):
    return ChatCompletionRequest(
        capability_id=1,
        input=payload or {"messages": [{"role": "user", "content": "hi"}]},
        **changes,
    )


# ---------------------------------------------------------------- 执行器选择


def test_executor_field_wins_over_code():
    cap = definition(executor="summary", code="chat-completions")
    assert resolve_executor(cap) == "summary"


def test_empty_executor_falls_back_to_legacy_code():
    assert resolve_executor(definition(executor="", code="long-summary")) == "summary"
    assert resolve_executor(definition(executor="", code="chat-completions")) == "chat"


def test_unknown_code_without_executor_has_no_executor():
    assert resolve_executor(definition(executor="", code="vision-parse")) == ""


def test_unregistered_executor_is_rejected_with_2008():
    # image-generate 在 D3 已实现，这里改用确实未注册的执行器。
    cap = definition(executor="video-generate", price_per_call=0)
    with pytest.raises(BizException) as error:
        prepare_execution(cap, request())
    assert error.value.code == 2008


def test_registry_only_exposes_implemented_executors():
    assert set(EXECUTORS) == {"chat", "summary", "image-generate"}


def test_chat_executor_is_selected_by_field_and_keeps_code():
    cap = definition(executor="chat", code="my-own-code")
    prepared = prepare_execution(cap, request())
    assert prepared.executor == "chat" and prepared.code == "my-own-code"


@pytest.mark.parametrize("executor,payload", [
    ("chat", {"messages": [{"role": "user", "content": "hi"}]}),
    ("summary", {"text": "team notes", "max_length": 50}),
])
def test_prepare_keeps_model_optional_instead_of_filling_global_default(executor, payload, monkeypatch):
    monkeypatch.setattr(settings, "model_name", "global-default-model")
    prepared = prepare_execution(definition(executor=executor), request(payload))

    assert prepared.request.model is None
    assert prepared.requested_model is None
    assert resolve_upstream_model(prepared, provider=None) == "global-default-model"


def test_explicit_request_model_is_preserved_and_wins_over_provider_default():
    prepared = prepare_execution(definition(), request(model="caller-selected-model"))

    assert prepared.requested_model == "caller-selected-model"
    assert prepared.request.model == "caller-selected-model"
    assert resolve_upstream_model(
        prepared, provider=type("Provider", (), {"model": "provider-default-model"})()
    ) == "caller-selected-model"


def test_bound_provider_without_any_model_fails_closed():
    prepared = prepare_execution(definition(), request())

    with pytest.raises(BizException) as error:
        resolve_upstream_model(prepared, provider=type("Provider", (), {"model": ""})())

    assert error.value.code == 4002
    assert "默认模型" in error.value.message


def test_execute_uses_provider_model_without_falling_back_to_global(monkeypatch):
    monkeypatch.setattr(settings, "model_name", "global-default-model")
    prepared = prepare_execution(definition(), request())
    seen = {}

    class ModelClient:
        async def complete(self, messages, **kwargs):
            seen.update(kwargs)
            return mc.ModelReply(
                content="answer", call_status="success", model_name=kwargs["model"],
                usage_source="missing",
            )

    reply = asyncio.run(execute_prepared(
        prepared,
        runtime=type("Runtime", (), {"use_mock": False})(),
        model_client=ModelClient(),
        provider=SimpleNamespace(
            alias="qwen-provider", model="qwen-plus", base_url="https://provider.test/v1",
            protocol="openai-chat", timeout=10.0, api_key="synthetic-test-key",
        ),
        definition=definition(),
    ))

    assert seen["model"] == "qwen-plus"
    assert reply.model_name == "qwen-plus"


def test_unbound_execution_uses_explicit_model_then_global_default(monkeypatch):
    monkeypatch.setattr(settings, "model_name", "global-default-model")
    implicit = prepare_execution(definition(), request())
    explicit = prepare_execution(definition(), request(model="caller-model"))

    assert resolve_upstream_model(implicit, None) == "global-default-model"
    assert resolve_upstream_model(explicit, None) == "caller-model"


# ---------------------------------------------------------------- D4 参数白名单


def test_whitelisted_params_are_passed_through():
    prepared = prepare_execution(
        definition(),
        request({"messages": [{"role": "user", "content": "hi"}],
                 "top_p": 0.5, "seed": 7, "presence_penalty": 0.1}),
    )
    assert prepared.model_params["top_p"] == 0.5
    assert prepared.model_params["seed"] == 7
    assert prepared.model_params["presence_penalty"] == 0.1


def test_unlisted_param_is_still_rejected():
    with pytest.raises(BizException) as error:
        prepare_execution(
            definition(),
            request({"messages": [{"role": "user", "content": "hi"}], "foo": 1}),
        )
    assert error.value.code == 2001


def test_absent_params_are_not_sent_as_none():
    prepared = prepare_execution(definition(), request())
    assert prepared.model_params == {}


def test_max_tokens_is_capped_by_capability():
    cap = definition(max_output_tokens=256)
    assert effective_max_tokens(cap, None) == 256
    assert effective_max_tokens(cap, 8000) == 256
    assert effective_max_tokens(cap, 100) == 100


# ---------------------------------------------------------------- D4 容错


@pytest.mark.parametrize("status,expected", [
    (429, ModelErrorCode.UPSTREAM_RATE_LIMIT),
    (401, ModelErrorCode.UPSTREAM_AUTH),
    (402, ModelErrorCode.UPSTREAM_AUTH),
    (500, ModelErrorCode.UPSTREAM_FAULT),
    (503, ModelErrorCode.UPSTREAM_FAULT),
])
def test_status_maps_to_specific_error_code(status, expected):
    assert mc._error_code_for_status(status) == expected


def test_only_timeout_and_5xx_are_retryable():
    assert mc._retryable(None) is True
    assert mc._retryable(500) is True
    assert mc._retryable(429) is False
    assert mc._retryable(400) is False


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class _FakeClient:
    """按脚本返回响应，并记录调用次数（用于验证"只重试一次"）。"""

    calls = 0
    script: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, **kwargs):
        index = min(_FakeClient.calls, len(_FakeClient.script) - 1)
        _FakeClient.calls += 1
        result = _FakeClient.script[index]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture()
def fake_http(monkeypatch):
    _FakeClient.calls = 0
    _FakeClient.script = []

    # 连接复用后不再有 `async with httpx.AsyncClient(...)`，
    # 替身从"打客户端构造器"改成"打共享客户端的取用函数"。
    async def get_client():
        return _FakeClient()

    monkeypatch.setattr(mc, "get_http_client", get_client)
    # 退避时间在测试里置 0，避免无谓等待
    monkeypatch.setattr(mc, "RETRY_BACKOFF_SECONDS", 0)
    return _FakeClient


def test_5xx_is_retried_once_then_reported_as_5005(fake_http):
    import asyncio
    fake_http.script = [_Response(500), _Response(500)]
    reply = asyncio.run(mc.model_client.complete(
        [{"role": "user", "content": "hi"}], model="m", temperature=0.1,
        base_url="https://api.example.com/v1", api_key="k",
    ))
    assert fake_http.calls == 2
    assert reply.degraded and reply.error_code == 5005


def test_4xx_is_not_retried(fake_http):
    import asyncio
    fake_http.script = [_Response(429)]
    reply = asyncio.run(mc.model_client.complete(
        [{"role": "user", "content": "hi"}], model="m", temperature=0.1,
        base_url="https://api.example.com/v1", api_key="k",
    ))
    assert fake_http.calls == 1
    assert reply.error_code == 5003


def test_success_after_retry_keeps_single_reply(fake_http):
    import asyncio
    fake_http.script = [
        _Response(502),
        _Response(200, {
            "model": "m", "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }),
    ]
    reply = asyncio.run(mc.model_client.complete(
        [{"role": "user", "content": "hi"}], model="m", temperature=0.1,
        base_url="https://api.example.com/v1", api_key="k",
    ))
    assert fake_http.calls == 2
    assert reply.content == "ok" and reply.total_tokens == 7

"""OpenAI 兼容层的单元测试：不依赖数据库与真实模型。"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import openai_compat
from app.db.session import get_db
from app.main import app
from app.schemas.chat import MAX_MESSAGE_CONTENT_LENGTH
from app.service.catalog_cache import OpenAIModelCatalog

HEADERS = {"Authorization": "Bearer sk_test-only-secret-value"}


class _FakeChatService:
    """记录入参并返回平台执行结果的替身。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, db, request, user):
        self.calls.append({"capability_id": request.capability_id, "input": request.input,
                           "user_id": user.user_id, "model": request.model})
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "deepseek-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好，我是替身回复。"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 6, "total_tokens": 9},
            "request_id": "req-test",
            "cost": 5,
        }

    async def stream(self, db, request, user):
        """E1 后兼容层走真流式：替身按上游 SSE 的样子逐块产出。"""

        self.calls.append({"capability_id": request.capability_id, "input": request.input,
                           "user_id": user.user_id, "stream": True})
        yield 'data: {"model":"deepseek-flash","choices":[{"delta":{"content":"你"}}]}'
        yield 'data: {"model":"deepseek-flash","choices":[{"delta":{"content":"好"}}]}'
        yield ('data: {"model":"deepseek-flash","choices":[],'
               '"usage":{"prompt_tokens":3,"completion_tokens":6,"total_tokens":9}}')


@pytest.fixture()
def compat(monkeypatch):
    fake = _FakeChatService()

    async def fake_verify(*args, **kwargs):
        return {"user_id": 1, "username": "demo", "role": "user", "key_id": 1,
                "access_key": "ak_test"}

    async def fake_openai_model_catalog():
        return OpenAIModelCatalog({"deepseek-flash": 1}, frozenset({1}))

    monkeypatch.setattr(openai_compat, "chat_service", fake)
    monkeypatch.setattr(openai_compat, "call_internal", fake_verify)
    monkeypatch.setattr(openai_compat.capability_client, "openai_model_catalog", fake_openai_model_catalog)
    monkeypatch.setattr(openai_compat, "expected_internal_token", lambda: "token")
    app.dependency_overrides[get_db] = lambda: None
    try:
        yield fake, TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_missing_bearer_is_openai_authentication_error(compat) -> None:
    _, client = compat
    response = client.post("/v1/chat/completions", json={"model": "deepseek-flash", "messages": []})
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"


def test_unknown_model_is_not_silently_routed(compat) -> None:
    _, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS,
                           json={"model": "gpt-9", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "platform_2002"


def test_messages_are_mapped_to_capability_input(compat) -> None:
    fake, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash",
        "temperature": 0.4,
        "messages": [{"role": "system", "content": "简洁"}, {"role": "user", "content": "你好"}],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "你好，我是替身回复。"
    assert body["platform_cost"] == 5
    assert body["platform_request_id"] == "req-test"
    assert fake.calls[0]["capability_id"] == 1
    assert fake.calls[0]["input"]["temperature"] == 0.4
    assert [m["role"] for m in fake.calls[0]["input"]["messages"]] == ["system", "user"]


def test_segmented_content_is_joined(compat) -> None:
    fake, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "分段"}, {"type": "text", "text": "内容"}]}],
    })
    assert response.status_code == 200
    assert fake.calls[0]["input"]["messages"][0]["content"] == "分段内容"


def test_empty_messages_rejected(compat) -> None:
    _, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS,
                           json={"model": "deepseek-flash", "messages": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "platform_2001"


def test_stream_returns_incremental_chunks_and_usage(compat) -> None:
    """E1：不再是"一次性一个 chunk"，而是逐块转发并附带上游 usage。"""

    fake, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash", "stream": True,
        "messages": [{"role": "user", "content": "你好"}],
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert '"object": "chat.completion.chunk"' in text
    assert "data: [DONE]" in text
    # 两个内容块分别出现，证明是增量而不是一次性整段
    assert '"content": "你"' in text and '"content": "好"' in text
    # usage 只在最后一块出现，且数值来自上游
    assert '"total_tokens": 9' in text
    assert fake.calls[-1].get("stream") is True


def test_models_endpoint_lists_mapped_aliases(compat) -> None:
    _, client = compat
    response = client.get("/v1/models", headers=HEADERS)
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert "deepseek-flash" in ids


def test_dynamic_model_alias_routes_to_capability(compat, monkeypatch) -> None:
    fake, client = compat

    async def dynamic_models():
        return OpenAIModelCatalog({"qa-live-model": 42}, frozenset({42}))

    monkeypatch.setattr(openai_compat.capability_client, "openai_model_catalog", dynamic_models)
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "qa-live-model",
        "messages": [{"role": "user", "content": "hi"}],
    })

    assert response.status_code == 200
    assert fake.calls[0]["capability_id"] == 42
    assert fake.calls[0]["model"] is None


def test_configured_model_alias_overrides_dynamic_directory(compat, monkeypatch) -> None:
    fake, client = compat

    async def dynamic_models():
        return OpenAIModelCatalog(
            {"qa-live-model": 42, "qa-second-model": 7}, frozenset({42, 7})
        )

    monkeypatch.setattr(openai_compat.capability_client, "openai_model_catalog", dynamic_models)
    monkeypatch.setattr(openai_compat.settings, "openai_compat_model_map", "qa-live-model=7")

    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "qa-live-model",
        "messages": [{"role": "user", "content": "hi"}],
    })

    assert response.status_code == 200
    assert fake.calls[0]["capability_id"] == 7


def test_legacy_config_alias_remains_available_for_active_chat(compat, monkeypatch) -> None:
    fake, client = compat

    async def legacy_catalog():
        return OpenAIModelCatalog({}, frozenset({1}))

    monkeypatch.setattr(openai_compat.capability_client, "openai_model_catalog", legacy_catalog)
    monkeypatch.setattr(openai_compat.settings, "openai_compat_model_map", "deepseek-flash=1")

    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "hi"}],
    })

    assert response.status_code == 200
    assert fake.calls[0]["capability_id"] == 1


def test_internal_token_missing_fails_closed(compat, monkeypatch) -> None:
    _, client = compat
    monkeypatch.setattr(openai_compat, "expected_internal_token", lambda: "")
    response = client.post("/v1/chat/completions", headers=HEADERS,
                           json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "platform_4003"


def test_static_override_cannot_route_offline_or_non_chat_target(compat, monkeypatch):
    fake, client = compat

    async def directory():
        return OpenAIModelCatalog({}, frozenset({1}))

    monkeypatch.setattr(openai_compat.capability_client, "openai_model_catalog", directory)
    monkeypatch.setattr(openai_compat.settings, "openai_compat_model_map", "hidden-model=42")
    response = client.post("/v1/chat/completions", headers=HEADERS,
                           json={"model": "hidden-model", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "platform_2002"
    assert fake.calls == []


def test_oversized_message_is_invalid_request_not_platform_failure(compat) -> None:
    """超过单条上限的消息必须是 400 + platform_2001，且点明"太长"。

    回归线上故障：超长 content 撞 Pydantic max_length，被兜底成 500
    platform_error，第三方客户端只会看到"平台坏了"并无限重试。
    上限已提到 48000，所以边界取 48001（**不是** 13000：那个长度现在是合法的）。
    """

    fake, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "简" * (MAX_MESSAGE_CONTENT_LENGTH + 1)}],
    })
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "platform_2001"
    assert error["type"] == "invalid_request_error"
    assert "超过单条上限" in error["message"]
    assert fake.calls == []


def test_long_message_within_the_raised_limit_is_accepted(compat) -> None:
    """48000 字符以内的长上下文应正常进入执行链（不是 400 也不是 500）。"""

    fake, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "简" * 40000}],
    })
    assert response.status_code == 200
    assert len(fake.calls[0]["input"]["messages"][0]["content"]) == 40000


def test_other_field_violations_are_also_invalid_request(compat) -> None:
    """非长度类字段校验失败同样是 400/2001，不能漏到 500 兜底。"""

    fake, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash",
        "messages": [{
            "role": "tool",
            "content": "结果",
            "tool_call_id": "x" * 100,
        }],
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "platform_2001"
    assert fake.calls == []

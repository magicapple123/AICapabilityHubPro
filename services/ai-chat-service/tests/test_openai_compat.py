"""OpenAI 兼容层的单元测试：不依赖数据库与真实模型。"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import openai_compat
from app.db.session import get_db
from app.main import app

HEADERS = {"Authorization": "Bearer sk_test-only-secret-value"}


class _FakeChatService:
    """记录入参并返回平台执行结果的替身。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, db, request, user):
        self.calls.append({"capability_id": request.capability_id, "input": request.input,
                           "user_id": user.user_id})
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


@pytest.fixture()
def compat(monkeypatch):
    fake = _FakeChatService()

    async def fake_verify(*args, **kwargs):
        return {"user_id": 1, "username": "demo", "role": "user", "key_id": 1,
                "access_key": "ak_test"}

    monkeypatch.setattr(openai_compat, "chat_service", fake)
    monkeypatch.setattr(openai_compat, "call_internal", fake_verify)
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


def test_stream_returns_single_sse_chunk_and_done(compat) -> None:
    _, client = compat
    response = client.post("/v1/chat/completions", headers=HEADERS, json={
        "model": "deepseek-flash", "stream": True,
        "messages": [{"role": "user", "content": "你好"}],
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert '"object": "chat.completion.chunk"' in text
    assert "data: [DONE]" in text


def test_models_endpoint_lists_mapped_aliases(compat) -> None:
    _, client = compat
    response = client.get("/v1/models", headers=HEADERS)
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert "deepseek-flash" in ids


def test_internal_token_missing_fails_closed(compat, monkeypatch) -> None:
    _, client = compat
    monkeypatch.setattr(openai_compat, "expected_internal_token", lambda: "")
    response = client.post("/v1/chat/completions", headers=HEADERS,
                           json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "platform_4003"

"""E3 Responses 兼容层：协议翻译、多轮续接、工具结果回灌、流式事件。"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import responses as responses_api
from app.core.exceptions import BizException
from app.main import app

client = TestClient(app)
HEADERS = {"Authorization": "Bearer sk_test_1234567890"}


class _FakeChatService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, db, request, user):
        capability_input = request.capability_input()
        self.calls.append({
            "session_id": request.session_id,
            # 兼容层把消息放进 input.messages，这里按真实执行入口取。
            "messages": capability_input.get("messages", []),
            "input": request.input,
        })
        return {
            "id": "chatcmpl-x", "created": 1700000000, "model": "deepseek-flash",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "回答"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 6, "total_tokens": 9},
            "session_id": 42, "request_id": "req-1", "cost": 5,
        }

    async def stream(self, db, request, user):
        self.calls.append({"stream": True, "session_id": request.session_id})
        yield 'data: {"choices":[{"delta":{"content":"你"}}]}'
        yield 'data: {"choices":[{"delta":{"content":"好"}}]}'


@pytest.fixture()
def compat(monkeypatch):
    fake = _FakeChatService()

    async def fake_auth(_header):
        return __import__("app.core.security", fromlist=["UserContext"]).UserContext(
            user_id="1", user_name="demo", request_id="req-1",
        )

    monkeypatch.setattr(responses_api, "chat_service", fake)
    monkeypatch.setattr(responses_api, "_authenticate", fake_auth)
    monkeypatch.setattr(responses_api, "_model_map", lambda: {"deepseek-flash": 1})
    return fake


def test_string_input_is_translated_to_user_message(compat):
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "你好"},
    )
    body = response.json()
    assert response.status_code == 200, body
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == "回答"
    assert body["usage"] == {"input_tokens": 3, "output_tokens": 6, "total_tokens": 9}
    assert "error" not in body


def test_instructions_become_system_message(compat):
    client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "你好", "instructions": "只回答一个字"},
    )
    messages = compat.calls[-1]["messages"]
    assert messages[0] == {"role": "system", "content": "只回答一个字"}
    assert messages[-1] == {"role": "user", "content": "你好"}


def test_previous_response_id_resumes_the_same_session(compat):
    client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "第一轮",
              "previous_response_id": "resp_42_abcdef"},
    )
    assert compat.calls[-1]["session_id"] == 42


def test_function_call_output_is_turned_into_tool_message(compat):
    client.post(
        "/v1/responses", headers=HEADERS,
        json={
            "model": "deepseek-flash",
            "input": [
                {"role": "user", "content": "北京天气"},
                {"type": "function_call_output", "call_id": "call_1", "output": "晴"},
            ],
        },
    )
    messages = compat.calls[-1]["messages"]
    assert messages[-1] == {"role": "tool", "content": "晴", "tool_call_id": "call_1"}


def test_unknown_model_returns_404(compat):
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "no-such-model", "input": "hi"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "platform_2002"


def test_empty_input_is_rejected(compat):
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": []},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "platform_2001"


def test_stream_emits_responses_events(compat):
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "你好", "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "response.created" in text
    assert "response.output_text.delta" in text
    assert '"delta": "你"' in text and '"delta": "好"' in text
    assert "response.completed" in text
    assert "data: [DONE]" in text


def test_stream_records_session_from_previous_response(compat):
    client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "x", "stream": True,
              "previous_response_id": "resp_77_zz"},
    )
    assert compat.calls[-1]["session_id"] == 77


def test_tools_are_passed_through_when_provided(compat):
    client.post(
        "/v1/responses", headers=HEADERS,
        json={
            "model": "deepseek-flash", "input": "查天气",
            "tools": [{"type": "function", "name": "get_weather",
                       "parameters": {"type": "object"}}],
            "tool_choice": "auto",
        },
    )
    payload = compat.calls[-1]["input"]
    assert payload["tools"][0]["name"] == "get_weather"
    assert payload["tool_choice"] == "auto"


def test_auth_failure_is_mapped_to_openai_error(compat, monkeypatch):
    async def deny(_header):
        raise BizException(1001, "missing token")

    monkeypatch.setattr(responses_api, "_authenticate", deny)
    response = client.post(
        "/v1/responses", headers=HEADERS, json={"model": "deepseek-flash", "input": "x"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "platform_1001"

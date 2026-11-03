"""E3 / P12 Responses 兼容层：协议翻译、多轮续接、工具往返、流式事件序列。

P12 的语义变化（与需求清单一致）：
- `store: false` 放行；只有 `store: true` 才 4001；
- `reasoning` / `background` 接受但忽略，并在 `platform_warnings` 明示；
- `tools` 从 Responses 的扁平结构翻译成 chat 的嵌套结构（执行层只认嵌套）；
- 上游 `tool_calls` 反向翻译成 `function_call` 条目，`call_id` / `arguments` 必须齐全；
- SSE 事件按冻结顺序输出；
- `instructions` 超长只截断 + warning，不整单 4001。
"""

import json

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
        #: 需要模拟"模型要调工具"时由用例注入。
        self.tool_calls: list[dict] | None = None

    async def complete(self, db, request, user):
        capability_input = request.capability_input()
        self.calls.append({
            "session_id": request.session_id,
            "model": request.model,
            # 兼容层把消息放进 input.messages，这里按真实执行入口取。
            "messages": capability_input.get("messages", []),
            "input": request.input,
        })
        message: dict = {"role": "assistant", "content": "回答"}
        if self.tool_calls:
            message = {"role": "assistant", "content": "", "tool_calls": self.tool_calls}
        return {
            "id": "chatcmpl-x", "created": 1700000000, "model": "deepseek-flash",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if self.tool_calls else "stop",
                         "message": message}],
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

    async def fake_model_map():
        return {"deepseek-flash": 1}

    monkeypatch.setattr(responses_api, "chat_service", fake)
    monkeypatch.setattr(responses_api, "_authenticate", fake_auth)
    monkeypatch.setattr(responses_api, "_model_map", fake_model_map)
    return fake


def _sse_events(text: str) -> list[str]:
    """把 SSE 文本拆成事件名序列（`[DONE]` 用字面量表示）。"""

    names: list[str] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            names.append("[DONE]")
            continue
        if payload:
            names.append(json.loads(payload)["type"])
    return names


def test_string_input_is_translated_to_user_message(compat):
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "你好"},
    )
    body = response.json()
    assert response.status_code == 200, body
    assert compat.calls[0]["model"] is None
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == "回答"
    assert body["usage"] == {"input_tokens": 3, "output_tokens": 6, "total_tokens": 9}
    assert body["platform_warnings"] == []
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


def test_stream_event_order_is_frozen(compat):
    """P12：事件顺序固定，客户端靠 added/done 事件挂载与收尾输出项。"""

    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "你好", "stream": True},
    )
    names = _sse_events(response.text)
    non_delta = [name for name in names if name != "response.output_text.delta"]
    assert non_delta == [
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.done",
        "response.output_item.done",
        "response.completed",
        "[DONE]",
    ]
    assert names.count("response.output_text.delta") == 2
    # 文本只在 done 事件里出现一次完整值。
    done = [json.loads(line[5:]) for line in response.text.splitlines()
            if line.startswith("data:") and '"response.output_text.done"' in line]
    assert done[0]["text"] == "你好"


def test_stream_records_session_from_previous_response(compat):
    client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "x", "stream": True,
              "previous_response_id": "resp_77_zz"},
    )
    assert compat.calls[-1]["session_id"] == 77


def test_tools_are_translated_to_nested_chat_shape(compat):
    """P12：Responses 扁平工具 → chat 嵌套工具（执行层只认一种形态）。"""

    client.post(
        "/v1/responses", headers=HEADERS,
        json={
            "model": "deepseek-flash", "input": "查天气",
            "tools": [{"type": "function", "name": "get_weather",
                       "description": "查询天气",
                       "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}],
            "tool_choice": "auto",
        },
    )
    payload = compat.calls[-1]["input"]
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询天气",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    }]
    assert payload["tool_choice"] == "auto"


def test_named_tool_choice_is_translated(compat):
    client.post(
        "/v1/responses", headers=HEADERS,
        json={
            "model": "deepseek-flash", "input": "查天气",
            "tools": [{"type": "function", "name": "get_weather",
                       "parameters": {"type": "object"}}],
            "tool_choice": {"type": "function", "name": "get_weather"},
        },
    )
    payload = compat.calls[-1]["input"]
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "get_weather"}}


def test_tool_calls_become_function_call_items(compat):
    """反向翻译：上游 tool_calls → Responses function_call，call_id/arguments 齐全。"""

    compat.tool_calls = [{
        "id": "call_1", "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"北京"}'},
    }]
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "查天气"},
    )
    item = response.json()["output"][0]
    assert item["type"] == "function_call"
    assert item["call_id"] == "call_1"
    assert item["name"] == "get_weather"
    assert json.loads(item["arguments"]) == {"city": "北京"}
    assert item["id"].startswith("fc_")


def test_function_call_without_id_or_arguments_is_filled(compat):
    """上游省略 id/arguments 时也必须是可回灌的条目，不能给 null。"""

    compat.tool_calls = [{"function": {"name": "ping"}}]
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "ping"},
    )
    item = response.json()["output"][0]
    assert item["call_id"].startswith("call_")
    assert item["arguments"] == "{}"


def test_instructions_longer_than_message_limit_is_truncated(compat):
    """P12：系统提示不参与用户消息长度限制，超长只截断 + warning。"""

    long_instructions = "规" * (responses_api.MAX_INSTRUCTIONS_LENGTH + 50)
    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "你好", "instructions": long_instructions},
    )
    body = response.json()
    assert response.status_code == 200, body
    messages = compat.calls[-1]["messages"]
    assert messages[0]["role"] == "system"
    assert len(messages[0]["content"]) == responses_api.MAX_INSTRUCTIONS_LENGTH
    assert any("instructions" in warning for warning in body["platform_warnings"])


def test_auth_failure_is_mapped_to_openai_error(compat, monkeypatch):
    async def deny(_header):
        raise BizException(1001, "missing token")

    monkeypatch.setattr(responses_api, "_authenticate", deny)
    response = client.post(
        "/v1/responses", headers=HEADERS, json={"model": "deepseek-flash", "input": "x"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "platform_1001"


# ---------------------------------------------------------------- 不支持 / 忽略字段


def _assert_unsupported(compat, payload: dict, field: str) -> None:
    """业务码 4001 + message 点名字段 + 没有真正执行。"""

    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "hi", **payload},
    )
    body = response.json()
    assert response.status_code == 400, body
    assert body["error"]["code"] == "platform_4001"
    assert body["error"]["type"] == "invalid_request_error"
    assert field in body["error"]["message"]
    assert compat.calls == []


def test_store_true_is_rejected(compat):
    _assert_unsupported(compat, {"store": True}, "store")


def test_store_false_is_allowed(compat):
    """P12：store=false 与平台"不存储上游内容"一致，必须放行。"""

    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "hi", "store": False},
    )
    body = response.json()
    assert response.status_code == 200, body
    assert len(compat.calls) == 1
    assert "error" not in body


def test_reasoning_and_background_are_ignored_with_warnings(compat):
    """P12：这两个字段接受但忽略，绝不因为"客户端带了它"整单 4001。"""

    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": "hi",
              "reasoning": {"effort": "low"}, "background": True},
    )
    body = response.json()
    assert response.status_code == 200, body
    assert len(compat.calls) == 1
    warnings = body["platform_warnings"]
    assert any("reasoning" in warning for warning in warnings)
    assert any("background" in warning for warning in warnings)


def test_builtin_web_search_tool_is_rejected(compat):
    _assert_unsupported(compat, {"tools": [{"type": "web_search"}]}, "web_search")


def test_builtin_file_search_tool_is_rejected(compat):
    _assert_unsupported(compat, {"tools": [{"type": "file_search"}]}, "file_search")


def test_reasoning_item_in_input_is_ignored_not_rejected(compat):
    """P12：input 里的 reasoning 条目不进消息列表，但也不再 4001。"""

    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash",
              "input": [{"type": "reasoning", "id": "rs_1"},
                        {"role": "user", "content": "你好"}]},
    )
    body = response.json()
    assert response.status_code == 200, body
    messages = compat.calls[-1]["messages"]
    assert messages == [{"role": "user", "content": "你好"}]
    assert any("reasoning" in warning for warning in body["platform_warnings"])


def test_reasoning_only_input_is_still_rejected_as_empty(compat):
    """忽略 reasoning 之后没有可发送内容时，仍按"input 不能为空"拒绝。"""

    response = client.post(
        "/v1/responses", headers=HEADERS,
        json={"model": "deepseek-flash", "input": [{"type": "reasoning", "id": "rs_2"}]},
    )
    body = response.json()
    assert response.status_code == 400, body
    assert body["error"]["code"] == "platform_2001"
    assert compat.calls == []

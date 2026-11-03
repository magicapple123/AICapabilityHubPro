"""E2 工具调用：多轮协议、透传、无工具时响应体不变。"""

import pytest
from pydantic import ValidationError

from app.core.constants import CallStatus
from app.schemas.capability import CapabilityDefinition, ChatInput
from app.schemas.chat import ChatMessage, ChatCompletionRequest
from app.service.capability_adapters import prepare_execution
from app.service.completion_result import completion_result
from app.service.model_client import ModelClient, ModelReply

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查天气",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    },
}]


def definition(**changes):
    data = {
        "id": 1, "code": "chat-completions", "status": "online",
        "param_schema": {"type": "object"}, "price_per_call": 5,
    }
    return CapabilityDefinition(**{**data, **changes})


# ---------------------------------------------------------------- 消息协议


def test_tool_message_requires_tool_call_id():
    with pytest.raises(ValidationError):
        ChatMessage(role="tool", content="结果")


def test_non_tool_message_cannot_carry_tool_call_id():
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="hi", tool_call_id="call_1")


def test_tool_message_is_accepted_and_dumped_cleanly():
    message = ChatMessage(role="tool", content="晴", tool_call_id="call_1")
    dumped = message.model_dump(exclude_none=True)
    assert dumped == {"role": "tool", "content": "晴", "tool_call_id": "call_1"}


def test_request_accepts_tool_result_as_last_message():
    request = ChatCompletionRequest(
        capability_id=1,
        messages=[
            {"role": "user", "content": "北京天气"},
            {"role": "assistant", "content": "我来查一下"},
            {"role": "tool", "content": "晴 25 度", "tool_call_id": "call_1"},
        ],
    )
    assert request.messages[-1].role == "tool"


def test_chat_input_rejects_assistant_as_last_message():
    """请求体本身允许任意历史；"最后一条必须是 user/tool"由执行器输入约束把关。"""

    with pytest.raises(ValidationError):
        ChatInput(messages=[
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "y"},
        ])


# ---------------------------------------------------------------- 参数透传


def test_tools_are_forwarded_to_upstream():
    prepared = prepare_execution(
        definition(),
        ChatCompletionRequest(
            capability_id=1,
            input={
                "messages": [{"role": "user", "content": "北京天气"}],
                "tools": TOOLS,
                "tool_choice": "auto",
                "parallel_tool_calls": False,
            },
        ),
    )
    assert prepared.model_params["tools"] == TOOLS
    assert prepared.model_params["tool_choice"] == "auto"
    assert prepared.model_params["parallel_tool_calls"] is False


def test_no_tools_means_no_tool_params():
    prepared = prepare_execution(
        definition(),
        ChatCompletionRequest(capability_id=1, input={"messages": [{"role": "user", "content": "hi"}]}),
    )
    assert "tools" not in prepared.model_params


def test_unknown_tool_shape_is_still_rejected():
    with pytest.raises(ValidationError):
        ChatInput(messages=[{"role": "user", "content": "x"}], tools="not-a-list")


# ---------------------------------------------------------------- 响应解析


def test_parse_keeps_tool_calls_and_marks_finish_reason():
    reply = ModelClient._parse(
        {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {"content": "", "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "get_weather", "arguments": "{\"city\":\"北京\"}"}},
                ]},
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 6},
        },
        fallback_model="m",
    )
    assert reply.tool_calls and reply.tool_calls[0]["id"] == "call_1"
    assert reply.finish_reason == "tool_calls"
    assert reply.degraded is False
    assert reply.total_tokens == 11


def test_parse_without_content_or_tools_is_degraded():
    reply = ModelClient._parse({"choices": [{"message": {"content": ""}}]}, fallback_model="m")
    assert reply.degraded is True


def test_plain_reply_has_no_tool_calls():
    reply = ModelClient._parse(
        {"choices": [{"message": {"content": "普通回答"}}]}, fallback_model="m",
    )
    assert reply.tool_calls is None and reply.finish_reason == "stop"


# ---------------------------------------------------------------- 响应组装


def _result(reply):
    return completion_result(
        definition=definition(),
        session_id=7,
        message_id=9,
        reply=reply,
        duration_ms=12,
        receipt={"cost": 5, "record_id": 3},
    )


def test_completion_result_exposes_tool_calls_in_message():
    reply = ModelReply(
        content="", call_status=CallStatus.SUCCESS.value, model_name="m",
        prompt_tokens=5, completion_tokens=6, usage_source="upstream",
        tool_calls=[{"id": "call_1", "type": "function",
                     "function": {"name": "get_weather", "arguments": "{}"}}],
        finish_reason="tool_calls",
    )
    data = _result(reply)
    choice = data["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["id"] == "call_1"


def test_completion_result_without_tools_keeps_old_shape():
    reply = ModelReply(
        content="你好", call_status=CallStatus.SUCCESS.value, model_name="m",
        prompt_tokens=1, completion_tokens=2, usage_source="upstream",
    )
    data = _result(reply)
    message = data["choices"][0]["message"]
    assert "tool_calls" not in message
    assert data["choices"][0]["finish_reason"] == "stop"

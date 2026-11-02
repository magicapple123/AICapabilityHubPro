"""OpenAI Responses 兼容层（E3）。

为什么要有它：新版 SDK / Agent 框架默认走 `/v1/responses`，只支持
Chat Completions 会让这类客户端无法接入。这里做**协议翻译**，执行链完全复用
平台既有的 `chat_service.complete/stream`（计费、落库、审计一处不改）。

已实现的能力边界（与需求清单第 6 节一致）：
- `input` 支持字符串与消息数组（`input_text` / `output_text` 两种分段都认）；
- `instructions` 作为 system 消息；
- `previous_response_id` 支持多轮：响应 id 里编码了会话 id（`resp_<session>_<rand>`），
  下一轮带上它即可续接同一会话；
- `stream=true` 输出 `response.output_text.delta` 与 `response.completed` 事件；
- 工具调用：`tools` 透传，输出 `function_call` 项，不执行工具。
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.openai_compat import _authenticate, _model_map, _openai_error
from app.core.exceptions import BizException
from app.core.logging import use_identity
from app.core.security import UserContext
from app.db.session import get_db
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.service.chat_service import chat_service
from app.service.stream_service import DONE_FRAME, parse_sse_line, sse_frame

router = APIRouter()

ROLE_SET = {"system", "user", "assistant", "tool"}


def _text_of(content: Any) -> str:
    """把 Responses 的 content（字符串或分段数组）压成纯文本。"""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "".join(chunks)
    return ""


def _messages_of(payload: dict) -> list[ChatMessage]:
    """`input` + `instructions` → 平台消息列表；非法结构一律 2001。"""

    instructions = payload.get("instructions")
    messages: list[ChatMessage] = []
    if instructions is not None:
        if not isinstance(instructions, str):
            raise BizException(2001, "instructions 必须是字符串")
        if instructions.strip():
            messages.append(ChatMessage(role="system", content=instructions))

    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        if not raw_input.strip():
            raise BizException(2001, "input 不能为空")
        messages.append(ChatMessage(role="user", content=raw_input))
    elif isinstance(raw_input, list) and raw_input:
        for item in raw_input:
            if not isinstance(item, dict):
                raise BizException(2001, "input 元素格式不正确")
            # 工具调用结果在 Responses 里是 {type:function_call_output,...}
            if item.get("type") == "function_call_output":
                call_id = str(item.get("call_id") or "").strip()
                if not call_id:
                    raise BizException(2001, "function_call_output 缺少 call_id")
                messages.append(ChatMessage(
                    role="tool", content=_text_of(item.get("output")),
                    tool_call_id=call_id,
                ))
                continue
            role = str(item.get("role") or "user").strip()
            if role not in ROLE_SET:
                raise BizException(2001, f"不支持的角色：{role}")
            text = _text_of(item.get("content"))
            if not text.strip():
                raise BizException(2001, "消息内容不能为空")
            if role == "tool":
                call_id = str(item.get("tool_call_id") or item.get("call_id") or "").strip()
                if not call_id:
                    raise BizException(2001, "tool 消息必须带 call_id")
                messages.append(ChatMessage(role="tool", content=text, tool_call_id=call_id))
            else:
                messages.append(ChatMessage(role=role, content=text))
    else:
        raise BizException(2001, "input 不能为空")

    if len(messages) > 40:
        raise BizException(2001, "messages 最多 40 条")
    return messages


def _session_of(response_id: Any) -> int | None:
    """从 `resp_<session>_<rand>` 里解出会话 id；解不出就当新会话。"""

    if not isinstance(response_id, str) or not response_id.startswith("resp_"):
        return None
    parts = response_id.split("_")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    value = int(parts[1])
    return value if value > 0 else None


def _response_id(session_id: int | None) -> str:
    return f"resp_{session_id or 0}_{uuid4().hex}"


def _output_items(data: dict) -> list[dict]:
    """平台 completion → Responses 的 output 数组（文本 + function_call）。"""

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message", {})
    items: list[dict] = []
    text = message.get("content") or ""
    if text:
        items.append({
            "type": "message",
            "id": f"msg_{uuid4().hex[:24]}",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        })
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        items.append({
            "type": "function_call",
            "id": f"fc_{uuid4().hex[:24]}",
            "call_id": call.get("id"),
            "name": function.get("name"),
            "arguments": function.get("arguments"),
            "status": "completed",
        })
    return items


def _envelope(data: dict, model: str, previous: str | None) -> dict:
    usage = data.get("usage") or {}
    return {
        "id": _response_id(data.get("session_id")),
        "object": "response",
        "created_at": data.get("created") or int(time.time()),
        "status": "completed",
        "model": data.get("model") or model,
        "output": _output_items(data),
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "previous_response_id": previous,
        "platform_request_id": data.get("request_id"),
        "platform_cost": data.get("cost"),
    }


@router.post("")
async def create_response(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """`POST /v1/responses`：协议翻译 + 复用平台执行链。"""

    try:
        user = await _authenticate(authorization)
        alias = str(payload.get("model") or "").strip()
        capability_id = _model_map().get(alias)
        if capability_id is None:
            raise BizException(2002, f"模型 {alias or '(空)'} 未在平台注册")

        messages = _messages_of(payload)
        previous = payload.get("previous_response_id")
        request = ChatCompletionRequest(
            capability_id=capability_id,
            input={"messages": [message.model_dump(exclude_none=True) for message in messages]},
            session_id=_session_of(previous),
        )
        tools = payload.get("tools")
        if isinstance(tools, list) and tools:
            request.input["tools"] = tools
            request.input["tool_choice"] = payload.get("tool_choice") or "auto"
        if isinstance(payload.get("temperature"), (int, float)):
            request.input["temperature"] = min(max(float(payload["temperature"]), 0.0), 2.0)
        if isinstance(payload.get("max_output_tokens"), int):
            request.input["max_tokens"] = payload["max_output_tokens"]

        if payload.get("stream"):
            return _stream_response(db, request, user, alias, previous)

        with use_identity(user.user_id, user.user_name):
            data = await chat_service.complete(db, request, user)
    except BizException as error:
        return _openai_error(error)
    except Exception:  # noqa: BLE001 - 兼容层必须返回 OpenAI 错误结构
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "平台执行失败", "type": "api_error",
                               "code": "platform_error"}},
        )

    return _envelope(data, alias, previous if isinstance(previous, str) else None)


def _stream_response(
    db: Session, request: ChatCompletionRequest, user: UserContext,
    alias: str, previous: str | None,
) -> StreamingResponse:
    """把平台 SSE 翻译成 Responses 事件流。"""

    response_id = _response_id(_session_of(previous))
    created = int(time.time())

    def _event(name: str, data: dict) -> str:
        return sse_frame({"type": name, **data})

    async def _generate():
        with use_identity(user.user_id, user.user_name):
            yield _event("response.created", {
                "response": {"id": response_id, "object": "response",
                             "created_at": created, "status": "in_progress",
                             "model": alias},
            })
            collected: list[str] = []
            async for line in chat_service.stream(db, request, user):
                frame = parse_sse_line(line)
                if frame is None:
                    continue
                choices = frame.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                text = delta.get("content") if isinstance(delta, dict) else None
                if isinstance(text, str) and text:
                    collected.append(text)
                    yield _event("response.output_text.delta", {
                        "item_id": f"msg_{response_id}", "output_index": 0,
                        "content_index": 0, "delta": text,
                    })
            yield _event("response.completed", {
                "response": {
                    "id": response_id, "object": "response", "created_at": created,
                    "status": "completed", "model": alias,
                    "output": [{
                        "type": "message", "id": f"msg_{response_id}",
                        "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "".join(collected),
                                     "annotations": []}],
                    }],
                },
            })
            yield DONE_FRAME

    return StreamingResponse(
        _generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

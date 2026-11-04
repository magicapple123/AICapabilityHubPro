"""OpenAI Responses 兼容层（E3 / P12）。

为什么要有它：新版 SDK / Agent 框架默认走 `/v1/responses`，只支持
Chat Completions 会让这类客户端无法接入。这里做**协议翻译**，执行链完全复用
平台既有的 `chat_service.complete/stream`（计费、落库、审计一处不改）。

已实现的能力边界：

- `input` 支持字符串与消息数组（`input_text` / `output_text` 两种分段都认）；
- `instructions` 作为 system 消息；**它属于系统提示，不参与"用户消息长度"判定**：
  超长时截断到 `MAX_INSTRUCTIONS_LENGTH` 并在 `platform_warnings` 里说明，整单不失败；
- `previous_response_id` 支持多轮：响应 id 里编码了会话 id（`resp_<session>_<rand>`），
  下一轮带上它即可续接同一会话（**平台自有的多轮续接语义，不等于 OpenAI 的服务端
  会话存储**，契约里已注明）；
- `stream=true` 按 P12 冻结的顺序输出事件：
  `response.created` → `response.output_item.added` → `response.content_part.added`
  → `response.output_text.delta`（多次）→ `response.output_text.done`
  → `response.output_item.done` → `response.completed` → `[DONE]`；
- 工具调用：`tools[]` 只接受 `type=function`。Responses 的**扁平**结构
  `{type, name, description, parameters}` 在这里翻译成 chat 的**嵌套**结构
  `{type:"function", function:{...}}` 后再进执行链，因此执行层只认一种形态；
  上游返回的 `tool_calls` 反向翻译成 `function_call` 条目（补齐 `call_id` / `arguments`）。

**接受但忽略**（P12）：`store: false`（平台本就不存上游内容，语义一致）、
`reasoning`、`background`，以及 `input` 里的 `reasoning` 条目。忽略时不静默：在响应体
（含流式的 `response.created` / `response.completed`）回 `platform_warnings` 字符串数组。

**仍然拒绝**（`4001` + HTTP 400，message 点名字段）：`store: true`（服务端存储，
与平台"不存储"的承诺冲突）、内置工具（`web_search` / `file_search` 等 `type != function`）、
`input` 里的 `item_reference` 与服务端工具条目。
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1.openai_compat import (
    _authenticate,
    _model_map,
    _openai_error,
    message_too_long_error,
    validation_reason,
)
from app.core.exceptions import BizException
from app.core.logging import use_identity
from app.core.security import UserContext
from app.db.session import get_db
from app.schemas.chat import (
    MAX_MESSAGE_CONTENT_LENGTH,
    ChatCompletionRequest,
    ChatMessage,
)
from app.service.chat_service import chat_service
from app.service.stream_service import DONE_FRAME, parse_sse_line, sse_frame

router = APIRouter()

ROLE_SET = {"system", "user", "assistant", "tool"}

#: `instructions` 的上限**必须**等于单条消息 `content` 的上限：两者都会变成一条
#: `ChatMessage`，阈值更小只会让前一半系统提示被悄悄截断。所以直接引用同一个常量。
MAX_INSTRUCTIONS_LENGTH = MAX_MESSAGE_CONTENT_LENGTH

#: 语义与平台不兼容、必须拒绝的顶层字段：字段名 -> 人话标签。
UNSUPPORTED_FIELDS: dict[str, str] = {
    "store": "store=true（服务端存储）",
}

#: 接受但忽略的顶层字段：字段名 -> 人话标签。忽略时回 `platform_warnings`。
IGNORED_FIELDS: dict[str, str] = {
    "reasoning": "reasoning（推理强度/推理内容）",
    "background": "background（后台任务模式）",
}

#: `input` 里必须拒绝的条目类型（服务端存储/内置工具）。
UNSUPPORTED_ITEM_TYPES = {"item_reference", "web_search_call", "file_search_call"}

#: `input` 里接受但忽略的条目类型（推理条目不含用户可读内容）。
IGNORED_ITEM_TYPES = {"reasoning"}

#: `tools[]` 唯一支持的类型：函数工具。
SUPPORTED_TOOL_TYPE = "function"


class UnsupportedFieldError(BizException):
    """「格式合法但平台不支持」的字段。

    复用平台业务码 `4001`（需求 E3 指定），但对外 HTTP 用 400：
    这属于请求语义不被支持，让客户端按参数错误重试而不是退避限流。
    """

    def __init__(self, message: str) -> None:
        super().__init__(4001, message)


def _warn(warnings: list[str], message: str) -> None:
    """去重追加，避免同一请求里重复 40 条一样的提示。"""

    if message not in warnings:
        warnings.append(message)


def _validate_payload(payload: dict, warnings: list[str]) -> None:
    """在任何执行动作之前判定字段语义，并收集"忽略但不失败"的提示。"""

    # P12：store 只有 true 才与服务端存储冲突；false 与平台"不存储"完全一致，放行。
    for field, label in UNSUPPORTED_FIELDS.items():
        value = payload.get(field)
        if value is True or (field == "store" and isinstance(value, str)
                             and value.strip().lower() == "true"):
            raise UnsupportedFieldError(
                f"不支持 {label}：本兼容层不存储上游内容，请使用 store=false"
            )

    for field, label in IGNORED_FIELDS.items():
        if payload.get(field) is None:
            continue
        _warn(warnings, f"已忽略 {label}：本兼容层仅支持同步文本与函数工具调用")
        logger.info("Responses 兼容层忽略字段 field={}", field)

    tools = payload.get("tools")
    if tools is not None and not isinstance(tools, list):
        raise BizException(2001, "tools 必须是数组")
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                raise BizException(2001, "tools 元素格式不正确")
            kind = str(tool.get("type") or "").strip()
            if kind != SUPPORTED_TOOL_TYPE:
                raise UnsupportedFieldError(
                    f"不支持内置工具 {kind or '(缺少 type)'}：tools[].type 目前只支持 function"
                )

    raw_input = payload.get("input")
    if isinstance(raw_input, list):
        for item in raw_input:
            if isinstance(item, dict) and item.get("type") in UNSUPPORTED_ITEM_TYPES:
                raise UnsupportedFieldError(
                    f"不支持 input 条目类型 {item.get('type')}：仅支持消息、reasoning 与 function_call_output"
                )


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


def _append_message(messages: list[ChatMessage], index: int, **fields: Any) -> None:
    """构造一条消息，字段非法时统一成 `2001`。

    与 `/v1/chat/completions` 同一口径：输入问题必须是 400 + `platform_2001`，
    不能因为内部用的是 Pydantic 就冒出一个 500 `platform_error`。
    """

    try:
        messages.append(ChatMessage(**fields))
    except ValidationError as error:
        raise BizException(2001, validation_reason(error, index)) from error


def _messages_of(payload: dict, warnings: list[str]) -> list[ChatMessage]:
    """`input` + `instructions` → 平台消息列表；非法结构一律 2001。"""

    instructions = payload.get("instructions")
    messages: list[ChatMessage] = []
    if instructions is not None:
        if not isinstance(instructions, str):
            raise BizException(2001, "instructions 必须是字符串")
        text = instructions
        # P12：系统提示不参与用户消息长度限制。超长只截断 + warning，绝不整体 4001。
        if len(text) > MAX_INSTRUCTIONS_LENGTH:
            logger.warning("instructions 超长已截断 length={}", len(text))
            _warn(
                warnings,
                f"instructions 超过 {MAX_INSTRUCTIONS_LENGTH} 字符，已截断后使用",
            )
            text = text[:MAX_INSTRUCTIONS_LENGTH]
        if text.strip():
            _append_message(messages, len(messages) + 1, role="system", content=text)

    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        if not raw_input.strip():
            raise BizException(2001, "input 不能为空")
        if len(raw_input) > MAX_MESSAGE_CONTENT_LENGTH:
            raise message_too_long_error(len(messages) + 1, "user", len(raw_input))
        _append_message(messages, len(messages) + 1, role="user", content=raw_input)
    elif isinstance(raw_input, list) and raw_input:
        for item in raw_input:
            if not isinstance(item, dict):
                raise BizException(2001, "input 元素格式不正确")
            kind = item.get("type")
            # reasoning 条目不含用户可读内容：跳过并提示，不因为"带推理标记"整单失败。
            if kind in IGNORED_ITEM_TYPES:
                _warn(warnings, f"已忽略 input 中的 {kind} 条目")
                continue
            # 工具调用结果在 Responses 里是 {type:function_call_output,...}
            if kind == "function_call_output":
                call_id = str(item.get("call_id") or "").strip()
                if not call_id:
                    raise BizException(2001, "function_call_output 缺少 call_id")
                output = _text_of(item.get("output"))
                if len(output) > MAX_MESSAGE_CONTENT_LENGTH:
                    raise message_too_long_error(len(messages) + 1, "tool", len(output))
                _append_message(
                    messages, len(messages) + 1,
                    role="tool", content=output, tool_call_id=call_id,
                )
                continue
            role = str(item.get("role") or "user").strip()
            if role not in ROLE_SET:
                raise BizException(2001, f"不支持的角色：{role}")
            text = _text_of(item.get("content"))
            if not text.strip():
                raise BizException(2001, "消息内容不能为空")
            if len(text) > MAX_MESSAGE_CONTENT_LENGTH:
                raise message_too_long_error(len(messages) + 1, role, len(text))
            if role == "tool":
                call_id = str(item.get("tool_call_id") or item.get("call_id") or "").strip()
                if not call_id:
                    raise BizException(2001, "tool 消息必须带 call_id")
                _append_message(
                    messages, len(messages) + 1,
                    role="tool", content=text, tool_call_id=call_id,
                )
            else:
                _append_message(messages, len(messages) + 1, role=role, content=text)
    else:
        raise BizException(2001, "input 不能为空")

    if not messages:
        # 例如 input 只有一个 reasoning 条目：翻译后没有任何可发送内容。
        raise BizException(2001, "input 不能为空")
    if len(messages) > 40:
        raise BizException(2001, "messages 最多 40 条")
    return messages


def _tool_body(tool: dict[str, Any]) -> dict[str, Any] | None:
    """取工具的函数体：Responses 是扁平字段，chat 是 `function` 子对象，两种都认。"""

    nested = tool.get("function")
    return nested if isinstance(nested, dict) else None


def _translate_tools(tools: list[Any]) -> list[dict[str, Any]]:
    """Responses 扁平工具 → Chat Completions 嵌套工具（执行层只认嵌套形态）。"""

    translated: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise BizException(2001, "tools 元素格式不正确")
        nested = _tool_body(tool)
        name = str(tool.get("name") or (nested or {}).get("name") or "").strip()
        if not name:
            raise BizException(2001, "function 工具必须带 name")
        body: dict[str, Any] = {"name": name}
        description = tool.get("description", (nested or {}).get("description"))
        if description is not None:
            body["description"] = str(description)
        parameters = tool.get("parameters", (nested or {}).get("parameters"))
        body["parameters"] = (
            parameters if isinstance(parameters, dict)
            else {"type": "object", "properties": {}}
        )
        strict = tool.get("strict", (nested or {}).get("strict"))
        if strict is not None:
            body["strict"] = bool(strict)
        translated.append({"type": SUPPORTED_TOOL_TYPE, "function": body})
    return translated


def _translate_tool_choice(choice: Any) -> Any:
    """`{"type":"function","name":"x"}` → `{"type":"function","function":{"name":"x"}}`。"""

    if isinstance(choice, dict) and str(choice.get("type") or "") == SUPPORTED_TOOL_TYPE:
        nested = _tool_body(choice)
        name = str(choice.get("name") or (nested or {}).get("name") or "").strip()
        if not name:
            raise BizException(2001, "tool_choice 指定 function 时必须带 name")
        return {"type": SUPPORTED_TOOL_TYPE, "function": {"name": name}}
    return choice


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


def _arguments_text(raw: Any) -> str:
    """`arguments` 必须是 JSON 字符串；上游给对象时序列化，缺失时给 `{}`。"""

    if isinstance(raw, str):
        return raw
    if raw is None:
        return "{}"
    return json.dumps(raw, ensure_ascii=False)


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
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        items.append({
            "type": "function_call",
            "id": f"fc_{uuid4().hex[:24]}",
            # P12：call_id 与 arguments 必须齐全，否则客户端回灌 function_call_output 时对不上。
            "call_id": str(call.get("id") or "").strip() or f"call_{uuid4().hex[:24]}",
            "name": str(function.get("name") or call.get("name") or ""),
            "arguments": _arguments_text(function.get("arguments", call.get("arguments"))),
            "status": "completed",
        })
    return items


def _envelope(
    data: dict, model: str, previous: str | None, warnings: list[str] | None = None,
) -> dict:
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
        # P12：被忽略的字段在这里明示，不静默丢弃。
        "platform_warnings": list(warnings or []),
    }


@router.post("")
async def create_response(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """`POST /v1/responses`：协议翻译 + 复用平台执行链。"""

    warnings: list[str] = []
    try:
        user = await _authenticate(authorization)
        # P12：字段语义必须在执行前判定（store=true 拒绝，reasoning/background 忽略）。
        _validate_payload(payload, warnings)
        alias = str(payload.get("model") or "").strip()
        capability_id = (await _model_map()).get(alias)
        if capability_id is None:
            raise BizException(2002, f"模型 {alias or '(空)'} 未在平台注册")

        messages = _messages_of(payload, warnings)
        previous = payload.get("previous_response_id")
        request = ChatCompletionRequest(
            capability_id=capability_id,
            input={"messages": [message.model_dump(exclude_none=True) for message in messages]},
            session_id=_session_of(previous),
        )
        tools = payload.get("tools")
        if isinstance(tools, list) and tools:
            # P12：扁平 → 嵌套的翻译只在这里做一次，执行层与上游只认嵌套形态。
            request.input["tools"] = _translate_tools(tools)
            request.input["tool_choice"] = _translate_tool_choice(
                payload.get("tool_choice") or "auto"
            )
        if isinstance(payload.get("temperature"), (int, float)):
            request.input["temperature"] = min(max(float(payload["temperature"]), 0.0), 2.0)
        if isinstance(payload.get("max_output_tokens"), int):
            request.input["max_tokens"] = payload["max_output_tokens"]

        if payload.get("stream"):
            return _stream_response(db, request, user, alias, previous, warnings)

        with use_identity(user.user_id, user.user_name, user.api_key_id):
            data = await chat_service.complete(db, request, user)
    except UnsupportedFieldError as error:
        # 业务码 4001 + HTTP 400：明确"字段不支持"，不伪装成限流。
        return JSONResponse(
            status_code=400,
            content={"error": {"message": error.message, "type": "invalid_request_error",
                               "code": f"platform_{error.code}"}},
        )
    except BizException as error:
        return _openai_error(error)
    except ValidationError as error:
        # 与 chat/completions 同一口径：入参校验失败是 400/2001，不是平台故障。
        logger.warning("Responses 入参校验失败 type={}", type(error).__name__)
        return _openai_error(BizException(2001, validation_reason(error)))
    except Exception:  # noqa: BLE001 - 兼容层必须返回 OpenAI 错误结构
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "平台执行失败", "type": "api_error",
                               "code": "platform_error"}},
        )

    return _envelope(
        data, alias, previous if isinstance(previous, str) else None, warnings,
    )


def _stream_response(
    db: Session, request: ChatCompletionRequest, user: UserContext,
    alias: str, previous: str | None, warnings: list[str] | None = None,
) -> StreamingResponse:
    """把平台 SSE 翻译成 Responses 事件流（顺序见模块 docstring，P12 已冻结）。"""

    response_id = _response_id(_session_of(previous))
    item_id = f"msg_{response_id}"
    created = int(time.time())
    platform_warnings = list(warnings or [])

    def _event(name: str, data: dict) -> str:
        return sse_frame({"type": name, **data})

    def _base_response() -> dict:
        return {
            "id": response_id, "object": "response", "created_at": created,
            "model": alias, "platform_warnings": platform_warnings,
        }

    def _message_item(text: str, status: str) -> dict:
        return {
            "type": "message", "id": item_id, "role": "assistant", "status": status,
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }

    async def _generate():
        with use_identity(user.user_id, user.user_name, user.api_key_id):
            yield _event("response.created", {
                "response": {**_base_response(), "status": "in_progress", "output": []},
            })
            # 客户端靠这两个事件挂载输出项；缺了会表现为"有连接但没内容"。
            yield _event("response.output_item.added", {
                "output_index": 0,
                "item": {"type": "message", "id": item_id, "role": "assistant",
                         "status": "in_progress", "content": []},
            })
            yield _event("response.content_part.added", {
                "item_id": item_id, "output_index": 0, "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            })
            collected: list[str] = []
            try:
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
                            "item_id": item_id, "output_index": 0,
                            "content_index": 0, "delta": text,
                        })
            except BizException as error:
                # 头已经发出去了，改不了状态码；补一个失败事件再正常收尾，
                # 避免客户端一直等到超时（执行链已写 failed 占位、不计费）。
                logger.warning("Responses 流式执行中断 code={}", error.code)
                yield _event("response.failed", {
                    "response": {
                        **_base_response(), "status": "failed",
                        "error": {"message": error.message, "code": f"platform_{error.code}"},
                    },
                })
                yield DONE_FRAME
                return
            except Exception as error:  # noqa: BLE001
                logger.error("Responses 流式执行异常 type={}", type(error).__name__)
                yield _event("response.failed", {
                    "response": {
                        **_base_response(), "status": "failed",
                        "error": {"message": "平台执行失败，请稍后重试",
                                  "code": "platform_error"},
                    },
                })
                yield DONE_FRAME
                return

            text = "".join(collected)
            yield _event("response.output_text.done", {
                "item_id": item_id, "output_index": 0, "content_index": 0, "text": text,
            })
            yield _event("response.output_item.done", {
                "output_index": 0, "item": _message_item(text, "completed"),
            })
            yield _event("response.completed", {
                "response": {
                    **_base_response(), "status": "completed",
                    "output": [_message_item(text, "completed")],
                },
            })
            yield DONE_FRAME

    return StreamingResponse(
        _generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

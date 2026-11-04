"""OpenAI 兼容层：让 Cherry Studio、Continue、LangChain 这类只认 OpenAI 协议的
客户端，零改造接入本平台。

设计取舍：
- 认证：客户端只发一个 `Authorization: Bearer sk_...`，这里把它当作平台 API Key
  的 **Secret**，取 SHA-256 摘要后交给 user-service 内部接口反查归属用户。
  明文密钥不落日志、不进请求头透传。
- 模型：`model` 字段按配置映射到 `capability_id`（默认 deepseek-flash=1）。
  未知模型返回 404 `model_not_found`，不静默兜底，避免"以为调了 A 其实调了 B"。
- 计费：复用平台既有执行链，按目录价扣积分、写账单，响应里附带
  `platform_request_id` 与 `platform_cost` 便于对账。
- 流式：平台不支持 SSE 增量生成，这里把完整结果包成"一个 chunk + [DONE]"
  的标准 SSE，客户端能正常渲染，但首字延迟等于整段生成时间。
"""

from __future__ import annotations

import hashlib
from uuid import uuid4
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizException
from app.core.logging import get_request_id, use_identity
from app.core.security import UserContext
from app.core.service_auth import expected_internal_token
from app.core.service_call import call_internal
from app.db.session import get_db
from app.schemas.chat import (
    MAX_MESSAGE_CONTENT_LENGTH,
    ChatCompletionRequest,
    ChatMessage,
)
from app.service.chat_service import chat_service
from app.service.capability_client import capability_client
from app.service.catalog_cache import OpenAIModelCatalog
from app.service.stream_service import DONE_FRAME, parse_sse_line, sse_frame

router = APIRouter()

ROLE_SET = {"system", "user", "assistant", "tool"}

# 平台错误码 -> (HTTP 状态码, OpenAI 错误类型)
_ERROR_MAP: dict[int, tuple[int, str]] = {
    1001: (401, "authentication_error"),
    1003: (401, "authentication_error"),
    1005: (401, "authentication_error"),
    2001: (400, "invalid_request_error"),
    2002: (404, "model_not_found"),
    2008: (400, "invalid_request_error"),
    2009: (503, "api_error"),
    3001: (402, "insufficient_quota"),
    4001: (429, "rate_limit_exceeded"),
}


def _error(status: int, message: str, code: str, kind: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": kind, "code": code}},
    )


def _configured_model_map() -> dict[str, int]:
    """Parse explicit alias overrides; malformed fragments are ignored."""

    mapping: dict[str, int] = {}
    for item in settings.openai_compat_model_map.split(","):
        alias, _, raw_id = item.partition("=")
        alias, raw_id = alias.strip(), raw_id.strip()
        if alias and raw_id.isdigit() and int(raw_id) >= 1:
            mapping[alias] = int(raw_id)
    return mapping


async def _model_map() -> dict[str, int]:
    """Resolve dynamic directory aliases with configured values taking precedence."""

    try:
        catalog = await capability_client.openai_model_catalog()
    except BizException as error:
        logger.warning("动态模型目录不可用 error_code={}", error.code)
        raise
    mapping = {**catalog.aliases, **_configured_model_map()}
    return {alias: target for alias, target in mapping.items() if target in catalog.capability_ids}


def _content_text(content: Any) -> str:
    """兼容 `content` 为字符串或分段数组两种写法。"""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type", "text") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return ""


def _bearer(header: str | None) -> str:
    if not header or not header.lower().startswith("bearer "):
        raise BizException(1001, "缺少 Authorization: Bearer 令牌")
    token = header[7:].strip()
    if not token.startswith("sk_") or len(token) < 16:
        raise BizException(1003, "API Key 凭证无效")
    return token


async def _authenticate(header: str | None) -> UserContext:
    token = _bearer(header)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    internal_token = expected_internal_token()
    if not internal_token:
        raise BizException(4003, "服务间凭据未配置，兼容层暂不可用")
    payload = await call_internal(
        settings.user_service_name,
        "POST",
        "/internal/user/apikey/verify",
        json={"secret_hash": digest},
        headers={"X-Internal-Token": internal_token},
    )
    key_id = payload.get("key_id")
    return UserContext(
        user_id=str(payload["user_id"]),
        user_name=str(payload.get("username", "")),
        request_id=get_request_id(),
        # P6：兼容层是最容易泄露 Key 的入口，必须把 Key 身份带到账单上。
        api_key_id=int(key_id) if isinstance(key_id, int) and key_id > 0 else None,
        entrypoint="openai_compat",
    )


def _openai_error(error: BizException) -> JSONResponse:
    status, kind = _ERROR_MAP.get(error.code, (500, "api_error"))
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": error.message,
                "type": kind,
                "code": f"platform_{error.code}",
            }
        },
    )



def _capability_message(message: "ChatMessage") -> dict[str, Any]:
    """把内部消息转成能力 Schema 可接受的 dict。

    纯工具调用的 assistant 消息 content 为空，而能力 Schema 的 content 声明了
    `minLength: 1`（有值时才有约束）。直接带上空串会撞 2001，所以这里省掉。
    """

    body = message.model_dump(exclude_none=True)
    if body.get("role") == "assistant" and not body.get("content"):
        body.pop("content", None)
    return body


def message_too_long_error(index: int, role: str, length: int) -> BizException:
    """超长消息统一成 `2001`（HTTP 400），语义必须是"消息太长"。

    为什么不能交给 `ChatMessage` 自己校验：它抛的是 Pydantic `ValidationError`，
    落到本模块的 `except Exception` 兜底就变成 `500 platform_error`，客户端只会
    看到"平台坏了"并盲目重试，运维也无法从错误码定位真实原因。
    """

    return BizException(
        2001,
        f"第 {index} 条消息（role={role}）内容 {length} 字符，超过单条上限 "
        f"{MAX_MESSAGE_CONTENT_LENGTH} 字符；请拆分或缩短后重试",
    )


#: Pydantic 会给 `ValueError`/断言类失败自带英文前缀，直接透出去就成了
#: "Value error, tool 角色的消息必须带 tool_call_id"。这里只剥前缀，不动正文。
_VALIDATION_PREFIXES: tuple[str, ...] = (
    "Value error, ",
    "Assertion failed, ",
    "Invalid value, ",
)


def _field_max_length(field_name: str | None) -> int | None:
    """从 `ChatMessage` 的**字段定义**读取 `max_length`，不另建第二套常量表。

    为什么必须回读 Schema：`content` 上限是 48000，而 `name` 与 `tool_call_id`
    只有 64。文案里硬写 48000 会让后两者的超长提示张冠李戴（实测确实如此），
    另建一份常量表又会立刻和 `Field(max_length=...)` 漂移。因此这里直接取
    Pydantic 保存的 `MaxLen` 元数据，Schema 改一次，文案自动跟着改。
    """

    if not field_name:
        return None
    field = ChatMessage.model_fields.get(field_name)
    if field is None:
        return None
    for meta in field.metadata:
        limit = getattr(meta, "max_length", None)
        if isinstance(limit, int) and limit > 0:
            return limit
    return None


def _strip_pydantic_prefix(reason: str) -> str:
    """剥掉 Pydantic 自带的英文前缀，让用户看到干净的中文原因。"""

    for prefix in _VALIDATION_PREFIXES:
        if reason.startswith(prefix):
            return reason[len(prefix):].strip()
    return reason


def validation_reason(error: ValidationError, index: int | None = None) -> str:
    """把 Pydantic 校验失败翻译成**不含用户输入**的可读原因。

    `str(error)` 会把 `input_value=...` 整段带出来（那可能是用户的简历全文），
    所以这里只取 `loc` 与 `msg`，绝不拼接异常字符串本体，也不写日志。
    """

    errors = error.errors()
    first = errors[0] if errors else {}
    parts = [part for part in first.get("loc", ()) if str(part) != "__root__"]
    loc = ".".join(str(part) for part in parts)
    prefix = f"第 {index} 条消息" if index is not None else "请求参数"
    where = f"{prefix}.{loc}" if loc else prefix
    reason = _strip_pydantic_prefix(str(first.get("msg") or "字段校验未通过").strip())
    if first.get("type") == "string_too_long":
        # loc 末段的字符串就是出错字段名（`('name',)`、`('messages', 0, 'name')` 都适用）。
        field_name = next(
            (str(part) for part in reversed(parts) if isinstance(part, str)), None
        )
        limit = _field_max_length(field_name)
        if limit is not None:
            reason = f"超过 {limit} 字符上限"
        # 取不到字段定义时保留 Pydantic 原文，绝不猜一个数字（那正是 M1 的病根）。
    return f"{where} 不合法：{reason}"


async def _stream_response(
    db: Session, request: ChatCompletionRequest, user: UserContext, alias: str
) -> StreamingResponse:
    """E1：把上游真实 SSE 翻译成 OpenAI `chat.completion.chunk`。

    逐块转发；`usage` 只在上游真的给了的时候附在最后一块上，
    没给就不伪造（C1 口径）。客户端断开时上层生成器会被关闭，
    `chat_service.stream` 的 `finally` 负责落一条失败占位且不计费。
    """

    created = int(time.time())
    chunk_id = f"chatcmpl-{uuid4().hex}"
    model_name = alias

    def _chunk(delta: dict[str, Any], finish: str | None, usage: dict | None = None) -> str:
        frame: dict[str, Any] = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if usage is not None:
            frame["usage"] = usage
        return sse_frame(frame)

    async def _generate():
        with use_identity(user.user_id, user.user_name, user.api_key_id):
            yield _chunk({"role": "assistant"}, None)
            usage: dict | None = None
            try:
                async for line in chat_service.stream(db, request, user):
                    frame = parse_sse_line(line)
                    if frame is None:
                        continue
                    if isinstance(frame.get("model"), str):
                        model_name = frame["model"]
                    if isinstance(frame.get("usage"), dict):
                        usage = frame["usage"]
                    choices = frame.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                    text = delta.get("content") if isinstance(delta, dict) else None
                    if isinstance(text, str) and text:
                        yield _chunk({"content": text}, None)
            except BizException as error:
                # 响应头已经发出去了，改不了 HTTP 状态码；这里补一个 OpenAI 风格的
                # error 帧再正常收尾，避免客户端收到"半截流"（实测会一直等到超时）。
                logger.warning("流式执行中断 code={}", error.code)
                yield sse_frame({"error": {
                    "message": error.message,
                    "type": "invalid_request_error" if error.code < 5000 else "api_error",
                    "code": f"platform_{error.code}",
                }})
                yield DONE_FRAME
                return
            except Exception as error:  # noqa: BLE001 - 保住流的收尾，不让异常穿透成断连
                logger.error("流式执行异常 type={}", type(error).__name__)
                yield sse_frame({"error": {
                    "message": "平台执行失败，请稍后重试",
                    "type": "api_error",
                    "code": "platform_error",
                }})
                yield DONE_FRAME
                return
            yield _chunk({}, "stop", usage)
            yield DONE_FRAME

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/models")
async def list_models(authorization: str | None = Header(default=None)) -> Any:
    """Return aliases for online chat capabilities with an explicit public name."""

    try:
        await _authenticate(authorization)
    except BizException as error:
        return _openai_error(error)
    try:
        catalog = await capability_client.openai_model_catalog()
    except BizException as error:
        return _openai_error(error)
    mapping = {**catalog.aliases, **_configured_model_map()}
    eligible_ids = catalog.capability_ids
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": alias, "object": "model", "created": created, "owned_by": "aicapabilityhub"}
            for alias, capability_id in mapping.items()
            if capability_id in eligible_ids
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """OpenAI Chat Completions 兼容入口。"""

    try:
        user = await _authenticate(authorization)
        alias = str(payload.get("model") or "").strip()
        capability_id = (await _model_map()).get(alias)
        if capability_id is None:
            raise BizException(2002, f"模型 {alias or '(空)'} 未在平台注册")

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise BizException(2001, "messages 不能为空")
        if len(raw_messages) > 40:
            raise BizException(2001, "messages 最多 40 条")

        messages: list[ChatMessage] = []
        for index, item in enumerate(raw_messages, start=1):
            if not isinstance(item, dict):
                raise BizException(2001, "messages 元素格式不正确")
            role = str(item.get("role", "")).strip()
            if role not in ROLE_SET:
                raise BizException(2001, f"不支持的角色：{role}")
            content = _content_text(item.get("content"))
            # 超长必须显式判在这里：交给 ChatMessage 会抛 ValidationError，
            # 那就是 500 platform_error（长短消息的边界条件不能靠兜底异常表达）。
            if len(content) > MAX_MESSAGE_CONTENT_LENGTH:
                raise message_too_long_error(index, role, len(content))
            # E2：assistant 只回工具调用时 content 为空，这是合法的 OpenAI 形态。
            tool_calls = item.get("tool_calls")
            if not content.strip() and not (role == "assistant" and isinstance(tool_calls, list) and tool_calls):
                raise BizException(2001, "消息内容不能为空")
            # E2：工具回灌消息必须带上 tool_call_id，否则 ChatMessage 的校验会拒。
            tool_call_id = item.get("tool_call_id")
            name = item.get("name")
            # 其余字段级校验（tool_call_id/name 长度、角色与工具字段的一致性）
            # 同样要 400 而不是 500，所以就地转成 2001。
            try:
                messages.append(ChatMessage(
                    role=role,
                    content=content,
                    tool_call_id=str(tool_call_id).strip() if tool_call_id else None,
                    name=str(name).strip() if name else None,
                    tool_calls=tool_calls if isinstance(tool_calls, list) else None,
                ))
            except ValidationError as error:
                raise BizException(2001, validation_reason(error, index)) from error

        capability_input: dict[str, Any] = {
            # exclude_none 是必需的：ChatMessage 还有 tool_call_id/name 两个可选字段，
            # 带 null 落进能力 Schema 会撞 `additionalProperties: false`（实测 2001）。
            "messages": [_capability_message(item) for item in messages]
        }
        temperature = payload.get("temperature")
        if isinstance(temperature, (int, float)):
            capability_input["temperature"] = min(max(float(temperature), 0.0), 2.0)
        # E2：工具参数原样透传给执行器；平台不执行工具，只把上游 tool_calls 交回客户端。
        # 之前兼容层只搬 messages/temperature，导致 tools 被静默丢弃（实测模型答"没有工具"）。
        for name in ("tools", "tool_choice", "parallel_tool_calls"):
            if payload.get(name) is not None:
                capability_input[name] = payload[name]

        request = ChatCompletionRequest(
            capability_id=capability_id, input=capability_input
        )
        # 兼容层不带网关注入的身份头，执行前补上上下文，后续内部调用才会带上 X-User-Id。
        if payload.get("stream"):
            return await _stream_response(db, request, user, alias)
        with use_identity(user.user_id, user.user_name, user.api_key_id):
            data = await chat_service.complete(db, request, user)
    except BizException as error:
        return _openai_error(error)
    except ValidationError as error:
        # 兜底第二道：凡是入参校验类的失败一律 400/2001，绝不落成 500。
        logger.warning("兼容层入参校验失败 type={}", type(error).__name__)
        return _openai_error(BizException(2001, validation_reason(error)))
    except Exception as error:  # noqa: BLE001 - 兼容层必须返回 OpenAI 错误结构而非平台包裹
        logger.error("兼容层执行失败 type={}", type(error).__name__)
        return _error(500, "平台执行失败，请稍后重试", "platform_error", "api_error")

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message", {})
    text = message.get("content", "")
    tool_calls = message.get("tool_calls")
    body = {
        "id": data["id"],
        "object": "chat.completion",
        "created": data["created"],
        "model": data["model"],
        "choices": [
            {
                "index": 0,
                # E2：只有存在 tool_calls 时才加字段，普通回复的响应体不变。
                "message": {
                    "role": "assistant", "content": text,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
                "finish_reason": choice.get("finish_reason", "stop"),
            }
        ],
        "usage": data["usage"],
        "platform_request_id": data.get("request_id"),
        "platform_cost": data.get("cost"),
    }

    return body



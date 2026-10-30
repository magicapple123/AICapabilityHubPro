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
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizException
from app.core.logging import get_request_id, use_identity
from app.core.security import UserContext
from app.core.service_auth import expected_internal_token
from app.core.service_call import call_internal
from app.db.session import get_db
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.service.chat_service import chat_service

router = APIRouter()

ROLE_SET = {"system", "user", "assistant"}

# 平台错误码 -> (HTTP 状态码, OpenAI 错误类型)
_ERROR_MAP: dict[int, tuple[int, str]] = {
    1001: (401, "authentication_error"),
    1003: (401, "authentication_error"),
    1005: (401, "authentication_error"),
    2001: (400, "invalid_request_error"),
    2002: (404, "model_not_found"),
    2008: (400, "invalid_request_error"),
    3001: (402, "insufficient_quota"),
    4001: (429, "rate_limit_exceeded"),
}


def _error(status: int, message: str, code: str, kind: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": kind, "code": code}},
    )


def _model_map() -> dict[str, int]:
    """解析 `别名=能力ID` 配置；非法片段直接忽略，避免启动期因配置笔误崩溃。"""

    mapping: dict[str, int] = {}
    for item in settings.openai_compat_model_map.split(","):
        alias, _, raw_id = item.partition("=")
        alias, raw_id = alias.strip(), raw_id.strip()
        if alias and raw_id.isdigit() and int(raw_id) >= 1:
            mapping[alias] = int(raw_id)
    return mapping


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
    return UserContext(
        user_id=str(payload["user_id"]),
        user_name=str(payload.get("username", "")),
        request_id=get_request_id(),
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


@router.get("/models")
async def list_models(authorization: str | None = Header(default=None)) -> Any:
    """返回配置里可用的模型别名，供客户端下拉框使用。"""

    try:
        await _authenticate(authorization)
    except BizException as error:
        return _openai_error(error)
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": alias, "object": "model", "created": created, "owned_by": "aicapabilityhub"}
            for alias in _model_map()
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
        capability_id = _model_map().get(alias)
        if capability_id is None:
            raise BizException(2002, f"模型 {alias or '(空)'} 未在平台注册")

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise BizException(2001, "messages 不能为空")
        if len(raw_messages) > 40:
            raise BizException(2001, "messages 最多 40 条")

        messages: list[ChatMessage] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                raise BizException(2001, "messages 元素格式不正确")
            role = str(item.get("role", "")).strip()
            if role not in ROLE_SET:
                raise BizException(2001, f"不支持的角色：{role}")
            content = _content_text(item.get("content"))
            if not content.strip():
                raise BizException(2001, "消息内容不能为空")
            messages.append(ChatMessage(role=role, content=content))

        capability_input: dict[str, Any] = {
            "messages": [item.model_dump() for item in messages]
        }
        temperature = payload.get("temperature")
        if isinstance(temperature, (int, float)):
            capability_input["temperature"] = min(max(float(temperature), 0.0), 2.0)

        request = ChatCompletionRequest(
            capability_id=capability_id, input=capability_input
        )
        # 兼容层不带网关注入的身份头，执行前补上上下文，后续内部调用才会带上 X-User-Id。
        with use_identity(user.user_id, user.user_name):
            data = await chat_service.complete(db, request, user)
    except BizException as error:
        return _openai_error(error)
    except Exception as error:  # noqa: BLE001 - 兼容层必须返回 OpenAI 错误结构而非平台包裹
        logger.error("兼容层执行失败 type={}", type(error).__name__)
        return _error(500, "平台执行失败，请稍后重试", "platform_error", "api_error")

    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    body = {
        "id": data["id"],
        "object": "chat.completion",
        "created": data["created"],
        "model": data["model"],
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": data["usage"],
        "platform_request_id": data.get("request_id"),
        "platform_cost": data.get("cost"),
    }

    if not payload.get("stream"):
        return body

    created = data["created"]
    chunk_id = data["id"]

    def _chunk(delta: dict[str, Any], finish: str | None) -> str:
        frame = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": data["model"],
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"

    def _stream():
        yield _chunk({"role": "assistant", "content": text}, None)
        yield _chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")

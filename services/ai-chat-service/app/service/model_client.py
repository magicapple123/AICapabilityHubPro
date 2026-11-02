"""OpenAI 兼容模型的调用适配层。

职责边界：
- 只负责一次 HTTP 调用与结果解析，不读写数据库、不抛业务异常；
- 超时、连接失败、响应格式异常都折算成**降级结果**（`degraded=True`），
  由 service 层决定话术与计费状态，保证闭环不中断（指南 3.4）。

token 口径（C1）：
- 只采信上游 `usage`；`prompt_tokens` / `completion_tokens` 分别落库，两者可直接相加；
- Responses 协议用 `input_tokens` / `output_tokens`，这里统一归一化；
- 上游没给 usage 时 `usage_source="missing"`，**不再用字符数冒充 token**：
  `per_call` 能力照常按次计费，`per_token` 能力由 service 层失败关闭。

容错（D4）：
- 错误码细分：`5003` 上游限流(429) / `5004` 鉴权欠费(401/402/403) / `5005` 上游故障(5xx)；
- **只对超时与 5xx 重试一次**（退避 300ms），4xx 不重试；
- 重试发生在"取到结果之前"，计费在调用返回之后，因此**一次调用只会产生一条账单**。
"""

import asyncio
import time
from dataclasses import dataclass

import httpx
from loguru import logger

from app.core.config import ModelRuntimeSettings, settings
from app.core.constants import CallStatus, DEGRADED_REPLY, ModelErrorCode, TokenSource

# 重试退避（秒）；只用于超时与 5xx。
RETRY_BACKOFF_SECONDS = 0.3


def _non_negative_int(value: object) -> int | None:
    """只接受真正的整数（含 0）；bool 与浮点一律视为缺失，避免 1.0 之类被静默截断。"""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def normalize_usage(body: object) -> tuple[int, int, str]:
    """把上游 `usage` 归一化为 `(prompt_tokens, completion_tokens, source)`。

    - Chat Completions：`prompt_tokens` / `completion_tokens`
    - Responses：`input_tokens` / `output_tokens`
    - 缺失或畸形：`(0, 0, "missing")`，由调用方决定失败关闭还是照常按次计费
    """

    if not isinstance(body, dict):
        return 0, 0, TokenSource.MISSING.value
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, TokenSource.MISSING.value

    prompt = _non_negative_int(usage.get("prompt_tokens"))
    completion = _non_negative_int(usage.get("completion_tokens"))
    if prompt is None:
        prompt = _non_negative_int(usage.get("input_tokens"))
    if completion is None:
        completion = _non_negative_int(usage.get("output_tokens"))
    if prompt is None or completion is None:
        return 0, 0, TokenSource.MISSING.value
    if prompt + completion <= 0:
        # 真实调用不可能 0 token；当作上游没给，避免把"没给"记成"用了 0"。
        return 0, 0, TokenSource.MISSING.value
    return prompt, completion, TokenSource.UPSTREAM.value


@dataclass(frozen=True)
class ModelReply:
    """一次模型调用的结果；`error_code` 仅在降级时有值。"""

    content: str
    call_status: str
    model_name: str
    # C1：两个分量分别来自上游 usage，可直接相加、可独立计价。
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_source: str = TokenSource.MISSING.value
    error_code: int | None = None
    # 是否来自 Mock 分支（`USE_MOCK=true`），用于在响应里区分真实调用。
    mock: bool = False
    # E2：模型要求调用的工具；为空表示普通回复。
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"
    # D3：文生图结果（url 列表）；文本执行器为 None。
    images: list[dict] | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def degraded(self) -> bool:
        return self.call_status == CallStatus.DEGRADED.value


def _error_code_for_status(status: int) -> ModelErrorCode:
    """HTTP 状态 → 平台错误码（D4 细分）。"""

    if status == 429:
        return ModelErrorCode.UPSTREAM_RATE_LIMIT
    if status in (401, 402, 403):
        return ModelErrorCode.UPSTREAM_AUTH
    return ModelErrorCode.UPSTREAM_FAULT


def _retryable(status: int | None) -> bool:
    """只重试超时（status=None）与 5xx；4xx 一律不重试，避免放大计费风险。"""

    return status is None or status >= 500


class ModelClient:
    """把对话消息发给 OpenAI 兼容接口，失败时降级为兜底话术。"""

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        runtime: ModelRuntimeSettings | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        params: dict | None = None,
        max_tokens: int | None = None,
    ) -> ModelReply:
        """`base_url/api_key/timeout` 优先于 `runtime`（provider 覆盖全局配置）。"""

        resolved_base = base_url or (
            runtime.model_base_url if runtime else settings.model_base_url
        )
        resolved_key = api_key or (runtime.model_api_key if runtime else settings.model_api_key)
        resolved_timeout = timeout or settings.model_timeout
        url = f"{resolved_base.rstrip('/')}/chat/completions"

        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or settings.model_max_tokens,
            "stream": False,
        }
        # D4：白名单参数透传；未列入白名单的字段在入口就被 2001 拒绝，这里只做转发。
        for key, value in (params or {}).items():
            if value is not None:
                payload[key] = value

        headers = {
            "Authorization": f"Bearer {resolved_key}",
            "Content-Type": "application/json",
        }

        last_error = ModelErrorCode.BAD_RESPONSE
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(
                    timeout=resolved_timeout, follow_redirects=False
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
                if response.status_code >= 400:
                    code = _error_code_for_status(response.status_code)
                    logger.warning(
                        "模型返回错误 model={} status={} code={}",
                        model, response.status_code, int(code),
                    )
                    if attempt == 1 and _retryable(response.status_code):
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                        last_error = code
                        continue
                    return self._degraded(model, code)
                body = response.json()
                return self._parse(body, fallback_model=model)
            except httpx.TimeoutException:
                # 只记录类型与模型名，不打印请求体或 Key（指南 5.7）。
                logger.warning("模型调用超时 model={} attempt={}", model, attempt)
                last_error = ModelErrorCode.TIMEOUT
                if attempt == 1:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                    continue
                return self._degraded(model, ModelErrorCode.TIMEOUT)
            except Exception as exc:
                logger.warning(
                    "模型调用失败 model={} type={} attempt={}", model, type(exc).__name__, attempt
                )
                last_error = ModelErrorCode.BAD_RESPONSE
                if attempt == 1:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                    continue
                return self._degraded(model, ModelErrorCode.BAD_RESPONSE)

        return self._degraded(model, last_error)

    @staticmethod
    def _parse(body: object, *, fallback_model: str) -> ModelReply:
        """解析 OpenAI 兼容响应；结构不符时同样按降级处理。"""

        if not isinstance(body, dict):
            return ModelClient._degraded(fallback_model, ModelErrorCode.BAD_RESPONSE)

        choices = body.get("choices")
        content = ""
        tool_calls: list[dict] | None = None
        finish_reason = "stop"
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                finish_reason = str(first.get("finish_reason") or "stop")
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
                    raw_calls = message.get("tool_calls")
                    if isinstance(raw_calls, list) and raw_calls:
                        tool_calls = [call for call in raw_calls if isinstance(call, dict)]
        # E2：只有 tool_calls、没有正文，是合法回复（模型在要工具，不是故障）。
        if not content and not tool_calls:
            return ModelClient._degraded(fallback_model, ModelErrorCode.BAD_RESPONSE)

        prompt_tokens, completion_tokens, source = normalize_usage(body)

        return ModelReply(
            content=content,
            call_status=CallStatus.SUCCESS.value,
            model_name=str(body.get("model") or fallback_model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usage_source=source,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else finish_reason,
        )

    @staticmethod
    def _degraded(model: str, error_code: ModelErrorCode) -> ModelReply:
        return ModelReply(
            content=DEGRADED_REPLY,
            call_status=CallStatus.DEGRADED.value,
            model_name=model,
            usage_source=TokenSource.MISSING.value,
            error_code=int(error_code),
        )


model_client = ModelClient()

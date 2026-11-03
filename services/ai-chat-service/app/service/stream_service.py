"""真流式（E1）：逐块转发上游 SSE，流期间不持有数据库事务。

关键约束（已冻结）：
- **流期间不持连接**：用户消息先提交，上游流结束后再开新事务写助手消息与账单；
- 只认上游 `usage`（需向上游要 `stream_options.include_usage`）；上游没给就记
  `usage_source="missing"`，`per_token` 能力在结算时失败关闭（与 C1 一致）；
- **客户端中途断开**：取消上游流，写一条 `failed` 占位消息、**不计费**并记
  `stream_aborted`。理由：没有上游 usage 就无法诚实计价，宁可 0 元留痕，
  也不拿字符数估算冒充 token（与 C1「不拿字符数冒充」一致）。
  这一条与需求清单第 6 节"按已生成 token 计费"的建议不同，已记入日志待产品确认。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx
from loguru import logger

from app.core.constants import CallStatus, TokenSource
from app.core.exceptions import BizException
from app.core.http_client import get_http_client
from app.core.provider_breaker import provider_breaker
from app.core.provider_guard import SafeTarget, pinned_request_parts
from app.service.model_client import normalize_usage


@dataclass
class StreamOutcome:
    """一次流式调用累计出的结果，用于落库与计费。"""

    content: str = ""
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_source: str = TokenSource.MISSING.value
    finished: bool = False
    aborted: bool = False
    error_code: int | None = None
    frames: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def call_status(self) -> str:
        if self.aborted or self.error_code is not None:
            return CallStatus.FAILED.value
        return CallStatus.SUCCESS.value


def _delta_text(frame: dict) -> str:
    choices = frame.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def parse_sse_line(line: str) -> dict | None:
    """解析一行 SSE；非 `data:` 行与 `[DONE]` 返回 None。"""

    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        frame = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return frame if isinstance(frame, dict) else None


async def stream_upstream(
    *,
    base_url: str,
    api_key: str,
    payload: dict,
    timeout: float,
    outcome: StreamOutcome,
    on_frame=None,
    target: SafeTarget | None = None,
    breaker_key: str | None = None,
):
    """逐块产出上游 SSE 文本，把累计结果写进调用方传入的 `outcome`。

    为什么用传入对象而不是返回值：async generator 不能 `return` 值，
    变异一个显式传入的账本对象是唯一可靠的"边流边记账"方式。

    `target`（P15）：非空时按已校验 IP 建连，Host/SNI 仍是原域名。
    `breaker_key`（P16）：供应商 alias；熔断打开时先标 `outcome.error_code=5005`
    再抛 `BizException`，保证上层结算走"失败占位 + 不计费"，而不是留下空成功。
    """

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    extensions = None
    if target is not None:
        url, pinned_headers, extensions = pinned_request_parts(target, "/chat/completions")
        headers.update(pinned_headers)
    request_payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}

    try:
        provider_breaker.guard(breaker_key)
    except BizException:
        outcome.error_code = 5005
        raise

    try:
        # 共享 client 的 stream() 只借用连接，不关闭连接池；响应用完即释放回池。
        client = await get_http_client()
        async with client.stream(
            "POST", url, json=request_payload, headers=headers, timeout=timeout,
            extensions=extensions, follow_redirects=False,
        ) as response:
            if response.status_code >= 400:
                outcome.error_code = _status_code(response.status_code)
                provider_breaker.record_failure(breaker_key, outcome.error_code)
                logger.warning(
                    "流式上游返回错误 status={} code={}",
                    response.status_code, outcome.error_code,
                )
                return
            async for line in response.aiter_lines():
                frame = parse_sse_line(line)
                if frame is None:
                    # 仍然把空行/注释转发出去，保持 SSE 心跳语义
                    if line.strip():
                        yield line
                    continue
                outcome.frames += 1
                outcome.model_name = str(frame.get("model") or outcome.model_name)
                outcome.content += _delta_text(frame)
                prompt, completion, source = normalize_usage(frame)
                if source == TokenSource.UPSTREAM.value:
                    outcome.prompt_tokens, outcome.completion_tokens = prompt, completion
                    outcome.usage_source = source
                if on_frame is not None:
                    on_frame(frame)
                yield line
            outcome.finished = True
            provider_breaker.record_success(breaker_key)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        outcome.error_code = 5001 if isinstance(exc, httpx.TimeoutException) else 5005
        provider_breaker.record_failure(breaker_key, outcome.error_code)
        logger.warning("流式调用中断 type={}", type(exc).__name__)
    except GeneratorExit:  # 客户端断开
        outcome.aborted = True
        logger.info("流式调用被客户端中止 frames={}", outcome.frames)
        raise


def _status_code(status: int) -> int:
    if status == 429:
        return 5003
    if status in (401, 402, 403):
        return 5004
    return 5005


def sse_frame(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


DONE_FRAME = "data: [DONE]\n\n"

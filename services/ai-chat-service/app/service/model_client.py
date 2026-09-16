"""OpenAI 兼容模型的调用适配层。

职责边界：
- 只负责一次 HTTP 调用与结果解析，不读写数据库、不抛业务异常；
- 超时、连接失败、响应格式异常都折算成**降级结果**（`degraded=True`），
  由 service 层决定话术与计费状态，保证闭环不中断（指南 3.4）。

模型地址与 Key 来自 Nacos 热更新快照（`model_runtime_config`），
超时、最大 token 与系统提示词来自环境变量，均不硬编码。
"""

import time
from dataclasses import dataclass

import httpx
from loguru import logger

from app.core.config import ModelRuntimeSettings, settings
from app.core.constants import CallStatus, DEGRADED_REPLY, ModelErrorCode


@dataclass(frozen=True)
class ModelReply:
    """一次模型调用的结果；`error_code` 仅在降级时有值。"""

    content: str
    call_status: str
    token_count: int
    model_name: str
    error_code: int | None = None
    # 是否来自 Mock 分支（`USE_MOCK=true`），用于在响应里区分真实调用。
    mock: bool = False

    @property
    def degraded(self) -> bool:
        return self.call_status == CallStatus.DEGRADED.value


class ModelClient:
    """把对话消息发给 OpenAI 兼容接口，失败时降级为兜底话术。"""

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        runtime: ModelRuntimeSettings,
    ) -> ModelReply:
        url = f"{runtime.model_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": settings.model_max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {runtime.model_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=settings.model_timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
            return self._parse(body, fallback_model=model)
        except httpx.TimeoutException:
            # 只记录类型与模型名，不打印请求体或 Key（指南 5.7）。
            logger.warning("模型调用超时 model={}", model)
            return self._degraded(model, ModelErrorCode.TIMEOUT)
        except Exception as exc:
            logger.warning("模型调用失败 model={} type={}", model, type(exc).__name__)
            return self._degraded(model, ModelErrorCode.BAD_RESPONSE)

    @staticmethod
    def _parse(body: object, *, fallback_model: str) -> ModelReply:
        """解析 OpenAI 兼容响应；结构不符时同样按降级处理。"""

        if not isinstance(body, dict):
            return ModelClient._degraded(fallback_model, ModelErrorCode.BAD_RESPONSE)

        choices = body.get("choices")
        content = ""
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
        if not content:
            return ModelClient._degraded(fallback_model, ModelErrorCode.BAD_RESPONSE)

        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        token_count = usage.get("total_tokens")
        if not isinstance(token_count, int) or token_count < 0:
            token_count = len(content)

        return ModelReply(
            content=content,
            call_status=CallStatus.SUCCESS.value,
            token_count=token_count,
            model_name=str(body.get("model") or fallback_model),
        )

    @staticmethod
    def _degraded(model: str, error_code: ModelErrorCode) -> ModelReply:
        return ModelReply(
            content=DEGRADED_REPLY,
            call_status=CallStatus.DEGRADED.value,
            token_count=len(DEGRADED_REPLY),
            model_name=model,
            error_code=int(error_code),
        )


model_client = ModelClient()

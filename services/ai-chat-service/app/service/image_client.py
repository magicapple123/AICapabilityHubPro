"""文生图执行器（D3）。

为什么会有一个 `dashscope-image` 协议：
百炼（DashScope）的兼容模式**不提供** `/images/generations`（实测 404），
文生图走原生**异步任务**：提交 `image-synthesis` 拿 task_id，再轮询 `/tasks/{id}`。
因此这里按协议分流：`openai-image` 走同步 `/images/generations`，
`dashscope-image` 走"提交 + 轮询"。

计费：按件（`per_unit`），件数来自请求的 `n`；**失败/超时一律返回 error_code**，
由上层按 0 元记账，不产生"没出图还扣钱"。
"""

import asyncio
import time
from dataclasses import dataclass, field

import httpx
from loguru import logger

from app.core.constants import ModelErrorCode
from app.core.http_client import get_http_client

# 轮询参数：最多等 90 秒，间隔 2 秒（百炼 turbo 模型通常 10~30 秒出图）。
POLL_INTERVAL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 90.0


@dataclass
class ImageResult:
    images: list[dict] = field(default_factory=list)
    model_name: str = ""
    error_code: int | None = None
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error_code is None and bool(self.images)


def _size_to_dashscope(size: str) -> str:
    """`512x512` → `512*512`；非法值回落到 1024*1024。"""

    parts = size.lower().replace("*", "x").split("x")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}*{parts[1]}"
    return "1024*1024"


def _error_of_status(status: int) -> int:
    if status == 429:
        return int(ModelErrorCode.UPSTREAM_RATE_LIMIT)
    if status in (401, 402, 403):
        return int(ModelErrorCode.UPSTREAM_AUTH)
    return int(ModelErrorCode.UPSTREAM_FAULT)


async def generate_dashscope(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    n: int,
    size: str,
    timeout: float,
) -> ImageResult:
    """提交异步任务并轮询到完成；返回图片 URL 列表。"""

    started = time.perf_counter()
    root = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": _size_to_dashscope(size), "n": max(1, min(n, 4))},
    }

    try:
        # 提交 + 轮询共用一条 keep-alive 连接；轮询间隔 2 s，不会占满连接池。
        client = await get_http_client()
        submit = await client.post(
            f"{root}/api/v1/services/aigc/text2image/image-synthesis",
            json=payload,
            headers={**headers, "X-DashScope-Async": "enable"},
            timeout=timeout,
        )
        if submit.status_code >= 400:
            logger.warning("文生图提交失败 status={}", submit.status_code)
            return ImageResult(
                model_name=model, error_code=_error_of_status(submit.status_code),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        body = submit.json()
        task_id = (body.get("output") or {}).get("task_id")
        if not task_id:
            return ImageResult(model_name=model,
                               error_code=int(ModelErrorCode.BAD_RESPONSE))

        deadline = time.monotonic() + min(POLL_TIMEOUT_SECONDS, timeout)
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            poll = await client.get(
                f"{root}/api/v1/tasks/{task_id}", headers=headers, timeout=timeout
            )
            if poll.status_code >= 400:
                logger.warning("文生图轮询失败 status={}", poll.status_code)
                return ImageResult(
                    model_name=model, error_code=_error_of_status(poll.status_code),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            output = poll.json().get("output") or {}
            status = str(output.get("task_status") or "").upper()
            if status in ("SUCCEEDED", "SUCCESS"):
                images = [
                    {"url": item.get("url"), "revised_prompt": item.get("orig_prompt")}
                    for item in output.get("results") or []
                    if isinstance(item, dict) and item.get("url")
                ]
                if not images:
                    return ImageResult(
                        model_name=model,
                        error_code=int(ModelErrorCode.BAD_RESPONSE),
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                    )
                return ImageResult(
                    images=images, model_name=model,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                logger.warning("文生图任务失败 status={} task_id={}", status, task_id)
                return ImageResult(
                    model_name=model,
                    error_code=int(ModelErrorCode.UPSTREAM_FAULT),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
    except httpx.TimeoutException:
        return ImageResult(model_name=model, error_code=int(ModelErrorCode.TIMEOUT),
                           elapsed_ms=int((time.perf_counter() - started) * 1000))
    except Exception as exc:  # noqa: BLE001
        logger.warning("文生图调用异常 type={}", type(exc).__name__)
        return ImageResult(model_name=model,
                           error_code=int(ModelErrorCode.BAD_RESPONSE),
                           elapsed_ms=int((time.perf_counter() - started) * 1000))

    return ImageResult(model_name=model, error_code=int(ModelErrorCode.TIMEOUT),
                       elapsed_ms=int((time.perf_counter() - started) * 1000))


async def generate_openai(
    *, base_url: str, api_key: str, model: str, prompt: str, n: int, size: str,
    timeout: float,
) -> ImageResult:
    """同步 `/images/generations`（OpenAI 兼容协议的供应商）。"""

    started = time.perf_counter()
    try:
        client = await get_http_client()
        response = await client.post(
            f"{base_url.rstrip('/')}/images/generations",
            json={"model": model, "prompt": prompt, "n": max(1, n), "size": size},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except httpx.TimeoutException:
        return ImageResult(model_name=model, error_code=int(ModelErrorCode.TIMEOUT))
    except Exception as exc:  # noqa: BLE001
        logger.warning("文生图调用异常 type={}", type(exc).__name__)
        return ImageResult(model_name=model, error_code=int(ModelErrorCode.BAD_RESPONSE))

    if response.status_code >= 400:
        return ImageResult(model_name=model,
                           error_code=_error_of_status(response.status_code))
    items = (response.json() or {}).get("data") or []
    images = [
        {"url": item.get("url"), "revised_prompt": item.get("revised_prompt")}
        for item in items if isinstance(item, dict) and item.get("url")
    ]
    return ImageResult(
        images=images, model_name=model,
        error_code=None if images else int(ModelErrorCode.BAD_RESPONSE),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )

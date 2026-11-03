"""进程级 HTTP 客户端单例：内部服务调用与上游模型调用共用一套连接池。

为什么必须复用：Windows + Docker 端口转发下，新建一条 TCP 连接实测 200–450 ms 单跳；
一次 chat 调用要跨 3–4 跳，若每跳都 `async with httpx.AsyncClient(...)`，
光握手就是 0.6–0.8 s 的固定开销（`docs/压测报告-2026-11-02.md` 第 5.2 节；
复测实测改前 1.8–2.0 s/次 → 改后 0.12–0.14 s/次，见第 7.3 节）。

三条约束：

1. **只在同一事件循环内复用**。连接池与事件循环绑定，跨循环复用会抛
   `RuntimeError: Event loop is closed`。检测到循环变化时丢弃旧实例重建
   （测试里每个用例一个 loop，靠这一条保证不串）。
   因此不要在线程池 / `asyncio.run()` 里调用 `call_internal`；那类场景应
   降级为临时 `httpx.AsyncClient`。
2. **超时不在这里固定**。内部 RPC、上游模型、图片轮询的超时语义完全不同，
   统一由调用点逐请求传入 `client.request(..., timeout=...)`。这里的
   `timeout=10.0` 只是"漏传时不至于永不超时"的兜底。
3. **`trust_env=False`**：不探测系统代理，同机实测省约 70 ms（压测报告 5.2）。

关闭时机：`app/main.py` 的 lifespan shutdown 调 `close_http_client()`。
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx

# 单进程内 4 跳链路共用；100 并发上限远低于系统端口上限，
# 50 条 keep-alive 正好覆盖 4 跳 × 10 并发的常驻场景。
DEFAULT_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=50,
    keepalive_expiry=30,
)

# 漏传 timeout 时的兜底，不是生效值（见模块 docstring 第 2 条）。
FALLBACK_TIMEOUT = 10.0

_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        limits=DEFAULT_LIMITS,
        timeout=FALLBACK_TIMEOUT,
        trust_env=False,
    )


async def get_http_client() -> httpx.AsyncClient:
    """返回当前事件循环内的共享 client；首次调用时懒加载。

    调用方**不要**关闭它（不要 `async with`），进程退出时由
    `close_http_client()` 统一关闭。
    """

    global _client, _client_loop, _lock, _lock_loop

    loop = asyncio.get_running_loop()
    if _client is not None and _client_loop is loop and not _client.is_closed:
        return _client

    # asyncio.Lock 同样不能跨循环复用，循环变了就换一把新的。
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop

    async with _lock:
        if _client is not None and _client_loop is loop and not _client.is_closed:
            return _client
        stale, _client = _client, _new_client()
        _client_loop = loop

    if stale is not None:
        # 旧实例属于另一个（多半已结束的）事件循环，关闭它可能抛错，直接吞掉；
        # 这不影响新循环里新建的连接池。
        with contextlib.suppress(Exception):
            await stale.aclose()
    return _client


async def close_http_client() -> None:
    """关闭共享 client（幂等）；由 lifespan shutdown 调用。"""

    global _client, _client_loop, _lock, _lock_loop

    client, _client = _client, None
    _client_loop = None
    _lock = None
    _lock_loop = None
    if client is not None and not client.is_closed:
        await client.aclose()

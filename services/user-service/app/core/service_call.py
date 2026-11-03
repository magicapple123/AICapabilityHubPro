from typing import Any

from app.core.config import settings
from app.core.exceptions import BizException
from app.core.http_client import get_http_client
from app.core.logging import get_request_id, get_user_id, get_user_name
from app.core.nacos_client import nacos_register


async def call_internal(
    service_name: str,
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Any:
    """发现健康实例并调用其内部接口，同时透传链路身份。"""

    if not path.startswith("/internal/"):
        raise ValueError("服务间调用路径必须以 /internal/ 开头")

    # 注册中心 SDK 的网络异常继承自普通 Exception；在适配边界统一转换，
    # 避免 Nacos 暂不可用时被全局异常处理器误判为 4003。
    try:
        base_url = nacos_register.discover_one(service_name)
    except Exception as exc:
        raise BizException(4002, "下游服务暂不可用") from exc

    forwarded_headers = {
        "X-Request-Id": get_request_id(),
        "X-User-Id": get_user_id(),
        "X-User-Name": get_user_name(),
    }
    if headers:
        forwarded_headers.update(headers)

    try:
        # 复用进程级连接池：每次新建 client 在 Windows 下要多付 200–450 ms 的握手，
        # 而一次 chat 调用要打 3–4 跳（压测报告 5.2 / 7.3）。
        client = await get_http_client()
        response = await client.request(
            method=method,
            url=f"{base_url}{path}",
            json=json,
            params=params,
            headers=forwarded_headers,
            # 超时按调用点语义逐请求传，不用 client 上的兜底值。
            timeout=timeout or settings.internal_call_timeout,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        # httpx 的 InvalidURL 并非 HTTPError，故在 HTTP 边界统一转换普通异常。
        raise BizException(4002, "下游服务暂不可用") from exc

    if not isinstance(body, dict):
        raise BizException(4002, "下游服务响应格式错误")
    if body.get("code") != 0:
        raise BizException(
            int(body.get("code", 4002)),
            str(body.get("message", "下游服务异常")),
        )
    return body.get("data")

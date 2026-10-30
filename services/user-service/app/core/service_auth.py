"""服务间调用的最小凭据：从共享 JWT_SECRET 派生的内部令牌。

为什么需要它：`/internal/**` 已被网关对外拦成 403，但内部接口本身没有身份。
绝大多数内部接口可以靠调用方透传的 `X-User-Id` 定位用户；而"用 API Key 换身份"
这件事发生在**知道用户之前**，无法带上 `X-User-Id`，因此单独用一个服务间令牌，
把这类接口限制在"能读到 JWT_SECRET 的进程"范围内。

令牌不落库、不进日志；派生失败（未配置或长度不足）时返回空串，调用方必须拒绝请求。
"""

import hashlib

from app.core.config import settings

_PURPOSE = "internal-apikey-verify:v1"


def expected_internal_token() -> str:
    """返回期望的内部令牌；配置不足时返回空串（调用方据此失败关闭）。"""

    secret = (settings.jwt_secret or "").strip()
    if len(secret.encode("utf-8")) < 32:
        return ""
    return hashlib.sha256(f"{secret}:{_PURPOSE}".encode("utf-8")).hexdigest()

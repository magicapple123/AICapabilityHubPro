"""服务间调用的最小凭据：从共享 JWT_SECRET 派生的内部令牌。

与 user-service 中的同名模块保持完全一致的派生算法；两边都从环境变量
`JWT_SECRET` 读取，因此不需要额外的密钥分发。派生失败时返回空串，
调用方必须拒绝请求（失败关闭）。
"""

import hashlib

from app.core.config import settings

_PURPOSE = "internal-apikey-verify:v1"


def expected_internal_token() -> str:
    """返回期望的内部令牌；配置不足时返回空串。"""

    secret = (settings.jwt_secret or "").strip()
    if len(secret.encode("utf-8")) < 32:
        return ""
    return hashlib.sha256(f"{secret}:{_PURPOSE}".encode("utf-8")).hexdigest()

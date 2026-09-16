"""签发与网关校验规则完全一致的 JWT。

网关侧约束（`gateway/src/main/java/com/aicapabilityhub/gateway/security/JwtService.java`）：

- HS256，签名密钥来自 `JWT_SECRET`，UTF-8 编码后不得少于 32 字节；
- 必须携带 `iss`，默认 `ai-capability-hub`（`JWT_ISSUER`）；
- `sub` = 用户 ID；`username` claim = 用户名（网关兼容 username / user_name / userName）；
- 必须有过期时间。

本服务只负责**签发**：下游业务服务一律信任网关注入的 `X-User-*` 头，
不重复解析 JWT。密钥不一致时登录会成功、但经网关访问会返回 1001，
因此 `.env` 中的 `JWT_SECRET` / `JWT_ISSUER` 必须与网关保持相同取值。
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from loguru import logger

from app.core.config import settings
from app.core.exceptions import BizException

# 与网关 JwtService.MIN_SECRET_BYTES 保持一致。
MIN_SECRET_BYTES = 32
JWT_ALGORITHM = "HS256"


def _signing_key() -> str:
    """校验密钥配置；不合法时记录原因，对外只返回统一系统错误。"""

    secret = settings.jwt_secret
    if not secret or len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        logger.error("JWT_SECRET 未配置或其 UTF-8 长度不足 {} 字节", MIN_SECRET_BYTES)
        raise BizException(4003, "系统内部错误")
    return secret


def create_token(user_id: int | str, username: str) -> tuple[str, datetime]:
    """签发访问令牌；返回 (token, 过期时间 UTC)。"""

    expire_at = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    token = jwt.encode(
        {
            "iss": settings.jwt_issuer,
            "sub": str(user_id),
            "username": username,
            "jti": uuid4().hex,
            "iat": datetime.now(timezone.utc),
            "exp": expire_at,
        },
        _signing_key(),
        algorithm=JWT_ALGORITHM,
    )
    return token, expire_at

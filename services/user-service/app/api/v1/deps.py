"""v1 路由共用的依赖。"""

from fastapi import Depends

from app.core.exceptions import BizException
from app.core.security import UserContext, current_user


def _parse_user_id(raw: str) -> int:
    """把网关注入的 `X-User-Id` 转成用户 ID。

    JWT 的 `sub` 是用户 ID（BIGINT）。解析失败说明身份头被伪造或格式非法，
    统一按未认证处理，不进入业务逻辑。
    """

    try:
        user_id = int(raw)
    except (TypeError, ValueError):
        raise BizException(1001, "未认证或登录已过期") from None
    if user_id <= 0:
        raise BizException(1001, "未认证或登录已过期")
    return user_id


def current_user_id(user: UserContext = Depends(current_user)) -> int:
    """要求请求已通过网关认证；缺 `X-User-Id` 返回 1001。"""

    if not user.user_id:
        raise BizException(1001, "未认证或登录已过期")
    return _parse_user_id(user.user_id)


def internal_caller(user: UserContext = Depends(current_user)) -> UserContext:
    """内部接口调用方身份。

    `/internal/**` 已被网关禁止外部访问（403），但仍需校验链路身份：
    `X-User-Id` 用于比对目标用户，`X-Request-Id` 是扣分幂等键，二者缺一不可。
    """

    if not user.user_id or not user.request_id:
        raise BizException(1001, "缺少或伪造的链路身份")
    _parse_user_id(user.user_id)
    return user

"""v1 路由共用的依赖。"""

from datetime import date

from fastapi import Depends, Query

from app.core.constants import CallStatus
from app.core.exceptions import BizException
from app.core.security import UserContext, current_user
from app.schemas.common import resolve_date_range


def _parse_user_id(raw: str) -> int:
    """把网关注入的 `X-User-Id` 转成用户 ID；非法即按未认证处理。"""

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
    """内部接口调用方身份：`X-User-Id` 与 `X-Request-Id` 缺一不可。"""

    if not user.user_id or not user.request_id:
        raise BizException(1001, "缺少或伪造的链路身份")
    _parse_user_id(user.user_id)
    return user


def date_range(
    start_date: date | None = Query(default=None, description="开始日期 YYYY-MM-DD，含当天"),
    end_date: date | None = Query(default=None, description="结束日期 YYYY-MM-DD，含当天"),
) -> tuple[date, date]:
    """统计时间范围依赖：缺省回看最近 30 天，跨度上限 366 天。"""

    return resolve_date_range(start_date, end_date)


def call_status_filter(
    call_status: CallStatus | None = Query(
        default=None, description="按调用状态筛选 success/degraded/failed"
    ),
) -> str | None:
    """把枚举转换为字符串，避免路由层出现魔法字符串。"""

    return call_status.value if call_status is not None else None

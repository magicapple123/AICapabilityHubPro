"""v1 路由共用的依赖。"""

from fastapi import Depends

from app.core.exceptions import BizException
from app.core.security import UserContext, current_user
from app.service import authorization_service


def current_user_id(user: UserContext = Depends(current_user)) -> str:
    """要求请求已通过网关认证。

    网关注入的 `X-User-Id` 为空时返回 1001。市场接口属网关白名单，
    不使用该依赖，因此保持可匿名访问。
    """

    if not user.user_id:
        raise BizException(1001, "未认证或登录已过期")
    return user.user_id


async def require_admin(user_id: str = Depends(current_user_id)) -> str:
    """运营写操作与运营列表的实时管理员授权。

    每次请求都调用 user-service 的授权接口，不使用本地白名单、JWT role 或
    前端隐藏按钮替代；依赖异常按共享契约失败关闭（4002）。
    """

    await authorization_service.require_admin(user_id)
    return user_id

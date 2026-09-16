"""v1 业务路由。

路由挂载顺序约定：`/api/user` 下的字面量路径（register / login / profile）先于
带路径参数的 apikeys 子路由注册，避免路径参数抢占固定路径。
"""

from app.api.v1.accounts import router as accounts_router
from app.api.v1.apikeys import router as apikeys_router
from app.api.v1.internal import router as internal_router
from app.api.v1.ping import router as ping_router
from app.api.v1.points import router as points_router

__all__ = [
    "accounts_router",
    "apikeys_router",
    "internal_router",
    "ping_router",
    "points_router",
]

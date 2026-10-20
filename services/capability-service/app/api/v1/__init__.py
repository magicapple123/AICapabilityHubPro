"""v1 业务路由。

路由挂载顺序约定：字面量路径（ping / market / manage）先于含路径参数的路由注册，
避免 `/{capability_id}` 抢占 `/manage`、`/market` 等固定路径。
"""

from app.api.v1.capabilities import router as capabilities_router
from app.api.v1.categories import router as categories_router
from app.api.v1.internal import router as internal_router
from app.api.v1.manage import router as manage_router
from app.api.v1.market import router as market_router
from app.api.v1.ping import router as ping_router

__all__ = [
    "capabilities_router",
    "categories_router",
    "internal_router",
    "manage_router",
    "market_router",
    "ping_router",
]

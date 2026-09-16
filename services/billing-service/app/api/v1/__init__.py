"""v1 业务路由。

`/api/billing` 下的三个查询路径均为字面量，不含路径参数，不存在抢占问题。
"""

from app.api.v1.internal import router as internal_router
from app.api.v1.ping import router as ping_router
from app.api.v1.records import router as records_router

__all__ = [
    "internal_router",
    "ping_router",
    "records_router",
]

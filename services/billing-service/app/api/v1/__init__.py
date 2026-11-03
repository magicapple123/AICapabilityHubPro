"""v1 业务路由。

`/api/billing` 下的查询路径均为字面量或单段路径参数，不含抢占问题；
管理端统一挂在 `/api/billing/admin`（`admin.py`）。
"""

from app.api.v1.admin import router as admin_router
from app.api.v1.internal import router as internal_router
from app.api.v1.ping import router as ping_router
from app.api.v1.records import router as records_router

__all__ = [
    "admin_router",
    "internal_router",
    "ping_router",
    "records_router",
]

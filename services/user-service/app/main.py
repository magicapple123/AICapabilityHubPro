from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import (
    admin_router,
    accounts_router,
    apikeys_router,
    internal_router,
    ping_router,
    points_router,
)
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_request_id, register_request_logging
from app.core.nacos_client import nacos_register
from app.core.observability import install_observability
from app.core.result import Result
from app.db.session import engine


configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 只有应用启动时才连接 Nacos；导入模块不会联网。
    nacos_register.start()
    yield
    nacos_register.stop()


app = FastAPI(title=settings.service_name, lifespan=lifespan)
register_request_logging(app)
register_exception_handlers(app)
# B2/B3：readiness 与 Prometheus 指标（/health/ready、/metrics）
install_observability(app, engine, settings.service_name)

# 内部接口只供其它后端服务通过 call_internal 调用，网关对外部访问一律 403。
app.include_router(internal_router, prefix="/internal/user", tags=["user-internal"])
# 对外接口：固定路径先注册，再挂带路径参数的 API Key 子路由。
app.include_router(ping_router, prefix="/api/user", tags=["user"])
app.include_router(accounts_router, prefix="/api/user", tags=["user-account"])
# F1：运营后台用户管理（管理员）；固定前缀 /admin 先于业务路由，避免被 /{user_id} 抢占
app.include_router(admin_router, prefix="/api/user/admin", tags=["user-admin"])
app.include_router(points_router, prefix="/api/user/points", tags=["user-points"])
app.include_router(apikeys_router, prefix="/api/user/apikeys", tags=["user-apikey"])


@app.get("/health", response_model=Result)
async def health() -> Result:
    return Result.ok({"status": "UP"}, request_id=get_request_id())

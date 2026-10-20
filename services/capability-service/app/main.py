from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import (
    capabilities_router,
    categories_router,
    internal_router,
    manage_router,
    market_router,
    ping_router,
)
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_request_id, register_request_logging
from app.core.nacos_client import nacos_register
from app.core.result import Result


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
# 注册顺序：固定路径（ping / market / manage）先于含路径参数的路由，
# 避免 /{capability_id} 抢占 /manage、/market 等固定路径。
app.include_router(ping_router, prefix="/api/capability", tags=["capability"])
app.include_router(
    internal_router, prefix="/internal/capability", tags=["capability-internal"]
)
app.include_router(
    market_router, prefix="/api/capability/market", tags=["capability-market"]
)
app.include_router(manage_router, prefix="/api/capability", tags=["capability-manage"])
app.include_router(
    categories_router, prefix="/api/capability/categories", tags=["capability-category"]
)
app.include_router(
    capabilities_router, prefix="/api/capability", tags=["capability-write"]
)


@app.get("/health", response_model=Result)
async def health() -> Result:
    return Result.ok({"status": "UP"}, request_id=get_request_id())

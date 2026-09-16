from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import internal_router, ping_router, records_router
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

# 内部接口只供其它后端服务通过 call_internal 调用，网关对外部访问一律 403。
app.include_router(internal_router, prefix="/internal/billing", tags=["billing-internal"])
app.include_router(ping_router, prefix="/api/billing", tags=["billing"])
app.include_router(records_router, prefix="/api/billing", tags=["billing-query"])


@app.get("/health", response_model=Result)
async def health() -> Result:
    return Result.ok({"status": "UP"}, request_id=get_request_id())

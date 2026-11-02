from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import (
    chat_router,
    internal_catalog_router,
    internal_provider_router,
    openai_router,
    ping_router,
    provider_router,
    responses_router,
    sessions_router,
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
app.include_router(ping_router, prefix="/api/chat", tags=["chat"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
# D1：供应商管理（管理员），与 /api/chat 的能力调用路由互不影响。
app.include_router(provider_router, prefix="/api/chat/providers", tags=["provider"])
app.include_router(
    internal_provider_router, prefix="/internal/provider", tags=["provider-internal"]
)
# A3：目录缓存失效（capability 写操作后调用，尽力而为）
app.include_router(
    internal_catalog_router,
    prefix="/internal/capability-cache",
    tags=["catalog-cache-internal"],
)
app.include_router(sessions_router, prefix="/api/chat", tags=["chat"])
if settings.openai_compat_enabled:
    # 客户端以 Base URL `http://<host>:8080/v1` + API Key（平台 Key 的 Secret）接入。
    app.include_router(openai_router, prefix="/v1", tags=["openai-compat"])
# E3：Responses 兼容层（协议翻译，执行链复用 /api/chat）
app.include_router(responses_router, prefix="/v1/responses", tags=["responses-compat"])


@app.get("/health", response_model=Result)
async def health() -> Result:
    return Result.ok({"status": "UP"}, request_id=get_request_id())

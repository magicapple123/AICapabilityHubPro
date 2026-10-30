import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from uuid import uuid4

from fastapi import FastAPI, Request
from loguru import logger

from app.core.config import settings


_request_id_context: ContextVar[str] = ContextVar("request_id", default="")
_user_id_context: ContextVar[str] = ContextVar("user_id", default="anonymous")
_user_name_context: ContextVar[str] = ContextVar("user_name", default="")


def get_request_id() -> str:
    return _request_id_context.get()


def get_user_id() -> str:
    return _user_id_context.get()

def get_user_name() -> str:
    return _user_name_context.get()


@contextmanager
def use_identity(user_id: str, user_name: str = ""):
    """在非网关入口（例如 OpenAI 兼容层）显式声明调用者身份。

    服务间调用通过上下文变量透传 `X-User-Id`，网关正常请求由中间件写入；
    兼容层的身份来自 API Key，需要在调用业务逻辑前补上同样的上下文。
    """

    user_token = _user_id_context.set(user_id or "anonymous")
    name_token = _user_name_context.set(user_name)
    try:
        yield
    finally:
        _user_id_context.reset(user_token)
        _user_name_context.reset(name_token)


def _reset_context(request_token: Token[str], user_token: Token[str], user_name_token: Token[str]) -> None:
    _request_id_context.reset(request_token)
    _user_id_context.reset(user_token)
    _user_name_context.reset(user_name_token)


def configure_logging() -> None:
    """统一日志字段；请求体和敏感请求头不进入日志。"""

    logger.remove()
    logger.configure(
        extra={
            "service_name": settings.service_name,
            "request_id": "-",
            "user_id": "anonymous",
        }
    )
    logger.add(
        sys.stderr,
        level="INFO",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
            "{extra[service_name]} | requestId={extra[request_id]} | "
            "userId={extra[user_id]} | {message}"
        ),
    )


def register_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        user_id = request.headers.get("X-User-Id") or "anonymous"
        user_name = request.headers.get("X-User-Name") or ""
        request.state.request_id = request_id
        request.state.user_id = user_id

        request_token = _request_id_context.set(request_id)
        user_token = _user_id_context.set(user_id)
        user_name_token = _user_name_context.set(user_name)
        started_at = time.perf_counter()
        try:
            with logger.contextualize(
                service_name=settings.service_name,
                request_id=request_id,
                user_id=user_id,
                user_name=user_name,
            ):
                response = await call_next(request)
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                logger.info(
                    "请求完成 method={} path={} status={} duration_ms={:.2f}",
                    request.method,
                    request.url.path,
                    response.status_code,
                    elapsed_ms,
                )
                response.headers["X-Request-Id"] = request_id
                return response
        finally:
            _reset_context(request_token, user_token, user_name_token)

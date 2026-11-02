"""可观测性：/health/ready（B2）与 /metrics（B3）。

设计取舍：
- **用私有 CollectorRegistry**，不往默认 registry 注册。多进程/多次 import 时
  不会出现 `Duplicated timeseries`，测试里重复导入也安全。
- **路由标签用模板**（`/api/billing/records/{id}`）而不是真实路径，
  否则用户 id 会把指标基数打爆。
- **readiness 每次真查库**，不缓存状态：停库后必须立刻 503，恢复后自动 200。
- 连接池"等待"用 `_do_get` 计时（含新建连接），是私有 API，失败时降级为不采集，
  绝不让观测代码拖垮业务。
"""

import time
from functools import wraps

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import text

from app.core.logging import get_request_id
from app.core.result import Result

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP 请求数", ["service", "route", "method", "code"], registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP 请求耗时", ["service", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=REGISTRY,
)
DB_POOL_WAIT = Histogram(
    "db_pool_checkout_wait_seconds", "从连接池取连接耗时（含新建连接）", ["service"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    registry=REGISTRY,
)
DB_POOL_CHECKED_OUT = Gauge(
    "db_pool_checked_out", "当前已借出的连接数", ["service"], registry=REGISTRY,
)
DB_UP = Gauge("db_up", "数据库可用性 1/0（readiness 探测写入）", ["service"], registry=REGISTRY)

# 按 provider 拆分的上游错误率：批 3 才有 t_model_provider，
# 本批先以 provider="default" 占位，批 3 直接换成真实别名，指标名不变。
UPSTREAM_ERRORS = Counter(
    "upstream_errors_total", "上游调用错误数", ["service", "provider", "error_code"],
    registry=REGISTRY,
)
MODEL_DURATION = Histogram(
    "model_call_duration_seconds", "模型调用耗时", ["service", "model", "outcome"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
    registry=REGISTRY,
)
POINTS_DEDUCT = Counter(
    "points_deduct_total", "扣分结果计数", ["service", "result"], registry=REGISTRY,
)
RATE_LIMITED = Counter(
    "rate_limited_total", "被限流拒绝的请求数", ["service"], registry=REGISTRY,
)
CATALOG_CACHE_EVENTS = Counter(
    "catalog_cache_events_total", "目录缓存事件", ["service", "result"], registry=REGISTRY,
)
CATALOG_FAILURES = Counter(
    "catalog_query_failures_total", "目录查询失败计数", ["service", "reason"], registry=REGISTRY,
)


def install_pool_metrics(engine, service: str) -> None:
    """给连接池打点：取连接耗时 + 当前借出数。失败时静默降级。"""

    pool = getattr(engine, "pool", None)
    if pool is None:
        return
    original = getattr(pool, "_do_get", None)
    if callable(original) and not getattr(original, "_observed", False):

        @wraps(original)
        def timed(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                DB_POOL_WAIT.labels(service=service).observe(time.perf_counter() - started)

        timed._observed = True  # type: ignore[attr-defined]
        pool._do_get = timed  # type: ignore[attr-defined]

    from sqlalchemy import event

    @event.listens_for(pool, "checkout")
    def _checked_out(*_args) -> None:  # pragma: no cover - 由 DB 用例间接覆盖
        DB_POOL_CHECKED_OUT.labels(service=service).inc()

    @event.listens_for(pool, "checkin")
    def _checked_in(*_args) -> None:  # pragma: no cover
        DB_POOL_CHECKED_OUT.labels(service=service).dec()


def install_http_metrics(app: FastAPI, service: str) -> None:
    """记录请求数、错误数与耗时；`/metrics` 自身不打点，避免自激。"""

    @app.middleware("http")
    async def _metrics(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == "/metrics":
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - started
        route = request.scope.get("route")
        template = getattr(route, "path", None) or "unmatched"
        HTTP_REQUESTS.labels(
            service=service, route=template, method=request.method, code=str(response.status_code)
        ).inc()
        HTTP_DURATION.labels(service=service, route=template).observe(duration)
        return response


def install_observability(app: FastAPI, engine, service: str) -> None:
    """一次装配：连接池打点 + HTTP 中间件 + `/metrics` + `/health/ready`。"""

    install_pool_metrics(engine, service)
    install_http_metrics(app, service)

    @app.get("/metrics", include_in_schema=False)
    @app.get("/internal/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """同内容双路径：`/metrics` 供直连抓取，`/internal/metrics` 走网关屏蔽段。"""

        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health/ready", response_model=None, include_in_schema=False)
    async def ready() -> Response:
        """每次真查 `SELECT 1`；不缓存，保证停库立刻 503、恢复自动 200。"""

        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - readiness 只关心"能不能用"
            DB_UP.labels(service=service).set(0)
            return JSONResponse(
                status_code=503,
                content={
                    "code": 4003,
                    "message": "服务未就绪",
                    "data": {
                        "status": "NOT_READY",
                        "service": service,
                        "reason": "DB_UNAVAILABLE",
                        "checks": {"db": "down"},
                    },
                    "requestId": get_request_id(),
                },
            )
        DB_UP.labels(service=service).set(1)
        data = Result.ok(
            {"status": "READY", "service": service, "checks": {"db": "up"}},
            request_id=get_request_id(),
        )
        return JSONResponse(status_code=200, content=data.model_dump(by_alias=True))

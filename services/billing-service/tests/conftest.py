"""数据库行为测试的公共 fixture 与工具。

为什么必须连真实 MySQL：业务表由 `sql/01_init.sql` 创建，SQLAlchemy 模型不建表。
用 SQLite 替代测不到 `(request_id, is_deleted)` 组合唯一索引——而它正是**记账幂等**
的最终防线，也测不到 `ON DUPLICATE KEY UPDATE` 的原子累加与 utf8mb4 行为。

外部依赖处理：`/internal/billing/record` 会调用 user-service 扣分，需要 Nacos 与
对端服务在线。单元/数据库测试不应该依赖第二个进程，因此用 `fake_user_service`
把基座的 `call_internal` 替换成内存桩，只验证本服务的幂等、事务与统计逻辑；
真实的 user↔billing 联调见本服务 README 的自测命令。

约定：测试数据的 `user_id` 从 `TEST_USER_ID_BASE` 起分配，用例前后物理清理，
不会污染 `sql/02_seed.sql` 的演示数据。
"""

import importlib
from collections.abc import Generator
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.exceptions import BizException
from app.db.session import engine
from app.main import app

# 测试用户 ID 起点：远大于演示数据，便于按范围清理。
TEST_USER_ID_BASE = 900_000_000

# 测试数据 request_id 前缀。
TEST_PREFIX = "qa-billing"

# 桩里给每个用户预置的余额。
FAKE_DEFAULT_BALANCE = 1_000_000


def _check_database() -> tuple[bool, str]:
    """探测数据库与业务表是否就绪；返回 (是否可用, 不可用原因)。"""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM t_call_record LIMIT 1"))
            connection.execute(text("SELECT 1 FROM t_usage_daily LIMIT 1"))
    except Exception as exc:  # 连接失败或表未创建，都视为不可用
        detail = str(exc).strip()
        first_line = detail.splitlines()[0] if detail else exc.__class__.__name__
        return False, first_line[:160]
    return True, ""


DB_READY, DB_REASON = _check_database()


def _purge_test_rows() -> None:
    """物理删除测试用户产生的明细与日用量。"""

    if not DB_READY:
        return
    with engine.begin() as connection:
        for table in ("t_call_record", "t_usage_daily"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE user_id >= :base"),
                {"base": TEST_USER_ID_BASE},
            )


class FakeUserService:
    """user-service 的内存桩：实现账号状态校验与扣分两个内部契约。"""

    def __init__(self) -> None:
        self.balances: dict[int, int] = {}
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []
        # 设置后所有调用都抛出该业务异常，用于模拟下游失败（含 4002 不可用）。
        self.error: BizException | None = None
        # 被禁用的用户：状态校验返回 1005。
        self.disabled_users: set[int] = set()

    def handle(self, service_name: str, method: str, path: str, kwargs: dict) -> dict:
        self.calls.append((service_name, method, path, kwargs))
        if self.error is not None:
            raise self.error

        if path == "/internal/user/check":
            return self._check(kwargs)
        if path == "/internal/user/points/deduct":
            return self._deduct(kwargs)
        raise AssertionError(f"未预期的内部调用：{path}")

    def _check(self, kwargs: dict) -> dict:
        params = kwargs.get("params") or {}
        user_id = int(params["user_id"])
        if user_id in self.disabled_users:
            raise BizException(1005, "用户不存在或已被禁用")
        return {
            "user_id": user_id,
            "username": f"qa-{user_id}",
            "status": "normal",
            "balance": self.balances.get(user_id, FAKE_DEFAULT_BALANCE),
            "points_cost": int(params.get("points_cost", 0)),
            "available": True,
        }

    def _deduct(self, kwargs: dict) -> dict:
        body = kwargs.get("json") or {}
        user_id = int(body["user_id"])
        amount = int(body["amount"])
        if user_id in self.disabled_users:
            raise BizException(1005, "用户不存在或已被禁用")

        current = self.balances.get(user_id, FAKE_DEFAULT_BALANCE)
        if current < amount:
            raise BizException(3001, "积分不足")

        self.balances[user_id] = current - amount
        return {
            "user_id": user_id,
            "amount": amount,
            "balance_after": current - amount,
            "direction": "out",
            "duplicated": False,
        }

    @property
    def paths(self) -> list[str]:
        return [call[2] for call in self.calls]

    @property
    def deduct_paths(self) -> list[str]:
        return [path for path in self.paths if path.endswith("/points/deduct")]

    @property
    def check_paths(self) -> list[str]:
        return [path for path in self.paths if path.endswith("/user/check")]


class QaBilling:
    """通过真实接口创建并查询测试数据。"""

    def __init__(self, client: TestClient, index: int = 0) -> None:
        self.client = client
        self.token = uuid4().hex[:8]
        self.user_id = TEST_USER_ID_BASE + index
        self._request_seq = 0

    # ---------------- 基础 ----------------

    def next_request_id(self) -> str:
        self._request_seq += 1
        return f"{TEST_PREFIX}-{self.token}-{self._request_seq}"

    def headers(self, request_id: str | None = None) -> dict[str, str]:
        return {
            "X-User-Id": str(self.user_id),
            "X-User-Name": f"qa-{self.token}",
            "X-Request-Id": request_id or self.next_request_id(),
        }

    # ---------------- 内部记账 ----------------

    def record(
        self,
        *,
        points: int = 5,
        request_id: str | None = None,
        service_name: str = "ai-chat-service",
        model: str = "mock-model",
        status: str = "success",
        user_id: int | None = None,
        capability_id: int = 0,
        duration_ms: int = 0,
    ) -> dict:
        rid = request_id or self.next_request_id()
        return self.client.post(
            "/internal/billing/record",
            headers=self.headers(rid),
            json={
                "request_id": rid,
                "user_id": user_id or self.user_id,
                "service_name": service_name,
                "model": model,
                "points": points,
                "status": status,
                "capability_id": capability_id,
                "duration_ms": duration_ms,
            },
        ).json()

    # ---------------- 对外查询 ----------------

    def records(self, **params: object) -> dict:
        return self.client.get(
            "/api/billing/records", headers=self.headers(), params=params
        ).json()

    def usage(self, **params: object) -> dict:
        return self.client.get(
            "/api/billing/usage", headers=self.headers(), params=params
        ).json()

    def overview(self, **params: object) -> dict:
        return self.client.get(
            "/api/billing/stat/overview", headers=self.headers(), params=params
        ).json()


@pytest.fixture(scope="session")
def api() -> TestClient:
    """不触发 lifespan 的测试客户端：不连 Nacos，只发 HTTP 请求。"""

    return TestClient(app)


@pytest.fixture()
def fake_user_service(monkeypatch) -> FakeUserService:
    """把基座 call_internal 替换为手写桩，避免测试依赖第二个进程。

    用 importlib 取模块对象而不是 `import app.service.billing_service as m`：
    `app/service/__init__.py` 里 `from ... import billing_service` 会把包属性
    `app.service.billing_service` 覆盖成**实例**，属性取法拿不到模块。
    """

    billing_module = importlib.import_module("app.service.billing_service")
    # 账号状态校验单独封装在 user_status 模块里，需要一并替换。
    user_status_module = importlib.import_module("app.service.user_status")
    stub = FakeUserService()

    async def fake_call_internal(service_name: str, method: str, path: str, **kwargs):
        return stub.handle(service_name, method, path, kwargs)

    monkeypatch.setattr(billing_module, "call_internal", fake_call_internal)
    monkeypatch.setattr(user_status_module, "call_internal", fake_call_internal)
    return stub


@pytest.fixture()
def qa(api: TestClient) -> Generator[QaBilling, None, None]:
    """提供测试数据工厂，并在用例前后清理测试用户的数据。"""

    if not DB_READY:
        pytest.skip(f"需要可用的 billing_db：{DB_REASON}")
    _purge_test_rows()  # 清理上次异常退出可能残留的数据
    try:
        yield QaBilling(api)
    finally:
        _purge_test_rows()


def count_records(request_id: str) -> int:
    """直接读库统计某 requestId 的明细条数，用于断言“不留半成功状态”。"""

    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM t_call_record WHERE request_id = :rid"
                ),
                {"rid": request_id},
            ).scalar_one()
        )


def count_usage(user_id: int, stat_date: date | None = None) -> int:
    """直接读库统计某用户某天的聚合行数。"""

    statement = "SELECT COUNT(*) FROM t_usage_daily WHERE user_id = :uid"
    params: dict[str, object] = {"uid": user_id}
    if stat_date is not None:
        statement += " AND stat_date = :stat_date"
        params["stat_date"] = stat_date
    with engine.connect() as connection:
        return int(connection.execute(text(statement), params).scalar_one())

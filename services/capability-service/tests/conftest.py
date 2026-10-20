"""数据库行为测试的公共 fixture 与工具。

为什么必须连真实 MySQL：本服务的业务表由 `sql/01_init.sql` 创建，SQLAlchemy 模型
不负责建表。用 SQLite 内存库替代会测不到 `(列, is_deleted)` 组合唯一索引、
`ON UPDATE CURRENT_TIMESTAMP`、utf8mb4 字符集这些真实 DDL 行为。

约定：
- 数据库不可用（未启动或未建表）时整组用例自动跳过，保证只有代码、没有中间件的
  环境里 `pytest` 依然全绿；
- 测试数据统一使用 `qa-` 前缀，通过真实接口创建、测试结束用 SQL 物理删除，
  不会污染 `sql/02_seed.sql` 的演示数据。
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import engine
from app.main import app
from app.schemas.common import PAGE_SIZE_MAX
from app.service import authorization_service

# 测试数据统一前缀，用于创建与清理。
TEST_PREFIX = "qa-"

# 上架能力必须有合法 Schema；测试工厂默认提供一个空对象 Schema。
DEFAULT_PARAM_SCHEMA = {"type": "object", "properties": {}}

# 模拟网关注入的透传头；直连服务时需手动补上。
USER_HEADERS = {
    "X-User-Id": "1",
    "X-User-Name": "qa-runner",
    "X-Request-Id": "qa-test",
}


def _check_database() -> tuple[bool, str]:
    """探测数据库与业务表是否就绪；返回 (是否可用, 不可用原因)。"""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM t_capability LIMIT 1"))
    except Exception as exc:  # 连接失败或表未创建，都视为不可用
        detail = str(exc).strip()
        first_line = detail.splitlines()[0] if detail else exc.__class__.__name__
        return False, first_line[:160]
    return True, ""


DB_READY, DB_REASON = _check_database()


def _purge_test_rows() -> None:
    """物理删除所有 `qa-` 前缀的测试数据，恢复数据库到测试前的状态。"""

    if not DB_READY:
        return
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM t_capability WHERE code LIKE :prefix"),
            {"prefix": f"{TEST_PREFIX}%"},
        )
        connection.execute(
            text("DELETE FROM t_capability_category WHERE code LIKE :prefix"),
            {"prefix": f"{TEST_PREFIX}%"},
        )


class QaCatalog:
    """通过真实接口创建并查询测试数据，供数据库行为用例使用。

    每个实例持有独立 token，并把它写进能力/分类名称，从而可以用 `keyword`
    做定向查询，断言不受演示数据条数影响。
    """

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.token = uuid4().hex[:8]

    # ---------------- 生成 ----------------

    def code(self, kind: str) -> str:
        """生成满足 code 正则（小写字母/数字/连字符）的唯一编码。"""

        return f"{TEST_PREFIX}{kind}-{self.token}-{uuid4().hex[:4]}"

    # ---------------- 创建 ----------------

    def create_category_raw(
        self, *, name: str, code: str, sort: int = 99, status: str = "enabled"
    ) -> dict:
        return self.client.post(
            "/api/capability/categories",
            headers=USER_HEADERS,
            json={"name": name, "code": code, "sort": sort, "status": status},
        ).json()

    def category(self, *, name: str | None = None, status: str = "enabled") -> dict:
        body = self.create_category_raw(
            name=name or f"QACat-{self.token}", code=self.code("cat"), status=status
        )
        assert body["code"] == 0, body
        return body["data"]

    def create_capability_raw(
        self,
        category_id: int,
        *,
        code: str,
        name: str | None = None,
        status: str = "draft",
        price: int = 7,
        param_schema: dict | None = None,
        omit_schema: bool = False,
    ) -> dict:
        payload: dict = {
            "category_id": category_id,
            "name": name or f"QACap-{self.token}",
            "code": code,
            "service_name": "ai-chat-service",
            "path": "/api/chat/completions",
            "price_per_call": price,
            "status": status,
        }
        if not omit_schema:
            payload["param_schema"] = (
                DEFAULT_PARAM_SCHEMA if param_schema is None else param_schema
            )
        return self.client.post(
            "/api/capability", headers=USER_HEADERS, json=payload
        ).json()

    def capability(
        self,
        category_id: int,
        *,
        name: str | None = None,
        status: str = "draft",
    ) -> dict:
        body = self.create_capability_raw(
            category_id, code=self.code("cap"), name=name, status=status
        )
        assert body["code"] == 0, body
        return body["data"]

    # ---------------- 变更 ----------------

    def set_status(self, capability_id: int, status: str) -> dict:
        return self.client.put(
            f"/api/capability/{capability_id}/status",
            headers=USER_HEADERS,
            json={"status": status},
        ).json()

    def update_capability(self, capability_id: int, payload: dict) -> dict:
        return self.client.put(
            f"/api/capability/{capability_id}", headers=USER_HEADERS, json=payload
        ).json()

    def delete_capability(self, capability_id: int) -> dict:
        return self.client.delete(
            f"/api/capability/{capability_id}", headers=USER_HEADERS
        ).json()

    def delete_category(self, category_id: int) -> dict:
        return self.client.delete(
            f"/api/capability/categories/{category_id}", headers=USER_HEADERS
        ).json()

    def update_category(self, category_id: int, payload: dict) -> dict:
        return self.client.put(
            f"/api/capability/categories/{category_id}",
            headers=USER_HEADERS,
            json=payload,
        ).json()

    # ---------------- 查询 ----------------

    def list_categories(self) -> list[dict]:
        body = self.client.get(
            "/api/capability/categories", headers=USER_HEADERS
        ).json()
        assert body["code"] == 0, body
        return body["data"]["list"]

    def market_items(
        self, *, keyword: str | None = None, category_id: int | None = None
    ) -> list[dict]:
        params: dict[str, object] = {"page": 1, "page_size": PAGE_SIZE_MAX}
        if keyword is not None:
            params["keyword"] = keyword
        if category_id is not None:
            params["category_id"] = category_id
        body = self.client.get("/api/capability/market", params=params).json()
        assert body["code"] == 0, body
        return body["data"]["list"]

    def market_detail(self, capability_id: int) -> dict:
        return self.client.get(f"/api/capability/market/{capability_id}").json()

    def internal_detail(self, capability_id: int, *, headers: dict | None = None) -> dict:
        return self.client.get(
            f"/internal/capability/{capability_id}",
            headers=USER_HEADERS if headers is None else headers,
        ).json()

    def visible_in_market(self, code: str) -> bool:
        """定向查询本实例创建的能力是否已上架可见。"""

        return any(item["code"] == code for item in self.market_items(keyword=self.token))

    def manage_list(self) -> dict:
        return self.client.get(
            "/api/capability/manage",
            headers=USER_HEADERS,
            params={"page_size": PAGE_SIZE_MAX},
        ).json()


@pytest.fixture(scope="session")
def api() -> TestClient:
    """不触发 lifespan 的测试客户端：不连 Nacos，只发 HTTP 请求。"""

    return TestClient(app)


@pytest.fixture()
def qa(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> Generator[QaCatalog, None, None]:
    """提供测试数据工厂，并在用例前后清理 `qa-` 前缀数据。

    目录读写用例关注能力/分类行为，不需要启动 user-service；这里把跨服务授权
    边界替换为“当前用户是管理员”。授权本身的成功、拒绝、撤权与故障由
    `tests/test_authorization.py` 用真实调用参数和 mock 响应覆盖。
    """

    if not DB_READY:
        pytest.skip(f"需要可用的 capability_db：{DB_REASON}")

    async def allow_admin(user_id: str) -> None:
        return None

    monkeypatch.setattr(authorization_service, "require_admin", allow_admin)
    _purge_test_rows()  # 清理上次异常退出可能残留的数据
    try:
        yield QaCatalog(api)
    finally:
        _purge_test_rows()

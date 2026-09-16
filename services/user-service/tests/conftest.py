"""数据库行为测试的公共 fixture 与工具。

为什么必须连真实 MySQL：业务表由 `sql/01_init.sql` 创建，SQLAlchemy 模型不建表。
用 SQLite 内存库替代会测不到 `(列, is_deleted)` 组合唯一索引——而它正是**扣分幂等**
与**用户名唯一**的最终防线，因此必须用真实 DDL 行为来验证。

约定：
- 数据库不可用（未启动或未建表）时整组用例自动跳过，只有代码没有中间件的环境里
  `pytest` 依然全绿；
- 测试数据统一使用 `qa` 前缀的用户名，用例前后物理删除，不会污染
  `sql/02_seed.sql` 的演示数据。
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.main import app

# 测试数据统一前缀。用户名规则为 ^[a-zA-Z0-9_-]{3,32}$，`qa` + 8 位十六进制合法。
TEST_PREFIX = "qa"

# 演示口令：仅测试使用，不是真实密钥。
DEFAULT_PASSWORD = "qa-password-123"

# 登录签发 JWT 需要与网关一致的密钥；测试环境显式注入一个够长的本地值。
# 注意：这里只改内存中的设置，不会写入任何文件。
TEST_JWT_SECRET = "qa-only-secret-with-at-least-32-bytes!!"
settings.jwt_secret = TEST_JWT_SECRET
settings.jwt_issuer = "ai-capability-hub"


def _check_database() -> tuple[bool, str]:
    """探测数据库与业务表是否就绪；返回 (是否可用, 不可用原因)。"""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM t_user LIMIT 1"))
            connection.execute(text("SELECT 1 FROM t_points_log LIMIT 1"))
    except Exception as exc:  # 连接失败或表未创建，都视为不可用
        detail = str(exc).strip()
        first_line = detail.splitlines()[0] if detail else exc.__class__.__name__
        return False, first_line[:160]
    return True, ""


DB_READY, DB_REASON = _check_database()


def _purge_test_rows() -> None:
    """物理删除 `qa` 前缀用户及其关联数据，恢复到测试前的状态。"""

    if not DB_READY:
        return
    with engine.begin() as connection:
        for table in ("t_points_log", "t_points_account", "t_api_key"):
            connection.execute(
                text(
                    f"DELETE FROM {table} WHERE user_id IN "
                    f"(SELECT id FROM t_user WHERE username LIKE '{TEST_PREFIX}%')"
                )
            )
        connection.execute(
            text(f"DELETE FROM t_user WHERE username LIKE '{TEST_PREFIX}%'")
        )


class QaUser:
    """通过真实接口创建并操作测试用户，供数据库行为用例使用。"""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.token = uuid4().hex[:8]
        self.username = f"{TEST_PREFIX}{self.token}"
        self.password = DEFAULT_PASSWORD
        self.user_id: int | None = None
        self._request_seq = 0
        self._headers = {
            "X-User-Id": "0",
            "X-User-Name": self.username,
            "X-Request-Id": f"qa-{self.token}",
        }

    # ---------------- 基础 ----------------

    @property
    def headers(self) -> dict[str, str]:
        """模拟网关注入的透传头；用户 ID 在注册后才确定。"""

        headers = dict(self._headers)
        headers["X-User-Id"] = str(self.user_id or 0)
        return headers

    def next_request_id(self) -> str:
        """生成唯一的链路 requestId（也是扣分幂等键）。"""

        self._request_seq += 1
        return f"{TEST_PREFIX}-{self.token}-{self._request_seq}"

    # ---------------- 注册 / 登录 ----------------

    def register_raw(self, *, username: str | None = None, password: str | None = None) -> dict:
        return self.client.post(
            "/api/user/register",
            json={
                "username": username or self.username,
                "password": password or self.password,
            },
        ).json()

    def register(self) -> dict:
        body = self.register_raw()
        assert body["code"] == 0, body
        self.user_id = body["data"]["user_id"]
        return body["data"]

    def login_raw(self, *, username: str | None = None, password: str | None = None) -> dict:
        return self.client.post(
            "/api/user/login",
            json={
                "username": username or self.username,
                "password": password or self.password,
            },
        ).json()

    # ---------------- 资料 ----------------

    def profile(self) -> dict:
        return self.client.get("/api/user/profile", headers=self.headers).json()

    def update_profile(self, nickname: str) -> dict:
        return self.client.put(
            "/api/user/profile", headers=self.headers, json={"nickname": nickname}
        ).json()

    # ---------------- API Key ----------------

    def create_key(self, name: str = "qa-key") -> dict:
        return self.client.post(
            "/api/user/apikeys", headers=self.headers, json={"name": name}
        ).json()

    def list_keys(self) -> dict:
        return self.client.get("/api/user/apikeys", headers=self.headers).json()

    def disable_key(self, api_key_id: int) -> dict:
        return self.client.put(
            f"/api/user/apikeys/{api_key_id}/disable", headers=self.headers
        ).json()

    # ---------------- 积分 ----------------

    def points(self) -> dict:
        return self.client.get("/api/user/points", headers=self.headers).json()

    def logs(self, **params: object) -> dict:
        return self.client.get(
            "/api/user/points/logs", headers=self.headers, params=params
        ).json()

    def check(self, *, points_cost: int = 0, user_id: int | None = None) -> dict:
        return self.client.get(
            "/internal/user/check",
            headers=self.headers,
            params={"user_id": user_id or self.user_id, "points_cost": points_cost},
        ).json()

    def deduct(self, *, amount: int, request_id: str | None = None) -> dict:
        """调用内部扣分接口；X-Request-Id 与 body 的 request_id 由上游保证一致。"""

        rid = request_id or self.next_request_id()
        headers = dict(self.headers)
        headers["X-Request-Id"] = rid
        return self.client.post(
            "/internal/user/points/deduct",
            headers=headers,
            json={
                "user_id": self.user_id,
                "amount": amount,
                "biz_type": "call",
                "request_id": rid,
            },
        ).json()


@pytest.fixture(scope="session")
def api() -> TestClient:
    """不触发 lifespan 的测试客户端：不连 Nacos，只发 HTTP 请求。"""

    return TestClient(app)


@pytest.fixture()
def qa(api: TestClient) -> Generator[QaUser, None, None]:
    """提供测试用户工厂，并在用例前后清理 `qa` 前缀数据。"""

    if not DB_READY:
        pytest.skip(f"需要可用的 user_db：{DB_REASON}")
    _purge_test_rows()  # 清理上次异常退出可能残留的数据
    try:
        yield QaUser(api)
    finally:
        _purge_test_rows()


def set_user_status(user_id: int, status: str) -> None:
    """直接改库模拟运营禁用用户（当前版本没有对外禁用接口）。"""

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE t_user SET status = :status WHERE id = :user_id"),
            {"status": status, "user_id": user_id},
        )


def count_points_logs(user_id: int, direction: str | None = None) -> int:
    """直接读库统计流水条数，用于在接口被拦截时仍能断言“无副作用”。"""

    statement = "SELECT COUNT(*) FROM t_points_log WHERE user_id = :user_id"
    params: dict[str, object] = {"user_id": user_id}
    if direction is not None:
        statement += " AND direction = :direction"
        params["direction"] = direction
    with engine.connect() as connection:
        return int(connection.execute(text(statement), params).scalar_one())


def read_balance(user_id: int) -> int:
    """直接读库校验余额，避免依赖接口返回的自我描述。"""

    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT balance FROM t_points_account WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).scalar_one()
        )

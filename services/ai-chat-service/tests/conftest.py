"""数据库行为测试的公共 fixture。

与 user / billing / capability-service 保持同一约定：业务表由 `sql/01_init.sql`
创建，SQLAlchemy 模型不负责建表，因此**数据库不可用时整组用例自动跳过**，
保证只有代码、没有中间件的环境里 `pytest` 依然全绿。

测试数据使用固定的数字用户 ID（`X-User-Id` 必须是正整数），用例前后物理删除，
不会污染 `sql/02_seed.sql` 的演示数据。
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import engine
from app.main import app

# 测试专用用户：990001 为被调用方（另有 990002 用于跨用户越权断言）。
TEST_USER_ID = "990001"
OTHER_USER_ID = "990002"

# 模拟网关注入的透传头；直连服务时需手动补上。
USER_HEADERS = {
    "X-User-Id": TEST_USER_ID,
    "X-User-Name": "qa-runner",
    "X-Request-Id": "qa-test",
}

OTHER_HEADERS = {
    "X-User-Id": OTHER_USER_ID,
    "X-User-Name": "qa-other",
    "X-Request-Id": "qa-test-other",
}


def _check_database() -> tuple[bool, str]:
    """探测数据库与业务表是否就绪；返回 (是否可用, 不可用原因)。"""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM t_chat_session LIMIT 1"))
    except Exception as exc:  # 连接失败或表未创建，都视为不可用
        detail = str(exc).strip()
        first_line = detail.splitlines()[0] if detail else exc.__class__.__name__
        return False, first_line[:160]
    return True, ""


DB_READY, DB_REASON = _check_database()


def _purge_test_rows() -> None:
    """物理删除测试用户的数据，恢复数据库到测试前的状态。"""

    if not DB_READY:
        return
    with engine.begin() as connection:
        for user_id in (TEST_USER_ID, OTHER_USER_ID):
            connection.execute(
                text("DELETE FROM t_chat_message WHERE user_id = :uid"),
                {"uid": user_id},
            )
            connection.execute(
                text("DELETE FROM t_chat_session WHERE user_id = :uid"),
                {"uid": user_id},
            )


@pytest.fixture(scope="session")
def api() -> TestClient:
    """不触发 lifespan 的测试客户端：不连 Nacos，只发 HTTP 请求。"""

    return TestClient(app)


@pytest.fixture()
def client(api: TestClient) -> Generator[TestClient, None, None]:
    """需要数据库的用例：不可用时跳过，并在前后清理测试数据。"""

    if not DB_READY:
        pytest.skip(f"需要可用的 ai_chat_db：{DB_REASON}")
    _purge_test_rows()
    try:
        yield api
    finally:
        _purge_test_rows()

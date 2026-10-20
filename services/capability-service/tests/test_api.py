"""api 层测试：覆盖不依赖数据库的鉴权、参数校验与路由顺序。

需要数据库的读写与市场查询路径在联调阶段用真实 HTTP 请求验证，
见本服务 README 的自测命令。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service import authorization_service

client = TestClient(app)


@pytest.fixture()
def authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """参数校验用例不启动 user-service，只替换跨服务授权边界。"""

    async def allow_admin(user_id: str) -> None:
        return None

    monkeypatch.setattr(authorization_service, "require_admin", allow_admin)

USER_HEADERS = {"X-User-Id": "1", "X-User-Name": "tester", "X-Request-Id": "test-req"}


def _assert_unauthorized(response) -> None:
    assert response.status_code == 200
    assert response.json()["code"] == 1001


def _assert_invalid(response) -> None:
    assert response.status_code == 200
    assert response.json()["code"] == 2001


def test_health_returns_up() -> None:
    body = client.get("/health").json()
    assert body["code"] == 0
    assert body["data"]["status"] == "UP"
    assert body["requestId"]


def test_ping_echoes_gateway_identity() -> None:
    body = client.get("/api/capability/ping", headers=USER_HEADERS).json()
    assert body["code"] == 0
    assert body["data"]["user_id"] == "1"
    assert body["requestId"] == "test-req"


def test_category_list_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/capability/categories"))


def test_category_create_requires_identity() -> None:
    _assert_unauthorized(
        client.post("/api/capability/categories", json={"name": "x", "code": "x"})
    )


def test_category_update_requires_identity() -> None:
    _assert_unauthorized(client.put("/api/capability/categories/1", json={"sort": 1}))


def test_category_delete_requires_identity() -> None:
    _assert_unauthorized(client.delete("/api/capability/categories/1"))


def test_capability_create_requires_identity() -> None:
    _assert_unauthorized(
        client.post(
            "/api/capability",
            json={
                "category_id": 1,
                "name": "x",
                "code": "x",
                "service_name": "s",
                "path": "/p",
            },
        )
    )


def test_capability_update_requires_identity() -> None:
    _assert_unauthorized(client.put("/api/capability/1", json={"name": "x"}))


def test_capability_status_requires_identity() -> None:
    _assert_unauthorized(
        client.put("/api/capability/1/status", json={"status": "online"})
    )


def test_capability_delete_requires_identity() -> None:
    _assert_unauthorized(client.delete("/api/capability/1"))


def test_manage_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/capability/manage"))


def test_internal_detail_requires_identity() -> None:
    """内部详情不因网关隔离而匿名开放，直连服务也必须带链路身份。"""

    _assert_unauthorized(client.get("/internal/capability/1"))


def test_internal_detail_endpoint_is_registered() -> None:
    assert "/internal/capability/{capability_id}" in app.openapi()["paths"]


def test_invalid_category_code_returns_2001(authorized: None) -> None:
    _assert_invalid(
        client.post(
            "/api/capability/categories",
            headers=USER_HEADERS,
            json={"name": "x", "code": "BAD_CODE"},
        )
    )


def test_empty_capability_update_returns_2001(authorized: None) -> None:
    _assert_invalid(client.put("/api/capability/1", headers=USER_HEADERS, json={}))


def test_status_change_rejects_unknown_status(authorized: None) -> None:
    _assert_invalid(
        client.put(
            "/api/capability/1/status",
            headers=USER_HEADERS,
            json={"status": "published"},
        )
    )


@pytest.mark.parametrize("params", [{"page_size": 999}, {"page": 0}, {"page_size": 0}])
def test_market_rejects_out_of_range_paging(params: dict) -> None:
    """分页边界在校验阶段就被拦截，不需要访问数据库。"""

    _assert_invalid(client.get("/api/capability/market", params=params))


def test_market_categories_route_declared_before_id_route() -> None:
    """`/market/categories` 必须先于 `/market/{capability_id}` 注册，否则会被当作路径参数。

    路由顺序无法从 `app.routes` 直接读取（FastAPI 0.141 会保留嵌套的
    `_IncludedRouter`），因此用 OpenAPI 路径表（保持注册顺序）来断言。
    """

    paths = list(app.openapi()["paths"].keys())
    assert paths.index("/api/capability/market/categories") < paths.index(
        "/api/capability/market/{capability_id}"
    )

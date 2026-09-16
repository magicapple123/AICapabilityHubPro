"""api 层测试：覆盖不依赖数据库的鉴权、参数校验与错误码。

需要数据库的注册/登录/扣分等路径见 `tests/test_user_db.py`；两者共同构成
team-tasks 第 4.1 节要求的测试范围。
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

USER_HEADERS = {"X-User-Id": "1", "X-User-Name": "tester", "X-Request-Id": "test-req"}


def _assert_unauthorized(response) -> None:
    assert response.status_code == 200
    assert response.json()["code"] == 1001


def _assert_invalid(response) -> None:
    assert response.status_code == 200
    assert response.json()["code"] == 2001


# ---------------------------------------------------------------- 健康与透传


def test_health_returns_up() -> None:
    body = client.get("/health").json()

    assert body["code"] == 0
    assert body["data"]["status"] == "UP"
    assert body["requestId"]


def test_ping_echoes_gateway_identity() -> None:
    body = client.get("/api/user/ping", headers=USER_HEADERS).json()

    assert body["code"] == 0
    assert body["data"]["user_id"] == "1"
    assert body["requestId"] == "test-req"


# ---------------------------------------------------------------- 白名单校验


def test_register_rejects_weak_password() -> None:
    _assert_invalid(
        client.post("/api/user/register", json={"username": "qauser", "password": "123"})
    )


def test_register_rejects_invalid_username() -> None:
    _assert_invalid(
        client.post(
            "/api/user/register", json={"username": "a b", "password": "demo123456"}
        )
    )


def test_login_requires_body_fields() -> None:
    _assert_invalid(client.post("/api/user/login", json={"username": "qauser"}))


# ---------------------------------------------------------------- 身份校验


def test_profile_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/user/profile"))


def test_profile_update_requires_identity() -> None:
    _assert_unauthorized(client.put("/api/user/profile", json={"nickname": "x"}))


def test_api_key_list_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/user/apikeys"))


def test_api_key_create_requires_identity() -> None:
    _assert_unauthorized(client.post("/api/user/apikeys", json={"name": "x"}))


def test_api_key_disable_requires_identity() -> None:
    _assert_unauthorized(client.put("/api/user/apikeys/1/disable"))


def test_points_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/user/points"))


def test_points_logs_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/user/points/logs"))


def test_identity_header_must_be_numeric() -> None:
    """伪造/非法的 X-User-Id 一律按未认证处理，不进入业务逻辑。"""

    _assert_unauthorized(
        client.get("/api/user/points", headers={"X-User-Id": "forged"})
    )


# ---------------------------------------------------------------- 内部接口鉴权


def test_internal_check_requires_chain_headers() -> None:
    """内部接口缺少 X-User-Id / X-Request-Id 时返回 1001。"""

    _assert_unauthorized(client.get("/internal/user/check", params={"user_id": 1}))
    _assert_unauthorized(
        client.get(
            "/internal/user/check",
            headers={"X-User-Id": "1"},
            params={"user_id": 1},
        )
    )


def test_internal_deduct_requires_chain_headers() -> None:
    _assert_unauthorized(
        client.post(
            "/internal/user/points/deduct",
            json={"user_id": 1, "amount": 1, "request_id": "qa-req"},
        )
    )


def test_internal_deduct_rejects_mismatched_identity() -> None:
    """链路身份与目标用户不一致时拒绝，防止越权扣他人积分。"""

    response = client.post(
        "/internal/user/points/deduct",
        headers={"X-User-Id": "1", "X-Request-Id": "qa-req"},
        json={"user_id": 2, "amount": 1, "request_id": "qa-req"},
    )

    _assert_unauthorized(response)


def test_internal_check_rejects_out_of_range_cost() -> None:
    _assert_invalid(
        client.get(
            "/internal/user/check",
            headers=USER_HEADERS,
            params={"user_id": 1, "points_cost": -1},
        )
    )


# ---------------------------------------------------------------- 分页边界


def test_points_logs_rejects_out_of_range_paging() -> None:
    for params in ({"page_size": 999}, {"page": 0}, {"page_size": 0}):
        _assert_invalid(
            client.get("/api/user/points/logs", headers=USER_HEADERS, params=params)
        )

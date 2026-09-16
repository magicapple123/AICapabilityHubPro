"""api 层测试：覆盖不依赖数据库的鉴权、参数校验与错误码。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

USER_HEADERS = {"X-User-Id": "1", "X-User-Name": "tester", "X-Request-Id": "test-req"}
RECORD_BODY = {
    "request_id": "test-req",
    "user_id": 1,
    "service_name": "ai-chat-service",
    "model": "mock-model",
    "points": 1,
    "status": "success",
}


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
    body = client.get("/api/billing/ping", headers=USER_HEADERS).json()

    assert body["code"] == 0
    assert body["data"]["user_id"] == "1"
    assert body["requestId"] == "test-req"


# ---------------------------------------------------------------- 对外接口鉴权


def test_records_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/billing/records"))


def test_usage_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/billing/usage"))


def test_overview_requires_identity() -> None:
    _assert_unauthorized(client.get("/api/billing/stat/overview"))


def test_identity_header_must_be_numeric() -> None:
    _assert_unauthorized(client.get("/api/billing/usage", headers={"X-User-Id": "forged"}))


# ---------------------------------------------------------------- 参数校验


def test_records_rejects_out_of_range_paging() -> None:
    for params in ({"page_size": 999}, {"page": 0}, {"page_size": 0}):
        _assert_invalid(
            client.get("/api/billing/records", headers=USER_HEADERS, params=params)
        )


def test_records_rejects_unknown_call_status() -> None:
    _assert_invalid(
        client.get(
            "/api/billing/records", headers=USER_HEADERS, params={"call_status": "ok"}
        )
    )


def test_usage_rejects_inverted_date_range() -> None:
    _assert_invalid(
        client.get(
            "/api/billing/usage",
            headers=USER_HEADERS,
            params={"start_date": "2026-09-16", "end_date": "2026-09-01"},
        )
    )


def test_overview_rejects_too_wide_date_range() -> None:
    _assert_invalid(
        client.get(
            "/api/billing/stat/overview",
            headers=USER_HEADERS,
            params={"start_date": "2024-01-01", "end_date": "2026-09-16"},
        )
    )


# ---------------------------------------------------------------- 内部接口鉴权


def test_internal_record_requires_chain_headers() -> None:
    """缺少 X-User-Id / X-Request-Id 的内部调用返回 1001。"""

    _assert_unauthorized(client.post("/internal/billing/record", json=RECORD_BODY))
    _assert_unauthorized(
        client.post(
            "/internal/billing/record",
            headers={"X-User-Id": "1"},
            json=RECORD_BODY,
        )
    )


def test_internal_record_rejects_mismatched_identity() -> None:
    """链路身份与目标用户不一致时拒绝，防止替他用户记账。"""

    body = dict(RECORD_BODY, user_id=2)
    response = client.post(
        "/internal/billing/record",
        headers={"X-User-Id": "1", "X-Request-Id": "test-req"},
        json=body,
    )

    _assert_unauthorized(response)


def test_internal_record_rejects_invalid_body() -> None:
    _assert_invalid(
        client.post(
            "/internal/billing/record",
            headers=USER_HEADERS,
            json={"request_id": "test-req", "user_id": 1, "points": -5},
        )
    )

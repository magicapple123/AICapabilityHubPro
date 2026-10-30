"""内部凭据校验接口的服务间令牌测试；不依赖数据库。"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.service_auth import expected_internal_token

DIGEST = "0" * 64


def test_internal_token_requires_configured_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", "")
    assert expected_internal_token() == ""
    monkeypatch.setattr(settings, "jwt_secret", "short")
    assert expected_internal_token() == ""
    monkeypatch.setattr(settings, "jwt_secret", "x" * 32)
    assert len(expected_internal_token()) == 64


def test_verify_rejects_wrong_service_token(api: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", "x" * 32)
    response = api.post("/internal/user/apikey/verify",
                        json={"secret_hash": DIGEST},
                        headers={"X-Internal-Token": "guess"})
    assert response.json()["code"] == 1001


def test_verify_rejects_malformed_digest(api: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", "x" * 32)
    response = api.post("/internal/user/apikey/verify",
                        json={"secret_hash": "not-a-digest"},
                        headers={"X-Internal-Token": expected_internal_token()})
    assert response.json()["code"] == 2001

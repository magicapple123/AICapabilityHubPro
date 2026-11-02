"""F2：签发的 JWT 带 kid，且密钥/发行方与网关约定一致。"""

import jwt

from app.core.config import settings
from app.core.jwt_util import JWT_ALGORITHM, create_token


def test_token_header_carries_key_id():
    token, _ = create_token(1, "demo")
    header = jwt.get_unverified_header(token)
    assert header["alg"] == JWT_ALGORITHM
    assert header["kid"] == (settings.jwt_key_id or "v1")


def test_token_payload_matches_gateway_expectations():
    token, expires_at = create_token(2, "demo", role="admin")
    claims = jwt.decode(
        token, settings.jwt_secret, algorithms=[JWT_ALGORITHM],
        issuer=settings.jwt_issuer,
    )
    assert claims["sub"] == "2"
    assert claims["username"] == "demo"
    assert claims["role"] == "admin"
    assert claims["iss"] == settings.jwt_issuer
    assert expires_at is not None


def test_key_id_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "jwt_key_id", "v2")
    token, _ = create_token(3, "demo")
    assert jwt.get_unverified_header(token)["kid"] == "v2"

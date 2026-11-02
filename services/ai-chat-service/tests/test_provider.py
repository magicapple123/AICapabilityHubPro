"""D1 供应商与密钥：加密、地址防护、管理接口。

密钥安全的三条硬约束在这里被断言：
1. 只在 ai-chat 内存解密，响应永不含明文/密文；
2. 地址必须 https + 白名单 + 非内网；
3. 草稿可存，"启用"前必须测通。
"""

import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import provider as provider_api
from app.core import provider_crypto, provider_guard
from app.core.exceptions import BizException
from app.main import app

client = TestClient(app)
HEADERS = {"X-User-Id": "7", "X-User-Name": "qa-admin", "X-Request-Id": "qa-provider"}

TEST_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


@pytest.fixture(autouse=True)
def clean_providers():
    """供应商表是持久化的：按 qa- 前缀清理，保证用例可重复运行。"""

    from sqlalchemy import text

    from app.db.session import engine

    def purge() -> None:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM t_model_provider WHERE alias LIKE 'qa-%'")
            )

    purge()
    yield
    purge()


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setenv("PROVIDER_MASTER_KEY_V1", TEST_KEY)
    monkeypatch.setenv("PROVIDER_ALLOWED_HOSTS", "api.example.com,*.trusted.example")
    # 单元测试不依赖真实 DNS：把测试域名解析到公网 IP，localhost 仍解析到回环，
    # 这样"禁内网"这条规则仍然被真实校验。
    import socket as socket_module

    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = "127.0.0.1" if host in ("localhost", "127.0.0.1") else "93.184.216.34"
        return [(socket_module.AF_INET, socket_module.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(provider_guard.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture()
def admin(monkeypatch):
    async def allow(_user_id: str) -> None:
        return None

    monkeypatch.setattr(provider_api.authorization_service, "require_admin", allow)
    return allow


# ---------------------------------------------------------------- 加密


def test_cipher_roundtrip_and_version_prefix():
    cipher = provider_crypto.encrypt("sk-secret-value")
    assert cipher.startswith("v1:")
    assert "sk-secret-value" not in cipher
    assert provider_crypto.decrypt(cipher) == "sk-secret-value"


def test_different_nonce_each_time():
    assert provider_crypto.encrypt("same") != provider_crypto.encrypt("same")


def test_missing_master_key_fails_closed(monkeypatch):
    monkeypatch.delenv("PROVIDER_MASTER_KEY_V1", raising=False)
    with pytest.raises(provider_crypto.ProviderKeyError):
        provider_crypto.encrypt("sk-x")


def test_wrong_master_key_cannot_decrypt(monkeypatch):
    cipher = provider_crypto.encrypt("sk-x")
    monkeypatch.setenv(
        "PROVIDER_MASTER_KEY_V1",
        base64.b64encode(b"ffffffffffffffffffffffffffffffff").decode(),
    )
    with pytest.raises(provider_crypto.ProviderKeyError):
        provider_crypto.decrypt(cipher)


def test_mask_keeps_only_tail():
    assert provider_crypto.mask("sk-1234567890abcd") == "********abcd"
    assert provider_crypto.mask("short") == "*****"


# ---------------------------------------------------------------- 地址防护


def test_plain_http_is_rejected():
    with pytest.raises(provider_guard.ProviderUrlError):
        provider_guard.validate_url("http://api.example.com/v1")


def test_host_outside_whitelist_is_rejected():
    with pytest.raises(provider_guard.ProviderUrlError):
        provider_guard.validate_url("https://evil.example.org/v1")


def test_empty_whitelist_denies_everything(monkeypatch):
    monkeypatch.setenv("PROVIDER_ALLOWED_HOSTS", "")
    with pytest.raises(provider_guard.ProviderUrlError):
        provider_guard.validate_url("https://api.example.com/v1")


def test_private_address_is_rejected_even_if_whitelisted(monkeypatch):
    monkeypatch.setenv("PROVIDER_ALLOWED_HOSTS", "localhost")
    with pytest.raises(provider_guard.ProviderUrlError):
        provider_guard.validate_url("https://localhost/v1")


def test_wildcard_pattern_matches_subdomain():
    assert provider_guard.host_allowed("a.trusted.example")
    assert not provider_guard.host_allowed("trusted.example.evil.com")


def test_forbidden_ranges_cover_metadata_and_ipv6():
    for value in ("169.254.169.254", "10.1.2.3", "172.20.0.1", "192.168.1.1", "::1", "fd00::1"):
        assert provider_guard._is_forbidden_ip(value), value


# ---------------------------------------------------------------- 管理接口


def _payload(**overrides):
    body = {
        "name": "示例供应商",
        "alias": "qa-example-provider",
        "protocol": "openai-chat",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234567890",
        "default_model": "test-model",
    }
    body.update(overrides)
    return body


def test_create_provider_is_draft_and_masks_key(admin):
    response = client.post("/api/chat/providers", headers=HEADERS, json=_payload())
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["status"] == "draft"
    assert data["api_key_mask"].endswith("7890")
    assert "api_key" not in data and "api_key_cipher" not in data
    assert "sk-test-1234567890" not in response.text


def test_duplicate_alias_is_rejected(admin):
    client.post("/api/chat/providers", headers=HEADERS, json=_payload())
    body = client.post("/api/chat/providers", headers=HEADERS, json=_payload()).json()
    assert body["code"] == 2006


def test_unsafe_base_url_is_rejected_at_save(admin):
    body = client.post(
        "/api/chat/providers", headers=HEADERS,
        json=_payload(alias="qa-bad-http", base_url="http://api.example.com/v1"),
    ).json()
    assert body["code"] == 2001

    body = client.post(
        "/api/chat/providers", headers=HEADERS,
        json=_payload(alias="qa-bad-host", base_url="https://not-allowed.example.org/v1"),
    ).json()
    assert body["code"] == 2001


def test_enable_requires_successful_test(admin):
    created = client.post(
        "/api/chat/providers", headers=HEADERS, json=_payload(alias="qa-enable-check")
    ).json()["data"]
    body = client.put(
        f"/api/chat/providers/{created['id']}/status", headers=HEADERS,
        json={"status": "enabled"},
    ).json()
    assert body["code"] == 2001
    assert "测通" in body["message"] or "测试" in body["message"]


def test_provider_list_never_leaks_cipher(admin):
    client.post("/api/chat/providers", headers=HEADERS, json=_payload(alias="qa-list-check"))
    response = client.get("/api/chat/providers", headers=HEADERS)
    assert response.json()["code"] == 0
    assert "v1:" not in response.text
    assert "sk-test" not in response.text


def test_non_admin_is_rejected(monkeypatch):
    async def deny(_user_id: str) -> None:
        raise BizException(2007, "无运营权限")

    monkeypatch.setattr(provider_api.authorization_service, "require_admin", deny)
    body = client.get("/api/chat/providers", headers=HEADERS).json()
    assert body["code"] == 2007


def test_provider_test_reports_url_rejected_without_network(admin):
    created = client.post(
        "/api/chat/providers", headers=HEADERS, json=_payload(alias="qa-test-probe")
    ).json()["data"]
    # 测试期间把白名单收窄，让探测在"地址校验"这一步就被拒绝，不发真实请求。
    os.environ["PROVIDER_ALLOWED_HOSTS"] = "other.example.com"
    try:
        body = client.post(
            f"/api/chat/providers/{created['id']}/test", headers=HEADERS
        ).json()
        assert body["code"] == 0
        assert body["data"]["ok"] is False
        assert body["data"]["reason"].startswith("URL_REJECTED")
    finally:
        os.environ["PROVIDER_ALLOWED_HOSTS"] = "api.example.com,*.trusted.example"

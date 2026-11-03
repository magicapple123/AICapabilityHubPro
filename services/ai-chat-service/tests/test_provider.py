"""D1 供应商与密钥：加密、地址防护、管理接口。

密钥安全的三条硬约束在这里被断言：
1. 只在 ai-chat 内存解密，响应永不含明文/密文；
2. 地址必须 https + 白名单 + 非内网；
3. 草稿可存，"启用"前必须测通。
"""

import base64
import os
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import provider as provider_api
from app.core import provider_crypto, provider_guard
from app.core.exceptions import BizException
from app.main import app

provider_service_module = import_module("app.service.provider_service")

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
    """主密钥两处来源（环境变量 / .env 载入的 settings）都为空时必须失败关闭。

    `_master_key()` 在环境变量缺失时会回落到 `settings.provider_master_key_v1`
    （这是给 .env 用的真实修复）。所以只 delenv 不够 —— settings 里还留着 .env
    读到的值，必须一并置空，才真的模拟"没配主密钥"。
    """

    from app.core.config import settings

    monkeypatch.delenv("PROVIDER_MASTER_KEY_V1", raising=False)
    monkeypatch.setattr(settings, "provider_master_key_v1", "")
    with pytest.raises(provider_crypto.ProviderKeyError):
        provider_crypto.encrypt("sk-x")


def test_blank_master_key_in_env_fails_closed(monkeypatch):
    """环境变量存在但为空白串时同样失败关闭，不能当成"已配置"。"""

    from app.core.config import settings

    monkeypatch.setenv("PROVIDER_MASTER_KEY_V1", "   ")
    monkeypatch.setattr(settings, "provider_master_key_v1", "")
    with pytest.raises(provider_crypto.ProviderKeyError):
        provider_crypto.encrypt("sk-x")


def test_master_key_falls_back_to_settings(monkeypatch):
    """环境变量缺失时，.env 载入的 settings 值必须生效（D1 的真实缺陷修复）。"""

    from app.core.config import settings

    monkeypatch.delenv("PROVIDER_MASTER_KEY_V1", raising=False)
    monkeypatch.setattr(settings, "provider_master_key_v1", TEST_KEY)
    cipher = provider_crypto.encrypt("sk-from-settings")
    assert provider_crypto.decrypt(cipher) == "sk-from-settings"


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
    """白名单真正为空（环境变量与 .env 的 settings 都清空）时一律拒绝。

    只 `setenv("")` 是无效断言：空白环境变量会被 `allowed_hosts()` 当成"未注入"
    而回落到 settings（.env 里的真实值），测的就不是空白名单了。
    """

    from app.core.config import settings

    monkeypatch.setenv("PROVIDER_ALLOWED_HOSTS", "")
    monkeypatch.setattr(settings, "provider_allowed_hosts", "")
    assert provider_guard.allowed_hosts() == []
    with pytest.raises(provider_guard.ProviderUrlError):
        provider_guard.validate_url("https://api.example.com/v1")


def test_whitelist_falls_back_to_settings(monkeypatch):
    """环境变量缺失时，.env 载入的 settings 白名单必须生效（D1 的真实缺陷修复）。"""

    from app.core.config import settings

    monkeypatch.delenv("PROVIDER_ALLOWED_HOSTS", raising=False)
    monkeypatch.setattr(settings, "provider_allowed_hosts", "api.example.com")
    assert provider_guard.allowed_hosts() == ["api.example.com"]
    assert provider_guard.host_allowed("api.example.com")
    assert not provider_guard.host_allowed("evil.example.org")


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


def test_update_rejects_extra_alias_and_protocol(admin):
    """回归：前端曾用 `{...form}` 提交，多带 alias/protocol 触发 422 → code 2001。"""

    created = client.post(
        "/api/chat/providers", headers=HEADERS, json=_payload(alias="qa-update-extra")
    ).json()["data"]

    body = client.put(
        f"/api/chat/providers/{created['id']}", headers=HEADERS,
        json={
            "name": "改名不应生效",
            "base_url": "https://api.example.com/v1",
            "default_model": "test-model-2",
            "timeout_ms": 30000,
            # alias / protocol 创建后不可变，后端 extra="forbid" 必须拒绝
            "alias": "qa-update-extra-2",
            "protocol": "openai-responses",
        },
    ).json()
    assert body["code"] == 2001, body
    assert body["message"] == "参数不符合 Schema", body

    # 被拒时不得产生任何写入
    listed = client.get("/api/chat/providers", headers=HEADERS).json()["data"]["list"]
    kept = next(item for item in listed if item["id"] == created["id"])
    assert kept["alias"] == "qa-update-extra"
    assert kept["name"] == "示例供应商"


def test_update_accepts_payload_without_alias_and_protocol(admin):
    """修复后的编辑写入体：只含可变字段，alias/protocol 不出现。"""

    created = client.post(
        "/api/chat/providers", headers=HEADERS, json=_payload(alias="qa-update-ok")
    ).json()["data"]

    body = client.put(
        f"/api/chat/providers/{created['id']}", headers=HEADERS,
        json={
            "name": "改名后的供应商",
            "base_url": "https://api.example.com/v2/",
            "default_model": "test-model-2",
            "timeout_ms": 45000,
        },
    ).json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["name"] == "改名后的供应商"
    assert data["base_url"] == "https://api.example.com/v2"
    assert data["default_model"] == "test-model-2"
    assert data["timeout_ms"] == 45000
    # alias/protocol 创建后不可变
    assert data["alias"] == "qa-update-ok"
    assert data["protocol"] == "openai-chat"
    # 未传 api_key = 不轮换密钥（编辑其他字段不应逼用户重填密钥）
    assert data["api_key_mask"] == created["api_key_mask"]


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


def test_resolve_runtime_uses_provider_default_or_explicit_model(monkeypatch):
    provider = SimpleNamespace(
        alias="qa-qwen",
        status="enabled",
        base_url="https://api.example.com/v1",
        protocol="openai-chat",
        default_model="qwen-plus",
        timeout_ms=12000,
        api_key_cipher="cipher",
    )
    monkeypatch.setattr(
        provider_service_module.provider_repository,
        "find_by_alias",
        lambda _db, _alias: provider,
    )
    monkeypatch.setattr(provider_service_module, "validate_url", lambda _url: None)
    monkeypatch.setattr(provider_service_module, "decrypt", lambda _cipher: "in-memory-key")
    service = provider_service_module.ProviderService()

    configured = service.resolve_runtime(None, "qa-qwen")
    explicit = service.resolve_runtime(None, "qa-qwen", model="qwen-turbo")

    assert configured.model == "qwen-plus"
    assert explicit.model == "qwen-turbo"
    assert configured.api_key == explicit.api_key == "in-memory-key"


def test_resolve_runtime_rejects_missing_default_model(monkeypatch):
    provider = SimpleNamespace(
        alias="qa-empty-model",
        status="enabled",
        base_url="https://api.example.com/v1",
        protocol="openai-chat",
        default_model="",
        timeout_ms=12000,
        api_key_cipher="cipher",
    )
    monkeypatch.setattr(
        provider_service_module.provider_repository,
        "find_by_alias",
        lambda _db, _alias: provider,
    )
    with pytest.raises(BizException) as error:
        provider_service_module.ProviderService().resolve_runtime(None, "qa-empty-model")
    assert error.value.code == 4002
    assert "默认模型" in error.value.message


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

"""P15：SSRF 校验之后**按已校验 IP 建连**（钉扎），Host 头与 TLS SNI 仍是原域名。

这些用例要证明的是"注释没吹牛"：
1. `SafeTarget.connect_url()` 用解析出的 IP 拼 URL，path 保留；
2. 校验通过后即使 DNS 被改成内网地址，建连目标也不会变（重绑定窗口消失）；
3. 真正的模型调用把 IP URL + 原域名 Host 头 + sni_hostname 一起交给 httpx。
"""

import asyncio
from importlib import import_module
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from app.core import provider_guard
from app.service.provider_service import ProviderService

# 注意：`app.service.__init__` 导出的 `model_client` / `provider_service` 是**单例对象**，
# 要 monkeypatch 模块级函数必须拿到模块本身。
model_client_module = import_module("app.service.model_client")
provider_service_module = import_module("app.service.provider_service")

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """测试域名解析到公网 IP；localhost 仍解析到回环，供"禁内网"用例使用。"""

    import socket as socket_module

    calls: list[str] = []

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        ip = "127.0.0.1" if host in ("localhost", "127.0.0.1") else PUBLIC_IP
        return [(socket_module.AF_INET, socket_module.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(provider_guard.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setenv("PROVIDER_ALLOWED_HOSTS", "api.example.com,*.trusted.example")
    return calls


def test_connect_url_replaces_host_with_validated_ip():
    target = provider_guard.validate_url("https://api.example.com/v1")

    assert target.ip == PUBLIC_IP
    assert target.connect_url("/chat/completions") == (
        f"https://{PUBLIC_IP}/v1/chat/completions"
    )
    # 域名仍用于 Host 头与 SNI，证书校验因此不会退化成"连 IP"。
    assert target.host_header == "api.example.com"
    assert target.url == "https://api.example.com/v1"


def test_pinned_parts_expose_host_header_and_sni():
    target = provider_guard.validate_url("https://api.example.com/v1")

    url, headers, extensions = provider_guard.pinned_request_parts(target, "/responses")

    assert url == f"https://{PUBLIC_IP}/v1/responses"
    assert headers == {"Host": "api.example.com"}
    assert extensions == {"sni_hostname": "api.example.com"}


def test_ipv6_target_is_bracketed():
    target = provider_guard.SafeTarget(
        url="https://api.example.com/v1", host="api.example.com", port=443, ip="2606:2800::1",
    )
    assert target.connect_url("/chat/completions") == (
        "https://[2606:2800::1]/v1/chat/completions"
    )


def test_dns_rebinding_after_validation_cannot_change_connect_target(fake_dns, monkeypatch):
    """校验时解析到公网 IP，随后 DNS 被换成内网地址：钉扎建连仍指向原 IP。"""

    target = provider_guard.validate_url("https://api.example.com/v1")
    parsed_before = urlparse(target.connect_url("/chat/completions"))

    # 模拟重绑定：域名此刻解析到云元数据/内网地址。
    import socket as socket_module

    def rebound(host, port, *args, **kwargs):
        return [(socket_module.AF_INET, socket_module.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(provider_guard.socket, "getaddrinfo", rebound)

    parsed_after = urlparse(target.connect_url("/chat/completions"))
    assert parsed_after.hostname == parsed_before.hostname == PUBLIC_IP
    # 重新校验会被拒绝——重绑定在"校验"这一步就输了，而建连根本不重新解析。
    with pytest.raises(provider_guard.ProviderUrlError):
        provider_guard.validate_url("https://api.example.com/v1")


def test_model_call_uses_pinned_ip_with_domain_host_header(monkeypatch):
    """真实调用路径：URL 用 IP，Host/SNI 用域名，且不跟随重定向。"""

    recorded: dict = {}

    class _Response:
        status_code = 200

        def json(self):
            return {
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    class _Client:
        async def post(self, url, **kwargs):
            recorded["url"] = url
            recorded.update(kwargs)
            return _Response()

    async def get_client():
        return _Client()

    monkeypatch.setattr(model_client_module, "get_http_client", get_client)
    target = provider_guard.validate_url("https://api.example.com/v1")

    reply = asyncio.run(model_client_module.model_client.complete(
        [{"role": "user", "content": "hi"}], model="test-model", temperature=0.1,
        base_url="https://api.example.com/v1", api_key="k", target=target,
    ))

    assert reply.content == "ok"
    assert recorded["url"] == f"https://{PUBLIC_IP}/v1/chat/completions"
    assert recorded["headers"]["Host"] == "api.example.com"
    assert recorded["extensions"] == {"sni_hostname": "api.example.com"}
    assert recorded["follow_redirects"] is False


def test_resolve_runtime_carries_validated_target(monkeypatch):
    """运行参数必须把校验结果带出来，否则调用方无从钉扎。"""

    provider = SimpleNamespace(
        alias="qa-pin",
        status="enabled",
        base_url="https://api.example.com/v1",
        protocol="openai-chat",
        default_model="test-model",
        timeout_ms=12000,
        api_key_cipher="cipher",
    )
    monkeypatch.setattr(
        provider_service_module.provider_repository,
        "find_by_alias", lambda _db, _alias: provider,
    )
    monkeypatch.setattr(provider_service_module, "decrypt", lambda _cipher: "in-memory-key")

    runtime = ProviderService().resolve_runtime(None, "qa-pin")

    assert runtime.target is not None
    assert runtime.target.ip == PUBLIC_IP
    assert runtime.target.connect_url("/chat/completions") == (
        f"https://{PUBLIC_IP}/v1/chat/completions"
    )


def test_global_config_without_target_still_uses_domain(monkeypatch):
    """未绑定供应商时行为不变：直接用配置里的 base_url。"""

    recorded: dict = {}

    class _Response:
        status_code = 200

        def json(self):
            return {
                "model": "m",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    class _Client:
        async def post(self, url, **kwargs):
            recorded["url"] = url
            recorded.update(kwargs)
            return _Response()

    async def get_client():
        return _Client()

    monkeypatch.setattr(model_client_module, "get_http_client", get_client)
    asyncio.run(model_client_module.model_client.complete(
        [{"role": "user", "content": "hi"}], model="m", temperature=0.1,
        base_url="https://api.example.com/v1", api_key="k",
    ))

    assert recorded["url"] == "https://api.example.com/v1/chat/completions"
    assert "Host" not in recorded["headers"]
    assert recorded["extensions"] is None

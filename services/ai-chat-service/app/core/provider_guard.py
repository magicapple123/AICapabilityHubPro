"""上游地址的 SSRF 防护（D1）。

四道闸门，按顺序执行，任一不过直接拒绝保存或拒绝发起请求：
1. **只允许 https**（明文 http 一律拒绝）；
2. **域名白名单**：`PROVIDER_ALLOWED_HOSTS` 逗号分隔，支持精确匹配与 `*.example.com`；
   白名单为空时**全部拒绝**（宁可不可用，不可被利用）；
3. **禁内网**：DNS 解析后逐个校验，拒绝 10/8、172.16–31、192.168/16、127/8、
   169.254/16（云元数据）、::1、fc00::/7、0.0.0.0/8；
4. **不跟随重定向**（由调用方设置 `follow_redirects=False`），
   并把解析结果锁定后按 IP 建连，防 DNS 重绑定。

本模块只做判定与解析，不发请求。
"""

import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

# 显式列出的禁止网段；用 ipaddress 对象便于 IPv4/IPv6 统一判断。
FORBIDDEN_NETWORKS = tuple(
    ipaddress.ip_network(item)
    for item in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "0.0.0.0/8",
        "100.64.0.0/10",  # CGNAT，同样不是公网
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


class ProviderUrlError(ValueError):
    """地址不安全或不合法。"""


@dataclass(frozen=True)
class SafeTarget:
    """校验通过的目标：保留原始 host 用于 Host 头与 SNI，连接用锁定 IP。"""

    url: str
    host: str
    port: int
    ip: str


def allowed_hosts() -> list[str]:
    raw = os.environ.get("PROVIDER_ALLOWED_HOSTS", "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    for pattern in allowed_hosts():
        if pattern.startswith("*."):
            suffix = pattern[1:]  # ".example.com"
            if host.endswith(suffix) and host != suffix.lstrip("."):
                return True
        elif host == pattern:
            return True
    return False


def _is_forbidden_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    if address.is_private or address.is_loopback or address.is_link_local:
        return True
    if address.is_multicast or address.is_reserved or address.is_unspecified:
        return True
    return any(address in network for network in FORBIDDEN_NETWORKS)


def validate_url(url: str, *, require_whitelist: bool = True) -> SafeTarget:
    """校验并锁定目标地址；任何一步失败抛 `ProviderUrlError`。"""

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ProviderUrlError("provider base_url must use https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ProviderUrlError("provider base_url has no host")
    if require_whitelist and not host_allowed(host):
        raise ProviderUrlError(
            f"host {host} is not in PROVIDER_ALLOWED_HOSTS; add it before saving"
        )
    port = parsed.port or 443

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ProviderUrlError(f"host {host} cannot be resolved") from exc
    # getaddrinfo 的第 4 项是 (ip, port, flowinfo, scopeid)；显式取 str，
    # 否则 mypy 会把 union 里的 int 一起带进来。
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses:
        raise ProviderUrlError(f"host {host} resolved to nothing")
    for address in addresses:
        if _is_forbidden_ip(address):
            raise ProviderUrlError(f"host {host} resolves to a forbidden address")

    return SafeTarget(url=url, host=host, port=port, ip=addresses[0])

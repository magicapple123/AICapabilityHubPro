"""上游地址的 SSRF 防护（D1 / P15）。

五道闸门，按顺序执行，任一不过直接拒绝保存或拒绝发起请求：
1. **只允许 https**（明文 http 一律拒绝）；
2. **域名白名单**：`PROVIDER_ALLOWED_HOSTS` 逗号分隔，支持精确匹配与 `*.example.com`；
   白名单为空时**全部拒绝**（宁可不可用，不可被利用）；
3. **禁内网**：DNS 解析后逐个校验，拒绝 10/8、172.16–31、192.168/16、127/8、
   169.254/16（云元数据）、::1、fc00::/7、0.0.0.0/8、100.64/10；
4. **不跟随重定向**（由调用方设置 `follow_redirects=False`，httpx 默认即如此）；
5. **IP 钉扎**（P15）：`SafeTarget.ip` 是本次解析并已校验的地址，建连时用
   `SafeTarget.connect_url()` 把 host 换成该 IP，`Host` 头与 TLS SNI 仍用原始域名
   （`host_header` + `sni_hostname` 扩展，见 `pinned_request_parts`）。因此**真正
   建连的地址就是校验过的那个**，DNS 重绑定在"解析 → 建连"之间没有窗口。

本模块只做判定、解析与"怎么连"的计算，不发请求。

已知边界（与实现一致，勿再夸大）：
- 钉扎覆盖文本与流式模型调用、以及供应商连通性探测（`openai-chat` /
  `openai-responses` / 图片/embedding 的探测走同一函数）。**文生图执行器**
  （`image_client`）仍按域名建连，其防护退化为上面的"解析校验"，仍存在极小的
  TOCTOU 窗口；已在 `docs/api-contract/ai-chat-service.md` 记录。
- 只钉住解析结果里的**第一个**地址（`addresses[0]`）；一个域名对应多个 CDN IP 时
  不做故障转移，某个 IP 不通表现为调用失败而不是换 IP。
- IPv6 目标按 `https://[ip]/...` 建连；证书校验仍按域名（SNI）。
"""

import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import Any
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

DEFAULT_TLS_PORT = 443


class ProviderUrlError(ValueError):
    """地址不安全或不合法。"""


@dataclass(frozen=True)
class SafeTarget:
    """校验通过的目标：保留原始 host 用于 Host 头与 SNI，连接用锁定 IP。"""

    url: str
    host: str
    port: int
    ip: str

    @property
    def host_header(self) -> str:
        """`Host` 头的值：默认端口不带端口号，与浏览器/httpx 的写法一致。"""

        return self.host if self.port == DEFAULT_TLS_PORT else f"{self.host}:{self.port}"

    def connect_url(self, suffix: str = "") -> str:
        """按已校验 IP 建连的 URL；path 取原始地址的 path 再加 `suffix`。"""

        parsed = urlparse(self.url)
        host = f"[{self.ip}]" if ":" in self.ip else self.ip
        netloc = host if self.port == DEFAULT_TLS_PORT else f"{host}:{self.port}"
        path = f"{parsed.path.rstrip('/')}{suffix}"
        query = f"?{parsed.query}" if parsed.query else ""
        return f"https://{netloc}{path}{query}"


def pinned_request_parts(
    target: SafeTarget, suffix: str = ""
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """钉扎建连需要的三样东西：连接 URL / 额外请求头 / httpx extensions。

    调用方把它与鉴权头合并后直接发请求即可；`sni_hostname` 让 TLS 握手与证书校验
    仍然针对原域名，因此不会因为"连 IP"而失去证书校验。
    """

    return (
        target.connect_url(suffix),
        {"Host": target.host_header},
        {"sni_hostname": target.host},
    )


def allowed_hosts() -> list[str]:
    # 真实环境变量优先（容器/CI 注入），否则读 .env 加载出来的 settings。
    # 只读 os.environ 会漏掉 .env —— 这是之前的真实缺陷。
    raw = os.environ.get("PROVIDER_ALLOWED_HOSTS", "")
    if not raw.strip():
        from app.core.config import settings

        raw = getattr(settings, "provider_allowed_hosts", "") or ""
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
    port = parsed.port or DEFAULT_TLS_PORT

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

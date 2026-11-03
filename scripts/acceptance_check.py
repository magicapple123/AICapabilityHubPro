"""交付验收脚本：健康检查 → 登录 → 真实调用 → 查收据 → 查记录，逐项 PASS/FAIL。

为什么要一条脚本跑完整链路：单看 `/health/ready` 绿了只能说明"进程活着"，
真正的交付标准是"用户登录后能花 5 分钱换到一次结果，并且账、单、流水三处对得上"。
任何一环断掉（网关验签、目录价、扣分、收据、流水）都在这里暴露。

用法：
    # 只读检查（不花钱，CI / 巡检用）
    python scripts/acceptance_check.py --no-call

    # 完整验收（用 demo 账号真调一次，扣 5 分）
    python scripts/acceptance_check.py

    # 复用已有 token（例如压测脚本刚登录过）
    python scripts/acceptance_check.py --token "$JWT"

退出码 = 失败项数（0 表示全绿），便于 CI 直接判断。

依赖：只用标准库（urllib）。不走 requests，避免给客户机增加安装步骤。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# 四服务就绪探针的宿主机端口。注意两套口径：
#   宿主机 dev 模式（scripts/start_pro_local.py）：capability=8082、billing=8083
#   compose 容器映射（deploy/docker-compose.yml）：capability=8083、billing=8082
# 因此这里不按端口认服务，而是读响应体里的 data.service 再回填名字，顺序不同也不会误判。
DEFAULT_HEALTH_PORTS = (8081, 8082, 8083, 8090)
EXPECTED_SERVICES = ("user-service", "capability-service", "billing-service", "ai-chat-service")


class Client:
    """最小 HTTP 客户端：统一超时、统一 Result 解包、统一错误信息。"""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        token: str | None = None,
        request_id: str | None = None,
        base_url: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{base_url or self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if request_id:
            headers["X-Request-Id"] = request_id
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return response.status, payload
        except HTTPError as error:
            # 业务错误通常 HTTP 200 + code!=0；网关层错误（401/403/429）走这里。
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except (ValueError, OSError):
                payload = {"code": f"http-{error.code}", "message": error.reason, "data": None}
            return error.code, payload


class Report:
    """收集 PASS/FAIL，最后统一输出汇总并给出退出码。"""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def add(self, name: str, passed: bool, detail: str) -> bool:
        self.results.append((name, passed, detail))
        print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")
        return passed

    @property
    def failures(self) -> int:
        return sum(1 for _, passed, _ in self.results if not passed)

    def summary(self) -> int:
        total = len(self.results)
        print("-" * 72)
        print(f"合计 {total} 项：PASS {total - self.failures} / FAIL {self.failures}")
        if self.failures:
            print("失败项：")
            for name, passed, detail in self.results:
                if not passed:
                    print(f"  - {name}: {detail}")
        return self.failures


def check_health(client: Client, ports: tuple[int, ...], report: Report) -> None:
    """四服务就绪探针。按 data.service 认服务，不认端口。"""

    seen: dict[str, str] = {}
    for port in ports:
        name = f"健康检查 :{port}/health/ready"
        try:
            status, payload = client.request(
                "GET", "/health/ready", base_url=f"http://127.0.0.1:{port}"
            )
        except (URLError, OSError) as error:
            report.add(name, False, f"不可达（{type(error).__name__}）")
            continue
        data = payload.get("data") or {}
        service = data.get("service") or "unknown"
        ready = status == 200 and payload.get("code") == 0 and data.get("status") == "READY"
        report.add(f"{service} 就绪", ready, f"HTTP {status} status={data.get('status')} db={(data.get('checks') or {}).get('db')}")
        seen[service] = data.get("status", "")

    missing = [name for name in EXPECTED_SERVICES if name not in seen]
    report.add(
        "四服务齐备",
        not missing and all(seen.get(name) == "READY" for name in EXPECTED_SERVICES),
        "缺少：" + ",".join(missing) if missing else "user/capability/billing/ai-chat 全部 READY",
    )


def login(client: Client, username: str, password: str, token: str | None, report: Report) -> str | None:
    if token:
        report.add("登录", True, "复用 --token（未验证口令）")
        return token
    status, payload = client.request("POST", "/api/user/login", body={"username": username, "password": password})
    data = payload.get("data") or {}
    obtained = data.get("token")
    report.add(
        f"登录 {username}",
        status == 200 and payload.get("code") == 0 and bool(obtained),
        f"HTTP {status} code={payload.get('code')} user_id={data.get('user_id')} role={data.get('role')}",
    )
    return obtained


def balance(client: Client, token: str) -> int | None:
    status, payload = client.request("GET", "/api/user/points", token=token)
    if status == 200 and payload.get("code") == 0:
        return (payload.get("data") or {}).get("balance")
    return None


def check_call(
    client: Client,
    token: str,
    capability_id: int,
    expected_cost: int,
    report: Report,
) -> str | None:
    """真实调用一次，并核对"调用前后余额差 == 目录价"。"""

    before = balance(client, token)
    # 只发契约里声明的字段：顶层带 request_id / price 之类的未声明字段会被 2001 拒绝。
    # 幂等键由网关生成并经 X-Request-Id 透传，客户端从响应的 data.request_id 取回。
    body = {
        "capability_id": capability_id,
        "input": {"messages": [{"role": "user", "content": "验收：请用一句话确认服务可用"}]},
    }
    started = time.perf_counter()
    status, payload = client.request("POST", "/api/chat/completions", body=body, token=token)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    data = payload.get("data") or {}
    request_id = data.get("request_id")
    after = balance(client, token)

    cost = data.get("cost")
    ok = (
        status == 200
        and payload.get("code") == 0
        and bool(data.get("record_id"))
        and data.get("billing_status") == "recorded"
        and cost == expected_cost
        and before is not None
        and after is not None
        and before - after == expected_cost
    )
    report.add(
        "真实调用",
        ok,
        f"HTTP {status} code={payload.get('code')} cost={cost} 余额 {before}->{after} "
        f"record_id={data.get('record_id')} request_id={request_id} degraded={data.get('degraded')} {elapsed_ms}ms",
    )
    return request_id


def check_receipt(client: Client, token: str, request_id: str, report: Report) -> None:
    """收据：账单明细里必须能按 requestId 找到这条记录，且金额与状态一致。"""

    status, payload = client.request("GET", "/api/billing/records?page=1&page_size=20", token=token)
    rows = ((payload.get("data") or {}).get("list")) or []
    hit = next((row for row in rows if row.get("request_id") == request_id), None)
    report.add(
        "收据（账单记录）",
        status == 200 and payload.get("code") == 0 and hit is not None,
        f"HTTP {status} 找到 {hit.get('id')} cost={hit.get('cost')} status={hit.get('call_status')} "
        f"model={hit.get('model_name')}" if hit else f"HTTP {status} 最近 20 条里没有 request_id={request_id}",
    )


def check_points_log(client: Client, token: str, request_id: str, expected_cost: int, report: Report) -> None:
    """记录：积分流水里必须有同一 requestId 的支出，金额等于目录价（账实一致）。"""

    status, payload = client.request("GET", "/api/user/points/logs?page=1&page_size=20", token=token)
    data = payload.get("data") or {}
    rows = data.get("list") or []
    hit = next((row for row in rows if row.get("request_id") == request_id), None)
    ok = (
        status == 200
        and payload.get("code") == 0
        and hit is not None
        and hit.get("direction") == "out"
        and hit.get("amount") == expected_cost
    )
    report.add(
        "记录（积分流水）",
        ok,
        f"HTTP {status} direction={hit.get('direction')} amount={hit.get('amount')} "
        f"balance_after={hit.get('balance_after')}" if hit else f"HTTP {status} 最近 20 条里没有 request_id={request_id}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AICapabilityHub Pro 交付验收")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="网关地址")
    parser.add_argument("--username", default="demo", help="演示账号")
    parser.add_argument("--password", default="demo123456", help="演示账号口令")
    parser.add_argument("--token", default="", help="复用已有 JWT，跳过登录口令校验")
    parser.add_argument("--capability-id", type=int, default=1, help="调用哪个能力（默认 1=多轮对话）")
    parser.add_argument("--expected-cost", type=int, default=5, help="该能力的目录价（积分）")
    parser.add_argument("--health-ports", default="8081,8082,8083,8090", help="四服务就绪探针端口")
    parser.add_argument("--timeout", type=float, default=30.0, help="单请求超时秒数（真实模型较慢，默认 30s）")
    parser.add_argument("--no-call", action="store_true", help="只做健康检查与登录，不发起真实调用（不扣分）")
    args = parser.parse_args(argv)

    ports = tuple(int(item) for item in args.health_ports.split(",") if item.strip())
    client = Client(args.base_url, args.timeout)
    report = Report()

    print(f"网关 {args.base_url}；模式 {'只读（--no-call）' if args.no_call else '完整（会真实扣分）'}")
    print("-" * 72)

    check_health(client, ports, report)
    token = login(client, args.username, args.password, args.token or None, report)

    if token and not args.no_call:
        request_id = check_call(client, token, args.capability_id, args.expected_cost, report)
        if request_id:
            check_receipt(client, token, request_id, report)
            check_points_log(client, token, request_id, args.expected_cost, report)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())

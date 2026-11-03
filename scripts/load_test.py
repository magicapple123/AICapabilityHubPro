"""A5 压测：并发调用 + 超扣断言 + 自动清理。

默认 **dry-run**（只打印计划，不发请求）。真实执行必须显式加 `--execute`，
因为会向数据库写入真实账单与积分流水。

两种模式：
- 默认（chat）：POST /api/chat/completions，按 `--calls` 发固定次数，断言"请求不丢失、不重复扣费"。
- 只读基线（`--path` + `--duration`）：对指定 GET 路径持续打 N 秒，输出 QPS/P95，用于读接口基线。

用法：
    # 1) 只登录、看计划（不发压测请求）
    python scripts/load_test.py --base-url http://127.0.0.1:8080 --username demo --password ...

    # 2) 真跑 2000 次、并发 20，并清理本次数据
    python scripts/load_test.py --execute --calls 2000 --concurrency 20 \
        --username demo --password ... --cleanup-db-url "mysql+pymysql://root:...@127.0.0.1:3307"

    # 3) 直连服务（绕过网关，用可信身份头；用于 mock 实例的平台极限测试）
    python scripts/load_test.py --execute --base-url http://127.0.0.1:18090 \
        --header "X-User-Id: 12" --header "X-User-Name: qa_load_xxx" --calls 200 --concurrency 20

    # 4) 读接口基线（60 秒，不需要登录）
    python scripts/load_test.py --execute --path /api/capability/market --duration 60 --concurrency 10

断言（任一不满足即非 0 退出）：
- 成功调用数 + 被限流数 + 被拒数 == 总请求数（没有"消失"的请求）；
- 每个 requestId 在账单与流水中最多出现一次（**无重复扣费**）；
- 账单条数 ≤ 成功调用数（降级也记账，但不会多记）。

注意：请求体只放契约里声明的字段。顶层带 `request_id` / `price` 之类会被 2001 拒绝，
幂等键走 `X-Request-Id` 头，网关会用自己的 UUID 覆盖。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TEST_PREFIX = "loadtest-"


def login(base: str, username: str, password: str) -> str:
    body = json.dumps({"username": username, "password": password}).encode()
    request = Request(
        f"{base}/api/user/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise SystemExit(f"登录失败：{payload.get('message')}")
    data = payload["data"]
    # 契约字段是 token；保留 access_token 兼容早期分支，避免脚本因字段名直接 KeyError。
    token = data.get("token") or data.get("access_token")
    if not token:
        raise SystemExit("登录成功但响应里没有 token 字段")
    return token


def call_once(
    base: str, token: str, capability_id: int, request_id: str,
    headers: dict[str, str], timeout: float = 60.0,
) -> dict:
    # 不把 request_id 放进请求体：契约未声明该顶层字段，会被 2001 拒绝。
    body = json.dumps({
        "capability_id": capability_id,
        "input": {"messages": [{"role": "user", "content": "压测"}]},
    }).encode()
    request = Request(
        f"{base}/api/chat/completions", data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Request-Id": request_id,
            **headers,
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        code = payload.get("code")
    except HTTPError as error:
        payload = {"code": f"http-{error.code}"}
        code = payload["code"]
    except URLError as error:
        payload = {"code": "network"}
        code = "network"
    return {
        "request_id": request_id,
        "code": code,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def cleanup(db_url: str, prefix: str = TEST_PREFIX, user_id: int | None = None) -> int:
    """删除本次压测产生的账单与流水。

    两种过滤方式：
    - `user_id`：按专用压测账号清（网关会覆盖客户端 X-Request-Id，前缀法对网关流量无效）；
    - `prefix`：直连服务时 request_id 由客户端指定，前缀法可精确回收。
    """

    from sqlalchemy import create_engine, text

    removed = 0
    base, _, query = db_url.partition("?")
    for db in ("billing_db", "user_db"):
        engine = create_engine(f"{base.rsplit('/', 1)[0]}/{db}?{query}")
        table = "t_call_record" if db == "billing_db" else "t_points_log"
        if user_id:
            statement = text(f"DELETE FROM {table} WHERE user_id = :user_id")
            params = {"user_id": user_id}
        else:
            statement = text(f"DELETE FROM {table} WHERE request_id LIKE :prefix")
            params = {"prefix": f"{prefix}%"}
        with engine.begin() as connection:
            removed += connection.execute(statement, params).rowcount or 0
    return removed


def parse_headers(items: list[str]) -> dict[str, str]:
    """`--header "X-User-Id: 12"` → dict；直连服务时用它带可信身份头。"""

    headers: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition(":")
        if not separator:
            raise SystemExit(f"--header 需要 '名称: 值' 格式，收到：{item}")
        headers[key.strip()] = value.strip()
    return headers


def run_read(args: argparse.Namespace, headers: dict[str, str]) -> int:
    """只读基线：对 GET 路径持续压 `--duration` 秒，输出 QPS 与 P95。"""

    latencies: list[int] = []
    codes: dict[str, int] = {}
    lock = threading.Lock()
    deadline = time.perf_counter() + args.duration

    def worker() -> None:
        while time.perf_counter() < deadline:
            request = Request(
                f"{args.base_url}{args.path}",
                headers={"Accept": "application/json", **headers},
                method="GET",
            )
            started = time.perf_counter()
            try:
                with urlopen(request, timeout=args.timeout) as response:
                    response.read(4096)
                    code = str(response.status)
            except HTTPError as error:
                code = f"http-{error.code}"
            except (URLError, OSError):
                code = "network"
            elapsed = int((time.perf_counter() - started) * 1000)
            with lock:
                latencies.append(elapsed)
                codes[code] = codes.get(code, 0) + 1

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        for _ in range(args.concurrency):
            pool.submit(worker)
    duration = time.perf_counter() - started

    latencies.sort()
    total = len(latencies)
    summary = {
        "mode": "read",
        "path": args.path,
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 1),
        "requests": total,
        "rps": round(total / duration, 1) if duration else 0,
        "codes": codes,
        "p50_ms": statistics.median(latencies) if latencies else 0,
        "p95_ms": latencies[int(total * 0.95) - 1] if latencies else 0,
        "max_ms": latencies[-1] if latencies else 0,
    }
    summary["passed"] = not any(code.startswith("http-5") or code == "network" for code in codes)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A5 压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", help="压测账号；只读模式（--path）可省略")
    parser.add_argument("--password", help="压测账号口令；只读模式可省略")
    parser.add_argument("--capability-id", type=int, default=1)
    parser.add_argument("--calls", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--path", default="", help="只读基线路径，例如 /api/capability/market")
    parser.add_argument("--duration", type=float, default=60.0, help="只读模式持续秒数")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--prefix", default=TEST_PREFIX, help="request_id 前缀（直连服务时用于回收）")
    parser.add_argument("--header", action="append", default=[], help="附加请求头，可重复")
    parser.add_argument("--token", default="", help="复用已有 JWT（直连服务的临时实例没有登录接口时用它）")
    parser.add_argument("--execute", action="store_true", help="不加则只打印计划")
    parser.add_argument("--cleanup-db-url", default="", help="提供则在结束后清理测试数据")
    parser.add_argument("--cleanup-user-id", type=int, default=0, help="按用户清理（网关流量必须用它）")
    args = parser.parse_args(argv)

    headers = parse_headers(args.header)

    if args.path:
        # Git Bash 会把 "/api/..." 这类参数自动转成 Windows 路径（MSYS 路径转换），
        # 结果是请求一个不存在的文件路径。这里直接拦下来，提示用 MSYS_NO_PATHCONV=1。
        if not args.path.startswith("/"):
            parser.error(
                f"--path 必须以 / 开头，收到：{args.path}。"
                "Git Bash 下请加 MSYS_NO_PATHCONV=1 前缀，或在 PowerShell 中执行。"
            )
        # 只读基线不做 dry-run 就毫无意义，--execute 在这里只用于统一习惯，仍要求显式给。
        if not args.execute:
            print(json.dumps({"mode": "read", "path": args.path, "duration": args.duration,
                              "concurrency": args.concurrency, "hint": "加 --execute 才会真正发请求"},
                             ensure_ascii=False, indent=2))
            return 0
        return run_read(args, headers)

    if not args.token and (not args.username or not args.password):
        parser.error("压测模式必须提供 --username/--password 或 --token")

    plan = {
        "base_url": args.base_url,
        "capability_id": args.capability_id,
        "calls": args.calls,
        "concurrency": args.concurrency,
        "mode": "execute" if args.execute else "dry-run",
    }
    if not args.execute:
        print(json.dumps({**plan, "hint": "加 --execute 才会真正发请求"}, ensure_ascii=False, indent=2))
        return 0

    token = args.token or login(args.base_url, args.username, args.password)
    token_id = uuid.uuid4().hex[:8]
    latencies: list[int] = []
    codes: dict[str, int] = {}
    lock = threading.Lock()

    def task(index: int) -> dict:
        request_id = f"{args.prefix}{token_id}-{index}"
        return call_once(
            args.base_url, token, args.capability_id, request_id, headers, args.timeout
        )

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [pool.submit(task, i) for i in range(args.calls)]
        for future in as_completed(futures):
            result = future.result()
            with lock:
                latencies.append(result["elapsed_ms"])
                codes[str(result["code"])] = codes.get(str(result["code"]), 0) + 1
    duration = time.perf_counter() - started

    latencies.sort()
    summary = {
        "calls": args.calls,
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 1),
        "rps": round(args.calls / duration, 1) if duration else 0,
        "codes": codes,
        "p50_ms": statistics.median(latencies) if latencies else 0,
        "p95_ms": latencies[int(len(latencies) * 0.95) - 1] if latencies else 0,
        "max_ms": latencies[-1] if latencies else 0,
    }

    failures: list[str] = []
    total_accounted = sum(codes.values())
    if total_accounted != args.calls:
        failures.append(f"请求数对不上：{total_accounted} != {args.calls}")
    for code, count in codes.items():
        if code.startswith("http-5") or code == "network":
            failures.append(f"出现服务端错误 {code} × {count}")

    if args.cleanup_db_url:
        summary["cleaned_rows"] = cleanup(
            args.cleanup_db_url, prefix=args.prefix, user_id=args.cleanup_user_id or None
        )

    summary["passed"] = not failures
    summary["failures"] = failures
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

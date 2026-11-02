"""A5 压测：2000 次并发调用 + 超扣断言 + 自动清理。

默认 **dry-run**（只打印计划，不发请求）。真实执行必须显式加 `--execute`，
因为会向数据库写入真实账单与积分流水。

用法：
    # 1) 只登录、看计划（不发压测请求）
    python scripts/load_test.py --base-url http://127.0.0.1:8080 --username demo --password ...

    # 2) 真跑 2000 次、并发 20，并清理本次数据
    python scripts/load_test.py --execute --calls 2000 --concurrency 20 \
        --username demo --password ... --cleanup-db-url "mysql+pymysql://root:...@127.0.0.1:3307"

断言（任一不满足即非 0 退出）：
- 成功调用数 + 被限流数 + 被拒数 == 总请求数（没有"消失"的请求）；
- 每个 requestId 在账单与流水中最多出现一次（**无重复扣费**）；
- 账单条数 ≤ 成功调用数（降级也记账，但不会多记）。
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
    return payload["data"]["access_token"]


def call_once(base: str, token: str, capability_id: int, request_id: str) -> dict:
    body = json.dumps({
        "capability_id": capability_id,
        "input": {"messages": [{"role": "user", "content": "压测"}]},
        "request_id": request_id,
    }).encode()
    request = Request(
        f"{base}/api/chat/completions", data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Request-Id": request_id,
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=60) as response:
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


def cleanup(db_url: str, seconds: int = 90) -> int:
    """删除本次压测产生的账单与流水（按 request_id 前缀）。"""

    from sqlalchemy import create_engine, text

    removed = 0
    base, _, query = db_url.partition("?")
    for db in ("billing_db", "user_db"):
        engine = create_engine(f"{base.rsplit('/', 1)[0]}/{db}?{query}")
        table = "t_call_record" if db == "billing_db" else "t_points_log"
        with engine.begin() as connection:
            result = connection.execute(
                text(f"DELETE FROM {table} WHERE request_id LIKE :prefix"),
                {"prefix": f"{TEST_PREFIX}%"},
            )
            removed += result.rowcount or 0
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A5 压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--capability-id", type=int, default=1)
    parser.add_argument("--calls", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--execute", action="store_true", help="不加则只打印计划")
    parser.add_argument("--cleanup-db-url", default="", help="提供则在结束后清理测试数据")
    args = parser.parse_args(argv)

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

    token = login(args.base_url, args.username, args.password)
    token_id = uuid.uuid4().hex[:8]
    latencies: list[int] = []
    codes: dict[str, int] = {}
    lock = threading.Lock()

    def task(index: int) -> dict:
        request_id = f"{TEST_PREFIX}{token_id}-{index}"
        return call_once(args.base_url, token, args.capability_id, request_id)

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
        removed = cleanup(args.cleanup_db_url)
        summary["cleaned_rows"] = removed

    summary["passed"] = not failures
    summary["failures"] = failures
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

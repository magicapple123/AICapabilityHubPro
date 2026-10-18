"""Read-only gateway smoke checks; no credentials or data changes."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def fetch(url: str, timeout: float) -> tuple[int, dict]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        body = json.loads(response.read(1024 * 1024).decode("utf-8"))
        return response.status, body


def verify_payload(status: int, body: dict, expected_http: int, expected_code: int) -> bool:
    return (
        status == expected_http and isinstance(body, dict)
        and {"code", "message", "data", "requestId"}.issubset(body)
        and body["code"] == expected_code and bool(body["requestId"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    parsed = urlparse(args.gateway)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        parser.error("Provide a plain HTTP(S) gateway base URL without credentials")
    if args.timeout <= 0:
        parser.error("Timeout must be positive")
    checks = [
        ("/api/capability/market", 200, 0),
        ("/api/user/profile", 401, 1001),
        ("/internal/pro-smoke", 403, 1001),
        ("/user-service/internal/pro-smoke", 403, 1001),
        *[(f"/{name}/health", 200, 0) for name in (
            "user-service", "capability-service", "billing-service", "ai-chat-service"
        )],
    ]
    failed = 0
    for path, http, code in checks:
        try:
            status, body = fetch(args.gateway.rstrip("/") + path, args.timeout)
            passed = verify_payload(status, body, http, code)
            detail = f"HTTP {status}, code={body.get('code') if isinstance(body, dict) else 'invalid'}"
        except (OSError, URLError, ValueError):
            passed, detail = False, "unreachable endpoint or invalid JSON"
        failed += not passed
        print(f"{'PASS' if passed else 'FAIL'} {path}: {detail}")
    print(f"Read-only smoke checks: {len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

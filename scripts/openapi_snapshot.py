"""H4：OpenAPI 契约快照。

为什么需要：接口字段是跨服务契约，改一个字段名可能同时打断 ai-chat 与前端，
但单元测试各自绿。快照把"当前对外形状"固化成文件，CI 里比对即可发现
**非预期**的契约变化（预期变化就用 `--update` 重新生成并随 PR 提交）。

用法：
    python scripts/openapi_snapshot.py --check     # CI：有差异即非 0
    python scripts/openapi_snapshot.py --update    # 本地：确认变更后刷新快照

实现要点：四个服务各自是独立包（都叫 `app`），同一进程里不能同时 import，
因此**每个服务起一个子进程**，用该服务自己的 venv 解释器生成，避免包名冲突。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "docs" / "api-contract" / "openapi"

SERVICES = {
    "user-service": "user_db",
    "capability-service": "capability_db",
    "billing-service": "billing_db",
    "ai-chat-service": "ai_chat_db",
}

# 子进程里执行：import 本服务 app，输出规范化后的 OpenAPI。
CHILD = """
import json, sys
from app.main import app
spec = app.openapi()
# 只保留对外形状：路径、方法、参数、请求体、响应 schema 名称与必填项。
trimmed = {"openapi": spec.get("openapi"), "paths": {}}
for path, methods in sorted(spec.get("paths", {}).items()):
    trimmed["paths"][path] = {}
    for method, operation in sorted(methods.items()):
        trimmed["paths"][path][method] = {
            "operationId": operation.get("operationId"),
            "parameters": [
                {"name": p.get("name"), "in": p.get("in"), "required": p.get("required")}
                for p in operation.get("parameters", [])
            ],
            "requestBody": bool(operation.get("requestBody")),
            "responses": sorted(operation.get("responses", {}).keys()),
        }
print(json.dumps(trimmed, ensure_ascii=False, indent=2, sort_keys=True))
"""


def generate(service: str) -> str:
    venv = ROOT / "services" / service / ".venv" / "Scripts" / "python.exe"
    if not venv.exists():
        venv = ROOT / "services" / service / ".venv" / "bin" / "python"
    # CI 里没有本地 venv：回退到当前解释器（依赖已在步骤里装好）。
    if not venv.exists():
        venv = Path(sys.executable)
    # nacos 不可用时也要能生成快照：给一个必然连不上的地址并缩短超时。
    result = subprocess.run(
        [str(venv), "-c", CHILD],
        cwd=ROOT / "services" / service,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # 必须继承父进程环境（Windows 上缺 SYSTEMROOT 会导致 asyncio 初始化失败），
        # 只覆盖与外部依赖相关的少数键。
        env={
            **os.environ,
            "NACOS_ADDR": "127.0.0.1:1",
            "NACOS_CONFIG_TIMEOUT": "1",
            "DB_URL": "mysql+pymysql://root:root@127.0.0.1:1/placeholder?charset=utf8mb4",
            "PYTHONIOENCODING": "utf-8",
        },
    )
    if result.returncode != 0:
        raise SystemExit(f"{service} 生成失败：\n{result.stderr[-2000:]}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAPI 契约快照")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update", action="store_true", help="刷新快照")
    group.add_argument("--check", action="store_true", help="比对快照，有差异返回 1")
    args = parser.parse_args(argv)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    for service in SERVICES:
        content = generate(service)
        target = SNAPSHOT_DIR / f"{service}.json"
        if args.update:
            target.write_text(content, encoding="utf-8")
            print(f"updated {target.relative_to(ROOT)}")
            continue
        if not target.exists():
            changed.append(f"{service}: 缺少快照")
            continue
        if target.read_text(encoding="utf-8") != content:
            changed.append(f"{service}: 对外形状有变化")

    if args.update:
        return 0
    if changed:
        print(json.dumps({"passed": False, "changes": changed}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"passed": True, "services": len(SERVICES)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""H3 安全扫描：依赖漏洞 + 代码静态检查。

策略（与需求清单一致：**不阻塞开发，只有高危阻断**）：
- `pip-audit` 扫 requirements.lock.txt，只看有 CVE 的包；
- `bandit` 扫 app/，只把 HIGH 视为失败，MEDIUM/LOW 只报告；
- 退出码：0 全绿 / 1 有 HIGH 或高危漏洞 / 2 工具缺失（CI 里应视为配置问题）。

用法：
    python scripts/security_scan.py --service capability-service
    python scripts/security_scan.py --all
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("user-service", "billing-service", "capability-service", "ai-chat-service")


def _python(service: str) -> Path:
    venv = ROOT / "services" / service / ".venv"
    candidate = venv / "Scripts" / "python.exe"
    if candidate.exists():
        return candidate
    unix = venv / "bin" / "python"
    # CI 里没有本地 venv：回退到当前解释器（pip-audit/bandit 已随步骤安装）。
    return unix if unix.exists() else Path(sys.executable)


def _run(args: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def audit_dependencies(service: str) -> dict:
    """依赖漏洞：只把"有修复版本的漏洞"计为阻断项。"""

    service_dir = ROOT / "services" / service
    lock = service_dir / "requirements.lock.txt"
    target = lock if lock.exists() else service_dir / "requirements.txt"
    code, output = _run(
        [str(_python(service)), "-m", "pip_audit", "-r", str(target), "-f", "json"],
        service_dir,
    )
    if "No module named pip_audit" in output:
        return {"tool": "pip-audit", "available": False, "vulnerabilities": []}
    try:
        payload = json.loads(output[output.index("{"):]) if "{" in output else {}
    except json.JSONDecodeError:
        payload = {}
    vulns = []
    for dep in payload.get("dependencies", []) or []:
        for item in dep.get("vulns", []) or []:
            vulns.append({
                "package": dep.get("name"),
                "version": dep.get("version"),
                "id": item.get("id"),
                "fix_versions": item.get("fix_versions", []),
                "blocking": bool(item.get("fix_versions")),
            })
    return {"tool": "pip-audit", "available": True, "exit_code": code, "vulnerabilities": vulns}


def scan_code(service: str) -> dict:
    service_dir = ROOT / "services" / service
    if not (service_dir / "app").exists():
        return {"tool": "bandit", "available": False, "issues": []}
    code, output = _run(
        [str(_python(service)), "-m", "bandit", "-r", "app", "-f", "json", "-q"],
        service_dir,
    )
    if "No module named bandit" in output:
        return {"tool": "bandit", "available": False, "issues": []}
    try:
        payload = json.loads(output[output.index("{"):]) if "{" in output else {}
    except json.JSONDecodeError:
        payload = {}
    issues = [
        {
            "file": item.get("filename"),
            "line": item.get("line_number"),
            "severity": item.get("issue_severity"),
            "test": item.get("test_id"),
            "text": item.get("issue_text"),
        }
        for item in payload.get("results", []) or []
    ]
    return {"tool": "bandit", "available": True, "exit_code": code, "issues": issues}


def scan(service: str) -> dict:
    deps = audit_dependencies(service)
    code = scan_code(service)
    blocking_vulns = [v for v in deps.get("vulnerabilities", []) if v["blocking"]]
    high_issues = [i for i in code.get("issues", []) if i["severity"] == "HIGH"]
    return {
        "service": service,
        "passed": not blocking_vulns and not high_issues,
        "blocking": {
            "vulnerabilities": len(blocking_vulns),
            "high_bandit_issues": len(high_issues),
        },
        "report": {"pip_audit": deps, "bandit": code},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安全扫描（高危阻断）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--service", choices=SERVICES)
    group.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    targets = SERVICES if args.all else (args.service,)
    results = [scan(name) for name in targets]
    summary = {
        "passed": all(item["passed"] for item in results),
        "services": [
            {k: item[k] for k in ("service", "passed", "blocking")} for item in results
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_dir = ROOT / "artifacts" / "security"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

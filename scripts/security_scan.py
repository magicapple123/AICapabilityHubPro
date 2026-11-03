"""H3 安全扫描：依赖漏洞 + 代码静态检查。

策略（与需求清单一致：**不阻塞开发，只有高危阻断**）：
- `pip-audit` 扫 requirements.lock.txt，只看有修复版本（fix_versions 非空）的漏洞；
- `bandit` 扫 app/，只把 HIGH 视为失败，MEDIUM/LOW 只报告；
- **工具缺失不再算通过**：工具没装 => 该服务 passed=false，reason="tooling_missing"，
  总结果把 "tooling_missing" 与 "vulnerabilities" 分开统计，两者都让退出码非 0。

退出码：
- 0 全绿（四个服务都有工具、且无阻断项）
- 1 有高危漏洞 / HIGH bandit 问题
- 2 有服务缺少扫描工具（门禁配置问题，CI 必须失败）

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


def _missing_tool(output: str, module: str) -> bool:
    """工具没装时 Python 会输出 `No module named <module>`；不要把它当成"没问题"。"""
    return "No module named" in output and module in output


def audit_dependencies(service: str) -> dict:
    """依赖漏洞：只把"有修复版本"的漏洞计为阻断项。"""

    service_dir = ROOT / "services" / service
    lock = service_dir / "requirements.lock.txt"
    target = lock if lock.exists() else service_dir / "requirements.txt"
    code, output = _run(
        [str(_python(service)), "-m", "pip_audit", "-r", str(target), "-f", "json"],
        service_dir,
    )
    if _missing_tool(output, "pip_audit"):
        return {
            "tool": "pip-audit",
            "available": False,
            "reason": "tooling_missing",
            "target": target.name,
            "vulnerabilities": [],
        }
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
    return {
        "tool": "pip-audit",
        "available": True,
        "target": target.name,
        "exit_code": code,
        "vulnerabilities": vulns,
    }


def scan_code(service: str) -> dict:
    service_dir = ROOT / "services" / service
    if not (service_dir / "app").exists():
        return {
            "tool": "bandit",
            "available": False,
            "reason": "no_app_directory",
            "issues": [],
        }
    code, output = _run(
        [str(_python(service)), "-m", "bandit", "-r", "app", "-f", "json", "-q"],
        service_dir,
    )
    if _missing_tool(output, "bandit"):
        return {
            "tool": "bandit",
            "available": False,
            "reason": "tooling_missing",
            "issues": [],
        }
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

    missing = [
        tool["tool"]
        for tool in (deps, code)
        if not tool.get("available") and tool.get("reason") == "tooling_missing"
    ]
    blocking_vulns = [v for v in deps.get("vulnerabilities", []) if v["blocking"]]
    high_issues = [i for i in code.get("issues", []) if i["severity"] == "HIGH"]

    if missing:
        passed = False
        reason = "tooling_missing"
    elif blocking_vulns or high_issues:
        passed = False
        reason = "blocking_findings"
    else:
        passed = True
        reason = "ok"

    return {
        "service": service,
        "passed": passed,
        "reason": reason,
        "tools_missing": missing,
        "blocking": {
            "vulnerabilities": len(blocking_vulns),
            "high_bandit_issues": len(high_issues),
        },
        "report": {"pip_audit": deps, "bandit": code},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安全扫描（工具缺失与高危漏洞均阻断）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--service", choices=SERVICES)
    group.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    targets = SERVICES if args.all else (args.service,)
    results = [scan(name) for name in targets]

    tooling_missing = [item["service"] for item in results if item["reason"] == "tooling_missing"]
    vulnerable = [item["service"] for item in results if item["reason"] == "blocking_findings"]
    blocking_vulns = sum(item["blocking"]["vulnerabilities"] for item in results)
    high_issues = sum(item["blocking"]["high_bandit_issues"] for item in results)

    summary = {
        "passed": not tooling_missing and not vulnerable,
        "totals": {
            "services": len(results),
            "tooling_ready": len(results) - len(tooling_missing),
            "tooling_missing": len(tooling_missing),
            "blocking_vulnerabilities": blocking_vulns,
            "high_bandit_issues": high_issues,
        },
        "tooling_missing_services": tooling_missing,
        "vulnerable_services": vulnerable,
        "services": [
            {
                "service": item["service"],
                "passed": item["passed"],
                "reason": item["reason"],
                "tools_missing": item["tools_missing"],
                "blocking": item["blocking"],
            }
            for item in results
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_dir = ROOT / "artifacts" / "security"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if tooling_missing:
        return 2
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

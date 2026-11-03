"""Low-cost repository checks for the shared API-contract boundary.

This script deliberately does not implement any member's business feature. It
checks the public artifacts that must stay aligned while the three members work
in parallel: contract files, environment templates, service boundaries and
secret hygiene.
"""

from __future__ import annotations

import json
import ast
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = ROOT / "docs" / "api-contract"
SERVICE_DIR = ROOT / "services"
SHARED_EXECUTION_ERROR_CODES = {2008: "执行器未实现", 2009: "供应商不可用"}

#: 模板文件里不该出现的东西：OpenAI 风格长 Key、32 字节以上 base64、常见明文口令。
SECRET_LIKE = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,})|(?:[A-Za-z0-9+/]{43,}={0,2})|(?:password[ \t]*=[ \t]*(?!change-me|changeme|<)[^\s#]{8,})",
    re.IGNORECASE,
)


def check_contracts(errors: list[str]) -> None:
    expected = {
        "user-service.md",
        "billing-service.md",
        "capability-service.md",
        "ai-chat-service.md",
    }
    actual = {path.name for path in CONTRACT_DIR.glob("*.md")}
    for missing in sorted(expected - actual):
        errors.append(f"missing API contract: {missing}")

    for path in sorted(CONTRACT_DIR.glob("*.md")):
        if path.name == "_template.md":
            continue
        content = path.read_text(encoding="utf-8")
        for marker in ("code", "message", "data", "requestId"):
            if marker not in content:
                errors.append(f"{path.name} does not mention Result field {marker}")
        if "/internal/" not in content:
            errors.append(f"{path.name} does not document an internal boundary")
        if path.name in expected:
            for code in SHARED_EXECUTION_ERROR_CODES:
                if str(code) not in content:
                    errors.append(f"{path.name} does not document shared execution code {code}")


def check_env_templates(errors: list[str]) -> None:
    expected = [
        ROOT / "deploy" / ".env.example",
        ROOT / "web" / ".env.example",
        *(SERVICE_DIR / name / ".env.example" for name in (
            "user-service", "billing-service", "capability-service", "ai-chat-service"
        )),
    ]
    for path in expected:
        if not path.exists():
            errors.append(f"missing environment template: {path.relative_to(ROOT)}")


def check_service_boundaries(errors: list[str]) -> None:
    forbidden = re.compile(r"(?:user_db|billing_db|capability_db|ai_chat_db)")
    for service in sorted(SERVICE_DIR.glob("*-service")):
        own_name = service.name.removesuffix("-service").replace("-", "_")
        own_db = f"{own_name}_db"
        for path in service.glob("app/**/*.py"):
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(path))
            docstring_lines: set[int] = set()
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                if node.body and isinstance(node.body[0], ast.Expr):
                    value = node.body[0].value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        docstring_lines.update(
                            range(value.lineno, value.end_lineno + 1)
                        )
            for match in forbidden.finditer(content):
                line_start = content.rfind("\n", 0, match.start()) + 1
                line_number = content.count("\n", 0, match.start()) + 1
                line = content[line_start : content.find("\n", match.start())]
                if line_number in docstring_lines or line.lstrip().startswith("#"):
                    continue
                if match.group(0) != own_db:
                    errors.append(
                        f"cross-database reference in {path.relative_to(ROOT)}: {match.group(0)}"
                    )


def check_secret_hygiene(errors: list[str]) -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    )
    # Ignored local .env files are expected. Only staged/tracked and publishable
    # untracked candidates are checked; dependency directories are not walked.
    for value in set(result.stdout.decode("utf-8").split("\0")) - {""}:
        path = Path(value)
        name = path.name.lower()
        # `.env.example` 与 `.env.template` 都是**模板**（需求 G1 点名要后者）：
        # 放行这两个文件名，但下面仍会扫描内容，真实密钥写进模板照样报错。
        if name in {".env.example", ".env.template"}:
            content = path.read_text(encoding="utf-8", errors="replace")
            if SECRET_LIKE.search(content):
                errors.append(f"secret-like value inside template: {value}")
            continue
        sensitive = name == ".env" or name.startswith(".env.") or name.endswith((
            ".pem", ".key", "credentials.json", "token.txt"
        ))
        if sensitive:
            errors.append(f"possible credential file among Git candidates: {value}")


def main() -> int:
    errors: list[str] = []
    check_contracts(errors)
    check_env_templates(errors)
    check_service_boundaries(errors)
    try:
        check_secret_hygiene(errors)
    except (OSError, subprocess.CalledProcessError):
        errors.append("Git candidate scan failed; secret hygiene was not verified")
    result = {"root": str(ROOT), "errors": errors, "passed": not errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

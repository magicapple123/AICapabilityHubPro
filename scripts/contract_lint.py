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
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = ROOT / "docs" / "api-contract"
SERVICE_DIR = ROOT / "services"


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


def check_env_templates(errors: list[str]) -> None:
    expected = [
        ROOT / "deploy" / ".env.example",
        ROOT / "web" / ".env.example",
        *SERVICE_DIR.glob("*/.env.example"),
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
    patterns = (".env", ".pem", ".key", "credentials.json", "token.txt")
    tracked = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "node_modules" in path.parts:
            continue
        if path.name == ".env.example":
            continue
        if any(path.name.lower().endswith(suffix) for suffix in patterns):
            tracked.append(path)
    for path in tracked:
        errors.append(f"possible local secret file in workspace: {path.relative_to(ROOT)}")


def main() -> int:
    errors: list[str] = []
    check_contracts(errors)
    check_env_templates(errors)
    check_service_boundaries(errors)
    check_secret_hygiene(errors)
    result = {"root": str(ROOT), "errors": errors, "passed": not errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

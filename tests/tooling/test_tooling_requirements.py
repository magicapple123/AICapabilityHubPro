"""Keep `tests/requirements-tooling.txt` in sync with what the tooling tests import.

这批用例以前是"借"某个服务的依赖装出来的：`tests/tooling` 本身不声明任何依赖，
但 `scripts/devtools/seed_demo_data.py` 在模块级 `from sqlalchemy import ...`。
于是用系统 Python（没有服务 venv）直接 `python -m pytest tests/tooling -q` 时，
收集阶段就 `ModuleNotFoundError: No module named 'sqlalchemy'`，整批门禁直接红。

这里用静态扫描守住两件事：
1. tooling 依赖清单必须显式存在且包含关键包；
2. 被 tooling 用例 import 的 scripts/ 模块，其**模块级**第三方 import 必须全部
   在清单里声明，否则又会退回到"碰运气"。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = PROJECT_ROOT / "tests" / "requirements-tooling.txt"

#: tooling 用例直接 import 的 scripts/ 模块（相对 scripts/ 的路径）。
SCANNED_MODULES = (
    "devtools/seed_demo_data.py",
    "devtools/environment.py",
    "devtools/initialization.py",
    "smoke_check.py",
    "check_test_report.py",
)

#: 发行包名 -> 实际 import 名不同，或本身就是内置/本地模块的例外。
_IMPORT_ALIASES = {
    "sqlalchemy": "SQLAlchemy",
    "pymysql": "PyMySQL",
}
#: 标准库里包含、但名字容易和第三方混淆的模块（sys.stdlib_module_names 已覆盖大部分，
#: 这里只补 Python 版本差异导致漏判的项）。
_EXTRA_STDLIB = {"typing_extensions"}


def _declared_distributions() -> set[str]:
    """把清单里的 `Name>=1,<2` 归一成小写包名集合。"""

    declared: set[str] = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = line
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
            name = name.split(separator, 1)[0]
        declared.add(name.strip().lower())
    return declared


def _module_level_imports(path: Path) -> set[str]:
    """只取模块级（顶层）import 的根包名，函数内 import 不算硬依赖。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_requirements_file_declares_known_tooling_dependencies():
    assert REQUIREMENTS.is_file(), "tests/requirements-tooling.txt 必须存在"
    declared = _declared_distributions()
    for expected in ("pytest", "sqlalchemy", "pymysql"):
        assert expected in declared, f"{expected} 未在 tests/requirements-tooling.txt 声明"


def test_tooling_scripts_import_only_stdlib_or_declared_packages():
    declared = _declared_distributions()
    missing: list[str] = []
    for relative in SCANNED_MODULES:
        path = PROJECT_ROOT / "scripts" / relative
        assert path.is_file(), f"缺少被扫描的脚本: {relative}"
        for root in sorted(_module_level_imports(path)):
            if root in sys.stdlib_module_names or root in _EXTRA_STDLIB:
                continue
            # 本地模块（scripts/ 下自己的包）不是第三方依赖。
            if (PROJECT_ROOT / "scripts" / root).exists():
                continue
            if (PROJECT_ROOT / "scripts" / f"{root}.py").exists():
                continue
            distribution = _IMPORT_ALIASES.get(root, root).lower()
            if distribution not in declared:
                missing.append(f"{relative}: {root} (需要声明 {_IMPORT_ALIASES.get(root, root)})")
    assert not missing, "tooling 脚本的模块级依赖未在清单中声明:\n" + "\n".join(missing)

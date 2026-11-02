"""H4：OpenAPI 快照必须与当前代码一致（防止契约被悄悄改形）。"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "docs" / "api-contract" / "openapi"


def test_all_services_have_snapshot():
    for name in ("user-service", "capability-service", "billing-service", "ai-chat-service"):
        target = SNAPSHOTS / f"{name}.json"
        assert target.exists(), target
        spec = json.loads(target.read_text(encoding="utf-8"))
        assert spec["paths"], name


def test_check_mode_reports_no_drift():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "openapi_snapshot.py"), "--check"],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"passed": true' in result.stdout

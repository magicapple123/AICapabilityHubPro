"""CI must not silently pass skipped/missing DB tests or malformed HTTP results."""

from pathlib import Path

import pytest

from check_test_report import inspect_report
from smoke_check import verify_payload


@pytest.mark.parametrize("content,passed", [
    ("<testsuite><testcase name='actual'/></testsuite>", True),
    ("<testsuite/>", False),
    ("<testsuite><testcase><skipped/></testcase></testsuite>", False),
    ("<testsuite><testcase><failure/></testcase></testsuite>", False),
    ("<testsuite><testcase><error/></testcase></testsuite>", False),
])
def test_ci_requires_executed_success_without_skips(tmp_path: Path, content: str, passed: bool) -> None:
    path = tmp_path / "results.xml"
    path.write_text(content, encoding="utf-8")
    assert inspect_report(path)["passed"] is passed


def test_offline_skip_is_reported_as_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "results.xml"
    path.write_text("<testsuite><testcase/><testcase><skipped/></testcase></testsuite>", encoding="utf-8")
    result = inspect_report(path, allow_skips=True)
    assert result["passed"]
    assert result["skipped"] == 1
    assert result["database_coverage"] == "incomplete"


def test_smoke_requires_real_auth_http_and_result_fields() -> None:
    body = {"code": 1001, "message": "not authenticated", "data": None, "requestId": "trace"}
    assert verify_payload(401, body, 401, 1001)
    assert not verify_payload(200, body, 401, 1001)
    assert not verify_payload(401, {**body, "code": 0}, 401, 1001)
    assert not verify_payload(401, {**body, "requestId": ""}, 401, 1001)
    assert not verify_payload(401, {}, 401, 1001)

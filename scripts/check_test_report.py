"""Fail CI when database tests are missing, skipped, failed, or errored."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def inspect_report(path: Path, allow_skips: bool = False) -> dict:
    cases = list(ET.parse(path).getroot().iter("testcase"))
    skipped = sum(case.find("skipped") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    executed = len(cases) - skipped
    return {
        "total": len(cases), "executed": executed, "skipped": skipped,
        "failed": failed, "errors": errors,
        "passed": executed > 0 and not failed and not errors and (allow_skips or not skipped),
        "database_coverage": "incomplete" if skipped else "requires isolated-database CI context",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--allow-skips", action="store_true", help="offline local checks only")
    args = parser.parse_args()
    try:
        result = inspect_report(args.report, args.allow_skips)
    except (OSError, ET.ParseError):
        print("Missing or invalid JUnit evidence", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

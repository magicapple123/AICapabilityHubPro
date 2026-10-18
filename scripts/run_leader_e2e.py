"""Isolated leader E2E; requires installed service venvs, packaged Gateway and Nacos."""
import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from devtools.environment import PROJECT_ROOT
from leader_e2e.runtime import Runtime
from leader_e2e.model_server import ModelServer
from leader_e2e.checks import Checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nacos", default="127.0.0.1:8849")
    parser.add_argument("--catalog-mode", choices=["internal", "market"], default="internal")
    parser.add_argument("--browser", action="store_true", help="also verify the real UI with installed Playwright Chromium")
    args = parser.parse_args()
    run = PROJECT_ROOT / "artifacts/leader-e2e" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6])
    run.mkdir(parents=True, exist_ok=False)
    runtime, model = Runtime(PROJECT_ROOT, run, args.nacos), ModelServer()
    summary = {"passed": False, "catalog_mode": args.catalog_mode,
               "external_model": "local HTTP test double; four services, Gateway and MySQL are real",
               "developer_databases_used": False, "member_internal_contract_verified": False}
    checks = None
    try:
        runtime.create_database()
        model.start()
        runtime.start_services(model.base_url, args.catalog_mode)
        checks = Checks(runtime.gateway, model)
        summary["checks"] = checks.run()
        checks.verify_catalog_changes(runtime.sql)
        checks.verify_disabled_account(runtime.sql)
        checks.verify_gateway_exchange()
        if args.catalog_mode == "market":
            summary["member_internal_contract_verified"] = checks.verify_strict_mode(runtime.start_strict_probe())
        if args.browser:
            runtime.check_browser(checks.username, checks.password)
            summary["browser_verified"] = True
        summary["passed"] = True
        if args.catalog_mode == "internal": summary["member_internal_contract_verified"] = True
    except Exception as error:
        summary["error_type"] = type(error).__name__
        with (run / "failure.txt").open("x", encoding="utf-8") as out: traceback.print_exc(file=out)
        print("E2E failed:", type(error).__name__, "inspect", run, flush=True)
    finally:
        summary["checks"] = checks.results if checks else []
        summary["model_invocations"] = len(model.calls)
        runtime.close()
        if model.thread.is_alive(): model.stop()
        with (run / "summary.json").open("x", encoding="utf-8") as out: json.dump(summary, out, indent=2)
    print("E2E result:", summary["passed"], "checks:", len(summary["checks"]), "evidence:", run, flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

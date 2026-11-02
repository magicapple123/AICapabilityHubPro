#!/usr/bin/env bash
# 批次门禁执行器：固定本机实测口径（MySQL 3307 / 各服务独立 venv / USE_MOCK=true）。
# 用法: bash scripts/gate.sh <1|2|3|4|5|6|all>
# 每条门禁的真实退出码都会被记录，末尾打印 PASS/FAIL 汇总，直接贴进 docs/升级实施日志.md。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PWD="${GATE_DB_PWD:-4a506eacb81c1369473616daac5842115460219fc161f7d3}"
DB_PORT="${GATE_DB_PORT:-3307}"
DB_HOST="${GATE_DB_HOST:-127.0.0.1}"
export TEST_DB_ISOLATED=1
export USE_MOCK=true

RESULT_NAMES=()
RESULT_CODES=()
FAILED=0

record() {
  RESULT_NAMES+=("$1")
  RESULT_CODES+=("$2")
  if [ "$2" -ne 0 ]; then FAILED=1; fi
}

# 在指定目录跑一条命令，保留退出码，输出只留尾部 25 行。
run_in() {
  local name="$1" dir="$2"
  shift 2
  echo ""
  echo "===== ${name} ====="
  local out code
  out="$( cd "$dir" && "$@" 2>&1 )"
  code=$?
  printf '%s\n' "$out" | tail -25
  record "$name" "$code"
}

run_pytest() {
  local svc="$1" db="$2"
  run_in "pytest-${svc}" "$ROOT/services/${svc}" \
    env "DB_URL=mysql+pymysql://root:${DB_PWD}@${DB_HOST}:${DB_PORT}/${db}?charset=utf8mb4" \
    ./.venv/Scripts/python.exe -m pytest tests -q
}

TARGET="${1:-all}"
case "$TARGET" in
  1)
    run_pytest ai-chat-service ai_chat_db
    run_pytest billing-service billing_db
    run_in "contract-lint" "$ROOT" python scripts/contract_lint.py
    run_in "gateway-test" "$ROOT" mvn -q -f gateway/pom.xml test
    ;;
  2)
    run_pytest capability-service capability_db
    run_pytest user-service user_db
    # 批 2 新增了路由与网关健康路径放行，契约与网关必须一起验
    run_in "contract-lint" "$ROOT" python scripts/contract_lint.py
    run_in "gateway-test" "$ROOT" mvn -q -f gateway/pom.xml test
    run_in "smoke" "$ROOT" python scripts/smoke_check.py
    ;;
  3)
    run_pytest ai-chat-service ai_chat_db
    run_pytest capability-service capability_db
    run_in "tooling" "$ROOT" python -m pytest tests/tooling -q
    ;;
  4)
    run_in "web-lint" "$ROOT" pnpm --dir web lint
    run_in "web-build" "$ROOT" pnpm --dir web build
    run_pytest ai-chat-service ai_chat_db
    run_in "contract-lint" "$ROOT" python scripts/contract_lint.py
    ;;
  5)
    run_pytest user-service user_db
    run_pytest billing-service billing_db
    run_in "web-lint" "$ROOT" pnpm --dir web lint
    run_in "web-build" "$ROOT" pnpm --dir web build
    ;;
  6)
    run_in "compose-config" "$ROOT" docker compose -f deploy/docker-compose.yml config --quiet
    ;;
  all)
    run_pytest user-service user_db
    run_pytest billing-service billing_db
    run_pytest capability-service capability_db
    run_pytest ai-chat-service ai_chat_db
    run_in "contract-lint" "$ROOT" python scripts/contract_lint.py
    run_in "gateway-test" "$ROOT" mvn -q -f gateway/pom.xml test
    run_in "tooling" "$ROOT" python -m pytest tests/tooling -q
    run_in "web-lint" "$ROOT" pnpm --dir web lint
    run_in "web-build" "$ROOT" pnpm --dir web build
    run_in "smoke" "$ROOT" python scripts/smoke_check.py
    ;;
  *) echo "unknown gate target: $TARGET"; exit 2 ;;
esac

echo ""
echo "================ GATE SUMMARY (target=${TARGET}) ================"
i=0
while [ $i -lt ${#RESULT_NAMES[@]} ]; do
  if [ "${RESULT_CODES[$i]}" -eq 0 ]; then
    printf '  PASS  %s\n' "${RESULT_NAMES[$i]}"
  else
    printf '  FAIL  %s (exit %s)\n' "${RESULT_NAMES[$i]}" "${RESULT_CODES[$i]}"
  fi
  i=$((i+1))
done
if [ "$FAILED" -eq 0 ]; then
  echo "GATE_RESULT=PASS"
  exit 0
else
  echo "GATE_RESULT=FAIL"
  exit 1
fi

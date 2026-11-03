# P13 follow-up handoff

Status: **READY for main-agent runtime recreation and public gate**. Product/document changes finished; this agent did not restart any container, run a full gate, modify deploy/.env, stage, or commit.

## Changed files and backup

- D:\AICapabilityHubPro\deploy\docker-compose.yml: added Nacos readiness and Sentinel HTTP healthchecks; changed the five existing Nacos dependencies from service_started to service_healthy. Prior ports, environment and existing healthchecks remain intact.
- D:\AICapabilityHubPro\deploy\README.md: corrected prerequisites to Bash 4+ and GNU utilities; documented four complete commands for the isolated Linux verification project; every Compose invocation includes its explicit file path. Config generation uses exclusive create with mode 600, refusing existing files. Acceptance runs Python from Docker and uses only urllib/stdlib, without httpx or host Python. Corrected loopback browser access and documented SSH forwarding for remote operators.
- D:\AICapabilityHubPro\docs\verify\P13-followup.md: this handoff only; the main implementation log remains owned by the main agent.

Original bytes preserved at D:\AICapabilityHubPro\artifacts\verify-2026-11-03\backups\P13-followup-38697c2a619f4f2586d91fe1aa3f120e\deploy\docker-compose.yml and README.md. No file deletion or cleanup occurred. Restore individual files only after reviewing later concurrent changes.

## Actual verification commands and results

1. docker exec aihub-verify-nacos sh -c 'command -v curl; command -v wget; command -v bash; curl -fsS http://127.0.0.1:8848/nacos/v1/console/health/readiness'
   - Output: /usr/bin/curl, /usr/bin/wget, /bin/bash, OK.
2. docker exec aihub-verify-sentinel sh -c 'command -v curl; command -v wget; command -v bash; wget -q -O - http://127.0.0.1:8858/'
   - Output: the same three tools plus actual Sentinel Dashboard HTML.
3. docker exec aihub-verify-nacos sh -c "curl -fsS --max-time 3 http://127.0.0.1:8848/nacos/v1/console/health/readiness | grep -qx 'OK'"
   - NACOS_PROBE_EXIT=0.
4. docker exec aihub-verify-sentinel sh -c 'curl -fsS --max-time 3 -o /dev/null http://127.0.0.1:8858/'
   - SENTINEL_PROBE_EXIT=0.
5. docker exec aihub-verify-nacos sh -c 'curl -fsS --max-time 1 http://127.0.0.1:8848/nonexistent-probe 2>/dev/null | grep -qx OK'
   - NACOS_NEGATIVE_EXIT=1, showing a failed endpoint is not healthy.
6. docker exec aihub-verify-sentinel sh -c 'curl -fsS --max-time 1 -o /dev/null http://127.0.0.1:8859/ 2>/dev/null'
   - SENTINEL_NEGATIVE_EXIT=7 for an unavailable port.
7. docker compose --env-file deploy/.env -p aihub-pro-verify --profile app -f deploy/docker-compose.yml -f deploy/docker-compose.verify.yml config --quiet
   - Exit 0. No resolved config or secrets printed.
8. The same config --format json captured into a PowerShell variable, printing only service names with healthcheck:
   - HEALTHCHECK_COUNT=9; ai-chat-service, billing-service, capability-service, gateway, mysql, nacos, nginx, sentinel, user-service.
9. & 'C:/Program Files/Git/bin/bash.exe' -n scripts/bootstrap_stack.sh
   - Exit 0. Script uses Bash associative arrays; README now says Bash rather than POSIX shell.
10. git diff --check -- deploy/docker-compose.yml deploy/README.md
    - Exit 0.
11. Parsed the exact README generator with Python shlex/ast; asserted newline literal, p.open("x"), and os.umask(0o077):
    - README generator syntax=PASS; newline=PASS; exclusive create=PASS; private mode=PASS.

The installed Nacos and Sentinel containers still report Up without health status because Compose changes are not applied retroactively. The other seven are healthy. This is **not evidence of nine healthy runtime containers yet**.

## Main-agent remaining validation

1. After the P11 real-upstream window finishes, use scripts/verify/runtime_support.mjs compose helper to preserve the current QA ai-chat provider master key in memory, then recreate Nacos and Sentinel. Do not print the key. Wait until all nine list healthy and save exact output.
2. Repeat P13 bootstrap twice, then appendix C gate and acceptance in the independent environment. Also exercise README on a clean Linux Docker+Compose host, or retain that platform limitation in the final report; Windows and existing volumes do not prove a fresh-machine installation.
3. Capture nine-health status and acceptance output in P13 screenshots. No screenshots or SQL evidence were manufactured here. Database rows are unaffected.
4. Append a factual correction to the earlier P13 implementation log: Bash bootstrap, not POSIX; the previous run showed seven healthy plus two running before these probes existed.

## Version-control gap

Read-only git status --short still reports these untracked:

- D:\AICapabilityHubPro\deploy\.env.template
- D:\AICapabilityHubPro\deploy\docker-compose.verify.yml
- D:\AICapabilityHubPro\scripts\bootstrap_stack.ps1
- D:\AICapabilityHubPro\scripts\bootstrap_stack.sh
- D:\AICapabilityHubPro\deploy\README.md

They exist in the working directory but are **not yet committed**. Main agent must resolve wave staging and include deliverables without swallowing the original 94-file baseline. This agent did not stage or commit.

## Failed attempts / corrections

- Two tool-side multiline Markdown patch strings failed JavaScript parsing; no file was written by those failed calls. Applied the README change through a scoped Python transformation after preserving original bytes.
- The first documentation draft used a literal backslash-n where the generator needed a newline escape. The literal assertion caught it; corrected before handoff, assertion now passes.
- Original README omitted the explicit Compose file path on root-directory commands. Retained commands now include it.
- Assignment suggested acceptance might need httpx; direct inspection found urllib only. Documentation follows the actual script.

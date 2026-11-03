# P14 implementation handoff

Status: product implementation complete at 2026-11-03 15:47 +08:00; awaiting main-agent integration/full gate, deployed runtime checks and screenshots. No database test or full gate run by this agent, per assigned ownership.

The shared task file was readable. Direct collaboration messages still arrive encrypted; please use this file or agent-p14-task.md for further instructions.

Current owned edits:
- user-service/app/api/v1/deps.py: current_user_id now checks active account.
- user-service/app/api/v1/accounts.py: passes direct peer IP to login service.
- user-service/app/api/v1/admin.py: disabled admin identity returns1005 before role authorization.
- user-service/app/service/user_service.py: checks lock before password hashing, records failure metadata.
- NEW service/login_protection.py: process-local bounded fingerprint-only windows (account5/IP25 in300s, cooldown900s).
- NEW service/login_audit.py: append-only login_failed audit, no raw username/IP/password.
- ai-chat-service/app/api/v1/sessions.py: every read checks user state, even when optional billing chain is off.
- Both service tests/conftest.py: isolate new process state and mock only session user-service transport.
- NEW user tests/test_login_protection.py and ai-chat tests/test_sessions_lifecycle.py.

Important: ai-chat existing session tests use synthetic user IDs. The new autouse fixture mocks only the sessions.call_internal boundary and asserts route/cost; dedicated lifecycle tests override it and verify 1005/4002 and active-after-reenable. No assertions/tests were removed or weakened.

Backups: artifacts/verify-2026-11-03/backups/P14-20261103-154321-210 and P14-fixtures-* preserve all original bytes. No files deleted.

## Absolute changed paths

- `D:\AICapabilityHubPro\services\user-service\app\api\v1\deps.py`
- `D:\AICapabilityHubPro\services\user-service\app\api\v1\accounts.py`
- `D:\AICapabilityHubPro\services\user-service\app\api\v1\admin.py`
- `D:\AICapabilityHubPro\services\user-service\app\service\user_service.py`
- `D:\AICapabilityHubPro\services\user-service\app\service\login_protection.py` (new)
- `D:\AICapabilityHubPro\services\user-service\app\service\login_audit.py` (new)
- `D:\AICapabilityHubPro\services\user-service\tests\conftest.py`
- `D:\AICapabilityHubPro\services\user-service\tests\test_login_protection.py` (new,16 cases)
- `D:\AICapabilityHubPro\services\user-service\tests\test_p14_accounts.py` (new,3 real-MySQL cases; not yet executed)
- `D:\AICapabilityHubPro\services\ai-chat-service\app\api\v1\sessions.py`
- `D:\AICapabilityHubPro\services\ai-chat-service\tests\conftest.py`
- `D:\AICapabilityHubPro\services\ai-chat-service\tests\test_sessions_lifecycle.py` (new,10 cases)
- `D:\AICapabilityHubPro\docs\verify\P14-implementation.md` (this handoff)

## Commands and actual results

Both test processes explicitly received `DB_URL` pointing at 127.0.0.1:23307 and `TEST_DB_ISOLATED=1`. Password was loaded from deploy/.env only into process memory and never printed. These selected tests perform no SQL mutation; each service conftest may read its independent DB readiness.

1. Working directory `D:\AICapabilityHubPro\services\user-service`: `.venv/Scripts/python.exe -m pytest tests/test_login_protection.py -q --no-cov` -> first10 cases passed; after dependency coverage was added, final `16 passed, 1 warning in 0.03s`, zero skips.
2. Working directory `D:\AICapabilityHubPro\services\ai-chat-service`: `.venv/Scripts/python.exe -m pytest tests/test_sessions_lifecycle.py -q --no-cov` -> `10 passed, 1 warning in 0.06s`, zero skips.
3. `services/user-service/.venv/Scripts/python.exe -m compileall -q` followed by explicit owned app/test Python paths -> exit0.
4. `git diff --check -- services/user-service/app/api/v1/deps.py services/user-service/app/api/v1/accounts.py services/user-service/app/api/v1/admin.py services/user-service/app/service/user_service.py services/user-service/tests/conftest.py services/ai-chat-service/app/api/v1/sessions.py services/ai-chat-service/tests/conftest.py` -> exit0; only existing CRLF warning.
5. Modular file scanner on login_protection.py ->98 lines, no warning/hard overflow.

No implementation test failures so far. Initial discovery used a malformed rg regex and guessed two nonexistent test/model paths; corrected to actual filenames, no product data touched.

## Decisions and contracts to merge into main docs

- Existing `current_user_id` is the unified active-account dependency. All account/profile/key/points routes using it now reject disabled or missing users with1005. Admin routes also reject disabled identities1005 before role2007; ordinary active users remain2007. `/ping` keeps its pre-existing diagnostic contract.
- Sessions call existing GET `/internal/user/check?user_id=<id>&points_cost=0` for both list and messages, validate identity/status response, and fail closed. This call happens even if `enable_internal_chain=false`; settlement configuration must not bypass account security. No new endpoint/schema or migration.
- Login: account5 failures/300s and direct-peer-IP25 failures/300s; reaching the threshold locks900s. First5 account failures remain1003, next request returns existing4001 with explicit lock text before user lookup or PBKDF2. Successful login clears account failures but cannot erase peer-IP spraying failures.
- Direct peer address is used; client-supplied Forwarded/X-Forwarded-For headers are ignored. Behind one gateway/NAT the IP budget is shared;25 is deliberate to avoid locking a whole team after5 mistakes. For large clusters replace this process-local state with a shared store/edge policy.
- Unknown account names are casefolded/hashed and follow the same policy as known accounts. At most10000 fingerprint windows are retained; full state fails closed4001, expired entries reclaimed.
- Failed/locked/disabled login attempts append `resource_type=user, action=login_failed`; unauthenticated actor anonymous, resource user_id when already known or account SHA256 fingerprint; JSON has only reason/account_fingerprint/peer_fingerprint. No username, rawIP, password, token, password hash or credential material. Audit commit precedes the business failure.
- JWT jti/denylist remains optional and was not introduced. Disabled-account enforcement gives immediate rejection of existing JWTs; re-enable is immediately visible without caches. Existing JWT format/TTL unchanged.

## Main-agent next actions

1. After other DB tests stop, run the user and ai-chat full suites against23307, including new test_p14_accounts.py (3 cases). Full coverage remains enforced; the pure unit command's --no-cov is only targeted verification, not a gate substitute.
2. Rebuild/restart user and ai-chat acceptance containers before runtime checking; current Docker images do not include these changes.
3. Create a dedicated P14 account (not opsdemo; use p14-live prefix so pytest qa cleanup cannot remove it), login once, disable, then use old JWT for profile/sessions/records ->1005. Restore normal and verify immediate access.
4. For a fresh P14 account send5 incorrect logins, then sixth(correct password) ->4001; query audit by action/login fingerprint and show six metadata-only rows. Screenshot sanitized responses as P14-*.png. Do not print token or credentials.
5. Run per-item fullgate/acceptance/lint/build, update primary implementation log and common API contract documentation. This subagent did not modify those shared files or create commits.

## P14 runtime script READY（2026-11-03）

- New owned file: `D:AICapabilityHubProscriptserifyp14_lifecycle.mjs` (107 lines). Product files and shared runtime_support.mjs unchanged.
- Actual local command: `node --check scripts/verify/p14_lifecycle.mjs` -> exit0. `git diff --check -- scripts/verify/p14_lifecycle.mjs` -> exit0 (new untracked file syntax is covered by node --check). No runtime call, container rebuild, SQL mutation, full gate or screenshot executed by this script-author agent.
- Main run command after rebuilding user-service: `node scripts/verify/p14_lifecycle.mjs`. It bootstraps isolated admin, creates two p14-live accounts, retains existing JWT through disable/reenable for profile/sessions/records, sends five wrong logins plus a sixth correct-password request, queries six sanitized metadata-only audit rows and dedicated accounts/points/billing counts. Evidence JSON and P14 screenshot paths are printed without tokens/passwords/raw inputs. Failure evidence is retained and exit code1 is returned; temporarily disabled account is restored in finally.
- The script deliberately asserts **the sixth attempt must4001 through the actual gateway**. Current product counters are process-local while Compose runs2 user workers, so routing across workers may reveal a genuine failure. Do not relax the assertion or multiply attempts to hide it; fix the product policy or accurately record deployment limitation according to the frozen requirement.
- Audit JSON is checked for exactly3 allowed keys and validated fingerprints before it is saved. Unsafe metadata is never printed/saved, only a boolean failure marker. Registration-only points and zero bill rows are required.
- Handoff backup: `D:AICapabilityHubProartifactserify-2026-11-03ackupsP14-runtime-handoff-439a5b136d7b407caefb4f025696aea5docserifyP14-implementation.md`. No deleted files.
- Read-only discovery initially guessed nonexistent point model filenames; actual models live in app/models/user.py. No product changes resulted.

Correction: final p14_lifecycle.mjs is94 lines (not107). Final node --check again exit0. Cleanup flag is set before disabling request, so a response/network failure after a successful write still triggers restoration. Both owned files remain untracked; no staging/commit performed.

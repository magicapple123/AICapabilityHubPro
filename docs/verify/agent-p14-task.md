# P14 implementation assignment

Read the frozen requirement docs/升级需求清单-2026-11-03.md P14 and appendices. Implement P14 now, preserving all pre-existing changes.

Exclusive ownership: user-service api/v1/deps.py, service/user_service.py, new login protection modules and user account routes/tests; ai-chat-service/app/api/v1/sessions.py and its specific tests. Do not edit F1 execution/provider files, capability, billing, web, main implementation log, or common API contract docs.

Deliver active-account enforcement on authenticated user routes and sessions, existing disabled JWT returning 1005; per-account plus IP login failure locking (5 failures, sixth locked), audit failed login without password. Token revocation is optional. Back up original files before patching, do not delete files/tests or weaken assertions.

Use only independent acceptance DB 23307. Do not run DB tests concurrently with the main gate; write pure unit tests and report integration commands. Write docs/verify/P14-implementation.md with absolute changed paths, decisions, commands/results, failures. Do not commit. Main agent runs full gate, screenshots and writes primary log.

Coordination: main P11 suite observed sessions failure before fixture landed. Please finish the sessions-boundary fixture then mark READY in P14-implementation.md. Do not run DB tests; main runs full gate serially. Main full tests must use USE_MOCK=true and NACOS_MODEL_CONFIG_ENABLED=false.

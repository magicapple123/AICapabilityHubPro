# agent-a-ai-chat · P12 / P15 / P16 实施报告（2026-11-03）

> 范围：`services/ai-chat-service` 执行链（F1/F8 内被分配给本 agent 的文件族）。
> 未触碰：`core/security.py`、`core/logging.py`、`core/service_call.py`、`service/execution_billing.py`、
> `api/v1/openai_compat.py`、billing/user/capability 服务、`web/**`、`gateway/**`、`deploy/**`、
> 需求清单与实施日志。
> 未执行 `git add/commit/reset`。

## 0. 结论

| 编号 | 状态 | 一句话 |
|---|---|---|
| P12 | ✅ 完成（实机 Codex 端到端未做） | `store:false`、`reasoning`、`background` 不再 4001；工具结构双向翻译；SSE 事件序列补齐并固定；`instructions` 超长只截断 |
| P15 | ✅ 钉扎完成 | 模型/流式/供应商探测三条出站按**已校验 IP** 建连，Host 与 TLS SNI 用原域名；文生图残余窗口已如实写进 docstring 与契约 |
| P16 | ✅ 完成 | 按 alias 的进程内熔断（5005 快速失败）+ 入口 deadline（默认 60s）+ `/metrics` 暴露状态 |

## 1. 改动文件（绝对路径）

新增：

- `D:\AICapabilityHubPro\services\ai-chat-service\app\core\provider_breaker.py`（熔断）
- `D:\AICapabilityHubPro\services\ai-chat-service\app\core\deadline.py`（整体超时预算）
- `D:\AICapabilityHubPro\services\ai-chat-service\tests\test_provider_pinning.py`（P15，7 例）
- `D:\AICapabilityHubPro\services\ai-chat-service\tests\test_provider_breaker.py`（P16，13 例）
- `D:\AICapabilityHubPro\services\ai-chat-service\tests\test_key_attribution.py`（P6 归因补充断言，4 例；应 team-lead 要求新增，未改他人断言）

修改：

- `...\app\api\v1\responses.py`（P12 主要改动）
- `...\app\core\provider_guard.py`（P15 钉扎能力 + docstring 口径）
- `...\app\core\config.py`（`request_budget_seconds` / `provider_breaker_*` / `provider_cooldown_seconds`）
- `...\app\service\provider_service.py`（`ProviderRuntime.target`、探测走钉扎）
- `...\app\service\model_client.py`（钉扎 + 熔断 + 预算压缩超时）
- `...\app\service\stream_service.py`（同上，流式路径）
- `...\app\service\capability_adapters.py`（向下传 target/breaker/deadline；图片执行器也纳入熔断）
- `...\app\service\chat_service.py`（入口建 `Deadline`，向下传递）
- `...\tests\conftest.py`（每个用例前后清空熔断状态）
- `...\tests\test_responses_compat.py`（按 P12 新语义重写断言）
- `...\tests\test_stream.py`（替身签名跟进新关键字参数）
- `D:\AICapabilityHubPro\docs\api-contract\openai-compat.md`（Responses 支持/忽略/拒绝矩阵、事件顺序、`platform_warnings`）
- `D:\AICapabilityHubPro\docs\api-contract\ai-chat-service.md`（§10.1 地址防护改为"已钉扎 + 残余边界"，新增 P15/P16 小节）

## 2. P12 · Responses 兼容

### 关键决策

1. **字段语义分三类**，不再"见到就拒"：
   - 拒绝（4001/HTTP 400）：`store: true`、`tools[].type != function`、
     `input[]` 里的 `item_reference` / `web_search_call` / `file_search_call`；
   - 接受但忽略：`store: false`（不产生 warning）、`reasoning`、`background`、
     `input[]` 的 `reasoning` 条目；
   - 兼容：`instructions` 超 12000 字符截断，不进"用户消息长度"判定。
2. **`platform_warnings: string[]` 恒定存在**（无提示时为空数组），非流式放在响应体，
   流式放在 `response.created` 与 `response.completed` 的 `response` 对象里；重复提示去重。
3. **工具翻译只做一次，位置固定在进入 `chat_service` 之前**（`responses.py::_translate_tools`）：
   - 正向：扁平 `{type,name,description,parameters[,strict]}` → `{type:"function",function:{...}}`；
     两种入参形态都认（已是嵌套的原样搬运），`parameters` 缺省补 `{"type":"object","properties":{}}`；
   - `tool_choice`：`{"type":"function","name":"x"}` → `{"type":"function","function":{"name":"x"}}`，
     `auto/none/required` 原样透传；
   - 反向：`tool_calls` → `function_call` 条目，`call_id` 缺失时补 `call_<hex>`、`arguments`
     缺失补 `"{}"`、对象形态 `json.dumps`，保证客户端回灌 `function_call_output` 能对上。
   - `openai_compat` 的 chat 路径本就收嵌套格式，**未在其侧重复翻译**（该文件也未改动）。
4. **SSE 顺序固定**：`created → output_item.added → content_part.added → delta* →
   output_text.done → output_item.done → completed → [DONE]`；原有事件名一个未删。
   新增失败路径事件 `response.failed`（执行期 `BizException` 时补发 + `[DONE]`），
   避免"头已发出但流静默断掉"。
5. `instructions` 截断而非拒绝，理由：能力 Schema 单条 `content` 上限 12000，整单 4001 会让
   长系统提示的 Agent（Codex 类）永远进不来；截断 + warning 是"可用且可解释"的折中。
6. `max_output_tokens → max_tokens` 与 `openai-responses` 上游字段差异**按现状保留**，未回退。

### 验证

```
./.venv/Scripts/python.exe -m pytest tests/test_responses_compat.py -q --no-cov
57 passed（含 test_stream_event_order_is_frozen / test_tools_are_translated_to_nested_chat_shape /
            test_tool_calls_become_function_call_items / test_store_false_is_allowed /
            test_instructions_longer_than_message_limit_is_truncated 等）
```

用例文件从 16 例增到 22 例，**无一例被删除或加 skip**；原 `store=true` 拒绝、内置工具拒绝保持。

## 3. P15 · SSRF IP 钉扎

### 关键决策（选了"钉扎"而不是"承认边界"）

- `provider_guard.SafeTarget` 增 `host_header` 与 `connect_url(suffix)`，
  新增 `pinned_request_parts(target, suffix) -> (url, {"Host": ...}, {"sni_hostname": ...})`。
- `ProviderRuntime` 增 `target: SafeTarget | None`；`resolve_runtime()` 把**本次校验**的
  结果带出来，所以"校验的 IP"与"建连的 IP"是同一个，DNS 重绑定窗口消失。
- 三条出站都改用它：`model_client.complete`、`stream_service.stream_upstream`、
  `provider_service.test_provider`（探测也走钉扎，否则"探测通过"证明不了真实建连路径）。
- 已验证环境支持：`httpx 0.28.1 + httpcore 1.0.9`，`httpcore/_async/connection.py` 读取
  `request.extensions["sni_hostname"]` 作为 TLS `server_hostname`（证书仍按域名校验）。
- **残余边界如实记录**（docstring + `ai-chat-service.md`）：① 文生图 `image_client` 仍按域名建连
  （该文件不在本 agent 文件族，未改），防护退化为解析校验；② 只钉第一个解析地址，无故障转移；
  ③ 未绑定供应商走全局 `MODEL_BASE_URL`，属部署期配置不钉扎。
  ——口径与代码一致，不存在"注释说防住了、代码没防"的状态。

### 验证

```
./.venv/Scripts/python.exe -c "from app.core.provider_guard import SafeTarget, pinned_request_parts; ..."
('https://93.184.216.34/v1/chat/completions', {'Host': 'api.example.com'}, {'sni_hostname': 'api.example.com'})

./.venv/Scripts/python.exe -m pytest tests/test_provider_pinning.py -q --no-cov
7 passed
```

DNS 重绑定用例：`test_dns_rebinding_after_validation_cannot_change_connect_target`
—— 校验后把 DNS 改成 `169.254.169.254`，`connect_url()` 仍指向校验时的公网 IP；
重新 `validate_url()` 则被拒绝。另有 `test_model_call_uses_pinned_ip_with_domain_host_header`
断言真实调用路径的 URL/Host/SNI/`follow_redirects=False`。

## 4. P16 · 熔断 + 整体超时预算

### 关键决策

1. `app/core/provider_breaker.py`：`closed →（连续 N 次 5xx/超时/连接错）→ open →
   （冷却 M 秒）→ half_open →（探测成功）closed /（失败）重新 open`。
   - 只有 `5001/5002/5005` 计入失败；`429(5003)`、`401/402/403(5004)` 不计入（过期 Key 不该熔断供应商）；
   - 半开只放**一个**探测，其余请求继续快速失败；
   - 参数走 settings：`PROVIDER_BREAKER_ENABLED`(true) / `PROVIDER_BREAKER_FAILURE_THRESHOLD`(5) /
     `PROVIDER_COOLDOWN_SECONDS`(30)，全部有默认值，**未引入新的 Nacos 依赖**。
2. `app/core/deadline.py`：入口 `Deadline.start()`（`REQUEST_BUDGET_SECONDS=60`），
   单次尝试超时 `min(供应商配置, 剩余预算)`；重试需剩余预算 ≥ 退避时间；预算耗尽直接按超时降级，
   **不再发起上游请求**。覆盖模型/流式/图片三条出站（内部 RPC 超时仍在 `service_call`，本轮不改）。
3. **计费语义不变**：熔断拒绝抛 `BizException(5005)`，走既有失败路径（一条 `failed` 占位消息、
   不产生账单、不扣分）；流式路径先把 `outcome.error_code=5005` 再抛，避免"空成功"结算。
4. `/metrics`：`provider_breaker_state{provider}`（0/1/2）、`provider_breaker_trips_total`、
   `provider_breaker_rejected_total`，注册在既有 `observability.REGISTRY`（未改 observability.py）。
5. **多 worker 已知限制写进模块 docstring**：状态进程内，真实阈值 ≈ worker 数 × 配置值，
   与 A4 令牌桶同一局限。

### 验证

```
./.venv/Scripts/python.exe -c "... provider_breaker.record_failure('dashscope-chat',5005) x5 ..."
{'dashscope-chat': 'open'}
provider_breaker_state{provider="dashscope-chat",service="ai-chat-service"} 2.0
provider_breaker_trips_total{provider="dashscope-chat",service="ai-chat-service"} 1.0
provider_breaker_rejected_total{...}  （counter，拒绝时自增）

./.venv/Scripts/python.exe -m pytest tests/test_provider_breaker.py -q --no-cov
13 passed
```
其中 `test_open_breaker_fails_fast_without_calling_upstream` 断言：熔断后单次调用
`calls==0`、`elapsed < 0.5s`（不是 30s×2）；`test_exhausted_budget_skips_upstream` 断言预算耗尽时
上游 0 次调用并返回 `5001`；`test_execute_prepared_short_circuits_when_breaker_open` 断言执行器层同样
抛出 5005 且不打上游。

## 5. 命令与结果尾巴（本次实际执行）

```
# 基线（改动前）
./.venv/Scripts/python.exe -m pytest tests -q --no-cov
2 failed, 232 passed        # 失败为 service_call.py:39 NameError: get_user_key_id（他人在改的文件）

# 指定四条
./.venv/Scripts/python.exe -m pytest tests/test_responses_compat.py tests/test_responses_upstream.py tests/test_stream.py tests/test_provider.py -q --no-cov
57 passed

# P12/P15/P16 相关合集
./.venv/Scripts/python.exe -m pytest tests/test_provider_breaker.py tests/test_provider_pinning.py tests/test_responses_compat.py tests/test_stream.py tests/test_provider.py -q --no-cov
74 passed

# P6 归因补充断言（team-lead 修完 logging/service_call 之后新增）
# 环境变量：DB_URL=...:23307/ai_chat_db、TEST_DB_ISOLATED=1、USE_MOCK=true、NACOS_MODEL_CONFIG_ENABLED=false
./.venv/Scripts/python.exe -m pytest tests/test_key_attribution.py -q --no-cov
4 passed, 1 warning in 0.35s

# 最终全量（DB_URL=...:23307/ai_chat_db, TEST_DB_ISOLATED=1, USE_MOCK=true）
./.venv/Scripts/python.exe -m pytest tests -q --no-cov
265 passed
```

用例总数 234 → 265（+31），**无删除、无 skip/xfail、无断言放宽**；原本断言"store/background/reasoning
一律 4001"的 3 例按需求改成新语义（拒绝 → 放行 + warning），并把"被忽略字段仍要可执行"、
"SSE 顺序"、"工具双向翻译"、"instructions 超长"、"钉扎"、"熔断"、"预算"全部补成断言。

## 5.1 P6 Key 归因补充断言（`tests/test_key_attribution.py`）

按 team-lead 给的现成接口写，不改 `security/logging/service_call/execution_billing/openai_compat`：

| 用例 | 断言 |
|---|---|
| `test_platform_api_reports_key_id_and_entrypoint` | 带 `X-User-Key-Id: 42` 调 `/api/chat/completions`，账单上报体 `api_key_id == 42`（`type is int`）、`entrypoint == "platform_api"` |
| `test_platform_api_without_key_header_reports_null_not_zero` | 不带该头：`api_key_id is None` 且 `!= 0`、`entrypoint == "web"` |
| `test_invalid_key_header_is_treated_as_no_key` | `abc`/`0`/空串都降级为"无 Key 身份"，不阻断请求；直调 `current_user` 时四个参数全部显式传入（其默认值是 `Header(...)` 描述对象，只传部分参数会让其余参数被 Pydantic 判成 `string_type` 错误） |
| `test_openai_compat_reports_key_id_and_entrypoint` | `/v1/chat/completions` 用 `sk_` 替身：`api_key_id == verify 返回的 77`、`entrypoint == "openai_compat"`；verify 入参只有 `secret_hash`，不含明文 Secret |

执行链是真实代码（仅替换目录边界与下游 HTTP 替身），落库走真实 `ai_chat_db`。

## 6. 未完成 / 受阻

1. ~~⛔ `tests/test_http_client.py` 两例失败~~ **已解决**：根因是 `app/core/service_call.py:39`
   调用 `get_user_key_id()` 而 `logging.py` 尚未定义（P6 半成品）。team-lead 补齐后
   `tests/test_key_attribution.py` 4 例 + 全量 265 例全绿。
2. `mypy` 无法运行：仓库根 `mypy.ini`/`setup.cfg` 含非 GBK 字节，本机默认 GBK 解码失败
   （`UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`）。属环境/配置问题，未改配置。
   `ruff` 未安装在该 venv。IDE 诊断 0 条。
3. P12 的**实机 Codex CLI 端到端**（读文件→改文件、只有一条账单）未做：需要整栈 + 真实上游 Key，
   且 `scripts/gate.sh`/`acceptance_check.py` 由主代理统一跑。协议层行为已由 22 例覆盖
   （含工具往返、事件顺序、`store:false`、`instructions` 超长）。建议主代理在整栈起来后按
   附录 C 的 P12 行补一次真机验证。
4. 未新增 `scripts/verify/p12_responses.mjs` 等实机脚本：本轮以 pytest（真实 TestClient + 真实 DB）
   完成验证，脚本形式对复现价值不大；如需要可再补。

## 7. 给主代理的口径提醒

- 行为变化会波及文档/前端文案：`/v1/responses` 现在**不会**因 `reasoning`/`background`/`store:false`
  报 4001；旧 E3 断言（"store/reasoning 均 4001"）必须更新，不能作为回归基线。
- 新增 4 个环境变量（均有默认值），Docker/compose 不需要动；若要关闭熔断，设
  `PROVIDER_BREAKER_ENABLED=false`。
- 熔断拒绝的错误码是 `5005`，与"上游 5xx"同码；若需要区分，可在后续加 `5006`（本轮按需求清单
  原文用 5005）。
- 文生图仍未钉扎（`image_client.py` 不在本 agent 文件族）；若要补齐，改 `generate_dashscope` /
  `generate_openai` 接受 `SafeTarget` 并用 `pinned_request_parts` 拼 URL 即可，改动约 20 行。

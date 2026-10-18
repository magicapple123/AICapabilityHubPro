# ai-chat-service 接口契约

> **Pro 已实施（2026-10-19）：** 第 8 节为现行升级契约。第 1–7 节保留兼容字段说明；其“固定单价”和旧执行顺序由第 8 节替代。

> 负责人：黄岑果
> 服务名：`ai-chat-service`
> 数据库：`ai_chat_db`（只有本服务可访问）
> 端口：8090
> 上游依赖：`user-service`（`GET /internal/user/check`）、`billing-service`（`POST /internal/billing/record`）

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401；网关限流 HTTP 429 + `code=4001`。

## 0. 通用约定

- **登录要求**：`/api/chat/**` 全部需要网关 JWT（网关白名单只放行 `/health`）。服务不解析 JWT，只读取网关注入的 `X-User-Id` / `X-User-Name` / `X-Request-Id`。
- **身份要求**：`X-User-Id` 必须是正整数（JWT 的 `sub` 是用户 ID），否则返回 `1001`；它同时作为会话归属隔离条件。
- **下游调用**：`ENABLE_INTERNAL_CHAIN=true`（默认）时按“校验用户/积分 → 执行能力 → 上报计费”顺序调用 `/internal/**`，只使用基座 `call_internal`（自动服务发现 + 透传 `X-Request-Id`）；关闭后为纯 Mock 自测模式。
- **时间格式**：`create_time` / `update_time` / `last_message_time` 返回 ISO 8601（`YYYY-MM-DDTHH:MM:SS`），由 FastAPI 统一序列化。
- **软删除**：所有查询默认过滤 `is_deleted=0`；本期没有物理删除接口。
- **金额语义**：积分一律整型（个），不使用浮点（指南 5.5）。

## 1. 数据字典

### `t_chat_session`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 会话 ID |
| `user_id` | VARCHAR(64) | NOT NULL | 用户标识（网关注入的 `X-User-Id`） |
| `title` | VARCHAR(200) | NOT NULL DEFAULT '新对话' | 会话标题，取自首条用户消息，超 30 字截断 |
| `last_message_time` | DATETIME | NULL | 最后一条消息时间，列表按它倒序 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

### `t_chat_message`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 消息 ID |
| `session_id` | BIGINT | NOT NULL, INDEX | 所属会话 |
| `user_id` | VARCHAR(64) | NOT NULL, INDEX | 用户标识 |
| `role` | VARCHAR(16) | NOT NULL | `system` / `user` / `assistant` |
| `content` | TEXT | NOT NULL | 消息内容 |
| `call_status` | VARCHAR(16) | NOT NULL DEFAULT 'success' | 助手消息的执行状态，与指南 5.5 统一枚举一致 |
| `token_count` | INT | NOT NULL DEFAULT 0 | 真实模型取 `usage.total_tokens`，Mock 与降级按字符数估算 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

**索引**：`t_chat_session(user_id, is_deleted, last_message_time)` 支撑列表查询与排序；`t_chat_message(session_id, is_deleted, id)` 支撑消息顺序读取。

## 2. 对话接口

### `POST /api/chat/completions`

- 负责人：黄岑果
- 是否需要登录：是
- 请求体（兼容 OpenAI Chat Completions）：

```json
{
  "session_id": 1,
  "model": "mock-model",
  "messages": [{"role": "user", "content": "你好"}],
  "temperature": 0.7,
  "stream": false
}
```

- `session_id` 为空时**新建会话**；传入时必须是当前用户自己的会话，否则返回 `4004`（不区分“不存在”与“不属于你”）。
- `messages` 至少一条；`role` 只接受 `system` / `user` / `assistant`，单条 `content` 长度 1~12000。
- `stream` 本期不支持，仅作参数兼容（指南非目标：SSE）；`temperature` 缺省 0.7。
- 未显式提供 `system` 消息时，服务注入 `.env` 的 `DEFAULT_SYSTEM_PROMPT`。

- 成功 data（OpenAI 风格 + 会话与调用状态扩展字段）：

```json
{
  "id": "chatcmpl-0f1a...",
  "object": "chat.completion",
  "created": 1758000000,
  "model": "mock-model",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好！..."}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 6, "completion_tokens": 18, "total_tokens": 24},
  "session_id": 1,
  "message_id": 2,
  "mock": true,
  "call_status": "success",
  "degraded": false,
  "error_code": null,
  "duration_ms": 12
}
```

- 错误码：`1001` 未认证；`2001` 参数不符合 Schema；`3001` 积分不足（执行前拦截，不落库）；`4002` 下游服务不可用；`4004` 会话不存在或不属于当前用户。
- 备注：
  - **固定处理顺序**：读取透传身份与 requestId → 准备会话 → 用户消息落库 → 校验用户/积分 → 执行 Mock 或模型 → 助手消息落库 → 上报计费 → 提交事务 → 返回；
  - 全流程共用一个事务，任何异常整体回滚，不留“有消息但没有计费”的半成功状态；
  - Mock 模式（`USE_MOCK=true`）返回固定回复，绝不访问外部地址；
  - **降级**：模型超时（`5001`）或响应异常（`5002`）时返回兜底话术，`call_status=degraded`、`degraded=true`、`error_code` 为对应 5xxx；此时上报 `points=0`（**不计费**），但仍写调用流水便于观察失败率。

## 3. 会话接口

### `GET /api/chat/sessions`

- 负责人：黄岑果
- 是否需要登录：是
- 查询参数：`page`（默认 1）、`page_size`（默认 20，最大 100）
- 成功 data：`{"list": [{"id": 1, "title": "你好", "last_message_time": "2026-09-16T10:00:00", "create_time": "...", "update_time": "..."}], "total": 1, "page": 1, "page_size": 20}`
- 备注：只返回当前用户、未删除的会话，按 `last_message_time`（缺失时用 `create_time`）倒序。

### `GET /api/chat/sessions/{session_id}/messages`

- 负责人：黄岑果
- 是否需要登录：是
- 成功 data：`{"list": [{"id": 1, "session_id": 1, "role": "user", "content": "...", "call_status": "success", "token_count": 6, "create_time": "..."}], "total": 2}`
- 错误码：`4004` 会话不存在或不属于当前用户
- 备注：按消息 ID 升序返回；`call_status` / `token_count` 只对助手消息有意义。

## 4. 健康检查

### `GET /health`、`GET /api/chat/ping`

- 健康检查白名单放行；`ping` 用于验证网关注入的 `X-User-Id`、`X-User-Name`、`X-Request-Id` 透传。

## 5. 错误码

| code | message | 触发场景 | 号段 |
|---|---|---|---|
| 1001 | 未认证或登录已过期 | 缺 `X-User-Id`，或它不是正整数 | 1xxx |
| 2001 | 参数不符合 Schema | 必填缺失、`messages` 为空、角色非法（基座统一处理） | 2xxx |
| 3001 | 积分不足 | `/internal/user/check` 返回，执行能力之前拦截 | 3xxx |
| 4002 | 下游服务暂不可用 | 服务发现失败或内部调用异常（基座统一处理） | 4xxx |
| 4003 | 系统内部错误 | 未预期异常、数据库不可用（基座统一处理） | 4xxx |
| 4004 | 会话不存在或不属于当前用户 | `session_id` 非本人会话或已软删除 | 4xxx |
| 5001 | 模型超时（已降级） | 请求模型超过 `MODEL_TIMEOUT`，返回兜底话术 | 5xxx |
| 5002 | 模型返回异常（已降级） | 连接失败、非 2xx、响应结构不合法 | 5xxx |

> `5001` / `5002` 通过响应体的 `error_code` 字段返回，HTTP 与业务 `code` 仍为成功（`code=0`），因为闭环已按指南 3.4 降级兜底。

## 6. 配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ENABLE_INTERNAL_CHAIN` | `true` | 是否启用 user/billing 内部链路；单独调试 Mock 时可设为 `false` |
| `USE_MOCK` / `MODEL_BASE_URL` / `MODEL_API_KEY` | `true` / 占位地址 / `replace-me` | 由 Nacos `ai-chat-service-model.json` 热更新，`.env` 为安全回退 |
| `MODEL_TIMEOUT` | `30` | 单次模型调用超时（秒） |
| `MODEL_MAX_TOKENS` | `1024` | 请求模型的 `max_tokens` |
| `DEFAULT_SYSTEM_PROMPT` | 中文助手提示词 | 未显式传 system 消息时注入 |
| `DEFAULT_TEMPERATURE` | `0.7` | 请求未显式传 temperature 时的默认值 |
| `POINTS_COST` | `1` | 每次成功对话扣减的积分（降级为 0） |

禁止提交真实 `.env`、模型 Key 与 Token。

## 8. Pro 能力执行契约（现行）

调用方仍使用 `POST /api/chat/completions`，统一响应为 `code/message/data/requestId`。

聊天请求：

```json
{"capability_id":1,"input":{"messages":[{"role":"user","content":"你好"}]}}
```

摘要请求：

```json
{"capability_id":2,"input":{"text":"待概括的材料","max_length":200}}
```

- `capability_id` 必须是正整数，兼容旧请求时缺省为 1；旧顶层 `messages` 仍可用，但必须重新读取目录，不绕过状态/Schema/价格。
- `input` 与非空顶层 `messages` 互斥；`stream=true`、请求中的价格/URL 等未知字段均返回 `2001`。
- 聊天仅接受 1–40 条消息，最后一条须为 user；单条内容 1–12000 字符。摘要接受非空白 `text`（≤12000）和整数 `max_length`（30–1000，缺省 200）。摘要不接受 `session_id`，每次保存独立会话。
- 执行顺序：验证身份 → 新鲜目录快照 → online/code/Schema/执行器输入校验 → 按目录价检查积分 → 会话归属/消息落库 → 模型/Mock → 助手落库 → 计量收据核对 → 本地提交。
- allowlist 只有 `chat-completions`、`long-summary`；未知 code 返回 `2008`。目录中的 service/path/URL 不参与执行目标选择。
- Schema 使用 JSON Schema Draft 2020-12；限制结构大小、深度，禁止 `$ref`、动态引用和 `$id`，不允许 Schema 触发远程读取。目录 Schema 无效为 `4002`；输入不匹配为 `2001`。
- 默认 `CAPABILITY_CATALOG_MODE=internal`，经 `call_internal` 读取 `GET /internal/capability/{id}`。要求返回 `id/code/status/param_schema/price_per_call`；缺失、类型错误、ID 不符、依赖异常均失败关闭，绝不自动切换数据来源。
- 显式 `CAPABILITY_CATALOG_MODE=market` 用于内部接口尚未交接的本地兼容联调，仅经服务发现读取已存在、固定路径的 `GET /api/capability/market/{id}`。该端点只返回 online 记录；404/业务 2002 不可执行。此模式不是内部详情接口已验收的证据。
- 计量上报包含 `capability_id`、`unit_price`、`points`、用户 ID、requestId、状态、模型、耗时。`points` 为目录价；降级为 0，单价仍保留真实目录价。现有 billing 使用 `points` 持久化 cost，新增 `unit_price` 的独立存储由其负责人扩展。
- user 预检必须回传相符 user_id、正常状态、余额、points_cost 和 available；billing 收据必须匹配 requestId/user_id/capability_id/cost/status，否则不能报成功。
- `ENABLE_INTERNAL_CHAIN=false` 只供测试，仍执行目录/Schema 校验；响应标记 `billing_status=not_reported`，不能作为计费通过证据。

成功 data 保留原 OpenAI/会话字段，新增：

```json
{"capability_id":2,"capability_code":"long-summary","price_per_call":3,"cost":3,
 "request_id":"与外层requestId及响应头相同","record_id":12,"billing_status":"recorded",
 "catalog_source":"internal"}
```

`GET /api/chat/executors`（需要登录）返回 `codes`、`input_schemas`、`catalog_mode`，供调试台识别已实现的执行器；不表示目录中的所有能力都可用。

本地消息事务失败会回滚。远端扣分/billing 已提交而本地最终 commit 失败时，不能声称全局回滚，须按 requestId 对账；不得盲目重试模型或宣称分布式事务原子性。

Gateway 冻结的兑换入口为精确 `POST /api/user/apikeys/exchange`；每个直接连接地址每分钟最多 10 次，响应禁止缓存。role 只来自已验证签名 JWT，`X-User-*`、role 别名及客户端 requestId 被替换。管理实时授权、Key 校验/TTL 仍由相关服务负责人实现。

## 7. 测试数据

- `sql/01_init.sql`：建表脚本，重复执行安全；
- 会话与消息由对话接口真实产生（`user_id` 为演示用户 `1`）；
- 测试用例使用固定用户 990001 / 990002，覆盖落库、会话续接、越权 `4004`、内部链路顺序与降级不计费，用例前后物理清理，不影响演示数据。

# AICapabilityHub Pro · 能力执行接口契约

负责人黄岑果；服务 ai-chat-service，端口 8090，独立 ai_chat_db。三人业务集成基线main `651275b`，CI `39420321602` 为9/9。规则见 [Pro 开发指南](../../AICapabilityHubPro-开发指南.md)与[共享契约](pro-shared.md)；本页已将旧聊天说明与 Pro 规则统一，不存在两套相反的计价/执行顺序。

## 0. HTTP 与身份

统一 Result：code、message、data、requestId。业务错误通常 HTTP 200，网关认证 401、隔离 403、限流 429。业务字段 snake_case；data.request_id 与统一 requestId、网关响应头、内部账单相同。

/api/chat/** 经 Gateway 需 JWT，只有 health 公开；ping 需认证。服务读取可信 X-User-Id/Name/Request-Id，不重复解析 JWT。用户ID须正整数，历史按当前用户隔离。服务端口不是公开认证入口。

## 1. 数据所有权

| 表 | 主要字段 | 行为 |
|---|---|---|
| t_chat_session | id、user_id、title、last_message_time、create_time/update_time/is_deleted | 当前用户未删除会话，按活跃时间排序 |
| t_chat_message | id、session_id、user_id、role、content、call_status、token_count、通用字段 | 本轮用户/助手消息，按 id 顺序 |

实际 DDL 以 sql/01_init.sql 为准。Schema/能力 ID/费用在调用与 billing 收据中返回，本轮没有给聊天表新增持久化能力/单价列。摘要每次新建会话，不复用 session_id。

## 2. 调用请求

POST /api/chat/completions：

```json
{"capability_id":1,"input":{"messages":[{"role":"user","content":"你好"}]},"model":"mock-model","temperature":0.7,"stream":false}
```

```json
{"capability_id":2,"input":{"text":"待概括的材料","max_length":200}}
```

| 字段 | 规则 |
|---|---|
| capability_id | 正整数，兼容旧请求时缺省 1 |
| input | 与非空顶层 messages 互斥，对应能力 Schema |
| session_id | 可选正整数，只用于当前用户聊天续接；摘要禁止 |
| model | 1–128 字符，默认 mock-model |
| temperature | 0–2，默认 0.7；聊天 input 可提供 adapter 支持的同名参数 |
| stream | 当前只允许 false；true 返回 2001 |
| 未声明顶层字段 | 客户端 price/URL 等拒绝，不决定执行目标 |

旧顶层 messages 请求保持兼容，但仍映射能力1并重查目录；不能以兼容形式绕过状态、Schema、登记价。

## 3. 执行器与输入

| code | input 规则 | 行为 |
|---|---|---|
| chat-completions | messages 1–40；role system/user/assistant；单条 content 1–12000；末条为 user；可选 temperature 0–2 | 聊天，无 system 时可注入默认提示 |
| long-summary | text 非空白 ≤12000；max_length 严格整数30–1000，默认200 | 独立摘要提示与 text 映射；拒绝 session_id |

目录 Schema 需 object，使用内联 Draft 2020-12，大小≤32768、深度≤20、节点≤2000；引用 $ref/$dynamicRef/$recursiveRef/$id 均禁止。输入序列化大小≤65536，再通过 adapter 强类型/长度约束。目录 Schema 无效为4002，输入不符合为2001。不执行目录 service/path 或用户任意 URL。

Mock 聊天使用模拟话术；Mock 摘要从输入提取并明确 mock=true，不访问模型接口。真实模式经过模型客户端，模型超时/响应异常转换为降级结果，不把 HTTP 替身测试冒称真实供应商验收。

## 4. 执行顺序与响应

身份 → 最新目录 → online/code/Schema/adapter → 目录价积分预检 → 会话归属/用户消息 → 模型或Mock → 助手消息 → billing收据 → 本地提交。

成功 data：

```json
{
  "id":"chatcmpl-example","object":"chat.completion","created":1792368000,
  "model":"mock-model",
  "choices":[{"index":0,"message":{"role":"assistant","content":"结果内容"},"finish_reason":"stop"}],
  "usage":{"prompt_tokens":4,"completion_tokens":10,"total_tokens":14},
  "session_id":1,"message_id":2,"mock":true,"call_status":"success",
  "degraded":false,"error_code":null,"duration_ms":12,
  "capability_id":2,"capability_code":"long-summary","price_per_call":3,
  "cost":3,"request_id":"same-id","record_id":12,
  "billing_status":"recorded","catalog_source":"market"
}
```

prompt_tokens 当前按传入有效消息字符数估算，completion_tokens 沿用模型返回或模拟估算，不是独立的精确 token 计量标准。

远端 user/billing 不是同一个 DB 事务。本地异常回滚消息；远端已成功、本地最终提交失败须按 requestId 对账，不能宣称全局回滚或自动重试模型。

## 5. 会话与执行器发现

| 方法/路径 | 参数与返回 | 约束 |
|---|---|---|
| GET /api/chat/sessions | page默认1、page_size默认20/最大100；list/total/page/page_size | 当前用户，活跃时间倒序 |
| GET /api/chat/sessions/{session_id}/messages | list/total，消息 id 顺序 | 不存在/他人/软删除会话同4004 |
| GET /api/chat/executors | codes、input_schemas、catalog_mode | 需登录；列出已实现代码，不保证所有登记能力可执行 |
| GET /health | data.status=UP | 公开，只是应用健康 |
| GET /api/chat/ping | 透传身份与追踪 | 需网关认证 |

## 6. 配置

| 配置 | 当前默认/行为 |
|---|---|
| CAPABILITY_CATALOG_MODE | internal，显式 market 供旧目录兼容联调 |
| CAPABILITY_SERVICE_NAME | capability-service |
| ENABLE_INTERNAL_CHAIN | true；false 只关闭 user/billing，仍查目录/校验；结果 not_reported |
| USE_MOCK / MODEL_BASE_URL / MODEL_API_KEY | 环境回退或 Nacos 模型快照，凭据不打印 |
| NACOS_MODEL_CONFIG_ENABLED | AI 默认 true，热更新仅 use_mock/base_url/api_key |
| MODEL_TIMEOUT / MODEL_MAX_TOKENS | 30秒 / 1024，以当前配置为准 |
| DEFAULT_SYSTEM_PROMPT / DEFAULT_TEMPERATURE | 默认提示 / 0.7；摘要有专用提示 |
| POINTS_COST | 仅历史配置兼容，Pro 不据此定价 |

## 7. 错误与验收

| code | 行为 |
|---|---|
| 1001 / 1005 | 缺少可信身份 / 账号禁用等拒绝 |
| 2001 | 输入、Schema实例或adapter不兼容 |
| 2002 | 能力未知、删除、草稿、下架 |
| 2008 | code 没有受支持执行器 |
| 3001 | 初始积分不足，模型不执行 |
| 4002 | 目录/user/billing不可用或响应/收据无效 |
| 4003 / 4004 | 未处理系统异常 / 会话不存在或越权 |
| 5001 / 5002 | 成功结果的 error_code，degraded=true、cost=0 |

新增测试覆盖目录刷新、价格改变、状态/输入拒绝前模型次数为0、禁用、收据字段、回滚、真实HTTP模型故障和会话越权。AI用例56项、集成四服务共369项零跳过；具体提交与新增页面覆盖见[收尾记录](../验收收尾记录-2026-10-20.md)。数据库夹具会清测试用户，必须使用独立实例并严格核验JUnit零跳过。

## 8. Pro 服务交接与兼容契约

本节保留既有“第8节”引用，现行全部章节已经统一适配 Pro。

- 默认内部客户端 GET /internal/capability/{id}，要求 id/code/status/param_schema/price_per_call；目录服务端已交付并通过完整internal真实链；缺失/格式异常仍失败关闭，不自动回退。
- 显式 market 使用服务发现后的固定 /api/capability/market/{id}，只允许已上架详情；API 2002不可执行。通过此路径不代表内部详情端点已验收。
- user预检 GET /internal/user/check 传 user_id/points_cost；必须返回匹配ID、normal、整数余额与价格、available=true。
- billing POST /internal/billing/record 传 capability_id、unit_price、points、request_id、user_id、service_name、model、status、duration_ms。正常points=目录价，degraded=0；unit_price始终登记价，billing已在main独立存储并兼容旧调用NULL。
- billing收据正record_id、request_id/user_id/capability_id/cost/call_status必须一致；未上报时 billing_status=not_reported，不能计费验收。
- user角色/Key exchange、billing实时授权和capability接入已集成main并完成真实联调，见[共享契约](pro-shared.md)。用户确认授权不足使用1006，Key不存在保留同码，按端点及消息区分。
- 市场入口固定 /chat?capability_id=<id>；Chat 与市场按钮已在10/20前端调整中接通。视觉等未支持能力不应显示可体验。
- 内部服务就绪后运行严格 --catalog-mode internal --browser，必须实际取得 member_internal_contract_verified=true；目前 market 模式与内部失败关闭的通过不能代替它。


## 9. 本轮增量：C1 token 用量 / C2 计价 / A1 事务边界

### 9.1 响应新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `usage.prompt_tokens` | int | 上游 `usage.prompt_tokens`（Responses 为 `input_tokens`），**不再用字符数** |
| `usage.completion_tokens` | int | 上游 `usage.completion_tokens`（Responses 为 `output_tokens`） |
| `usage.total_tokens` | int | 两者之和，可与上游控制台逐项对上 |
| `usage_source` | string | `upstream` / `mock` / `missing`，调用方可据此判断能否用于核算 |
| `billing_mode` | string | 本次调用采用的计价模式 |

旧字段（`price_per_call`、`cost`、`record_id`、`billing_status`、`call_status` 等）保持不变。

### 9.2 token 缺失的失败关闭

- `per_call` 能力：上游没有 usage 只影响 `usage` 展示，**金额不变**（仍按 `price_per_call`）。
- `per_token` 能力：上游缺 usage 或 `usage_source != upstream`（含 Mock）时返回 **`5002`**，且**不产生账单**——不允许按 0 元记账，也不允许编造 token 数。
- Mock 模式 `usage_source='mock'`，token 数为估算值（约 2 字符 1 token），仅用于开发与测试。

### 9.3 事务边界（A1）

执行链拆成三段：

1. 目录读取 + 余额预检（不占数据库连接）；
2. **事务 1**：建/取会话 + 写用户消息 → `commit`；
3. 模型调用（**不持有数据库连接**）；
4. **事务 2**：写助手消息 + 上报账单 → `commit`。

失败语义：

| 场景 | 落库结果 | 对外 |
|---|---|---|
| 模型降级 | 助手消息 `call_status=degraded`，`cost=0` | `code=0` + 兜底话术 |
| 模型硬异常 | 用户消息保留 + 一条 `failed` 占位消息（`error_code=4003`） | `4003` |
| 账单失败 | 用户消息保留 + 一条 `failed` 占位消息（`error_code` 为账单错误码） | 对应错误码 |

`t_chat_message.error_code` 为本轮新增列（`sql/02_add_message_error_code.sql`），仅失败占位消息写入。


## 10. 本轮增量：D1 供应商 / D2 执行器 / D4 参数与容错

### 10.1 供应商管理（`/api/chat/providers`，仅管理员）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/chat/providers` | 列表，**只返回 `api_key_mask`**，永不返回明文/密文 |
| POST | `/api/chat/providers` | 登记；**固定为草稿态**，别名重复 `2006`，地址不安全 `2001` |
| PUT | `/api/chat/providers/{id}` | 编辑；`api_key` 为空表示不轮换，换密钥会退回草稿并清空测通时间 |
| POST | `/api/chat/providers/{id}/test` | 连通性测试，返回 `{ok, reason, http_status, elapsed_ms}` |
| PUT | `/api/chat/providers/{id}/status` | `draft`/`enabled`/`disabled`；**未测通直接启用返回 `2001`** |

`t_model_provider`（`ai_chat_db`）：`name / alias / protocol / base_url / api_key_cipher /
api_key_mask / default_model / timeout_ms / extra_json / status / last_test_ok_at`。
`api_key_cipher` 为 `v1:<nonce_b64>:<cipher_b64>`（AES-256-GCM），主密钥 `PROVIDER_MASTER_KEY_V1`
（base64 32 字节）**只在 ai-chat 内存**，缺失时失败关闭。

地址防护（保存与每次调用前都校验）：只允许 https；域名必须在 `PROVIDER_ALLOWED_HOSTS`
（逗号分隔，支持 `*.example.com`，为空则全拒）；解析后拒绝 `10/8`、`172.16/12`、`192.168/16`、
`127/8`、`169.254/16`、`0.0.0.0/8`、`100.64/10`、`::1`、`fc00::/7`、`fe80::/10`；不跟随重定向。

> 已知限制：校验与建连之间仍有极短 TOCTOU 窗口；完全消除需要把连接钉在已校验 IP 上
> （自定义 SNI + 证书校验），本轮未做，已列入后续建议。

内部详情 `GET /internal/provider/{alias}` 只返回 `{alias, protocol, status, default_model}`，
供 capability 在保存阶段做执行器绑定校验。

### 10.2 执行器（D2）

- 能力表 `executor` 取值：`chat` / `summary` / `image-generate` / `embedding`；
  本服务已实现 `chat`、`summary` 两个（`image-generate` 在 D3 落地）。
- `GET /api/chat/executors` 新增 `executors` 与 `executor_protocols`；`codes` 保留给旧前端。
- 判断"暂无执行器"以 `executor ∈ EXECUTORS` 为准，不再看 `code`；`code` 为空执行器时
  保留 `chat-completions → chat`、`long-summary → summary` 的历史兜底。

### 10.3 参数白名单（D4）

`ChatInput` 仍为 `extra="forbid"`，只新增这 8 个可选字段：
`top_p`、`stop`、`seed`、`response_format`、`presence_penalty`、`frequency_penalty`、
`logprobs`、`max_tokens`。未列入白名单的字段照旧 `2001`。

`max_tokens` 实际下发 `min(请求值, 能力.max_output_tokens)`；能力未配置时用全局默认。

### 10.4 错误码细分与重试（D4）

| 上游情况 | 错误码 |
|---|---|
| 429 | `5003` 上游限流 |
| 401 / 402 / 403 | `5004` 上游鉴权或欠费 |
| 5xx | `5005` 上游故障 |
| 超时 | `5001` |
| 响应结构不符 | `5002` |

**只对超时与 5xx 重试一次**（退避 300ms），4xx 不重试。重试发生在计费之前，
一次调用**只产生一条账单、一次扣分**，仍挂同一 `requestId`。

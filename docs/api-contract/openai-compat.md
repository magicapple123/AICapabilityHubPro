# OpenAI 兼容入口契约（/v1）

状态：已实现（2026-10-30）。由 `ai-chat-service` 提供，经 Gateway 的 `/v1/**` 路由对外。

面向只认 OpenAI 协议的客户端（Cherry Studio、Continue、LangChain、OpenAI SDK）。
平台原生接口仍以 `Result{code,message,data,requestId}` 包裹；**本入口不包裹**，
直接返回 OpenAI 结构，避免客户端解析失败。

## 认证

```
Authorization: Bearer sk_xxxxxxxx
```

- `sk_...` 就是平台 API Key 的 **Secret Key**（创建时只显示一次）。
- 服务端只保存 Secret 的 SHA-256 摘要，因此这里对 Bearer 取摘要后，
  通过 `POST /internal/user/apikey/verify` 反查归属用户。
- 该内部接口发生在"知道用户是谁"之前，无法带 `X-User-Id`，改用从共享
  `JWT_SECRET` 派生的服务间令牌 `X-Internal-Token`；令牌未配置时失败关闭。
- `/internal/**` 由 Gateway 对外一律 403，外部无法直接调用。
- Key 被禁用、过期，或账号被禁用时，统一返回 401 `authentication_error`。

## 模型映射

`model` 不是上游模型名，而是平台登记的**别名**，映射到 `capability_id`。运营在能力中填写 `openai_alias` 后，在线且 `executor=chat` 的能力会进入动态目录；下线、软删除或清空别名后不再列出。

| 配置项 | 默认值 |
|---|---|
| `OPENAI_COMPAT_MODEL_MAP` | `deepseek-flash=1,deepseek-chat=1,chat-completions=1` |

`OPENAI_COMPAT_MODEL_MAP` 保留为显式覆盖与兼容配置，覆盖动态目录里的同名别名。静态兼容别名的目标必须仍是在线 chat 能力；因此旧配置可继续服务未填写 `openai_alias` 的既有能力。动态模型目录复用 ai-chat 的 5 秒目录缓存；同一进程的并发冷 miss 使用 single-flight 合并为一次下游读取。`catalog_cache_events_total` 暴露 `models-hit`、`models-miss`、`models-fetch` 事件，可用于核对命中和实际目录回源次数。能力新建、编辑、上下架和删除会通过现有失效接口清缓存，缓存命中时不会逐请求查询 capability-service。

`GET /v1/models` 只返回目标为在线 chat 能力的动态别名和显式兼容别名。新别名在保存后通常立即可见，失效通知不可用时最长等待缓存 TTL（5 秒）。未登记的模型返回 404 `model_not_found`，不做静默兜底——避免"以为调了 A 其实调了 B"。
上游实际使用的模型由平台配置（`MODEL_NAME`）决定，并在响应 `model` 字段回显。

## GET /v1/models

返回已登记的别名，供客户端下拉框使用。

```json
{"object":"list","data":[{"id":"deepseek-flash","object":"model","created":1793356000,"owned_by":"aicapabilityhub"}]}
```

## POST /v1/chat/completions

请求（兼容 `content` 为字符串或分段数组）：

```json
{
  "model": "deepseek-flash",
  "messages": [
    {"role": "system", "content": "回答尽量简短"},
    {"role": "user", "content": "你好"}
  ],
  "temperature": 0.3,
  "stream": false
}
```

响应：

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1793356299,
  "model": "deepseek-flash",
  "choices": [{"index":0,"message":{"role":"assistant","content":"..."},"finish_reason":"stop"}],
  "usage": {"prompt_tokens":30,"completion_tokens":125,"total_tokens":155},
  "platform_request_id": "0cc55534-...",
  "platform_cost": 5
}
```

`platform_request_id` 与 `platform_cost` 是平台附加字段（OpenAI 客户端会忽略），
用于和调用记录、账单、积分流水对账。

## 流式

`"stream": true` 时返回 `text/event-stream`：

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk",...,"delta":{"role":"assistant","content":"完整内容"},"finish_reason":null}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk",...,"delta":{},"finish_reason":"stop"}

data: [DONE]
```

平台不支持增量生成，因此是"一个 chunk + [DONE]"：客户端能正常渲染，
但首字延迟等于整段生成时间。真正的 SSE 增量需要执行器改造，不在本期范围。

## POST /v1/responses（E3）

协议翻译层：`input` / `instructions` / `tools`（仅 function）/ `stream` / `usage`
全部复用平台既有执行链（计费、落库、审计一处不改）。

### 支持范围

| 字段 | 行为 |
|---|---|
| `input`（字符串或 items） | 字符串转 `user` 消息；`input_text` / `output_text` 分段都认；`function_call_output` 转 `tool` 消息 |
| `instructions` | 作为 `system` 消息；**不参与用户消息长度限制**，超过 12000 字符截断并在 `platform_warnings` 说明（整单不失败） |
| `tools` | 仅接受 `type=function`；Responses 的扁平结构 `{type,name,description,parameters}` 在此翻译成 chat 的嵌套结构 `{type:"function",function:{...}}`，执行层只认一种形态；输出 `function_call` 项（`call_id` / `arguments` 齐全），平台不执行工具 |
| `stream` | 见下方事件顺序 |
| `previous_response_id` | **平台支持、非 OpenAI 语义等价**：响应 id（`resp_<session>_<rand>`）里编码了平台会话 id，带上下一次即可续接同一会话；它不是 OpenAI 的服务端响应存储 |

### 流式事件顺序（P12 冻结）

`response.created` → `response.output_item.added` → `response.content_part.added`
→ `response.output_text.delta`（多次）→ `response.output_text.done`
→ `response.output_item.done` → `response.completed` → `data: [DONE]`。

执行期失败（如限流、供应商不可用）补发 `response.failed` + `[DONE]`，不再静默断流；
此时执行链已写 `failed` 占位消息且**不计费**。

### 接受但忽略的字段（P12）

| 字段 / 形态 | 行为 |
|---|---|
| `store: false` | 放行（平台本就不存上游内容，语义一致） |
| `reasoning` | 接受但忽略，`platform_warnings` 里点名字段 |
| `background` | 接受但忽略，`platform_warnings` 里点名字段 |
| `input[]` 里的 `reasoning` 条目 | 跳过不进消息列表，`platform_warnings` 里说明；若忽略后没有可发送内容仍返回 `2001` |

`platform_warnings` 是字符串数组，出现在非流式响应体与流式的
`response.created` / `response.completed` 里（没有可提示项时为空数组）。

### 仍然拒绝的字段（返回 4001，不静默忽略）

| 字段 / 形态 | 结果 |
|---|---|
| `store: true`（服务端存储，与"不存储上游内容"的承诺冲突） | `4001`，message 点名 `store` |
| `tools[].type != "function"`（如 `web_search` / `file_search`） | `4001`，message 点名具体工具类型 |
| `input[]` 里的 `item_reference` / `web_search_call` / `file_search_call` 条目 | `4001`，message 点名条目类型 |

```json
{"error":{"message":"不支持内置工具 web_search：tools[].type 目前只支持 function","type":"invalid_request_error","code":"platform_4001"}}
```

`4001` 是需求指定的业务码；对"字段不支持"这类**请求语义错误**，HTTP 状态固定 **400**
（而不是限流场景的 429），避免客户端按限流失误退避。执行链在拒绝时不产生任何调用与账单。

## 错误映射

| 平台 code | HTTP | OpenAI type |
|---|---|---|
| 1001 / 1003 / 1005 | 401 | `authentication_error` |
| 2001 / 2008 | 400 | `invalid_request_error` |
| 2002（模型未登记或能力下线） | 404 | `model_not_found` |
| 3001（积分不足） | 402 | `insufficient_quota` |
| 4001（`/v1/responses` 不支持字段） | 400 | `invalid_request_error` |
| 4001（网关 / 服务内限流） | 429 | `rate_limit_exceeded` |
| 其它 | 500 | `api_error` |

```json
{"error":{"message":"积分不足","type":"insufficient_quota","code":"platform_3001"}}
```

## 与原生接口的差异

- 每次请求独立计费（按能力目录价）；`/v1/chat/completions` 不维护多轮会话 ID，客户端需自行带上历史 `messages`。
  `/v1/responses` 可用 `previous_response_id` 续接平台会话（见 E3 章节）。
- `/v1/chat/completions` 仍不支持 `tools` / `response_format` / `logprobs`，传入会被忽略；
  `/v1/responses` 的 `tools` 只支持 function 类型，其它类型返回 4001。
- `max_tokens` / `max_output_tokens` 的上限由平台配置 `MODEL_MAX_TOKENS` 与能力 `max_output_tokens` 约束。
- 模型降级（上游超时/坏响应）时仍返回 200 与兜底话术，`platform_cost=0`，
  与原生接口的 `degraded` 语义一致。

## 验证

```bash
python -m pytest services/ai-chat-service/tests/test_openai_compat.py -q
python -m pytest services/user-service/tests/test_internal_apikey.py -q
```

真实链路（本机）已覆盖：模型列表、非流式、流式、计费与账单一致性。

### P11 上游模型选择（2026-11-03）

平台 `/api/chat/completions` 的显式 `model` 优先于绑定供应商的 `default_model`；只有未绑定供应商时才回退全局 `MODEL_NAME`。绑定供应商但两者均为空时返回 `4002`，明确提示补默认模型，不静默发送全局名称。`/v1` 的 `model` 是平台能力别名，只用于解析能力，绝不作为上游模型名。相同规则适用于 chat、summary 与流式；图片仍由图片供应商配置决定。供应商编辑页在默认模型为空时给出调用限制提示。

### P1 供应商状态与错误码（2026-11-03）

`2008` 只表示执行器未实现，原文案保留。`2009` 表示绑定供应商不存在、未启用或被停用；运行期点名alias，OpenAI/Responses兼容层映射为HTTP503、type=api_error、code=platform_2009。保存绑定时仅接受enabled供应商，draft/disabled返回2001并提示先测试启用，状态缺失按4002失败关闭。供应商变更不改变一次调用一条账单、失败不扣分的口径。无新增表字段或接口。

### P6 兼容层 Key 归因（2026-11-03）

`/v1/**` 用 `Bearer sk_...` 认证时，`/internal/user/apikey/verify` 返回的 `key_id` 会写进 `UserContext.api_key_id`，账单 `entrypoint=openai_compat`；这是管理员"某把 Key 调过什么"的唯一来源，缺失时账单为 `NULL`，不会伪造为 0。`/v1/models` 与 `/v1/responses` 共用同一解析入口与同一份"在线 chat 别名"过滤。平台 API 走 `/api/**` 时由 exchange JWT 的 `key_id` claim 经网关注入 `X-User-Key-Id`，`entrypoint=platform_api`；网页调试台无 Key 身份，`entrypoint=web`。

### P3 兼容层错误文案（2026-11-03）

把 exchange 换来的 JWT 填进 `/v1/**` 仍然返回 `1003`（`_bearer` 只认 `sk_` 前缀）；设置页与「使用方法」抽屉必须明确写出"Secret 用于 `/v1`、JWT 用于 `/api`，两者不可互换"，避免用户误判 Key 建错。`/v1/models` 的别名清单与 `GET /api/capability/models` 过滤口径一致（online + chat + alias 非空）。

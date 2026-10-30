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

`model` 不是上游模型名，而是平台登记的**别名**，映射到 `capability_id`：

| 配置项 | 默认值 |
|---|---|
| `OPENAI_COMPAT_MODEL_MAP` | `deepseek-flash=1,deepseek-chat=1,chat-completions=1` |

未登记的模型返回 404 `model_not_found`，不做静默兜底——避免"以为调了 A 其实调了 B"。
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

## 错误映射

| 平台 code | HTTP | OpenAI type |
|---|---|---|
| 1001 / 1003 / 1005 | 401 | `authentication_error` |
| 2001 / 2008 | 400 | `invalid_request_error` |
| 2002（模型未登记或能力下线） | 404 | `model_not_found` |
| 3001（积分不足） | 402 | `insufficient_quota` |
| 4001（网关限流） | 429 | `rate_limit_exceeded` |
| 其它 | 500 | `api_error` |

```json
{"error":{"message":"积分不足","type":"insufficient_quota","code":"platform_3001"}}
```

## 与原生接口的差异

- 每次请求独立计费（按能力目录价），不维护多轮会话 ID；客户端需自行带上历史 `messages`。
- 不支持 `tools` / `function_call` / `response_format` / `logprobs`，传入会被忽略。
- `max_tokens` 不生效，输出上限由平台配置 `MODEL_MAX_TOKENS` 决定。
- 模型降级（上游超时/坏响应）时仍返回 200 与兜底话术，`platform_cost=0`，
  与原生接口的 `degraded` 语义一致。

## 验证

```bash
python -m pytest services/ai-chat-service/tests/test_openai_compat.py -q
python -m pytest services/user-service/tests/test_internal_apikey.py -q
```

真实链路（本机）已覆盖：模型列表、非流式、流式、计费与账单一致性。

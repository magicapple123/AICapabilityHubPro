# Pro 共享接口与身份、Schema、计量约定

负责人：三人共同维护；更新日期 2026-10-19。统一响应为 `code/message/data/requestId`。本文件区分 **已实现** 和 **新增约定、待实现**；后者来自团队任务交接，不因写入文档而自动成为可调用接口。

## 1. 通用规则

- 浏览器只访问 Gateway `/api/**`；服务内部路径 `/internal/**` 不对外开放，使用现有 `call_internal`，不跨库。
- 外部 requestId 由 Gateway 生成；同一链中内部 request_id、结果 data.request_id、账单与积分流水保持一致。
- Gateway 的签名 role 不能替代当前数据库授权；管理操作需实时校验，依赖异常失败关闭。
- 业务通常 HTTP 200 + code；网关 401/403/429 依现有语义。未知/格式不符的授权结果不能当作成功。

## 2. 当前授权约定（新增，user 服务端与业务调用侧待实现）

`GET /internal/user/authorization?user_id=<当前用户ID>&required_role=admin`

提供方 user-service；调用方 capability/billing。请求带当前链路 X-User-Id、X-User-Name、X-Request-Id。user_id 必须与调用身份一致，授权检查查询数据库当前状态与角色，不只依赖 JWT 声明。

成功：

```json
{"code":0,"message":"success","data":{"user_id":1,"status":"normal","role":"admin","authorized":true},"requestId":"same-id"}
```

| 条件 | 约定 code | 调用侧 |
|---|---|---|
| 链路身份缺失/不匹配 | 1001 | 拒绝 |
| 不存在/禁用账号 | 1005 | 拒绝 |
| 正常普通用户，不满足 admin | 1007（新增） | capability 对外可映射 2007，拒绝写/运营读取 |
| 超时、缺失端点、格式/用户ID错误 | 4002 | 失败关闭，不继续管理操作 |

只有 code=0、匹配 user_id、normal、admin、authorized=true 同时成立才授权；不允许本地用户白名单或前端隐藏按钮替代。**1006 已被当前 user 实现用于“API Key 不存在”，继续保留；此前 AI 提示词建议的权限码 1006 在本次代码核对后纠正为 1007。两位成员使用本文最新版，不照抄旧提示词。** 发现其他已确认契约冲突时先协商同步，不各自换路径。

## 3. 能力内部详情（AI 调用侧已实现，capability 服务端待交接）

`GET /internal/capability/{capability_id}` 返回 data：

```json
{"id":1,"name":"多轮对话","code":"chat-completions","status":"online","param_schema":{"type":"object","properties":{"messages":{"type":"array"}},"required":["messages"]},"price_per_call":5}
```

id 为匹配请求的正整数，价格为 0–1000000 整数，Schema 为对象。不存在/软删除返回 2002；如内部返回 draft/offline，必须如实标明，AI 在模型前拒绝。公开市场只返回 online，不泄露草稿存在性或 service/path。

默认 internal 无缓存读取且失败关闭。显式 market 只访问服务发现后的固定公开详情 `/api/capability/market/{id}`，不自动回退，不是内部契约已完成的证据。

## 4. 执行器与 Schema（已实现）

| code | input | 行为 |
|---|---|---|
| chat-completions | messages：1–40 条，role system/user/assistant，content 1–12000；最后一条 user；可选 temperature 0–2 | 多轮聊天 |
| long-summary | text 非空白 ≤12000；max_length 可选严格整数 30–1000，默认 200 | 单次摘要，不接受 session_id |

JSON Schema 使用内联 Draft 2020-12，不含 `$ref/$dynamicRef/$recursiveRef/$id`。目录校验后仍要通过 adapter 的强类型规则；未实现 code 返回 2008，未知/下架 2002，输入不匹配 2001，目录配置异常 4002。

市场体验入口约定 `/chat?capability_id=<id>`：调试台已接受，市场按钮待夏思凯改造。视觉/语音等没有执行器，不得宣传可体验。

## 5. 积分与计量（已有主链，unit_price 存储待扩展）

AI先GET /internal/user/check，params为可信上下文user_id和目录价points_cost，已核对返回user_id/status/balance/points_cost/available。user当前路由只检查必要链路头，尚需自行比较query.user_id与调用者，文档不将此缺口标成已验收。

执行后 `POST /internal/billing/record`：

```json
{"request_id":"same-id","user_id":1,"capability_id":2,"service_name":"ai-chat-service","model":"mock-model","unit_price":3,"points":3,"status":"success","duration_ms":12,"remark":"long-summary price=3"}
```

unit_price 为目录登记价，points 为实际收费；降级 points=0，单价仍保留。现有 billing 接受 capability_id/points，忽略额外 unit_price，不独立存储该字段；黄禹菲需提供兼容扩展与迁移，不能把当前状态写成已持久化单价。

AI 必须核对正 record_id、request_id/user_id/capability_id/cost/call_status，否则不返回成功。billing 幂等比较用户、服务、能力、费用和状态；浏览器重发是新 requestId，不能等同于内部账单重放。

## 6. API Key 兑换（Gateway 配套已有，user 服务端待实现）

精确 `POST /api/user/apikeys/exchange`。请求体的凭证字段应复用当前创建接口的 access_key/secret 语义，黄禹菲在实现时冻结字段、有效期配置和硬性上限，并同步 user 契约；未实现前不提供虚构 curl 成功示例。

Gateway 已提供匿名 POST、10 次/直接地址/分钟和 no-store。user 需校验 secret 摘要、所有者、当前账号、Key 状态/过期，role 和 TTL 来自服务端；secret/hash 不进入列表/日志，secret 只创建时展示一次。

## 7. 事务、迁移与验收

每服务本地事务不是分布式原子提交。远端扣分/账单成功但 AI 最终提交失败需按 requestId 对账，不盲目重试模型。增量迁移保留旧数据，历史未知单价不可伪造；SQL seed 仅供新环境/明确的隔离示例库。

各接口分别留正常/拒绝/故障与字段一致性测试；严格 internal E2E 必须实际通过并标记 member_internal_contract_verified=true。当前市场兼容链已经通过，不能据此标记角色/Key/内部详情已交付。

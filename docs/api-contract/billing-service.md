# AICapabilityHub Pro · billing-service 接口契约

**实现状态（2026-10-20，PR #4已合入main `651275b`）：** 已实现 nullable unit_price 存储、查询、迁移和实时管理员统计授权；兼容既有 AI 上报字段。规则见 [Pro 开发指南](../../AICapabilityHubPro-开发指南.md)与[共享契约](pro-shared.md)。

> 负责人：黄禹菲
> 服务名：`billing-service`
> 数据库：`billing_db`
> 端口：8083
> 上游依赖：user-service 的 `/internal/user/check` 与 `/internal/user/points/deduct`；实时 `/internal/user/authorization`，禁止读取 user_db。

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401。

## 0. 通用约定

- **登录要求**：`/api/billing/records`、`/api/billing/usage`、`/api/billing/stat/overview`、`/api/billing/admin/**` 均需要网关 JWT；`/health` 不需要。本服务无白名单业务接口。
- **内部接口**：`/internal/billing/record` 只允许其它后端服务经基座 `call_internal` 调用。网关对外部访问 `/internal/**` 一律 403；本服务另校验 `X-User-Id`（身份，必须等于 body 的 `user_id`）与 `X-Request-Id`（幂等键，必须等于 body 的 `request_id`）。
- **身份来源**：从网关注入的 `X-User-Id` / `X-User-Name` / `X-Request-Id` 读取，服务内不重复解析 JWT。
- **账号状态校验**：网关只校验 JWT 签名与有效期，**不知道账号是否已被禁用**，因此被禁用账号在 Token 过期前仍能通过网关。billing-service 没有 `user_db` 的访问权（禁止跨库），个人查询通过 `/internal/user/check`（`points_cost=0`）确认账号仍可用，全局统计通过实时 authorization 校验当前管理员身份：被禁用返回 `1005`，user-service 不可用返回 `4002`。校验放在参数校验之后，确保 `2001` / `1001` 的错误优先级稳定。
- **数据隔离**：`records` / `usage` 只返回当前用户自己的数据；`stat/overview` 为运营全局统计。
- **分页格式**：`data = {"list": [...], "total": 100, "page": 1, "page_size": 10}`；`page_size` 默认 10、最大 100。
- **统计时间范围**：`start_date` / `end_date` 为 `YYYY-MM-DD`，**含当天**。缺省回看最近 30 天（含今天）；跨度上限 366 天；`start_date > end_date` 或超跨度按参数错误处理。`today` 取服务器本地日期（容器 TZ = Asia/Shanghai），与 `t_usage_daily.stat_date` 口径一致。
- **软删除**：`t_call_record` 默认过滤 `is_deleted=0`；`t_usage_daily` 只累加、不软删除。
- **金额语义**：`cost` / `total_cost` 为整数积分数，不使用浮点（Pro开发指南第9节）。
- **时间格式**：`create_time` 返回 `YYYY-MM-DD HH:MM:SS`（Asia/Shanghai）；`stat_date` / `start_date` / `end_date` 返回 `YYYY-MM-DD`。
- **日志脱敏**：日志带 `requestId`，不打印模型 Key、Token 或用户口令。

## 1. 数据字典

### `t_call_record`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `request_id` | VARCHAR(64) | NOT NULL | **幂等键**，全链路 requestId，未删除范围内唯一 |
| `user_id` | BIGINT | NOT NULL, INDEX | 调用用户 |
| `capability_id` | BIGINT | NOT NULL DEFAULT 0 | Pro 新调用传真实能力 ID；0 仅保留历史未关联/旧调用方兼容含义 |
| `service_name` | VARCHAR(64) | NOT NULL DEFAULT '' | 承载调用的服务名，如 `ai-chat-service` |
| `unit_price` | BIGINT | NULL | 登记单价；历史未知为 NULL，不从 cost 推断 |
| `cost` | BIGINT | NOT NULL DEFAULT 0 | 本次消耗积分（整数） |
| `billing_mode` | VARCHAR(16) | NOT NULL DEFAULT 'per_call' | C2：`per_call` / `per_token` / `per_unit` |
| `prompt_tokens` | INT | NOT NULL DEFAULT 0 | C1：输入 token，取自上游 `usage.prompt_tokens`（Responses 为 `input_tokens`）；旧行为 0 |
| `completion_tokens` | INT | NOT NULL DEFAULT 0 | C1：输出 token，取自上游 `usage.completion_tokens`（Responses 为 `output_tokens`）；旧行为 0 |
| `token_source` | VARCHAR(16) | NOT NULL DEFAULT 'unknown' | C1：`upstream`（上游真值）/`mock`（本地模拟）/`missing`（上游未给）/`unknown`（历史未记录） |
| `units` | INT | NOT NULL DEFAULT 1 | C2：按件计费的数量（张/次），其余模式为 1 |
| `images` | JSON | NULL | D3：图片产物 `[{url, revised_prompt}]`；非文生图与历史行为 NULL，出参统一归一为空数组 |
| `call_status` | VARCHAR(16) | NOT NULL DEFAULT 'success' | `success` / `degraded` / `failed`（Pro统一调用状态） |
| `duration_ms` | INT | NOT NULL DEFAULT 0 | 调用耗时，缺省 0 |
| `model_name` | VARCHAR(128) | NOT NULL DEFAULT '' | 模型名；Mock 模式为请求中的 `model` |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

### `t_usage_daily`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `stat_date` | DATE | NOT NULL, INDEX | 统计日期（Asia/Shanghai） |
| `user_id` | BIGINT | NOT NULL, INDEX | 调用用户 |
| `capability_id` | BIGINT | NOT NULL DEFAULT 0 | 能力 ID，0 含义同上 |
| `call_count` | BIGINT | NOT NULL DEFAULT 0 | 当日调用次数 |
| `total_cost` | BIGINT | NOT NULL DEFAULT 0 | 当日消耗积分合计 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

**索引**：
- `t_call_record`：`UNIQUE(request_id, is_deleted)` 保证记账幂等；`INDEX(user_id, is_deleted, create_time)` 支撑个人明细分页；`INDEX(service_name, is_deleted, create_time)` 支撑按服务统计。
- t_usage_daily的UNIQUE(stat_date,user_id,capability_id)支撑原子累加，不含is_deleted。capability_id当前非空，0仅历史兼容；Pro新请求使用实际能力ID，避免NULL破坏唯一聚合语义。

> 实际请求/表映射为model→model_name、points→cost、status→call_status，以当前Schema与sql/01_init.sql为准，旧附录不覆盖实现。

## 2. 内部记账接口（服务间调用）

### `POST /internal/billing/record`

- 负责人：黄禹菲
- 调用方：`ai-chat-service`
- 是否需要登录：**不经网关对外暴露**（网关外部访问 `/internal/**` 返回 403）
- 请求头：`X-User-Id`（必填，等于 body 的 `user_id`）、`X-Request-Id`（必填，等于 body 的 `request_id`）
- 请求体（与 ai-chat 的实际上报一致）：

```json
{
  "request_id": "b3f1...c2",
  "user_id": 1,
  "service_name": "ai-chat-service",
  "model": "mock-model",
  "points": 5,
  "unit_price": 5,
  "status": "success",
  "capability_id": 1,
  "duration_ms": 12,
  "remark": "",
  "billing_mode": "per_call",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "token_source": "unknown",
  "units": 1
}
```

C1/C2 新增字段全部有默认值，**旧调用方只发原有字段时行为与改造前完全一致**（`billing_mode` 缺省 `per_call`）。按 token 计费时还应带上单价副本，供 billing 侧独立复算：

```json
{
  "request_id": "b3f1...c2",
  "user_id": 1,
  "service_name": "ai-chat-service",
  "model": "deepseek-flash",
  "billing_mode": "per_token",
  "prompt_tokens": 3000,
  "completion_tokens": 1050,
  "token_source": "upstream",
  "price_per_1k_input": 1,
  "price_per_1k_output": 1,
  "unit_price": null,
  "points": 5,
  "status": "success",
  "capability_id": 3
}
```

**金额校验规则（按模式）**：

| 模式 | 入口校验 | 说明 |
|---|---|---|
| `per_call` | `points == unit_price`（成功）/ `points == 0`（非成功）；不带 `unit_price` 时不校验 | 与改造前完全一致 |
| `per_token` | 非成功必须 `points == 0`；成功时若带 `price_per_1k_input/output`，则 `points` 必须等于 `ceil((p·in + c·out)/1000)`；`p+c` 必须 > 0 | 防止上游算错价后静默记账 |
| `per_unit` | `points == price_per_unit × units`（成功）/ `0`（非成功） | 缺 `price_per_unit` 时退回 `unit_price` |

- 成功 data：

```json
{
  "record_id": 1,
  "request_id": "b3f1...c2",
  "user_id": 1,
  "capability_id": 1,
  "service_name": "ai-chat-service",
  "cost": 5,
  "unit_price": 5,
  "call_status": "success",
  "duplicated": false,
  "balance_after": 95,
  "stat_date": "2026-10-19",
  "call_count": 1,
  "total_cost": 5,
  "billing_mode": "per_call",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "token_source": "unknown",
  "units": 1
}
```

- 错误码：`1001` 链路身份与目标用户不一致 / 缺少链路头；`1005` 用户不存在或已被禁用；`2001` 参数不符合 Schema；`3001` 积分不足；`3002` 同一 `requestId` 被不同调用占用；`4002` user-service 不可用；`4003` 系统内部错误
- 备注：
  - **处理顺序固定**为“幂等写调用记录 → 调 user 扣分 → 累计日用量”，账单与聚合在**同一本地事务**内（远端扣分独立提交）：明细先 `flush` 抢占 `request_id` 唯一键但不提交；扣分失败（含 `3001` / `1005` / `4002`）立即 `rollback`，明细与日用量都不会落库，**不留半成功状态**。
  - **幂等**：`request_id` 已存在且关键字段（`user_id`、`service_name`、`capability_id`、`cost`、`unit_price`、`model_name`、`duration_ms`、`call_status`、`billing_mode`、`prompt_tokens`、`completion_tokens`、`units`）一致时，返回 `code=0` + `duplicated=true`，`balance_after` 为 `null`（本次未扣分），不会重复扣费、不会重复累计用量；关键字段不一致时返回 `3002`。
  - **扣分**：只调用 `user-service` 的 `/internal/user/points/deduct`，自动服务发现，不写死地址、不读 `user_db`；`request_id` 原样透传，用户侧幂等键与计费侧一致。
  - **账号状态**：`points > 0` 时由扣分调用顺带完成状态校验（用户侧 `1005` 直接透传）；`points = 0` 的免费能力**不发起**扣分请求（用户侧要求 `amount ≥ 1`），因此单独调 `/internal/user/check` 校验状态，避免禁用账号经免费能力绕过校验。两种情况都不留半成功状态。
  - **日用量累加**：使用 `INSERT ... ON DUPLICATE KEY UPDATE call_count = call_count + 1, total_cost = total_cost + cost`，由数据库原子完成，避免并发丢失更新。
  - 明细先 flush 会在唯一键上短暂持有行锁，并发同 `request_id` 的后到请求会等待，最终以 `IntegrityError` 命中重放分支，不会双扣。

## 3. 调用明细

### `GET /api/billing/records`

- 负责人：黄禹菲
- 是否需要登录：是
- 查询参数：`start_date`、`end_date`（可选，缺省最近 30 天）、`service_name`（可选，精确匹配）、`call_status`（可选，`success` / `degraded` / `failed`）、`page`、`page_size`
- 成功 data：分页结构，列表项 `{"id": 1, "request_id": "...", "user_id": 1, "capability_id": 0, "service_name": "ai-chat-service", "cost": 1, "unit_price": null, "call_status": "success", "duration_ms": 0, "model_name": "mock-model", "create_time": "2026-09-16 10:00:00", "billing_mode": "per_call", "prompt_tokens": 0, "completion_tokens": 0, "token_source": "", "units": 1, "images": []}`
- 错误码：`1001` 未认证；`1005` 用户不存在或已被禁用；`2001` 参数不符合 Schema（分页越界、状态枚举非法、日期范围非法）；`4002` user-service 不可用
- 备注：只返回当前用户的数据，按 `id` 倒序；日期过滤使用 `create_time >= start 00:00:00 AND create_time < end+1 天` 的索引友好写法。

## 4. 用量统计

### `GET /api/billing/usage`

- 负责人：黄禹菲
- 是否需要登录：是
- 查询参数：`start_date`、`end_date`（可选，缺省最近 30 天）
- 成功 data：

```json
{
  "start_date": "2026-09-01",
  "end_date": "2026-09-16",
  "summary": {"call_count": 12, "total_cost": 60, "success_count": 10, "degraded_count": 1, "failed_count": 1},
  "by_day": [{"stat_date": "2026-09-16", "call_count": 3, "total_cost": 15}],
  "by_service": [{"service_name": "ai-chat-service", "call_count": 12, "total_cost": 60}]
}
```

- 错误码：`1001` 未认证；`1005` 用户不存在或已被禁用；`2001` 参数不符合 Schema；`4002` user-service 不可用
- 备注：**统计口径**——`summary` 与 `by_service` 取自 `t_call_record` 明细（可按状态与承载服务拆分），`by_day` 取自 `t_usage_daily` 聚合表。只统计当前用户。

### `GET /api/billing/stat/overview`

- 负责人：黄禹菲
- 是否需要登录：是（**运营全局统计**）
- 查询参数：`start_date`、`end_date`（可选，缺省最近 30 天）
- 成功 data：在个人统计三个区块基础上，`summary` 增加 `user_count`（去重用户数），并增加 `top_users`：

```json
{
  "start_date": "2026-09-01",
  "end_date": "2026-09-16",
  "summary": {"call_count": 40, "total_cost": 200, "user_count": 3, "success_count": 38, "degraded_count": 1, "failed_count": 1},
  "by_day": [{"stat_date": "2026-09-16", "call_count": 12, "total_cost": 60}],
  "by_service": [{"service_name": "ai-chat-service", "call_count": 40, "total_cost": 200}],
  "top_users": [{"user_id": 1, "call_count": 20, "total_cost": 100}]
}
```

- 错误码：`1001` 未认证；`1005` 用户不存在或已被禁用；`2001` 参数不符合 Schema；`4002` user-service 不可用
- 备注：全局口径，top_users 按费用取前 10。每次通过 user 实时授权当前 admin；普通用户 1006、禁用/不存在 1005，异常或不明确的授权 4002，失败关闭。

## 5. 错误码

| code | message | 触发场景 | 号段 |
|---|---|---|---|
| 1001 | 未认证或登录已过期 | 缺 `X-User-Id`、`X-User-Id` 非正整数 | 1xxx |
| 1001 | 缺少或伪造的链路身份 | 内部接口缺链路头，或 `X-User-Id` 与目标用户不一致 | 1xxx |
| 1005 | 用户不存在或已被禁用 | 查询接口的前置账号状态校验未通过（由 user-service 透传） | 1xxx |
| 2001 | 参数不符合 Schema | 必填缺失、类型错误、枚举非法、日期范围非法（基座与范围校验统一处理） | 2xxx |
| 2007 | 无运营权限，仅管理员可执行该操作 | 管理端接口对普通用户；由 user 侧 `1006` 映射 | 2xxx |
| 3001 | 积分不足 | 由 user-service 扣分失败透传，此时明细与用量已回滚 | 3xxx |
| 3002 | 重复计费：同一 requestId 已被其它调用占用 | 幂等键被不同调用复用（用户/服务/能力/实际费用/登记价/模型/耗时/状态任一不同） | 3xxx |
| 4002 | 下游服务暂不可用 | 服务发现失败、扣分调用异常，或账号状态校验时 user-service 不可用 | 4xxx |
| 4003 | 系统内部错误 | 未预期异常、幂等冲突但查不到明细 | 4xxx |

> **号段说明**：计费业务错误只用 `30xx`；参数类错误沿用平台统一的 `2001`（基座对 Schema 错误即返回该码），下游与系统错误由基座返回 `4002` / `4003`，不属于本服务业务号段。

## 6. Pro 实现与兼容要求

1. 查询前当前账号检查继续通过 user 的内部契约，依赖不可用为 4002，不跨库读状态。全局 overview 已调用共享实时 authorization，普通用户/角色撤销拒绝，异常失败关闭。
2. Gateway 签名 role 仅供展示；实时授权按[共享契约](pro-shared.md)。用户确认权限不足采用 1006，Key 不存在保留同码，按端点/消息区分。
3. Pro AI 已查新鲜目录并上报 capability_id、unit_price、points、status、duration_ms。unit_price 独立存储/查询；旧调用省略时保存 NULL。提供单价时 success 的 points 必须等于 unit_price，degraded/failed 的 points 必须为 0。增量迁移保留历史未知单价 NULL。
4. 正常收费 points=目录价，degraded points=0，登记单价与实际费用分开。AI 会核对收据 record_id/request_id/user_id/capability_id/cost/call_status；变更必须保持兼容。
5. 当前 by_day 聚合所有能力，summary/by_service 查明细，日统计查聚合；这是实际双源口径，新增维度或修复历史差异需有迁移/对账证据，不用文案改成另一实现。
6. 本地记账回滚不能撤销已提交的远端 user 扣分。跨服务最后提交/网络故障须 requestId 对账；不要宣称分布式原子性，不能盲目重试模型。

## 7. 测试数据计划

隔离示例库的 `sql/02_seed.sql` 与 user-service 的本地演示账号对应：

- `t_call_record`：2 条 `user_id=1`（`demo`）的 Mock 调用明细，`stat_date` 固定为 `2026-09-15`，`cost=5`，`call_status='success'`；
- `t_usage_daily`：`2026-09-15` + `user_id=1` + `capability_id=1`，`call_count=2`、`total_cost=10`。

脚本使用 `INSERT ... ON DUPLICATE KEY UPDATE`，可重复执行；日期固定便于稳定断言，不含任何真实密钥。联调时通过 `/internal/billing/record` 产生的数据会累加到当天，不会与演示数据冲突。

## 8. 迁移与验收

运行 `python -m app.migrate` 可重复增加 nullable unit_price；不删除账单或修改历史费用。参见[升级说明](../../services/user-service/UPGRADE.md)和[本人交接](../implementation/member-黄禹菲.md)。本地账单/聚合事务与远端 user 扣分不具备分布式原子性，最终提交失败须按 requestId 对账。


## 9. 本轮增量：C1 token 用量 / C2 双轨计费

### 9.1 token 口径（C1）

- `prompt_tokens` / `completion_tokens` **只采信上游 `usage`**：Chat Completions 取 `prompt_tokens` / `completion_tokens`，Responses 协议取 `input_tokens` / `output_tokens`，两者归一化后落库。
- 上游未返回 usage（或返回 0/0、负数、浮点、布尔）时，记为 `0/0` + `token_source='missing'`，**不再用字符数冒充 token**。
- 历史记录保持 `0/0` + `token_source='unknown'`，不回填、不估算。
- `t_chat_message.token_count` 语义固定为 `prompt_tokens + completion_tokens`；失败占位消息为 0。

### 9.2 计价模式（C2）

- 换算基准：**1000 tokens = 1 积分**（已在 capability 目录价中体现为 `price_per_1k_*`）。
- 公式：`per_token` 为 `ceil((prompt·price_per_1k_input + completion·price_per_1k_output) / 1000)`，整数向上取整，不使用浮点；`per_unit` 为 `price_per_unit × units`；`per_call` 为 `price_per_call`。
- 降级/失败一律 `cost = 0`，但仍保留一条账单（与改造前一致）。

### 9.3 迁移

- 增量脚本：`services/billing-service/sql/03_add_token_usage.sql`（可重复执行）。
- 只增列、不改旧数据；`01_init.sql` 同步更新，供全新环境直接建表。

## 10. 本轮增量：F1 管理端跨用户查询（`/api/billing/admin`）

运营后台需要按用户查看流水与用量；统计口径与个人接口**完全一致**，只有目标用户与权限不同。

### 10.1 `GET /api/billing/admin/records`

- 是否需要登录：是（**管理员**）
- 查询参数：
  - `user_id`（必填，正整数）：要查询的目标用户；
  - `start_date` / `end_date`（可选，缺省最近 30 天）；
  - `call_status`（可选，`success` / `degraded` / `failed`）；
  - `service_name`（可选，精确匹配）；
  - `page` / `page_size`（默认 10，最大 100）。
- 成功 data：与 `GET /api/billing/records` 同构的分页结构，列表项含
  `billing_mode` / `prompt_tokens` / `completion_tokens` / `units` / `images` 等 C1/C2/D3 字段。
- 错误码：`1001` 未认证；`2001` 参数非法；`2007` 非管理员；`4002` 授权依赖不可用（失败关闭）。
- 备注：只返回调用元数据，不含会话正文；`user_id` 过滤在 SQL 层完成，不会把其他用户的行带回前端。

### 10.2 `GET /api/billing/admin/users/{user_id}/usage`

- 是否需要登录：是（**管理员**）
- 查询参数：`start_date` / `end_date`（可选，缺省最近 30 天）
- 成功 data：与 `GET /api/billing/usage` 同构（`start_date` / `end_date` / `summary` / `by_day` / `by_service`），
  只是目标用户由路径参数指定。
- 错误码：同上。
- 备注：同一统计口径——`summary` / `by_service` 取自 `t_call_record`，`by_day` 取自 `t_usage_daily`。

### 10.3 权限映射

- 管理员身份由 user-service 的 `/internal/user/authorization?required_role=admin` 实时校验，
  失败关闭；user-service 返回的 `1006 权限不足` 在**本服务管理端**统一映射为平台运营口径的
  `2007 无运营权限`（与 capability-service 一致）。`1006` 在 API Key 端点保留原语义。
- 授权依赖超时 / 端点缺失 / 响应格式异常 → `4002`，不降级为“放行”。

### P11 上游模型选择（2026-11-03）

平台 `/api/chat/completions` 的显式 `model` 优先于绑定供应商的 `default_model`；只有未绑定供应商时才回退全局 `MODEL_NAME`。绑定供应商但两者均为空时返回 `4002`，明确提示补默认模型，不静默发送全局名称。`/v1` 的 `model` 是平台能力别名，只用于解析能力，绝不作为上游模型名。相同规则适用于 chat、summary 与流式；图片仍由图片供应商配置决定。供应商编辑页在默认模型为空时给出调用限制提示。

### P1 供应商状态与错误码（2026-11-03）

`2008` 只表示执行器未实现，原文案保留。`2009` 表示绑定供应商不存在、未启用或被停用；运行期点名alias，OpenAI/Responses兼容层映射为HTTP503、type=api_error、code=platform_2009。保存绑定时仅接受enabled供应商，draft/disabled返回2001并提示先测试启用，状态缺失按4002失败关闭。供应商变更不改变一次调用一条账单、失败不扣分的口径。无新增表字段或接口。

### P6 API Key 归因（2026-11-03）

- 表结构：`t_call_record` 增 `api_key_id BIGINT NULL`（索引 `idx_call_record_api_key_time (api_key_id, is_deleted, create_time)`）与 `entrypoint VARCHAR(16) NOT NULL DEFAULT ''`。历史行分别为 `NULL` / 空串，语义"未知"，**不回填**。
- 内部入参：`POST /internal/billing/record` 增 `api_key_id`（仅接受 ≥1 的整数，`0` 视为非法）与 `entrypoint`（`web` / `platform_api` / `openai_compat`）。缺省时行为与旧调用方一致。
- 出参：`CallRecordOut` 增 `api_key_id: int|null` 与 `entrypoint: string`。
- 查询：`GET /api/billing/admin/records` 增 `api_key_id` 过滤参数（组合在既有 `user_id` 必填之上）。
- 新增 `GET /api/billing/admin/users/{user_id}/keys-usage?start_date&end_date`：返回 `{"user_id","start_date","end_date","list":[{"api_key_id","call_count","total_cost","last_call_at"}]}`；只统计 `api_key_id IS NOT NULL` 的记录，避免把无 Key 身份的调用塞进某把 Key。
- 迁移：`sql/05_add_api_key_attribution.sql`，可重复执行，已同步 `deploy/mysql/init/04_billing_service.sql`。

### P5 全量用户用量聚合（2026-11-03）

新增 `GET /api/billing/admin/users/usage?start_date&end_date`（管理员，`_ensure_admin`）：
`{"start_date","end_date","list":[{"user_id","call_count","total_cost","last_call_at"}]}`，数据源 `t_usage_daily` 按 `user_id` 汇总，含零消耗用户之外的**所有有调用记录的用户**；零调用用户由 user-service 资料列表补位。`last_call_at` 是天粒度（聚合表本身只有天）。**规模边界**：用户数 ≤2000 时由前端 join 后排序分页；超过必须改为 billing 主导分页 + user-service 批量补资料（A2）。普通用户 `2007`。

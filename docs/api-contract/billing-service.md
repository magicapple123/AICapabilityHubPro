# billing-service 接口契约

> 负责人：黄禹菲
> 服务名：`billing-service`
> 数据库：`billing_db`
> 端口：8083
> 上游依赖：`user-service`（仅调用 `/internal/user/points/deduct`，**不读 `user_db`**）

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401。

## 0. 通用约定

- **登录要求**：`/api/billing/records`、`/api/billing/usage`、`/api/billing/stat/overview` 均需要网关 JWT；`/health` 不需要。本服务无白名单业务接口。
- **内部接口**：`/internal/billing/record` 只允许其它后端服务经基座 `call_internal` 调用。网关对外部访问 `/internal/**` 一律 403；本服务另校验 `X-User-Id`（身份，必须等于 body 的 `user_id`）与 `X-Request-Id`（幂等键，必须等于 body 的 `request_id`）。
- **身份来源**：从网关注入的 `X-User-Id` / `X-User-Name` / `X-Request-Id` 读取，服务内不重复解析 JWT。
- **账号状态校验**：网关只校验 JWT 签名与有效期，**不知道账号是否已被禁用**，因此被禁用账号在 Token 过期前仍能通过网关。billing-service 没有 `user_db` 的访问权（禁止跨库），三个查询接口都会先通过 `/internal/user/check`（`points_cost=0`）确认账号仍可用：被禁用返回 `1005`，user-service 不可用返回 `4002`。校验放在参数校验之后，确保 `2001` / `1001` 的错误优先级稳定。
- **数据隔离**：`records` / `usage` 只返回当前用户自己的数据；`stat/overview` 为运营全局统计。
- **分页格式**：`data = {"list": [...], "total": 100, "page": 1, "page_size": 10}`；`page_size` 默认 10、最大 100。
- **统计时间范围**：`start_date` / `end_date` 为 `YYYY-MM-DD`，**含当天**。缺省回看最近 30 天（含今天）；跨度上限 366 天；`start_date > end_date` 或超跨度按参数错误处理。`today` 取服务器本地日期（容器 TZ = Asia/Shanghai），与 `t_usage_daily.stat_date` 口径一致。
- **软删除**：`t_call_record` 默认过滤 `is_deleted=0`；`t_usage_daily` 只累加、不软删除。
- **金额语义**：`cost` / `total_cost` 为整数积分数，不使用浮点（指南 5.5）。
- **时间格式**：`create_time` 返回 `YYYY-MM-DD HH:MM:SS`（Asia/Shanghai）；`stat_date` / `start_date` / `end_date` 返回 `YYYY-MM-DD`。
- **日志脱敏**：日志带 `requestId`，不打印模型 Key、Token 或用户口令。

## 1. 数据字典

### `t_call_record`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `request_id` | VARCHAR(64) | NOT NULL | **幂等键**，全链路 requestId，未删除范围内唯一 |
| `user_id` | BIGINT | NOT NULL, INDEX | 调用用户 |
| `capability_id` | BIGINT | NOT NULL DEFAULT 0 | 能力 ID；**0 表示未关联具体能力**（当前 ai-chat 按“服务 + 固定单价”上报） |
| `service_name` | VARCHAR(64) | NOT NULL DEFAULT '' | 承载调用的服务名，如 `ai-chat-service` |
| `cost` | BIGINT | NOT NULL DEFAULT 0 | 本次消耗积分（整数） |
| `call_status` | VARCHAR(16) | NOT NULL DEFAULT 'success' | `success` / `degraded` / `failed`（指南 5.5 统一枚举） |
| `duration_ms` | INT | NOT NULL DEFAULT 0 | 调用耗时，缺省 0 |
| `model_name` | VARCHAR(128) | NOT NULL DEFAULT '' | 模型名；Mock 模式为请求中的 `model` |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

### `t_usage_daily`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `stat_date` | DATE | NOT NULL, INDEX | 统计日期（Asia/Shanghai） |
| `user_id` | BIGINT | NOT NULL, INDEX | 调用用户 |
| `capability_id` | BIGINT | NOT NULL DEFAULT 0 | 能力 ID，0 含义同上 |
| `call_count` | BIGINT | NOT NULL DEFAULT 0 | 当日调用次数 |
| `total_cost` | BIGINT | NOT NULL DEFAULT 0 | 当日消耗积分合计 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

**索引**：
- `t_call_record`：`UNIQUE(request_id, is_deleted)` 保证记账幂等；`INDEX(user_id, is_deleted, create_time)` 支撑个人明细分页；`INDEX(service_name, is_deleted, create_time)` 支撑按服务统计。
- `t_usage_daily`：`UNIQUE(stat_date, user_id, capability_id)` 是原子累加（`ON DUPLICATE KEY UPDATE`）的前提，按指南附录 B“联合唯一，用于聚合”。该唯一键**不包含** `is_deleted`，因为本表只累加、不软删除；`capability_id` 用 0 而不是 NULL，因为 MySQL 唯一索引不约束多个 NULL，会让 UPSERT 失效。

> **与附录 B 的差异说明**：附录 B 的 `t_call_record` 列 `model_name`，而入参使用 `model`（与 ai-chat 的实际上报一致），映射关系为 `model → model_name`、`points → cost`、`status → call_status`。

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
  "points": 1,
  "status": "success",
  "capability_id": 0,
  "duration_ms": 0,
  "remark": ""
}
```

- 成功 data：

```json
{
  "record_id": 1,
  "request_id": "b3f1...c2",
  "user_id": 1,
  "capability_id": 0,
  "service_name": "ai-chat-service",
  "cost": 1,
  "call_status": "success",
  "duplicated": false,
  "balance_after": 94,
  "stat_date": "2026-09-16",
  "call_count": 3,
  "total_cost": 15
}
```

- 错误码：`1001` 链路身份与目标用户不一致 / 缺少链路头；`1005` 用户不存在或已被禁用；`2001` 参数不符合 Schema；`3001` 积分不足；`3002` 同一 `requestId` 被不同调用占用；`4002` user-service 不可用；`4003` 系统内部错误
- 备注：
  - **处理顺序固定**为“幂等写调用记录 → 调 user 扣分 → 累计日用量”，三步在**同一事务**内：明细先 `flush` 抢占 `request_id` 唯一键但不提交；扣分失败（含 `3001` / `1005` / `4002`）立即 `rollback`，明细与日用量都不会落库，**不留半成功状态**。
  - **幂等**：`request_id` 已存在且关键字段（`user_id`、`service_name`、`capability_id`、`cost`、`call_status`）一致时，返回 `code=0` + `duplicated=true`，`balance_after` 为 `null`（本次未扣分），不会重复扣费、不会重复累计用量；关键字段不一致时返回 `3002`。
  - **扣分**：只调用 `user-service` 的 `/internal/user/points/deduct`，自动服务发现，不写死地址、不读 `user_db`；`request_id` 原样透传，用户侧幂等键与计费侧一致。
  - **账号状态**：`points > 0` 时由扣分调用顺带完成状态校验（用户侧 `1005` 直接透传）；`points = 0` 的免费能力**不发起**扣分请求（用户侧要求 `amount ≥ 1`），因此单独调 `/internal/user/check` 校验状态，避免禁用账号经免费能力绕过校验。两种情况都不留半成功状态。
  - **日用量累加**：使用 `INSERT ... ON DUPLICATE KEY UPDATE call_count = call_count + 1, total_cost = total_cost + cost`，由数据库原子完成，避免并发丢失更新。
  - 明细先 flush 会在唯一键上短暂持有行锁，并发同 `request_id` 的后到请求会等待，最终以 `IntegrityError` 命中重放分支，不会双扣。

## 3. 调用明细

### `GET /api/billing/records`

- 负责人：黄禹菲
- 是否需要登录：是
- 查询参数：`start_date`、`end_date`（可选，缺省最近 30 天）、`service_name`（可选，精确匹配）、`call_status`（可选，`success` / `degraded` / `failed`）、`page`、`page_size`
- 成功 data：分页结构，列表项 `{"id": 1, "request_id": "...", "user_id": 1, "capability_id": 0, "service_name": "ai-chat-service", "cost": 1, "call_status": "success", "duration_ms": 0, "model_name": "mock-model", "create_time": "2026-09-16 10:00:00"}`
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
- 备注：全局口径（不限用户）；`top_users` 按消耗积分倒序取前 10；**待确认**：平台暂无角色体系，当前按“已登录即可访问”处理，见第 6 节。

## 5. 错误码

| code | message | 触发场景 | 号段 |
|---|---|---|---|
| 1001 | 未认证或登录已过期 | 缺 `X-User-Id`、`X-User-Id` 非正整数 | 1xxx |
| 1001 | 缺少或伪造的链路身份 | 内部接口缺链路头，或 `X-User-Id` 与目标用户不一致 | 1xxx |
| 1005 | 用户不存在或已被禁用 | 查询接口的前置账号状态校验未通过（由 user-service 透传） | 1xxx |
| 2001 | 参数不符合 Schema | 必填缺失、类型错误、枚举非法、日期范围非法（基座与范围校验统一处理） | 2xxx |
| 3001 | 积分不足 | 由 user-service 扣分失败透传，此时明细与用量已回滚 | 3xxx |
| 3002 | 重复计费：同一 requestId 已被其它调用占用 | 幂等键被不同调用复用（用户/服务/能力/单价/状态任一不同） | 3xxx |
| 4002 | 下游服务暂不可用 | 服务发现失败、扣分调用异常，或账号状态校验时 user-service 不可用 | 4xxx |
| 4003 | 系统内部错误 | 未预期异常、幂等冲突但查不到明细 | 4xxx |

> **号段说明**：计费业务错误只用 `30xx`；参数类错误沿用平台统一的 `2001`（基座对 Schema 错误即返回该码），下游与系统错误由基座返回 `4002` / `4003`，不属于本服务业务号段。

## 6. 待确认事项（需在契约 Review 时与组长确认）

1. **查询接口依赖 user-service 可用性**：为拦截被禁用账号，三个查询接口会先调 `/internal/user/check`。代价是 user-service 不可用时用量页会返回 `4002`（而非展示旧数据），这是为了让「账号状态」只有一个权威来源、且不越过跨库禁令。若认为读接口不应被前置依赖拖累，候选方案：① 网关统一在认证阶段拦截被禁用账号（需要网关能访问用户状态）；② 本服务短期缓存状态（引入缓存组件，属本期非目标）。**请确认当前方案可接受。**
2. **运营权限方案**：`/api/billing/stat/overview` 当前对所有已登录用户开放。平台尚无角色体系（网关 JWT 只有 `userId` / `userName`），与 capability-service 契约第 6 节同类问题；候选方案为网关新增角色 Claim 或本服务配置运营用户白名单。
3. **是否按 `capability_id` 计费**：目前 ai-chat 用配置项 `POINTS_COST` 上报单价，`capability_id` 恒为 0，未按 capability-service 登记的 `price_per_call` 计算。若要求“以能力登记单价为准”，需要在本服务或 ai-chat 侧按 `capability_id` 查询单价（capability-service 需提供 `/internal` 查询接口，当前未实现）。
4. **`duration_ms` 数据来源**：ai-chat 当前未上报耗时，缺省 0。若运营页面需要真实延迟，需要 ai-chat 补充该字段。
5. **`t_usage_daily` 是否需要按能力维度出参**：本表已按 `capability_id` 聚合，但对外 `by_day` 未按能力拆分。若运营要“按能力看趋势”，可增加 `by_capability` 区块。
6. **统计口径双源一致性**：`summary` / `by_service` 来自明细表，`by_day` 来自聚合表。正常路径下两者由同一事务写入而一致；若有人工改库或历史数据缺失，两者可能不相等。需要确认是否接受双源，或统一改为全部从明细表聚合。

## 7. 测试数据计划

按指南 13.2，提供可重复导入的初始化数据（`sql/02_seed.sql`），与 user-service 的演示用户保持一致：

- `t_call_record`：2 条 `user_id=1`（`demo`）的 Mock 调用明细，`stat_date` 固定为 `2026-09-15`，`cost=5`，`call_status='success'`；
- `t_usage_daily`：`2026-09-15` + `user_id=1` + `capability_id=1`，`call_count=2`、`total_cost=10`。

脚本使用 `INSERT ... ON DUPLICATE KEY UPDATE`，可重复执行；日期固定便于稳定断言，不含任何真实密钥。联调时通过 `/internal/billing/record` 产生的数据会累加到当天，不会与演示数据冲突。

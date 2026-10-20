# AICapabilityHub Pro · billing-service 接口契约

**实现状态（2026-10-20，feature/pro-user-billing）：** 已实现 nullable unit_price 存储、查询、迁移和实时管理员统计授权；兼容既有 AI 上报字段。规则见 [Pro 开发指南](../../AICapabilityHubPro-开发指南.md)与[共享契约](pro-shared.md)。

> 负责人：黄禹菲
> 服务名：`billing-service`
> 数据库：`billing_db`
> 端口：8083
> 上游依赖：user-service 的 `/internal/user/check` 与 `/internal/user/points/deduct`；实时 `/internal/user/authorization`，禁止读取 user_db。

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401。

## 0. 通用约定

- **登录要求**：`/api/billing/records`、`/api/billing/usage`、`/api/billing/stat/overview` 均需要网关 JWT；`/health` 不需要。本服务无白名单业务接口。
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
  "remark": ""
}
```

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
  "total_cost": 5
}
```

- 错误码：`1001` 链路身份与目标用户不一致 / 缺少链路头；`1005` 用户不存在或已被禁用；`2001` 参数不符合 Schema；`3001` 积分不足；`3002` 同一 `requestId` 被不同调用占用；`4002` user-service 不可用；`4003` 系统内部错误
- 备注：
  - **处理顺序固定**为“幂等写调用记录 → 调 user 扣分 → 累计日用量”，账单与聚合在**同一本地事务**内（远端扣分独立提交）：明细先 `flush` 抢占 `request_id` 唯一键但不提交；扣分失败（含 `3001` / `1005` / `4002`）立即 `rollback`，明细与日用量都不会落库，**不留半成功状态**。
  - **幂等**：`request_id` 已存在且关键字段（`user_id`、`service_name`、`capability_id`、`cost`、`unit_price`、`model_name`、`duration_ms`、`call_status`）一致时，返回 `code=0` + `duplicated=true`，`balance_after` 为 `null`（本次未扣分），不会重复扣费、不会重复累计用量；关键字段不一致时返回 `3002`。
  - **扣分**：只调用 `user-service` 的 `/internal/user/points/deduct`，自动服务发现，不写死地址、不读 `user_db`；`request_id` 原样透传，用户侧幂等键与计费侧一致。
  - **账号状态**：`points > 0` 时由扣分调用顺带完成状态校验（用户侧 `1005` 直接透传）；`points = 0` 的免费能力**不发起**扣分请求（用户侧要求 `amount ≥ 1`），因此单独调 `/internal/user/check` 校验状态，避免禁用账号经免费能力绕过校验。两种情况都不留半成功状态。
  - **日用量累加**：使用 `INSERT ... ON DUPLICATE KEY UPDATE call_count = call_count + 1, total_cost = total_cost + cost`，由数据库原子完成，避免并发丢失更新。
  - 明细先 flush 会在唯一键上短暂持有行锁，并发同 `request_id` 的后到请求会等待，最终以 `IntegrityError` 命中重放分支，不会双扣。

## 3. 调用明细

### `GET /api/billing/records`

- 负责人：黄禹菲
- 是否需要登录：是
- 查询参数：`start_date`、`end_date`（可选，缺省最近 30 天）、`service_name`（可选，精确匹配）、`call_status`（可选，`success` / `degraded` / `failed`）、`page`、`page_size`
- 成功 data：分页结构，列表项 `{"id": 1, "request_id": "...", "user_id": 1, "capability_id": 0, "service_name": "ai-chat-service", "cost": 1, "unit_price": null, "call_status": "success", "duration_ms": 0, "model_name": "mock-model", "create_time": "2026-09-16 10:00:00"}`
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

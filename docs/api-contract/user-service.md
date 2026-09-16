# user-service 接口契约

> 负责人：黄禹菲
> 服务名：`user-service`
> 数据库：`user_db`
> 端口：8081
> 上游依赖：无（user-service 不调用任何其它服务）
> 下游调用方：`ai-chat-service`（`/internal/user/check`）、`billing-service`（`/internal/user/points/deduct`）

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401。

## 0. 通用约定

- **登录要求**：`/api/user/register`、`/api/user/login` 属网关白名单（**精确路径**，不带尾斜杠）；`/api/user/profile`、`/api/user/apikeys/**`、`/api/user/points/**` 需要网关 JWT。`/health` 不需要登录。
- **内部接口**：`/internal/user/**` 只允许其它后端服务经基座 `call_internal` 调用。网关对外部访问 `/internal/**` 一律返回 403；本服务另校验 `X-User-Id`（身份）与 `X-Request-Id`（幂等键），二者缺失或身份与目标用户不一致时返回 `1001`。
- **身份来源**：从网关注入的 `X-User-Id` / `X-User-Name` / `X-Request-Id` 读取，服务内不重复解析 JWT。`X-User-Id` 必须是正整数，否则按未认证处理。
- **账号状态校验**：网关只校验 JWT 签名与有效期，**不知道账号是否已被禁用**，因此被禁用账号在 Token 过期前仍能通过网关。除 `register` / `login` / `/health` 外，所有接口都会自行校验账号状态（user-service 拥有 `t_user`，一次主键查询即完成）；账号不存在或 `status=disabled` 一律返回 `1005`。`register` / `login` 不做该校验，以便被禁用用户仍能收到明确的 `1005` 提示。
- **分页格式**：`data = {"list": [...], "total": 100, "page": 1, "page_size": 10}`；`page_size` 默认 10、最大 100。API Key 列表不分页（单个用户 Key 数量少，前端一次取全）。
- **软删除**：所有查询默认过滤 `is_deleted=0`；本期没有物理删除接口。
- **时间格式**：`create_time` / `update_time` 返回 `YYYY-MM-DD HH:MM:SS`（Asia/Shanghai）；登录响应的 `expire_at` 为 **UTC** 时间，格式同上。
- **金额语义**：积分一律整型（个），不使用浮点（指南 5.5）。
- **口令安全**：口令以 PBKDF2-HMAC-SHA256 加盐哈希存储，格式 `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`；任何出参都不包含 `password` / `password_hash`。日志不打印口令、Token 与密钥。
- **JWT 签发**：`HS256`，必须携带 `iss`（默认 `ai-capability-hub`）、`sub`（用户 ID）、`username` claim 与过期时间，密钥取自 `JWT_SECRET`（UTF-8 后 ≥ 32 字节）。`.env` 中的 `JWT_SECRET` / `JWT_ISSUER` 必须与网关一致，否则登录成功但经网关访问返回 1001。

## 1. 数据字典

### `t_user`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 用户 ID |
| `username` | VARCHAR(32) | NOT NULL | 登录名，3~32 位字母/数字/下划线/连字符，未删除范围内唯一 |
| `password_hash` | VARCHAR(255) | NOT NULL | PBKDF2 自描述哈希串，禁止明文 |
| `nickname` | VARCHAR(32) | NOT NULL DEFAULT '' | 昵称，缺省等于 `username` |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'normal' | `normal` 正常 / `disabled` 禁用 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

### `t_api_key`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `user_id` | BIGINT | NOT NULL, INDEX | 所属用户 |
| `name` | VARCHAR(32) | NOT NULL DEFAULT '' | 备注名 |
| `access_key` | VARCHAR(64) | NOT NULL | 对外标识，`ak_` + 24 位十六进制，未删除范围内唯一 |
| `secret_hash` | VARCHAR(128) | NOT NULL | `secret_key` 的 SHA-256 十六进制摘要，用于校验，不可逆 |
| `secret_mask` | VARCHAR(32) | NOT NULL DEFAULT '' | 展示掩码，如 `sk_****a1b2` |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'enabled' | `enabled` / `disabled` |
| `expire_time` | DATETIME | NULL | 过期时间，NULL 表示永不过期 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

> **对附录 B 的扩展说明**：附录 B 只列出 `secret_mask`。若仅存掩码则无法校验密钥，因此本服务额外增加 `secret_hash` 列，用摘要替代明文；`secret_mask` 仅用于展示。需在契约 Review 时确认该扩展。

### `t_points_account`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `user_id` | BIGINT | NOT NULL, UNIQUE | 一个用户一条账户 |
| `balance` | BIGINT | NOT NULL DEFAULT 0 | 可用积分余额，条件更新下永不为负 |
| `frozen` | BIGINT | NOT NULL DEFAULT 0 | 冻结积分，本期不做冻结，恒为 0 |
| `version` | INT | NOT NULL DEFAULT 0 | 变更次数，便于对账 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

### `t_points_log`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `user_id` | BIGINT | NOT NULL, INDEX | 所属用户 |
| `direction` | VARCHAR(8) | NOT NULL | `in` 收入 / `out` 支出 |
| `amount` | BIGINT | NOT NULL DEFAULT 0 | 变动数量，正数 |
| `balance_after` | BIGINT | NOT NULL DEFAULT 0 | 变动后余额快照 |
| `biz_type` | VARCHAR(32) | NOT NULL DEFAULT '' | `register` 注册赠送 / `call` 能力调用 |
| `request_id` | VARCHAR(64) | NOT NULL | **幂等键**；注册赠送为 `register-{user_id}`，调用扣分复用全链路 requestId |
| `remark` | VARCHAR(255) | NOT NULL DEFAULT '' | 备注 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

**索引**：`UNIQUE(request_id, is_deleted)` 是扣分幂等的最终防线；`INDEX(user_id, is_deleted, create_time)` 支撑流水分页。

## 2. 认证与资料接口

### `POST /api/user/register`

- 负责人：黄禹菲
- 是否需要登录：**否（网关白名单，精确路径）**
- 请求体：`{"username": "demo", "password": "demo123456", "nickname": "可选，默认等于 username"}`
- 成功 data：`{"user_id": 1, "username": "demo", "nickname": "demo", "balance": 100, "initial_points": 100}`
- 错误码：`2001` 参数不符合 Schema（用户名不满足 `^[a-zA-Z0-9_-]{3,32}$`、口令长度 8~128）；`1004` 用户名已存在
- 备注：**同一事务内**创建 `t_user`、`t_points_account` 与一条 `direction=in` 的赠送流水，任何一步失败整体回滚，不产生“有用户没有账户”的半成功状态。初始积分取自 `INITIAL_POINTS`（默认 100）。并发重名由 `uk_user_username` 唯一索引兜底并映射为 `1004`。

### `POST /api/user/login`

- 负责人：黄禹菲
- 是否需要登录：**否（网关白名单，精确路径）**
- 请求体：`{"username": "demo", "password": "demo123456"}`
- 成功 data：`{"token": "<JWT>", "token_type": "Bearer", "expire_at": "2026-09-17 03:00:00", "user_id": 1, "username": "demo"}`
- 错误码：`2001` 参数不符合 Schema；`1003` 用户名或密码错误；`1005` 用户不存在或已被禁用
- 备注：用户名不存在与口令错误返回**同一个** `1003`，避免账号枚举；凭据正确但用户被禁用时返回 `1005`。`expire_at` 为 UTC，有效期 `JWT_TTL_HOURS`（默认 24 小时）。

### `GET /api/user/profile`

- 负责人：黄禹菲
- 是否需要登录：是
- 成功 data：`{"user_id": 1, "username": "demo", "nickname": "demo", "status": "normal", "create_time": "...", "update_time": "..."}`
- 错误码：`1001` 未认证；`1005` 用户不存在或已被禁用
- 备注：出参字段显式列举，绝不包含 `password_hash`。

### `PUT /api/user/profile`

- 负责人：黄禹菲
- 是否需要登录：是
- 请求体：`{"nickname": "新昵称"}`
- 成功 data：更新后的用户资料（同 `GET`）
- 错误码：`2001` 参数不符合 Schema（空 body 或显式 null）；`1005` 用户不存在或已被禁用
- 备注：幂等；本期只允许修改昵称，用户名与状态不可由用户自行修改。

## 3. API Key 接口

### `POST /api/user/apikeys`

- 负责人：黄禹菲
- 是否需要登录：是
- 请求体：`{"name": "本地调试", "expire_time": "2027-01-01 00:00:00"}`（两个字段均可选，`expire_time` 为空表示永不过期）
- 成功 data：`{"id": 1, "name": "本地调试", "access_key": "ak_xxx", "secret_mask": "sk_****a1b2", "status": "enabled", "expire_time": null, "create_time": "...", "secret_key": "sk_xxx"}`
- 错误码：`2001` 参数不符合 Schema；`1001` 未认证；`1005` 用户不存在或已被禁用
- 备注：`secret_key` **只在本次响应返回一次**，库内只保存 SHA-256 摘要；`access_key` 发生碰撞时最多重试 3 次，最终由 `uk_api_key_access_key` 兜底。被禁用账号不允许再签发新凭据（`1005`）。

### `GET /api/user/apikeys`

- 负责人：黄禹菲
- 是否需要登录：是
- 成功 data：`{"list": [{"id": 1, "name": "...", "access_key": "ak_xxx", "secret_mask": "sk_****a1b2", "status": "enabled", "expire_time": null, "create_time": "..."}], "total": 1}`
- 错误码：`1001` 未认证；`1005` 用户不存在或已被禁用
- 备注：按创建时间倒序；**不回传** `secret_key` 与 `secret_hash`。

### `PUT /api/user/apikeys/{api_key_id}/disable`

- 负责人：黄禹菲
- 是否需要登录：是
- 路径参数：`api_key_id`（int）
- 成功 data：`{"id": 1, "status": "disabled", "update_time": "..."}`
- 错误码：`1001` 未认证；`1005` 用户不存在或已被禁用；`1006` API Key 不存在
- 备注：幂等，重复禁用返回当前状态。**他人 Key 与不存在的 Key 都返回 `1006`**，不暴露资源是否存在。账号状态校验先于 `1006`：被禁用账号即使提交合法 `api_key_id` 也返回 `1005`（吊销动作由运营在账号层面处理，不做特例）。

## 4. 积分接口

### `GET /api/user/points`

- 负责人：黄禹菲
- 是否需要登录：是
- 成功 data：`{"user_id": 1, "balance": 95, "frozen": 0}`
- 错误码：`1001` 未认证；`1005` 用户不存在或已被禁用
- 备注：`frozen` 本期恒为 0。

### `GET /api/user/points/logs`

- 负责人：黄禹菲
- 是否需要登录：是
- 查询参数：`direction`（可选，`in` / `out`）、`page`、`page_size`
- 成功 data：分页结构，列表项 `{"id": 1, "direction": "out", "amount": 5, "balance_after": 95, "biz_type": "call", "request_id": "...", "remark": "...", "create_time": "..."}`
- 错误码：`2001` 参数不符合 Schema；`1001` 未认证；`1005` 用户不存在或已被禁用
- 备注：按 `id` 倒序（等价于时间倒序）；只能查询当前用户自己的流水。

## 5. 内部接口（服务间调用）

### `GET /internal/user/check`

- 负责人：黄禹菲
- 调用方：`ai-chat-service`（能力执行前校验）
- 是否需要登录：**不经网关对外暴露**；网关外部访问 `/internal/**` 返回 403
- 请求头：`X-User-Id`（必填）、`X-Request-Id`（必填）、`X-User-Name`（可选）
- 查询参数：`user_id`（int，≥1）、`points_cost`（int，≥0，缺省 0）
- 成功 data：`{"user_id": 1, "username": "demo", "status": "normal", "balance": 95, "points_cost": 5, "available": true}`
- 错误码：`1001` 缺少或伪造的链路身份（缺 `X-User-Id` / `X-Request-Id`，或 `X-User-Id` 非正整数）；`1005` 用户不存在或已被禁用；`3001` 积分不足
- 备注：`points_cost` 大于余额时直接返回 `3001`，能力服务应在**执行能力之前**拦截；`available` 恒为 `true`，仅在成功响应中出现。

### `POST /internal/user/points/deduct`

- 负责人：黄禹菲
- 调用方：`billing-service`（记账时扣分）
- 是否需要登录：**不经网关对外暴露**
- 请求头：`X-User-Id`（必填，必须等于 body 的 `user_id`）、`X-Request-Id`（必填，与 body 的 `request_id` 一致）
- 请求体：

```json
{
  "user_id": 1,
  "amount": 5,
  "biz_type": "call",
  "request_id": "b3f1...c2",
  "remark": "ai-chat-service 调用扣分"
}
```

- 成功 data：`{"user_id": 1, "amount": 5, "balance_after": 95, "direction": "out", "duplicated": false}`
- 错误码：`1001` 链路身份与目标用户不一致 / 缺少链路头；`1005` 用户不存在或已被禁用；`3001` 积分不足；`2001` 参数不符合 Schema（`amount` 必须 ≥ 1）
- 备注：
  - **幂等**：`request_id` 是幂等键，`t_points_log` 的 `UNIQUE(request_id, is_deleted)` 是最终防线。同一 `request_id` 重复提交返回 `code=0` 且 `duplicated=true`，`balance_after` 为**首次**扣分后的余额，余额不会二次减少。
  - **防超扣**：使用条件更新 `UPDATE t_points_account SET balance = balance - :cost, version = version + 1 WHERE user_id = :uid AND balance >= :cost`，以影响行数判定结果；不用“先查余额再更新”的读改写流程。
  - **顺序**：先插入流水占位（抢占幂等键）→ 条件更新扣减 → 回写 `balance_after` → 提交。任一步失败整体回滚，**不会留下流水但没扣分**的半成功状态。
  - 并发同 `request_id` 时，后到者命中唯一索引冲突，按重放返回首次结果。

## 6. 错误码

| code | message | 触发场景 | 号段 |
|---|---|---|---|
| 1001 | 未认证或登录已过期 | 缺 `X-User-Id`、`X-User-Id` 非正整数 | 1xxx |
| 1001 | 缺少或伪造的链路身份 | 内部接口缺链路头，或 `X-User-Id` 与目标用户不一致 | 1xxx |
| 1003 | 用户名或密码错误 | 用户不存在或口令错误（同一返回，避免枚举） | 1xxx |
| 1004 | 用户名已存在 | 注册重名（业务前置检查或唯一索引兜底） | 1xxx |
| 1005 | 用户不存在或已被禁用 | 用户不存在、已软删除、`status=disabled`；命中所有需要登录的接口（资料 / API Key / 积分 / 内部接口） | 1xxx |
| 1006 | API Key 不存在 | Key 不存在、已软删除或不属于当前用户 | 1xxx |
| 2001 | 参数不符合 Schema | 必填缺失、类型错误、枚举非法（基座统一处理） | 2xxx |
| 3001 | 积分不足 | 余额 < `points_cost`，或扣分时条件更新影响行数为 0 | 3xxx |
| 4003 | 系统内部错误 | 未预期异常、`JWT_SECRET` 未正确配置 | 4xxx |

> **号段说明**：用户/认证类错误使用 `10xx`；积分不足按指南 5.2 与 3.4 使用计费号段 `3001`，与 billing-service 判定口径一致。`request_id` 冲突属于幂等重放，不算错误，返回 `code=0` + `duplicated=true`。

## 7. 待确认事项（需在契约 Review 时与组长确认）

1. **`t_api_key.secret_hash` 扩展列**：附录 B 只列 `secret_mask`，本服务为支持密钥校验新增 `secret_hash`。若确认 API Key 本期只做管理展示、不参与鉴权，可去掉该列。
2. **账号状态校验放在哪里**：本期采用「网关只认证 + 各业务服务自查状态」的方案——网关无数据库、也无 Token 吊销能力，`JWT_SECRET` 一致即放行，所以 user-service 在每个需要登录的接口上做一次主键查询校验。代价是每个请求多一次索引查询（本服务自己的库，可接受），收益是不需要引入 Redis/黑名单等本期非目标组件。若后续要彻底解决（禁用即时生效、减少重复查询），候选方案：① 网关或专用服务维护 Token 黑名单；② 缩短 `JWT_TTL` 并配合刷新令牌。**请确认本期方案即可。**
3. **运营/管理权限**：禁用用户、查看他人数据等运营动作本期没有对外接口（`status` 只能由 SQL 或后续运营接口变更）。平台尚无角色体系，与 capability-service 契约第 6 节同类问题。被禁用账号的 API Key 也不会被自动吊销，需运营在账号层面处理。
4. **积分单位与 `price_per_call` 口径**：本服务 `amount` 为整数积分数；需确认与 capability-service 的 `price_per_call`（每次调用积分单价）同口径。当前 ai-chat 用配置项 `POINTS_COST` 上报，未按 `capability_id` 查单价，因此 billing 侧 `capability_id` 缺省为 0。
5. **API Key 是否需要参与网关鉴权**：本期网关只接受 JWT，API Key 仅做管理；若后续要求 `Authorization: ApiKey <key>` 鉴权，需要网关与 `secret_hash` 校验联动。
6. **`frozen` / `version` 语义**：`frozen` 本期恒为 0；`version` 仅作对账计数，未做乐观锁版本号比较（扣分靠条件更新的 `balance >= cost` 保证）。如需真正的版本号乐观锁（读改写场景），需要重新评审。

## 8. 测试数据计划

按指南 13.2，提供可重复导入的初始化数据（`sql/02_seed.sql`），口令均为公开演示口令 `demo123456`：

| 用户 | 状态 | 余额 | 用途 |
|---|---|---|---|
| `demo` | `normal` | 100 | 主闭环：登录 → 对话 → 扣分成功 |
| `demopoor` | `normal` | 0 | 积分不足分支：`3001` |
| `demodisabled` | `disabled` | 50 | 禁用用户分支：`1005` |

脚本使用 `INSERT ... ON DUPLICATE KEY UPDATE`（MySQL 8.0.19+ 语法），可重复执行；口令哈希为 PBKDF2-HMAC-SHA256（240000 次迭代）真实哈希，可直接登录，不含任何真实密钥。

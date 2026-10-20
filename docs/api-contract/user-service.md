# AICapabilityHub Pro · user-service 接口契约

**实现状态（2026-10-20，PR #4已合入main `651275b`）：** 已实现角色、实时授权、Key 短期 JWT 兑换及保留旧数据的迁移，详见第 7 节。统一规则见 [Pro 开发指南](../../AICapabilityHubPro-开发指南.md)及[共享契约](pro-shared.md)，不得再按原版“仅展示 Key”的目标删掉凭证校验基础。

> 负责人：黄禹菲
> 服务名：`user-service`
> 数据库：`user_db`
> 端口：8081
> 上游依赖：无（user-service 不调用任何其它服务）
> 下游调用方：`ai-chat-service`（`/internal/user/check`）、`billing-service`（`/internal/user/points/deduct`）

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401。

## 0. 通用约定

- **登录要求**：register/login 为公开入口，其余已实现用户接口需 JWT；精确 POST `/api/user/apikeys/exchange` 已有 Gateway 白名单，user 服务端已实现，不将 Key 列表/管理接口变成匿名。health 公开，ping 经网关需认证。
- **内部接口**：`/internal/user/**` 只允许可信后端经call_internal调用，Gateway对外403。现有内部依赖检查X-User-Id/Request-Id存在与ID格式；扣分另外比较body.user_id与调用者，不符1001。GET check 同样比较 query.user_id 与调用者，不符 1001。
- **身份来源**：从网关注入的 `X-User-Id` / `X-User-Name` / `X-Request-Id` 读取，服务内不重复解析 JWT。`X-User-Id` 必须是正整数，否则按未认证处理。
- **账号状态校验**：网关只校验 JWT 签名与有效期，**不知道账号是否已被禁用**，因此被禁用账号在 Token 过期前仍能通过网关。除 `register` / `login` / `/health` 外，所有接口都会自行校验账号状态（user-service 拥有 `t_user`，一次主键查询即完成）；账号不存在或 `status=disabled` 一律返回 `1005`。`register` / `login` 不做该校验，以便被禁用用户仍能收到明确的 `1005` 提示。
- **分页格式**：`data = {"list": [...], "total": 100, "page": 1, "page_size": 10}`；`page_size` 默认 10、最大 100。API Key 列表不分页（单个用户 Key 数量少，前端一次取全）。
- **软删除**：所有查询默认过滤 `is_deleted=0`；本期没有物理删除接口。
- **时间格式**：`create_time` / `update_time` 返回 `YYYY-MM-DD HH:MM:SS`（Asia/Shanghai）；登录响应的 `expire_at` 为 **UTC** 时间，格式同上。
- **金额语义**：amount、points_cost、price_per_call、cost 均为整数积分；AI 已按最新目录价传 points_cost，正常收费同价、降级零费。
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
| `role` | VARCHAR(16) | NOT NULL DEFAULT user | user/admin，普通接口不可修改 |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'normal' | `normal` 正常 / `disabled` 禁用 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

### `t_api_key`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `user_id` | BIGINT | NOT NULL, INDEX | 所属用户 |
| `name` | VARCHAR(32) | NOT NULL DEFAULT '' | 备注名 |
| `access_key` | VARCHAR(64) | NOT NULL | 对外标识，`ak_` + 24 位十六进制，未删除范围内唯一 |
| `secret_hash` | VARCHAR(128) | NOT NULL | `secret_key` 的 SHA-256 十六进制摘要，用于校验，不可逆 |
| `secret_mask` | VARCHAR(32) | NOT NULL DEFAULT '' | 展示掩码，如 `sk_****a1b2` |
| `role` | VARCHAR(16) | NOT NULL DEFAULT user | user/admin，普通接口不可修改 |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'enabled' | `enabled` / `disabled` |
| `expire_time` | DATETIME | NULL | 过期时间，NULL 表示永不过期 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

> secret_hash 是现有真实实现，secret_mask 仅供展示；两者职责不同，不能删掉摘要来恢复原版附录。现有创建响应字段为 access_key 和仅一次返回的 secret_key，后续兑换沿用其凭证语义。

### `t_points_account`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `user_id` | BIGINT | NOT NULL, UNIQUE | 一个用户一条账户 |
| `balance` | BIGINT | NOT NULL DEFAULT 0 | 可用积分余额，条件更新下永不为负 |
| `frozen` | BIGINT | NOT NULL DEFAULT 0 | 冻结积分，本期不做冻结，恒为 0 |
| `version` | INT | NOT NULL DEFAULT 0 | 变更次数，便于对账 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

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
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

**索引**：`UNIQUE(request_id, is_deleted)` 是扣分幂等的最终防线；`INDEX(user_id, is_deleted, create_time)` 支撑流水分页。

## 2. 认证与资料接口

### `POST /api/user/register`

- 负责人：黄禹菲
- 是否需要登录：**否（网关白名单，精确路径）**
- 请求体：`{"username": "demo", "password": "demo123456", "nickname": "可选，默认等于 username"}`
- 成功 data：`{"user_id": 1, "username": "demo", "nickname": "demo", "balance": 100, "initial_points": 100, "role": "user"}`
- 错误码：`2001` 参数不符合 Schema（用户名不满足 `^[a-zA-Z0-9_-]{3,32}$`、口令长度 8~128）；`1004` 用户名已存在
- 备注：**同一事务内**创建 `t_user`、`t_points_account` 与一条 `direction=in` 的赠送流水，任何一步失败整体回滚，不产生“有用户没有账户”的半成功状态。初始积分取自 `INITIAL_POINTS`（默认 100）。并发重名由 `uk_user_username` 唯一索引兜底并映射为 `1004`。

### `POST /api/user/login`

- 负责人：黄禹菲
- 是否需要登录：**否（网关白名单，精确路径）**
- 请求体：`{"username": "demo", "password": "demo123456"}`
- 成功 data：`{"token": "<JWT>", "token_type": "Bearer", "expire_at": "2026-09-17 03:00:00", "user_id": 1, "username": "demo", "role": "user"}`
- 错误码：`2001` 参数不符合 Schema；`1003` 用户名或密码错误；`1005` 用户不存在或已被禁用
- 备注：用户名不存在与口令错误返回**同一个** `1003`，避免账号枚举；凭据正确但用户被禁用时返回 `1005`。`expire_at` 为 UTC，有效期 `JWT_TTL_HOURS`（默认 24 小时）。

### `GET /api/user/profile`

- 负责人：黄禹菲
- 是否需要登录：是
- 成功 data：`{"user_id": 1, "username": "demo", "nickname": "demo", "status": "normal", "role": "user", "create_time": "...", "update_time": "..."}`
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

## 9. Pro 角色、授权与兑换现行契约（2026-10-20）

- `t_user.role` 仅 `user/admin`；注册强制 `user`，注册、登录和资料更新均拒绝未声明字段。JWT、注册/登录和资料响应返回数据库 role。
- 内部实时授权：`GET /internal/user/authorization?user_id=<当前用户ID>&required_role=admin`；调用者 X-User-Id 必须等于目标，且 X-Request-Id 非空。查询数据库当前账号角色/状态。成功 data 为 `{user_id,status,role,authorized:true}`；链路错误 1001，账号缺失/禁用 1005，权限不足按本任务确认 1006（消息“权限不足”），requestId 回传。
- Key 兑换：精确匿名 `POST /api/user/apikeys/exchange`，body 仅 `access_key`、`secret_key`。错误/不存在/禁用/过期/无效 owner 统一 1003 “API Key 凭证无效”。成功 data 为 token、token_type、expire_at UTC、expires_in、user_id、username、role。配置 `API_KEY_JWT_TTL_SECONDS` 默认 900、允许 1–3600，且不超过 Key 剩余期限。客户端无权指定角色或 TTL。Key 创建和兑换响应 no-store；Key 日期无时区时按 Asia/Shanghai 处理。
- Key 表仍只存原语义 SHA-256 secret_hash 与 secret_mask；secret 仅创建响应一次返回，兑换日志不记录凭证/Token。
- 旧库升级、管理员离线初始化和测试方式见 [升级说明](../../services/user-service/UPGRADE.md)。旧账号迁移默认 user；管理员口令隐藏交互输入，不通过公开注册或源码硬编码。

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

> 用户/认证使用10xx，积分不足3001与billing一致。扣分request_id重复且实际语义可重放时返回duplicated=true；不同字段冲突处理以实现/测试和共享契约记录，不应把所有冲突都概括为正常重放。

## 7. Pro 实现与兼容要求（2026-10-20）

1. **角色与迁移**：角色为 user/admin，注册默认 user，注册和资料修改拒绝额外字段（含 role）。登录 JWT、注册/登录/资料响应携带服务端 role。增量迁移保留旧用户，默认 user；管理员由离线工具创建，见[升级说明](../../services/user-service/UPGRADE.md)。旧 JWT 缺失 role 时 Gateway 默认 user。
2. **实时授权**：GET `/internal/user/authorization?user_id=<当前用户ID>&required_role=admin` 校验身份一致及当前 DB 状态/角色。成功 data 为 `{"user_id":1,"status":"normal","role":"admin","authorized":true}`；身份缺失/不匹配 1001，账号不存在/禁用 1005，普通用户 1006。统一 Result 保留 requestId。用户本次确认采用 1006；既有 Key 不存在码保留，按端点和消息区分。完整约定见[共享契约](pro-shared.md)。
3. **Key exchange**：精确 POST `/api/user/apikeys/exchange`，JSON 仅 `{"access_key":"<创建返回值>","secret_key":"<仅创建时展示的值>"}`，额外 role/TTL 字段拒绝。核验 SHA-256 摘要、所有者、账号、Key 状态及期限；无效凭证统一 1003 “API Key 凭证无效”。成功返回 token、token_type=Bearer、expire_at（UTC）、expires_in（秒）、user_id、username、role。`API_KEY_JWT_TTL_SECONDS` 默认 900，范围 1–3600，且 Token 不晚于 Key 到期；配置超界拒绝启动。身份与角色来自数据库。创建/兑换响应 no-store，不记录凭证或 Token。
4. **凭证与账号边界**：secret 只创建时展示，列表不返回 secret/hash，错误凭证不泄露 Key 是否存在；禁用账号不得因 Key 尚未禁用而继续兑换或管理。实时管理授权由业务调用方接入，不在 Gateway 伪造 DB 权限。
5. **积分一致性**：AI 按 capability_id 关联目录价，billing points 映射实际 cost；保留余额条件更新。扣分重放比较用户、金额、业务类型，不同则 3002；相同返回原流水。GET check 比较 query.user_id 与调用者，不符 1001。frozen 恒 0、version 为更新计数。跨服务事务不承诺分布式原子性。
6. **验收**：权限撤销/依赖故障、Key 失效/过期/摘要错误、TTL 上限、余额不足和迁移保留均需负例。单测替身与真实联调分别记录，禁止使用开发库跑会清理 qa 行的夹具。

## 8. 测试数据计划

隔离示例库使用 `sql/02_seed.sql`，口令均为公开本地演示口令 `demo123456`：

| 用户 | 状态 | 余额 | 用途 |
|---|---|---|---|
| `demo` | `normal` | 100 | 主闭环：登录 → 对话 → 扣分成功 |
| `demopoor` | `normal` | 0 | 积分不足分支：`3001` |
| `demodisabled` | `disabled` | 50 | 禁用用户分支：`1005` |

脚本重复执行会更新同名示例数据，不是保留业务数据的迁移。口令哈希为 PBKDF2-HMAC-SHA256 真实演示哈希；只用于明确的隔离/首次示例环境，现有业务库升级必须走增量迁移。

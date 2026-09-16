# billing-service

计量服务（FastAPI）。负责调用明细、幂等记账、按次扣分与用量统计，独立使用
`billing_db`；扣分只通过 `user-service` 的 `/internal/user/points/deduct`，
**不读 `user_db`**。

当前进度：**models、schemas、repository、service、api 五层已实现**，6 个接口可用；
字段、错误码与幂等语义以 `docs/api-contract/billing-service.md` 为准。

## 启动

1. 将 `.env.example` 复制为 `.env`，并按本机环境修改。
2. 执行 `python -m pip install -r requirements.txt`。
3. 执行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8083`。

`GET /health` 返回统一 Result 且 `data.status` 为 UP；`GET /api/billing/ping` 可验证
`X-User-Id`、`X-User-Name`、`X-Request-Id` 透传。Nacos 可用时服务每 5 秒发送心跳；
Nacos 暂不可用时服务仍可启动并在后台持续重试。

## 建库建表与演示数据

```powershell
$dbPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { 'root' }
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)   # 避免 PowerShell 5.1 向管道注入 BOM
Get-Content .\services\billing-service\sql\01_init.sql -Raw -Encoding UTF8 |
  docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot --default-character-set=utf8mb4
Get-Content .\services\billing-service\sql\02_seed.sql -Raw -Encoding UTF8 |
  docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot --default-character-set=utf8mb4
```

## 数据表

| 表 | 说明 |
|---|---|
| `t_call_record` | 调用明细：`request_id`（幂等键）、`user_id`、`capability_id`、`service_name`、`cost`、`call_status(success/degraded/failed)`、`duration_ms`、`model_name` |
| `t_usage_daily` | 按天用量：`stat_date`、`user_id`、`capability_id`、`call_count`、`total_cost` |

两表均含 `create_time`、`update_time`、`is_deleted` 通用字段。`t_call_record` 的
`UNIQUE(request_id, is_deleted)` 是记账幂等防线；`t_usage_daily` 的
`UNIQUE(stat_date, user_id, capability_id)` 是原子累加（`ON DUPLICATE KEY UPDATE`）的前提。

`capability_id` 缺省为 **0**（表示未关联具体能力）：当前 ai-chat 按“服务 + 固定单价”
上报，未携带能力 ID；用 0 而不是 NULL 是因为 MySQL 唯一索引不约束多个 NULL，会让
UPSERT 聚合失效。

## 接口一览

| 方法 | 路径 | 是否需要登录 |
|---|---|---|
| POST | `/internal/billing/record` | **仅服务间调用**（外部经网关访问 403） |
| GET | `/api/billing/records` | 是（仅本人明细） |
| GET | `/api/billing/usage` | 是（仅本人统计） |
| GET | `/api/billing/stat/overview` | 是（运营全局统计） |
| GET | `/api/billing/ping`、`/health` | 否 |

计费业务错误码只用 30xx 号段：`3001` 积分不足（由 user-service 透传）、
`3002` 同一 requestId 被不同调用占用；参数类错误沿用平台统一的 `2001`，
下游不可用与系统错误由基座返回 `4002` / `4003`。

## 关键设计

- **记账顺序固定**为“幂等写调用记录 → 调 user 扣分 → 累计日用量”，三步在**同一事务**
  内。明细先 `flush` 抢占 `request_id` 唯一键但不提交；扣分失败（`3001` / `1005` /
  `4002`）立即 `rollback`，明细与日用量都不落库，**不留半成功状态**。
- **幂等**：`request_id` 重复且关键字段一致时返回 `duplicated=true`，余额不变、
  用量不重复累计；关键字段不一致返回 `3002`。并发同 `request_id` 由唯一索引兜底，
  后到请求阻塞后命中重放分支，不会双扣。
- **日用量**用 `ON DUPLICATE KEY UPDATE call_count = call_count + n` 由数据库原子累加，
  避免“先查后写”的丢失更新。
- **免费能力**（`points = 0`）不发起扣分请求（用户侧要求 `amount ≥ 1`），但仍写明细与用量；
  因为少了扣分这一道校验，免费路径会单独调一次 `/internal/user/check` 校验账号状态。
- **禁用账号统一拦截**：网关只校验 JWT，**不知道账号是否已被禁用**，禁用后旧 Token 在
  有效期内仍能通过网关。billing 无 `user_db` 权限（禁止跨库），因此三个查询接口都先经
  `app/service/user_status.py` 调 `/internal/user/check`：禁用返回 `1005`，user-service
  不可用返回 `4002`。该校验在参数校验之后执行，保证 `2001` / `1001` 的优先级稳定。
- **统计口径**：`summary` / `by_service` 取自 `t_call_record` 明细，`by_day` 取自
  `t_usage_daily` 聚合表（契约第 6 节登记为待确认的“双源”方案）。
- **跨服务边界**：只调用 user-service 的内部契约，通过基座 `call_internal` 做服务发现，
  不写死地址、不读他人数据库。

## 测试

| 测试文件 | 用例数 | 覆盖内容 | 依赖数据库 |
|---|---|---|---|
| `tests/test_schemas.py` | 15 | ai-chat 实际上报字段兼容性、积分/状态边界、统计时间范围默认值与越界、出参时间与日期序列化 | 否 |
| `tests/test_api.py` | 13 | `/health` 与透传、三个查询接口的 `1001`、分页与枚举参数校验、日期范围校验、内部接口链路身份校验 | 否 |
| `tests/test_billing_db.py` | 24 | 明细 + 扣分 + 用量三写、幂等重放、`3002` 冲突、扣分失败不留半成功状态且可重试、明细分页与筛选、个人与全局统计、禁用账号在查询接口与免费记账路径被拦且可恢复 | **是** |

数据库行为测试必须连接真实 MySQL：业务表由 `sql/01_init.sql` 创建，SQLAlchemy 模型不建表，
用 SQLite 替代测不到组合唯一索引与 `ON DUPLICATE KEY UPDATE` 的真实行为。

`/internal/billing/record` 会调用 user-service，单元测试不应依赖第二个进程，因此
`tests/conftest.py` 用 `fake_user_service` 把基座的 `call_internal` 替换为内存桩，
只验证本服务的幂等、事务与统计逻辑；真实的 user↔billing 联调见下方自测命令。
测试数据统一使用 `user_id >= 900000000`，用例前后物理清理，不会污染演示数据；
数据库不可用时整组自动跳过而不是失败。

## 自测

```powershell
# 全量测试：28 个不依赖数据库的用例 + 24 个数据库行为用例（共 52）
# 数据库不可用时，数据库用例会自动跳过，不会导致失败
.\.venv\Scripts\python.exe -m pytest -q

# 启动后自测：查询接口需手动补 X-User-Id（模拟网关注入）
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8083
curl.exe -H "X-User-Id: 1" http://localhost:8083/api/billing/records
curl.exe -H "X-User-Id: 1" http://localhost:8083/api/billing/usage
curl.exe -H "X-User-Id: 1" http://localhost:8083/api/billing/stat/overview
```

`/internal/billing/record` 依赖 user-service 与 Nacos，请按指南 13.1 的顺序联调：
先启动 `docker compose`、user-service、billing-service，再把 ai-chat 的
`ENABLE_INTERNAL_CHAIN` 设为 `true`，然后：

```powershell
curl.exe -H "Content-Type: application/json" -H "X-User-Id: 1" -H "X-Request-Id: manual-bill-001" `
  -d '{\"request_id\":\"manual-bill-001\",\"user_id\":1,\"service_name\":\"ai-chat-service\",\"model\":\"mock-model\",\"points\":1,\"status\":\"success\"}' `
  http://localhost:8083/internal/billing/record
```

FastAPI 自带文档：<http://localhost:8083/docs>。

> 重复执行上一条命令（同一 `manual-bill-001`）应返回 `duplicated=true` 且余额不再减少，
> 这就是幂等键生效的证据。

## 分层约束

按 models、schemas、repository、service、api 分层扩展，路由层不写 SQL 与业务逻辑。
服务间调用必须通过 `app.core.service_call.call_internal` 访问 `/internal/**`，
不得写死其它服务地址。状态取值统一来自 `app.core.constants`，禁止魔法字符串。
repository 层只做 `add + flush`，**事务边界由 service 层控制**，因为记账是三表/三步骤
的原子操作。

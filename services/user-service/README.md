# user-service

用户服务（FastAPI）。负责注册登录、JWT 签发、API Key、积分账户与积分流水，
独立使用 `user_db`，**不调用任何其它服务**；被 `ai-chat-service`（校验积分）与
`billing-service`（扣分）通过 `/internal/**` 调用。

当前进度：**models、schemas、repository、service、api 五层已实现**，13 个接口可用；
字段、错误码与幂等语义以 `docs/api-contract/user-service.md` 为准。

## 启动

1. 将 `.env.example` 复制为 `.env`，并按本机环境修改；**`JWT_SECRET` / `JWT_ISSUER` 必须与网关一致**。
2. 执行 `python -m pip install -r requirements.txt`。
3. 执行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8081`。

`GET /health` 返回统一 Result 且 `data.status` 为 UP；`GET /api/user/ping` 可验证
`X-User-Id`、`X-User-Name`、`X-Request-Id` 透传。Nacos 可用时服务每 5 秒发送心跳；
Nacos 暂不可用时服务仍可启动并在后台持续重试。

## 建库建表与演示数据

在仓库根目录执行（`01_init.sql` 建 `user_db`、业务表与索引，`02_seed.sql` 导入
可重复执行的演示数据）：

```powershell
$dbPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { 'root' }
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)   # 避免 PowerShell 5.1 向管道注入 BOM
Get-Content .\services\user-service\sql\01_init.sql -Raw -Encoding UTF8 |
  docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot --default-character-set=utf8mb4
Get-Content .\services\user-service\sql\02_seed.sql -Raw -Encoding UTF8 |
  docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot --default-character-set=utf8mb4
```

## 数据表

| 表 | 说明 |
|---|---|
| `t_user` | 用户账号：`username`、`password_hash`（PBKDF2）、`nickname`、`status(normal/disabled)` |
| `t_api_key` | API Key：`access_key`、`secret_hash`、`secret_mask`、`status(enabled/disabled)`、`expire_time` |
| `t_points_account` | 积分账户：`balance`、`frozen`、`version` |
| `t_points_log` | 积分流水：`direction(in/out)`、`amount`、`balance_after`、`biz_type`、`request_id` |

四张表均含 `create_time`、`update_time`、`is_deleted` 通用字段，所有查询默认过滤
`is_deleted=0`；`username` 与 `access_key` 在未删除范围内唯一。

## 接口一览

| 方法 | 路径 | 是否需要登录 |
|---|---|---|
| POST | `/api/user/register` | 否（网关白名单，精确路径） |
| POST | `/api/user/login` | 否（网关白名单，精确路径） |
| GET / PUT | `/api/user/profile` | 是 |
| GET / POST | `/api/user/apikeys` | 是 |
| PUT | `/api/user/apikeys/{api_key_id}/disable` | 是 |
| GET | `/api/user/points` | 是 |
| GET | `/api/user/points/logs` | 是 |
| GET | `/internal/user/check` | **仅服务间调用**（外部经网关访问 403） |
| POST | `/internal/user/points/deduct` | **仅服务间调用**（外部经网关访问 403） |
| GET | `/api/user/ping`、`/health` | 否 |

业务错误码只用 1xxx 号段：`1003` 用户名或密码错误、`1004` 用户名已存在、
`1005` 用户不存在或已被禁用、`1006` API Key 不存在；积分不足按指南 3.4 使用
计费号段 `3001`。

## 关键设计

- **注册**：在同一事务内创建用户、积分账户与赠送流水，失败整体回滚，不会出现
  “有用户没有账户”；初始积分来自 `INITIAL_POINTS`（默认 100）。
- **登录**：口令以 PBKDF2-HMAC-SHA256 加盐哈希校验（标准库实现，不引入锁定清单外
  的依赖）；签发的 JWT 与网关同密钥、同 issuer，claim 为 `sub` + `username`。
- **扣分幂等**：`t_points_log` 的 `UNIQUE(request_id, is_deleted)` 是幂等键的最终
  防线，同一 requestId 重复提交返回 `duplicated=true` 且余额不再减少。
- **防超扣**：扣分走条件更新
  `UPDATE t_points_account SET balance = balance - :cost, version = version + 1 WHERE user_id = :uid AND balance >= :cost`，
  以影响行数判定结果，不使用“先查余额再更新”的读改写流程。
- **链路口径**：内部接口不重复解析 JWT，但校验 `X-User-Id`（与目标用户一致）与
  `X-Request-Id`（幂等键）。
- **禁用账号统一拦截**：网关只校验 JWT 签名与有效期，**不知道账号是否已被禁用**，
  禁用后旧 Token 在有效期内仍能通过网关。因此除 `register` / `login` / `/health` 外，
  所有接口都通过 `require_available_user` 先校验账号状态，账号不存在或 `status=disabled`
  统一返回 `1005`；恢复 `normal` 后同一 Token 即可继续访问。

## 测试

| 测试文件 | 用例数 | 覆盖内容 | 依赖数据库 |
|---|---|---|---|
| `tests/test_schemas.py` | 19 | 口令哈希与校验、用户名/口令边界、资料与 API Key 出参不泄露密钥、扣分入参校验 | 否 |
| `tests/test_api.py` | 18 | `/health` 与透传、白名单参数校验、8 个受保护路由的 `1001`、内部接口链路身份校验、分页边界 | 否 |
| `tests/test_user_db.py` | 30 | 注册赠送、重名 `1004`、登录 `1003`/`1005` 与 JWT claim、资料读写、API Key 幂等与越权 `1006`、流水筛选分页、内部校验、扣分幂等与余额不足不留副作用、禁用账号在全部受保护接口被拦且可恢复 | **是** |

数据库行为测试必须连接真实 MySQL：业务表由 `sql/01_init.sql` 创建，SQLAlchemy 模型
不建表，用 SQLite 替代测不到组合唯一索引（扣分幂等与用户名唯一的最终防线）。
数据统一用 `qa` 前缀创建、用例前后物理清理，不会污染 `02_seed.sql` 的演示数据；
数据库不可用时整组自动跳过而不是失败。

## 自测

```powershell
# 全量测试：37 个不依赖数据库的用例 + 30 个数据库行为用例（共 67）
# 数据库不可用时，数据库用例会自动跳过，不会导致失败
.\.venv\Scripts\python.exe -m pytest -q

# 启动后自测：注册/登录无需身份头，其余接口需手动补 X-User-Id（模拟网关注入）
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8081
curl.exe -H "Content-Type: application/json" -d '{\"username\":\"demo2\",\"password\":\"demo123456\"}' http://localhost:8081/api/user/register
curl.exe -H "Content-Type: application/json" -d '{\"username\":\"demo\",\"password\":\"demo123456\"}' http://localhost:8081/api/user/login
curl.exe -H "X-User-Id: 1" http://localhost:8081/api/user/points
curl.exe -H "X-User-Id: 1" -H "X-Request-Id: manual-001" "http://localhost:8081/internal/user/check?user_id=1&points_cost=5"
curl.exe -H "Content-Type: application/json" -H "X-User-Id: 1" -H "X-Request-Id: manual-002" -d '{\"user_id\":1,\"amount\":5,\"request_id\":\"manual-002\"}' http://localhost:8081/internal/user/points/deduct
```

FastAPI 自带文档：<http://localhost:8081/docs>。

> `demo` 是 `02_seed.sql` 的演示用户，口令 `demo123456`，初始余额 100。

## 分层约束

按 models、schemas、repository、service、api 分层扩展，路由层不写 SQL 与业务逻辑。
服务间调用必须通过 `app.core.service_call.call_internal` 访问 `/internal/**`，
不得写死其它服务地址。状态取值统一来自 `app.core.constants`，禁止魔法字符串。
repository 层只做 `add + flush`，**事务边界由 service 层控制**，因为注册与扣分都是
多表原子操作。

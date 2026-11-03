# AICapabilityHub Pro · 运维 Runbook

> 适用版本：2026-11-02 升级批（G1 容器化 / B2 readiness / B3 指标 / B4 对账）
> 读者：值班工程师（L1）。目标：**每类故障 3 步内给出可执行动作，10 分钟内判定是自愈、手工修，还是升级**。
> 所有命令都在仓库根目录执行，Windows PowerShell 与 bash（Git Bash）两种写法并列给出。

---

## 0. 先看这张表：三种部署形态的端口与日志

| 组件 | 容器名 | 容器内端口 | 宿主机 dev（`start_pro_local.py`） | compose（`--profile app`） | 日志 |
|---|---|---|---|---|---|
| MySQL | `aihub-pro-mysql` | 3306 | 3307 | 3306 | `docker logs aihub-pro-mysql` |
| Nacos | `aihub-pro-nacos` | 8848/9848 | 8849/9849 | 8848/9848 | `docker logs aihub-pro-nacos` |
| Sentinel | `aihub-pro-sentinel` | 8858 | 8859 | 8858 | `docker logs aihub-pro-sentinel` |
| gateway | `aihub-pro-gateway` | 8080 | 8080（Maven 本机） | 8080 | `docker logs aihub-pro-gateway` |
| user-service | `aicapabilityhubpro-user-service-1` | 8081 | 8081 | 8081 | `logs/runtime/user-service.err.log` |
| billing-service | `aicapabilityhubpro-billing-service-1` | 8082 | 8083 | 8082 | `logs/runtime/billing-service.err.log` |
| capability-service | `aicapabilityhubpro-capability-service-1` | 8083 | 8082 | 8083 | `logs/runtime/capability-service.err.log` |
| ai-chat-service | `aicapabilityhubpro-ai-chat-service-1` | 8090 | 8090 | 8090 | `logs/runtime/ai-chat-service.err.log` |

> **注意 8082/8083 是反的**：宿主机 dev 模式 capability=8082、billing=8083；容器镜像里 capability=8083、billing=8082。
> 排查时不要靠端口猜服务，读 `/health/ready` 响应里的 `data.service`（`scripts/acceptance_check.py` 就是这么做的）。

**唯一权威的"是否可用"判据**：四服务 `/health/ready`（真查库）+ 一次真实调用。
`/health` 和 `/ping` 只是占位，库挂了照样 200，**不能**用来判断可用性。

### 0.1 五分钟定位（一条命令看全貌）

```powershell
# PowerShell：先把 .env 里的口令读进环境变量，后面所有命令都复用（不打印明文）
$line = Get-Content deploy/.env | Where-Object { $_ -match '^MYSQL_ROOT_PASSWORD=' } | Select-Object -First 1
if ($line) { $env:MYSQL_ROOT_PASSWORD = ($line -split '=', 2)[1].Trim() }

docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
foreach ($port in 8081, 8082, 8083, 8090) {
    try {
        $code = (Invoke-WebRequest "http://127.0.0.1:$port/health/ready" -UseBasicParsing -TimeoutSec 3).StatusCode
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
    }
    Write-Output "$port -> $code"
}
python scripts/acceptance_check.py --no-call
```

```bash
# bash：导出 .env 里的变量（set -a 让变量自动 export）
set -a; . ./deploy/.env; set +a
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
for p in 8081 8082 8083 8090; do printf "%s -> " $p; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:$p/health/ready; done
python scripts/acceptance_check.py --no-call
```

`acceptance_check.py --no-call` 退出码非 0 就是有硬故障，按下面的分类往下走。

---

## 1. 故障一：数据库不可用（MySQL 挂 / 连不上 / 连接数打满）

### 症状

- 四个服务 `/health/ready` 全部返回 **503**，响应体 `data.status=NOT_READY`、`data.reason=DB_UNAVAILABLE`、`checks.db=down`。
- 业务接口返回 `code=4003`（系统内部错误）或 `4002`；网关日志出现 502/504。
- 服务日志（`logs/runtime/*.err.log` 或 `docker logs`）出现
  `Can't connect to MySQL server on 'mysql:3306'` / `(2003, "Can't connect to MySQL server")` /
  `(1040, 'Too many connections')` / `(1045, 'Access denied for user …')`。

### 三步处置

**第 1 步：分清"容器挂了"还是"库连不上"**

```powershell
docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' aihub-pro-mysql
docker exec -e MYSQL_PWD=$env:MYSQL_ROOT_PASSWORD aihub-pro-mysql mysql -uroot -N -B -e "SELECT 1, @@max_connections, (SELECT COUNT(*) FROM information_schema.PROCESSLIST);"
```

```bash
docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' aihub-pro-mysql
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" aihub-pro-mysql mysql -uroot -N -B -e "SELECT 1, @@max_connections, (SELECT COUNT(*) FROM information_schema.PROCESSLIST);"
```

- 输出 `running healthy` 且 `SELECT 1` 成功 → 库没问题，跳到第 2 步查服务侧配置。
- 输出 `exited` / `unhealthy` → 第 3 步重启并看日志。

**第 2 步：核对连接串与口令（最常见的"库里好好的，服务连不上"）**

```powershell
Get-Content deploy/.env | Select-String MYSQL_ROOT_PASSWORD   # compose 读的是这个
Get-Content .env | Select-String MYSQL_ROOT_PASSWORD          # 宿主机 dev 读的是这个
docker exec -e MYSQL_PWD=$env:MYSQL_ROOT_PASSWORD aihub-pro-mysql mysql -uroot -N -B -e "SELECT user,host FROM mysql.user WHERE user='root';"
```

```bash
grep MYSQL_ROOT_PASSWORD deploy/.env .env
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" aihub-pro-mysql mysql -uroot -N -B -e "SELECT user,host FROM mysql.user WHERE user='root';"
```

- 两处口令不一致：容器初始化时用的是**创建数据卷那一刻**的口令，改 `.env` 不会改库里的口令。
  改回原口令，或按第 3 步重建数据卷（**会丢数据，需组长批准**）。
- 连接数打满（`COUNT(*)` 接近 `max_connections`）：多半是压测/异常进程泄漏连接。
  `docker restart aihub-pro-gateway` 不解决；先按下面的 SQL 找来源，再重启对应服务。

```sql
SELECT user, host, db, COUNT(*) AS c FROM information_schema.processlist GROUP BY user, host, db ORDER BY c DESC;
SHOW VARIABLES LIKE 'max_connections';   -- compose 已设 500（4 服务×2 worker×(5+10)=120 上限）
```

**第 3 步：重启并验证（先软后硬）**

```powershell
docker restart aihub-pro-mysql
# 等 20-40 秒
docker exec -e MYSQL_PWD=$env:MYSQL_ROOT_PASSWORD aihub-pro-mysql mysqladmin -uroot ping
python scripts/acceptance_check.py --no-call
```

```bash
docker restart aihub-pro-mysql
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" aihub-pro-mysql mysqladmin -uroot ping
python scripts/acceptance_check.py --no-call
```

服务无需重启：`/health/ready` 每次真查库，库恢复后自动回 200（B2 的设计就是为了这个）。
容器起不来看 `docker logs aihub-pro-mysql --tail 100`：`No space left on device` → 走故障五；
`InnoDB: Data file … is corrupted` → **立即升级**，不要再重启。

### 升级路径

| 现象 | 升级到 | 需要带上 |
|---|---|---|
| 数据卷损坏 / 需要重建库（会丢数据） | 组长（决策）+ DBA（执行） | `docker logs` 尾部 100 行、`docker volume inspect aihub-pro-mysql-data` |
| `Access denied` 且口令确认一致 | 组长（可能是授权/初始化遗留） | `mysql.user` 查询结果 |
| 连接数持续打满、来源是业务服务 | ai-chat / billing 模块 Owner | `processlist` 快照（连续 3 次，间隔 30s） |

---

## 2. 故障二：Nacos 不可用（注册发现挂了）

### 症状

- 服务日志出现 `Nacos 注册或心跳失败，将自动重试: …`（每 5 秒一条，属于**服务自身还活着**的信号）。
- 经网关调用返回 **503** 或 `{"code":4002,"message":"下游服务暂不可用"}`；
  ai-chat 侧表现为"目录/user/billing 不可用"（它内部也是走服务发现）。
- 网关路由日志里出现 `Unable to find instance for capability-service`。
- `docker ps` 里 `aihub-pro-nacos` 不是 `Up`。

### 三步处置

**第 1 步：确认 Nacos 自身健康 + 服务是否注册成功**

```powershell
docker inspect -f '{{.State.Status}}' aihub-pro-nacos
Invoke-RestMethod http://127.0.0.1:8849/nacos/v1/console/health/readiness    # dev 形态用 8849，compose 用 8848
Invoke-RestMethod "http://127.0.0.1:8849/nacos/v1/ns/catalog/services?hasIpCount=true&withInstances=false&pageNo=1&pageSize=20&namespaceId=public"
```

```bash
docker inspect -f '{{.State.Status}}' aihub-pro-nacos
curl -s http://127.0.0.1:8849/nacos/v1/console/health/readiness
curl -s "http://127.0.0.1:8849/nacos/v1/ns/catalog/services?hasIpCount=true&withInstances=false&pageNo=1&pageSize=20&namespaceId=public"
```

- `readiness` 返回 `OK` 才算健康（Nacos 2.5 的返回值是 `OK`，不是 `UP`；返回其它值或超时 → 进第 2 步）。
- `readiness=OK` 但服务列表为空（`count=0`）→ Nacos 活着，是服务没注册上：检查服务进程/容器的 `NACOS_ADDR`
  是否指向**当前实际端口**（dev=8849、compose=nacos:8848），改完重启该服务。

**第 2 步：重启 Nacos，并确认启动耗时不拖垮服务**

```powershell
docker restart aihub-pro-nacos
# 等 30-60 秒（Nacos 2.5 standalone 冷启动约 20-40s）
docker logs aihub-pro-nacos --tail 60
```

```bash
docker restart aihub-pro-nacos
docker logs aihub-pro-nacos --tail 60
```

服务侧**不需要**跟着重启：注册客户端每 5 秒重试一次，`_register()` 成功后自动恢复。
若 5 分钟内仍不恢复，重启业务服务（它们是幂等启动的）：

```powershell
docker compose -f deploy/docker-compose.yml --profile app restart capability-service billing-service user-service ai-chat-service
```

```bash
docker compose -f deploy/docker-compose.yml --profile app restart capability-service billing-service user-service ai-chat-service
```

**第 3 步：验证"链路恢复"，而不是"端口活了"**

```powershell
python scripts/acceptance_check.py --no-call
```

```bash
python scripts/acceptance_check.py --no-call
```

必须看到 `四服务齐备 PASS` + `登录 demo PASS`。只看 `docker ps` 里 Up 是不够的：
Nacos 起来了但服务没重新注册时，网关照样 503。

### 升级路径

| 现象 | 升级到 | 需要带上 |
|---|---|---|
| `docker logs` 出现 `OutOfMemoryError` / 反复重启 | 组长（调 `JVM_XMX`） | `docker stats --no-stream aihub-pro-nacos` |
| Nacos 端口被占（8848/9848） | 组长 | `Get-NetTCPConnection -LocalPort 8848,9848` / `netstat -ano \| grep 884` |
| 单服务注册不上、其它正常 | 该服务 Owner | 服务启动日志前 50 行 + `NACOS_ADDR` 取值 |

---

## 3. 故障三：模型 401（上游鉴权失败 / 欠费）

### 症状

- 调用返回 `code=0` 且 `data.degraded=true`、`data.cost=0`、`data.error_code=5004`
  （**降级不扣分**，这是设计行为，不是计费 bug）。
- `/metrics` 里 `upstream_errors_total{error_code="5004"}` 持续增长；
  `model_call_duration_seconds{outcome=...}` 有对应计数。
- 供应商连通性测试返回 `ok=false, http_status=401/402/403`。
- ai-chat 日志出现 `上游鉴权失败` 或 `provider=… http_status=401`。

### 三步处置

**第 1 步：确认是"密钥错"还是"欠费/权限"（用管理端连通性测试，别猜）**

```powershell
# 管理员口令以部署时的设置为准（compose 首次部署见 deploy/.env 的 BOOTSTRAP_ADMIN_*）。
# 先确认这个账号真有 admin 角色：GET /api/user/profile 的 data.role 必须是 admin。
$adminUser = if ($env:ADMIN_USERNAME) { $env:ADMIN_USERNAME } else { 'admin' }
$body = @{ username = $adminUser; password = $env:ADMIN_PASSWORD } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/user/login `
  -ContentType 'application/json' -Body $body).data.token
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/user/profile -Headers @{ Authorization = "Bearer $token" } |
  Select-Object data
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/chat/providers -Headers @{ Authorization = "Bearer $token" } |
  ConvertTo-Json -Depth 6
# 记下 id 后测连通性（只返回 ok/reason/http_status/elapsed_ms，不返回密钥）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/chat/providers/1/test -Headers @{ Authorization = "Bearer $token" }
```

```bash
# 管理员口令以部署时的设置为准（见 deploy/.env 的 BOOTSTRAP_ADMIN_*）
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
TOKEN=$(curl -s -X POST http://127.0.0.1:8080/api/user/login -H 'Content-Type: application/json' \
  -d "$(ADMIN_USERNAME="$ADMIN_USERNAME" python -c 'import json,os;print(json.dumps({"username":os.environ["ADMIN_USERNAME"],"password":os.environ["ADMIN_PASSWORD"]}))')" \
  | python -c 'import sys,json;print(json.load(sys.stdin)["data"]["token"])')
curl -s http://127.0.0.1:8080/api/user/profile -H "Authorization: Bearer $TOKEN"     # data.role 必须是 admin
curl -s http://127.0.0.1:8080/api/chat/providers -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://127.0.0.1:8080/api/chat/providers/1/test -H "Authorization: Bearer $TOKEN"
```

> **管理员不可用（口令丢失 / 账号被误删）**：不要猜口令，直接幂等地再建一个管理员：
> `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_stack.ps1 -AdminUsername ops-admin -AdminPassword '<新口令>'`
> 脚本只在账号不存在时创建并初始积分，不会影响已有账号。

- `http_status=401` → 密钥失效/被吊销；`402/403` → 欠费或权限不足；`ok=true` 却仍 5004 → 走升级。

**第 2 步：轮换密钥（密文入库，需主密钥在位）**

先确认 `PROVIDER_MASTER_KEY_V1` 已配置且长度正确（AES-256-GCM 需要 32 字节的 base64）：

```powershell
(Get-Content .env | Select-String PROVIDER_MASTER_KEY_V1).Line
# 只打印长度，不打印值
[Convert]::FromBase64String($env:PROVIDER_MASTER_KEY_V1).Length   # 必须是 32
```

```bash
grep -c '^PROVIDER_MASTER_KEY_V1=.\{40,\}' .env   # 1 = 已配置
echo -n "$PROVIDER_MASTER_KEY_V1" | base64 -d | wc -c   # 必须是 32
```

然后更新供应商密钥（`api_key` 非空即轮换，**轮换后自动退回草稿态，必须重新测通再启用**）：

```powershell
Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8080/api/chat/providers/1 `
  -Headers @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' } `
  -Body '{"api_key":"sk-新的密钥","base_url":"https://api.deepseek.com","model":"deepseek-flash"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/chat/providers/1/test -Headers @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8080/api/chat/providers/1/status `
  -Headers @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' } -Body '{"status":"enabled"}'
```

```bash
curl -s -X PUT http://127.0.0.1:8080/api/chat/providers/1 -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"api_key":"sk-新的密钥","base_url":"https://api.deepseek.com","model":"deepseek-flash"}'
curl -s -X POST http://127.0.0.1:8080/api/chat/providers/1/test -H "Authorization: Bearer $TOKEN"
curl -s -X PUT http://127.0.0.1:8080/api/chat/providers/1/status -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"status":"enabled"}'
```

> 未测通直接启用会返回 `2001`——这是刻意的门禁，不要绕过。

**第 3 步：验证一次真实调用不再降级**

```powershell
python scripts/acceptance_check.py            # 期望 PASS 真实调用，degraded=False
```

```bash
python scripts/acceptance_check.py
```

若仍 `degraded=true` 且 `error_code=5004`：确认新密钥在该供应商控制台可用（余额、模型权限），
并把 `PROVIDER_ALLOWED_HOSTS` 与 `base_url` 的 host 对齐（白名单为空表示不限制，生产必须配）。

### 升级路径

| 现象 | 升级到 | 需要带上 |
|---|---|---|
| 控制台显示余额充足但仍 401/403 | 组长 → 供应商工单 | `providers/{id}/test` 返回体、调用时间戳 |
| 需要更换供应商/协议 | 组长（涉及契约与目录绑定） | 目标 base_url、模型名、协议 |
| 主密钥疑似泄露 | **立即升级组长**（安全事件） | 泄露途径、影响范围、轮换计划 |

---

## 4. 故障四：模型 429（上游限流，或平台自身限流）

### 症状

- 上游限流：`data.degraded=true`、`cost=0`、`error_code=5003`；`upstream_errors_total{error_code="5003"}` 上升。
- 平台限流**不是** 429 降级，而是直接拒绝：
  - 网关服务级限流 → HTTP **429** + `code=4001`（chat 默认 20 QPS，可通过 `GATEWAY_RATE_LIMIT_CHAT_QPS` 调）。
  - 服务内按用户限流（A4）→ `code=4001`，`rate_limited_total` 上升，`RATE_LIMIT_QPS` 默认 5/秒/worker。
- 压测或批量脚本时最典型：错误率阶梯式抬升，P95 不变但成功率掉。

### 三步处置

**第 1 步：分清"哪一层在限"**

```powershell
# 网关层限流：看 429 的来源
docker logs aihub-pro-gateway --tail 100 | Select-String "429|blocked by Sentinel|rate"
# 服务层限流 + 上游错误
(Invoke-WebRequest http://127.0.0.1:8090/metrics -UseBasicParsing).Content -split "`n" |
  Select-String "rate_limited_total|upstream_errors_total"
```

```bash
docker logs aihub-pro-gateway --tail 100 | grep -E "429|blocked|rate"
curl -s http://127.0.0.1:8090/metrics | grep -E "rate_limited_total|upstream_errors_total"
```

- `rate_limited_total` 增长、无 `5003` → 平台自身限流（第 2 步 A）。
- `upstream_errors_total{error_code="5003"}` 增长 → 上游限流（第 2 步 B）。

**第 2 步 A：平台限流——先降速，再决定是否调阈值**

```powershell
# 只读确认当前阈值
Get-Content gateway/src/main/resources/application.yml | Select-String "QPS"
# 临时放宽（重启网关生效；不要长期放宽，限流是保护不是障碍）
docker compose -f deploy/docker-compose.yml --profile app up -d gateway   # 环境变量已支持覆盖
```

```bash
grep -n "QPS" gateway/src/main/resources/application.yml
# 临时放宽示例：GATEWAY_RATE_LIMIT_CHAT_QPS=40 docker compose ... up -d gateway
```

服务内单用户限流要改 `RATE_LIMIT_QPS`（环境变量）并重启 ai-chat-service；
**注意**：内存令牌桶是每 worker 一份，多 worker 下实际速率 ≈ 配置值 × worker 数（已知限制，见 A4 备注）。

**第 2 步 B：上游限流——降并发 + 确认配额**

```powershell
# 单次探测：看上游是否恢复（返回 ok/elapsed_ms）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/chat/providers/1/test -Headers @{ Authorization = "Bearer $token" }
```

```bash
curl -s -X POST http://127.0.0.1:8080/api/chat/providers/1/test -H "Authorization: Bearer $TOKEN"
```

- `ok=true` → 上游已恢复，把压测并发降回阶梯起点（5 QPS）重试，不要继续打满。
- `http_status=429` → 供应商配额耗尽：等窗口重置，或按第 3 步换备用供应商。

**第 3 步：验证"限流正确"而不是"没有限流"**

限流生效时正确行为是：**429 + code=4001，且不产生账单、不扣分**。

```powershell
python scripts/acceptance_check.py --no-call
docker exec -e MYSQL_PWD=$env:MYSQL_ROOT_PASSWORD aihub-pro-mysql mysql -uroot -N -B -e "SELECT COUNT(*) FROM billing_db.t_call_record WHERE call_status='failed';"
```

```bash
python scripts/acceptance_check.py --no-call
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" aihub-pro-mysql mysql -uroot -N -B -e "SELECT COUNT(*) FROM billing_db.t_call_record WHERE call_status='failed';"
```

被限流的请求不应该在 `t_call_record` 里留下 `failed` 行——限流发生在执行前。

### 升级路径

| 现象 | 升级到 | 需要带上 |
|---|---|---|
| 上游 429 持续 > 30 分钟 | 组长（供应商配额谈判/多供应商） | 时间窗内 `5003` 次数、QPS 曲线 |
| 平台限流阈值需长期调整 | 组长（容量决策） | 压测报告中的 QPS/P95 与本次业务量 |
| 429 但账单里出现扣分 | **立即升级**（计费缺陷） | 具体 `request_id` 与 `t_points_log` 记录 |

---

## 5. 故障五：磁盘满

### 症状

- 写库失败：`OS error 28`、`No space left on device`、MySQL `Error writing file './…'`。
- 账单/流水写入报 `4003`，读接口正常（读不落盘）。
- Docker 构建失败：`no space left on device`、`failed to register layer`。
- 容器反复重启且日志为空（容器写日志就失败）。

### 三步处置

**第 1 步：定位是谁占的（先看，不删）**

```powershell
Get-PSDrive C | Select-Object Used,Free
docker system df
docker ps -s --format "table {{.Names}}\t{{.Size}}"
```

```bash
df -h /
docker system df
docker ps -s --format "table {{.Names}}\t{{.Size}}"
```

Docker Desktop 的 `docker.raw`/`ext4.vhdx` 是上限所在；`docker system df` 里
`BUILD CACHE` 通常是最大的可回收项（本仓库 Dockerfile 多阶段构建，缓存能吃几十 GB）。

**第 2 步：按"安全 → 需要确认"的顺序回收（**从上往下做，做到够用就停**）**

```powershell
# 安全：构建缓存与悬空镜像，不影响运行中的容器与数据卷
docker builder prune -f
docker image prune -f
# 安全：本地日志（脚本按天累积的运行日志）
Remove-Item logs/runtime/*.log -ErrorAction SilentlyContinue
```

```bash
docker builder prune -f
docker image prune -f
: > logs/runtime/gateway.err.log 2>/dev/null || true   # 单个文件清零，比 rm 更安全
rm -f logs/runtime/*.log
```

> **不要**执行 `docker system prune --volumes` / `docker volume prune`：
> 那会删掉 `aihub-pro-mysql-data`，等于清库。必须删卷时先升级组长，并先做 `scripts/backup_db.ps1` 备份。

**第 3 步：验证写入恢复**

```powershell
docker exec -e MYSQL_PWD=$env:MYSQL_ROOT_PASSWORD aihub-pro-mysql mysql -uroot -N -B -e "SELECT 1; CREATE TEMPORARY TABLE t_probe(id INT);"
python scripts/acceptance_check.py     # 完整验收：真实写一笔账单
```

```bash
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" aihub-pro-mysql mysql -uroot -N -B -e "SELECT 1; CREATE TEMPORARY TABLE t_probe(id INT);"
python scripts/acceptance_check.py
```

`acceptance_check.py` 全 PASS 才算恢复（它必须真写一条 `t_call_record` 与 `t_points_log`）。
建议同时把 MySQL 数据目录纳入容量告警（见升级路径）。

### 升级路径

| 现象 | 升级到 | 需要带上 |
|---|---|---|
| 清理后仍 >90% 占用 | 组长（扩容/迁移数据盘） | `docker system df -v` 输出、`du -sh` Top10 |
| 需要删卷/重建库 | 组长（决策）+ 备份责任人 | 备份文件路径与校验值 |
| 磁盘满期间出现过 4003 | 对账负责人 | 时间窗 + `python scripts/reconcile_billing.py` 报告 |

---

## 6. 故障六：服务起不来（进程退出 / 容器 unhealthy / 网关 502）

### 症状

- `docker compose ps` 里服务 `Restarting` / `unhealthy` / `Exited`。
- 宿主机 dev 模式：端口不监听（`GET /health/ready` 连接被拒绝），`logs/runtime/*.err.log` 有 traceback。
- 网关 502/503，nginx 502。
- 典型启动期错误：
  - `error while interpolating services.…JWT_SECRET: required variable JWT_SECRET is missing`（compose 阶段就失败）
  - `Address already in use` / `Port 8080 is occupied`（端口冲突）
  - `pydantic ValidationError` / `ModuleNotFoundError`（配置或依赖缺失）
  - `ValueError: JWT_SECRET 至少 32 字节`（密钥太短）

### 三步处置

**第 1 步：先看"起不来的是哪一层"**

```powershell
docker compose -f deploy/docker-compose.yml --profile app ps
docker compose -f deploy/docker-compose.yml --profile app logs --tail 80 gateway
docker compose -f deploy/docker-compose.yml --profile app logs --tail 80 user-service
```

```bash
docker compose -f deploy/docker-compose.yml --profile app ps
docker compose -f deploy/docker-compose.yml --profile app logs --tail 80 gateway
docker compose -f deploy/docker-compose.yml --profile app logs --tail 80 user-service
```

- **配置注入阶段失败**（报 `JWT_SECRET` 缺失）：先修 `.env`，见第 2 步 A。
- **进程起来又退出**：看日志最后 30 行，按报错关键字分派（数据库 → 故障一；Nacos → 故障二）。
- **端口冲突**：见第 2 步 B。

**第 2 步 A：补齐必填配置（JWT_SECRET / 数据库口令 / 主密钥）**

```powershell
# 生成 32 字节十六进制密钥并写入 deploy/.env（不要提交）
$secret = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLower()
(Get-Content deploy/.env) -replace '^JWT_SECRET=.*', "JWT_SECRET=$secret" | Set-Content deploy/.env -Encoding UTF8
docker compose -f deploy/docker-compose.yml --profile app config --quiet    # 退出码 0 才算配置合法
```

```bash
secret=$(openssl rand -hex 32)
python - "$secret" <<'PY'
import pathlib, re, sys
p = pathlib.Path("deploy/.env")
p.write_text(re.sub(r"(?m)^JWT_SECRET=.*$", f"JWT_SECRET={sys.argv[1]}", p.read_text(encoding="utf-8")), encoding="utf-8")
PY
docker compose -f deploy/docker-compose.yml --profile app config --quiet
```

> `JWT_SECRET` 必须与 user-service 完全一致（同一把签名/验签），否则登录成功但所有业务接口 401。
> 需要轮换时：把旧值放 `JWT_SECRET_PREVIOUS`，两端同时改，验证通过后再清空。

**第 2 步 B：解决端口冲突**

> 只想起中间件、不占业务端口：`docker compose -f deploy/docker-compose.yml up -d mysql nacos sentinel`（不带 `--profile app`）。
> 只想验证部署配置而不启动：`docker compose -f deploy/docker-compose.yml --profile app config --quiet`（退出码 0 即可）；
> 单镜像构建验证：`docker build -t aihub-pro-gateway:verify gateway`（2026-11-02 实测 exit 0，首次 10m01s，依赖层可缓存）。

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8080,8081,8082,8083,8090 -ErrorAction SilentlyContinue |
  Select-Object LocalPort, OwningProcess
# 网关在宿主机跑着，就别再起 compose 的 gateway（或先停宿主机进程）
```

```bash
netstat -ano | grep -E ":808[0-9]|:8090" | grep LISTENING
```

宿主机 dev 与 compose 两种形态**不能同时占用同一端口**。混跑时只起中间件：
`docker compose -f deploy/docker-compose.yml up -d mysql nacos sentinel`（不带 `--profile app`）。

**第 3 步：按依赖顺序拉起并验证**

```powershell
docker compose -f deploy/docker-compose.yml up -d mysql nacos sentinel
python scripts/bootstrap_stack.ps1            # 幂等：建库/迁移/管理员/目录/积分
docker compose -f deploy/docker-compose.yml --profile app up -d --build
python scripts/acceptance_check.py --no-call
```

```bash
docker compose -f deploy/docker-compose.yml up -d mysql nacos sentinel
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_stack.ps1
docker compose -f deploy/docker-compose.yml --profile app up -d --build
python scripts/acceptance_check.py --no-call
```

顺序不能颠倒：MySQL 未就绪时迁移必失败（`bootstrap_stack.ps1` 自带等待与重试）；
Nacos 未就绪时服务会注册失败但**不会退出**，表现为"容器 Up 但网关 503"。

### 升级路径

| 现象 | 升级到 | 需要带上 |
|---|---|---|
| 镜像构建失败（依赖下载、Maven 仓库） | 组长（网络/镜像源） | `docker compose build` 完整输出尾部 |
| 服务启动即 `ImportError` / 依赖缺失 | 该服务 Owner | 服务 `requirements.txt` 与 `pip freeze` 差异 |
| 迁移脚本报错（`Duplicate column` 等） | 组长（数据结构变更） | `python scripts/bootstrap_stack.ps1` 输出、`schema_migration` 表内容 |
| 需要回滚到上一版本 | 组长（发布决策） | 上一个可用的 git 提交/镜像 tag |

---

## 7. 在已有开发栈的机器上验证整栈（G2 标准动作）

开发机上 8080/3306/8848 往往已经被本地栈占着，`compose up` 会直接撞端口。用
`deploy/docker-compose.verify.yml` 覆盖一层，把整套栈搬到 28xxx 端口、容器名加 `-verify`、
数据卷独立，就能在不碰现有环境的前提下验证「空库 → 迁移 → 四服务 → 网关 → nginx」。

```bash
cd deploy
# 起（首次会构建 5 个镜像，约 10–15 分钟；之后走缓存 1 分钟）
docker compose -f docker-compose.yml -f docker-compose.verify.yml --profile app -p aihubverify up -d --build

# 等健康（四个业务服务 + mysql 应全 healthy；gateway 的 start_period 是 120s）
docker compose -f docker-compose.yml -f docker-compose.verify.yml -p aihubverify ps

# 验收入口：nginx 28088 → gateway 28080
curl -s http://127.0.0.1:28088/api/capability/market | head -c 200
# 期望 {"code":0,...,"list":[{"code":"long-summary",...}]}

# 注册 + 登录 + 真实调用（mock 口径，扣 5 分）
curl -s -X POST http://127.0.0.1:28088/api/user/register -H 'Content-Type: application/json' \
  -d '{"username":"qa_smoke","password":"qa12345678"}'
TOKEN=$(curl -s -X POST http://127.0.0.1:28088/api/user/login -H 'Content-Type: application/json' \
  -d '{"username":"qa_smoke","password":"qa12345678"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
curl -s -X POST http://127.0.0.1:28088/api/chat/completions -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"capability_id":1,"input":{"messages":[{"role":"user","content":"hi"}]}}'

# 收工（-v 连数据卷一起删，下次还是"空库"）
docker compose -f docker-compose.yml -f docker-compose.verify.yml --profile app -p aihubverify down -v
```

**2026-11-03 实测结果**：空卷首启 → 四服务 healthy、gateway healthy、nginx 200；
注册 200 / 登录 200 / 真实调用 `code=0 cost=5 record=3 usage_source=mock`。
这条路径同时验证了 `deploy/mysql/init` 基线（含 `tools` Schema 与 `images` 列）是完整的。

**三个只有整栈才暴露的坑**（已修）：

| 现象 | 根因 | 修法 |
|---|---|---|
| 网关对 `/api/**` 全部 503 `ConnectException`，但四服务 `/health/ready` 都 200 | 服务把 `127.0.0.1` 注册进 Nacos，别的容器连的是它自己 | `_advertise_host()`：显式配置 > `SERVICE_REGISTER_IP` > 容器自身 IP |
| 网关能发现实例但连不上（端口对不上） | 容器里 capability 监听 8083、billing 监听 8082，而注册用的是代码默认端口（正好互换） | compose 给四个服务显式 `SERVICE_PORT`，与 Dockerfile `--port` 一致 |
| 调用返回 `4003 系统内部错误`，billing 日志 `Unknown column 't_call_record.images'` | 增量迁移没同步进 `deploy/mysql/init` 基线，空库建表少了列 | 基线补 `images JSON NULL`；用下面的脚本自查 |

**上线前自查**（每次改迁移都跑一次）：

```bash
python scripts/devtools/check_init_drift.py        # 有漂移返回 1；--json 给机器读
```

它逐表比对 `deploy/mysql/init/*.sql` 与四个服务 `sql/01_init.sql` 的列，缺列/多列都会报出来。
建议串进 CI：这类漂移只会在"空库首启"时炸，跑 pytest 是发现不了的。

## 8. 升级路径总表（谁在什么时候接手）

| 级别 | 角色 | 触发条件 | 时限 |
|---|---|---|---|
| L1 | 值班工程师（本 runbook 执行者） | 任意故障 | 15 分钟内给出结论：已修复 / 需 L2 |
| L2 | 模块 Owner（user / capability / billing / ai-chat / gateway） | 需要改代码、改契约、改数据结构 | 1 小时内响应 |
| L3 | 组长 | 数据丢失风险、安全事件、发布回滚、容量决策 | 立即 |

升级时必须附上"三件套"：**现象（哪一步 FAIL）+ 证据（日志/SQL/metrics 片段）+ 已尝试的动作**。
没有证据的升级会被退回，因为无法复现的问题无法修。

---

## 9. 附录：一键收集诊断包

```powershell
$stamp = Get-Date -Format yyyyMMdd-HHmm
$dir = "artifacts/diag-$stamp"; New-Item -ItemType Directory -Force $dir | Out-Null
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | Out-File "$dir/docker-ps.txt" -Encoding UTF8
docker system df | Out-File "$dir/docker-df.txt" -Encoding UTF8
foreach ($c in 'aihub-pro-mysql','aihub-pro-nacos','aihub-pro-gateway') {
  docker logs --tail 200 $c *> "$dir/$c.log"
}
Get-ChildItem logs/runtime/*.log -ErrorAction SilentlyContinue | ForEach-Object {
  Get-Content $_.FullName -Tail 200 | Out-File "$dir/$($_.Name)" -Encoding UTF8
}
python scripts/acceptance_check.py --no-call *> "$dir/acceptance.txt"
Write-Output "诊断包：$dir"
```

```bash
stamp=$(date +%Y%m%d-%H%M); dir="artifacts/diag-$stamp"; mkdir -p "$dir"
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" > "$dir/docker-ps.txt"
docker system df > "$dir/docker-df.txt"
for c in aihub-pro-mysql aihub-pro-nacos aihub-pro-gateway; do docker logs --tail 200 "$c" > "$dir/$c.log" 2>&1; done
for f in logs/runtime/*.log; do [ -f "$f" ] && tail -n 200 "$f" > "$dir/$(basename "$f")"; done
python scripts/acceptance_check.py --no-call > "$dir/acceptance.txt" 2>&1
echo "诊断包：$dir"
```

诊断包含日志，**不要**直接外发：先确认没有 `sk-`、`password`、`JWT` 等敏感串
（`grep -iE "sk-|password|secret|token" artifacts/diag-*/`）。

---

## 10. 换上游密钥 / 停用供应商操作清单（P3-b）

换一次密钥或停用一个供应商，会让**所有绑定该 alias 的能力同时不可用**。界面已给出
"被 N 个能力引用"与停用前的能力清单，这里再固定一套操作顺序，避免"换完才发现谁挂了"。

1. **先看影响面**：Console → 模型服务 → 上游供应商，确认目标 alias 的「影响面」列
   （被 N 个能力引用 / 已上架 N / 市场展示 N）。这一列由能力列表聚合，不额外查库。
2. **换钥前先记住清单**：点「停用」会弹出能力清单（能力 ID + 名称 + 是否市场展示），
   把它抄进工单；这一步同时也是"停用范围"的确认。
3. **换钥**：编辑供应商 → 填新密钥 → 保存。注意：**换钥会自动把供应商退回 `draft`**
   （必须重新测试通过才能启用），此刻绑定它的能力已经返回 `2009 供应商不可用`。
4. **重测**：点「测试」，成功后才允许「启用」。
5. **恢复启用**：状态回到 `enabled`，列表上的 `待重测，影响 N 个能力` 提示消失。
6. **抽查**：用一个真实 Key 调一次 `/v1/chat/completions`，确认 `platform_cost > 0`，
   再到调用记录里核对 `model_name` 与 `api_key_id`（见第 11 节）。
7. 如果第 6 步失败，按第 2 节/第 3 节排查；此时不要再次换钥，先确认清单里的能力是否
   全部恢复。

> `draft` 状态的能力绑定在保存阶段就会被拒（`2001`，文案点名 alias 与状态），
> 所以"先绑再测"这条路已经堵住；本清单针对的是"已经绑好、事后换钥/停用"。

## 11. 按 API Key 归因排查（P6）

`t_call_record` 新增 `api_key_id`（可空）与 `entrypoint`（`web` / `platform_api` /
`openai_compat`）。历史行为 `NULL` / 空串，语义是"未知"，不参与按 Key 统计。

**Key 泄露时的标准动作**：

```sql
-- 1) 这把 Key 调过什么（只查验收/生产库，不要连开发库）
SELECT COUNT(*) AS calls, SUM(cost) AS points, MIN(create_time) AS first_at,
       MAX(create_time) AS last_at, GROUP_CONCAT(DISTINCT model_name) AS models
FROM billing_db.t_call_record
WHERE api_key_id = <KEY_ID> AND is_deleted = 0;

-- 2) 同一用户其它 Key 的分布（判断影响面是否只限一把）
SELECT api_key_id, COUNT(*) AS calls, SUM(cost) AS points
FROM billing_db.t_call_record
WHERE user_id = <USER_ID> AND is_deleted = 0 AND api_key_id IS NOT NULL
GROUP BY api_key_id ORDER BY calls DESC;
```

对应页面路径：Console → 用户与用量 → 点该用户 → 抽屉「按 Key 的调用分布」；
调用记录页可按 Key 筛选，`来源` 列区分网页调试 / 平台 API / OpenAI 兼容。

**禁用一把 Key**：设置页 → 禁用。禁用后该 Key 的后续调用返回 `1003`，其它 Key 不受
影响；创建与禁用都会写审计（`resource_type=apikey`，只含 name 与掩码后的 access_key，
不含任何密钥材料）。审计可按 `action=create|disable` 直接筛。

**排查"账单里 api_key_id 为空"**：说明这次调用没有 Key 身份——
网页调试台（`web`）、历史数据，或调用链路上某一跳丢了 `X-User-Key-Id`。
先确认请求头经网关（网关会剥离外部伪造的同名头，只有网关能写入），
再检查 ai-chat 的 `call_internal` 是否带上了该头。

## 12. 日预算（P10）

- 设置：Console → 用户与用量 → 用户行 → 抽屉「日预算」→ 输入整数（0 = 不限）→ 保存。
  变更即时生效，无需重启任何服务（`points_service` 每次按库里的值判断）。
- 语义区分：`3001` 是**余额不足**，`3003` 是**当日预算超限**；后者当天不再产生账单。
- 审计：`resource_type=user, action=budget`，before/after 都记 `daily_points_limit`；
  同值重复提交不写审计。
- 恢复不限：把预算改回 `0`，列表与抽屉都会显示「不限」。

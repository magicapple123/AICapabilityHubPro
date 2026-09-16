# AI 能力开放平台（AI Capability Hub）

这是按《AI能力开放平台-开发指南》实现的可运行 Monorepo：Spring Cloud Gateway 承担统一治理（JWT 鉴权、身份透传、Sentinel 限流、`/internal/**` 隔离），四个 Python 服务各自独立建库并完成业务闭环——user-service（注册登录、API Key、积分账户与流水）、capability-service（分类、能力登记与上下架、能力市场）、billing-service（幂等记账、扣分联动、用量统计）、ai-chat-service（多轮对话落库，Mock 或 OpenAI 兼容真实模型，超时自动降级不计费）。前端包含登录/注册、能力市场、在线调试台、调用记录、开发者中心与运营后台六个页面，全部经网关访问。Nginx 作为前端生产入口，负责静态资源托管和 `/api/**` 反向代理，Spring Cloud Gateway 仍是唯一后端网关。

## 架构简图

    浏览器
      ├─ 开发：Vite（5173）── /api 代理 ──┐
      └─ 生产：Nginx（80）── 静态文件 + /api ─┤
                                             ▼
    Spring Cloud Gateway（8080）── Nacos（8848/9848）
          │ lb:// 服务发现
          ├── user-service（8081）──── user_db
          ├── capability-service（8082） capability_db
          ├── billing-service（8083）── billing_db
          └── ai-chat-service（8090）── ai_chat_db
                              │
                   MySQL 8.4（3306）／Sentinel（8858）

Nginx 不替代网关：网关仍负责 JWT、限流、路由和身份透传。网关校验 JWT 后注入 X-User-Id、X-User-Name、X-Request-Id。服务间调用只允许 /internal/**，前端只通过 Nginx 或 Vite 的 `/api/**` 访问网关；每个服务只连接自己的数据库。

## 锁定版本与端口

| 组件 | 版本/端口 |
|---|---|
| JDK / Maven | JDK 21 / Maven 3.9.x |
| Spring Boot / Cloud / Alibaba | 3.5.x / 2025.0.x / 2025.0.0.0 |
| Python / FastAPI / Uvicorn | 3.12 / 0.115+ / 0.30+ |
| Node / React / pnpm | Node 24 / React 19.2 / pnpm |
| Web UI | Tailwind CSS 4、GSAP ScrollTrigger、Ant Design 5 |
| MySQL / Nacos / Sentinel | 8.4 / 2.5.1 / 1.8.10 |
| Nginx | 1.27-alpine（生产前端入口） |
| 网关 / Python 服务 | 8080 / 8081、8082、8083、8090 |
| 中间件 / 前端 | MySQL 3306；Nacos 8848、9848；Sentinel 8858；Vite 5173；Nginx 80（可配置） |

四个独立数据库为 user_db、capability_db、billing_db、ai_chat_db。所有响应统一为：

    {"code":0,"message":"success","data":{},"requestId":"..."}

错误码按 1xxx 认证、2xxx 能力、3xxx 计费、4xxx 系统、5xxx 模型划分。

## 环境要求

在 Windows PowerShell 中确认：

    java -version       # JDK 21
    mvn -v              # Maven 3.9
    python --version    # Python 3.12
    node -v             # Node 24
    pnpm -v
    docker -v

Docker Desktop 必须处于运行状态。首次启动前在仓库根目录设置网关签名密钥（至少 32 个 UTF-8 字节）：

    $env:JWT_SECRET = 'change-this-local-secret-to-at-least-32-bytes'

不要把真实 .env、Token、密码或模型 Key 提交到仓库。

## 从零启动

### 1. 启动中间件并自动建库

    Set-Location .\deploy
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    docker compose up -d --build
    docker compose ps

这条命令会启动 MySQL、Nacos、Sentinel，并构建启动 Nginx。Nginx 默认监听 `http://localhost`，把 `/api/**` 转发到宿主机的 `host.docker.internal:8080`。如果网关部署在别处，在 `deploy/.env` 修改 `NGINX_GATEWAY_UPSTREAM=主机名或IP:端口` 后重新执行 `docker compose up -d --build nginx`。只启动中间件时可执行 `docker compose up -d mysql nacos sentinel`。

MySQL 首次创建数据卷时会按文件名顺序执行 `deploy/mysql/init/` 下的全部脚本：`01_create_databases.sql` 创建四个库，`02_user_service.sql` ~ `05_ai_chat_service.sql` 建各服务业务表并写入演示数据（`demo` / `demopoor` / `demodisabled` 三个用户，口令均为 `demo123456`；2 个分类、3 个能力；若干调用流水）。**首次 `docker compose up -d` 后库表与演示数据即就绪，无需手工导入。**

这些文件是从 `services/*/sql/*.sql` 复制生成，修改请以服务目录为准并同步本文件。若已有旧数据卷（初始化脚本不会重复执行），可在仓库根目录手动导入（脚本均幂等，`CREATE ... IF NOT EXISTS` 与 `INSERT ... ON DUPLICATE KEY UPDATE`）：

    Set-Location D:\AICapabilityHub
    $dbPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { 'root' }
    Get-Content .\services\user-service\sql\01_init.sql -Raw | docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot
    Get-Content .\services\user-service\sql\02_seed.sql -Raw | docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot
    Get-Content .\services\capability-service\sql\01_init.sql -Raw | docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot
    Get-Content .\services\capability-service\sql\02_seed.sql -Raw | docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot
    Get-Content .\services\billing-service\sql\01_init.sql -Raw | docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot
    Get-Content .\services\billing-service\sql\02_seed.sql -Raw | docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot
    Get-Content .\services\ai-chat-service\sql\01_init.sql -Raw | docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot

### 2. 启动网关

    Set-Location ..\gateway
    $env:JWT_SECRET = 'change-this-local-secret-to-at-least-32-bytes'
    mvn -q -DskipTests package
    mvn spring-boot:run

也可以执行：

    java -jar target\api-gateway-0.1.0-SNAPSHOT.jar

### 3. 启动四个 Python 服务

每个服务使用自己目录内的独立 `.venv`。打开四个新的 PowerShell 窗口，分别执行对应的完整命令。

窗口一，启动 user-service：

    Set-Location D:\AICapabilityHub\services\user-service
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8081

窗口二，启动 capability-service：

    Set-Location D:\AICapabilityHub\services\capability-service
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8082

窗口三，启动 billing-service：

    Set-Location D:\AICapabilityHub\services\billing-service
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8083

窗口四，启动 ai-chat-service：

    Set-Location D:\AICapabilityHub\services\ai-chat-service
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8090

每个服务的 .env.example 已预填服务名、端口和对应库名。启动后可在 Nacos 控制台 http://localhost:8848/nacos（nacos/nacos）查看实例。

### Nacos 模型配置热更新

ai-chat-service 默认读取 Nacos 配置 `ai-chat-service-model.json`，统一使用 `DEFAULT_GROUP`；复制统一基座运行的 demo-service 默认读取 `demo-service-model.json`。JSON 配置仅包含以下三个字段，不要增加未实现的字段：

    {
      "use_mock": true,
      "model_base_url": "https://api.example.com/v1",
      "model_api_key": "replace-me"
    }

服务启动时先通过 Nacos 配置接口拉取配置，之后每 5 秒检查一次变更；发布有效变更后会更新运行时快照，无需重启服务。配置读取不启用 SDK 磁盘快照，不把模型 Key 写入工作区缓存。本地 `.env` 中的同名配置是安全回退：Nacos 暂不可用、配置为空或格式无效时，服务继续使用本地值或最近一次有效配置。

`use_mock=true` 时 ai-chat-service 返回固定 Mock 回复且不访问任何外部地址；`use_mock=false` 时按 `model_base_url + /chat/completions` 调用 OpenAI 兼容接口（超时、最大 token、系统提示词走 `.env`）。模型超时（`5001`）或响应异常（`5002`）时返回兜底话术、标记 `degraded` 且**不计费**，闭环不中断。

以下 Windows PowerShell 示例发布 ai-chat-service 的配置；若要测试统一基座，把 `$dataId` 改为 `demo-service-model.json`。示例只使用占位值 `replace-me`，命令不打印配置内容；不要把真实 Key 写入共享脚本、终端输出或日志。

    $dataId = 'ai-chat-service-model.json'
    $modelConfig = @{
        use_mock = $true
        model_base_url = 'https://api.example.com/v1'
        model_api_key = 'replace-me'
    } | ConvertTo-Json -Compress
    Invoke-RestMethod `
        -Method Post `
        -Uri 'http://localhost:8848/nacos/v1/cs/configs' `
        -ContentType 'application/x-www-form-urlencoded' `
        -Body @{ dataId = $dataId; group = 'DEFAULT_GROUP'; type = 'json'; content = $modelConfig } |
        Out-Null
    Write-Host 'Nacos 模型配置发布请求已提交，未输出配置内容。'

### 4. 启动前端

    Set-Location D:\AICapabilityHub\web
    pnpm install
    pnpm dev

打开 http://localhost:5173（若端口被占用，改 `web/.env` 的 `VITE_PORT` 即可，网关 CORS 已放行本地任意端口）。前端工作台包含六个页面，全部经网关 `/api/**` 访问后端：

| 页面 | 路由 | 数据来源 |
|---|---|---|
| 登录 / 注册 | `/login`、`/register` | `/api/user/login`、`/api/user/register` |
| 工作台首页 | `/` | 视觉首页（GSAP ScrollTrigger） |
| 能力市场 | `/capabilities` | `/api/capability/market`、`/market/categories` |
| 在线调试台 | `/chat` | `/api/chat/completions`、`/chat/sessions`、`/chat/sessions/{id}/messages` |
| 调用记录 | `/usage` | `/api/user/points`、`/api/billing/usage`、`/api/billing/records` |
| 开发者中心 | `/settings` | `/api/user/profile`、`/apikeys`、`/points`、`/points/logs` |
| 运营后台 | `/console` | `/api/capability/categories`、`/api/capability`（登记/上下架）、`/api/capability/manage`、`/api/billing/stat/overview` |

使用 Tailwind CSS 4 完成布局与视觉样式，GSAP ScrollTrigger 负责首页滚动动效。**默认前端使用本地占位登录**（`VITE_USE_MOCK_LOGIN=true`），签发的是占位 Token 而非合法 JWT，因此除首页外的数据页面会在顶部显示提示条并返回 401；请在 `web/.env` 把 `VITE_USE_MOCK_LOGIN` 设为 `false` 后重启，用演示账号 `demo / demo123456` 登录，或把 `VITE_DEV_TOKEN` 配置为 `DevTokenTool` 签发的 JWT（仅开发用途）。

此时也可以使用 Nginx 提供的生产构建：打开 http://localhost，或执行 `curl.exe http://localhost/nginx-health` 检查 Nginx。Nginx 镜像构建时使用 `deploy/.env` 中的 `VITE_API_BASE_URL` 和 `VITE_USE_MOCK_LOGIN`；切换这些值后需要重新构建 `nginx` 服务。

如果只想使用 Nginx 而不启动 Vite：

    Set-Location D:\AICapabilityHub\deploy
    docker compose up -d --build nginx

默认 Nginx 端口为 80；端口被占用时，在 `deploy/.env` 设置 `NGINX_PORT=8088`，然后访问 http://localhost:8088。

## DevTokenTool：获取本地联调 JWT

网关配置的密钥与工具必须一致。先在同一 PowerShell 设置 JWT_SECRET，再执行：

    Set-Location D:\AICapabilityHub\gateway
    mvn -q -DskipTests package
    .\mvnw.cmd -q exec:java '-Dexec.mainClass=com.aicapabilityhub.gateway.tool.DevTokenTool' '-Dexec.args=1 dev-user'

工具会打印 Token 并立即用同一密钥校验。请把输出临时放入环境变量，不要写入仓库：

    $token = '<上一步输出的 JWT>'

## 自测命令

直连服务（调试时手动补透传头）：

    curl.exe http://localhost:8081/health
    curl.exe -H "X-User-Id: 1" -H "X-User-Name: dev-user" http://localhost:8081/api/user/ping
    curl.exe -H "X-User-Id: 1" http://localhost:8090/api/chat/ping
    curl.exe -H "Content-Type: application/json" -H "X-User-Id: 1" -d '{"messages":[{"role":"user","content":"你好"}]}' http://localhost:8090/api/chat/completions

经网关访问：

    curl.exe -H "Authorization: Bearer $token" http://localhost:8080/api/user/ping
    curl.exe -H "Authorization: Bearer $token" http://localhost:8080/api/capability/ping
    curl.exe -H "Authorization: Bearer $token" http://localhost:8080/api/billing/ping
    curl.exe -H "Authorization: Bearer $token" http://localhost:8080/api/chat/ping
    curl.exe -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"你好"}]}' http://localhost:8080/api/chat/completions

经 Nginx 访问（网关 JWT、统一 Result 和路由规则不变）：

    curl.exe http://localhost/nginx-health
    curl.exe -H "Authorization: Bearer $token" http://localhost/api/user/ping
    curl.exe -H "Authorization: Bearer $token" http://localhost/api/capability/ping

通过服务发现定位器检查四个服务的健康状态（无需 Token）：

    curl.exe http://localhost:8080/user-service/health
    curl.exe http://localhost:8080/capability-service/health
    curl.exe http://localhost:8080/billing-service/health
    curl.exe http://localhost:8080/ai-chat-service/health

/health、注册/登录和能力市场白名单不需要 Token；任何外部 /internal/** 请求都返回 403。业务错误仍用 HTTP 200，通过 code 判断；网关认证失败是 HTTP 401、code=1001；触发限流是 HTTP 429、code=4001（规则见 `application.yml` 的 `gateway.rate-limit`，默认按路由 ID 限流，可用 `GATEWAY_RATE_LIMIT_*_QPS` 环境变量覆盖，`GATEWAY_RATE_LIMIT_ENABLED=false` 可临时关闭）。

## 常见问题

- Docker 无法连接：确认 Docker Desktop 已启动，并在 deploy 目录重试 docker compose up -d。
- Docker Hub 拉取超时：为 Docker Desktop 配置组织允许的 HTTPS 代理或镜像代理，镜像名与固定 tag 不得改成其他版本。
- Nginx 构建下载 npm 依赖超时：在 `deploy/.env` 临时设置 `NPM_REGISTRY=https://registry.npmmirror.com`（或组织批准的 npm 镜像）后执行 `docker compose up -d --build nginx`；依赖版本仍由 `pnpm-lock.yaml` 锁定。
- Nginx 返回 502：确认网关已经启动并监听 8080；检查 `deploy/.env` 的 `NGINX_GATEWAY_UPSTREAM`，宿主机服务默认使用 `host.docker.internal:8080`。
- Nginx 无法启动：检查 80 端口是否被占用；在 `deploy/.env` 设置 `NGINX_PORT` 为可用端口，并执行 `docker compose up -d --build nginx`。
- Nginx 页面空白或资源 404：确认已使用 `--build` 重新构建镜像；前端资源在镜像内，不需要也不应提交 `web/dist`。
- Nacos 看不到服务：核对 .env 中 SERVICE_NAME、SERVICE_PORT、NACOS_ADDR，查看注册日志；Nacos 暂不可用时基座会重试且不阻止 HTTP 服务启动。
- 网关 503 / service not found：服务尚未注册、服务名或端口不匹配；确认服务名全小写且以 -service 结尾。
- 返回 1001：缺少或过期 JWT；检查 Authorization: Bearer 和 JWT_SECRET 是否与签发工具一致。
- 下游没有身份头：只有经网关才会自动注入；直连调试需手动添加 X-User-Id 等头。
- Python 连不上 MySQL：检查 3306、对应库名和账号；示例路由不要求数据库连接，建表脚本可在库创建后执行。
- 跨域：网关的 CORS 只放行 `http://localhost:[任意端口]` 与 `http://127.0.0.1:[任意端口]`（本地 Vite 端口可能被占用而调整，例如 5173 → 5174）；非本地来源一律拒绝，前端不要直连 Python 端口。
- 端口占用：按指南端口表释放占用后再启动，不要随意改变服务名与路由约定。
- 跨主机联调：可把 Uvicorn 改为 `--host 0.0.0.0`，同时将 `SERVICE_HOST` 设置为网关可访问的实际 IP，禁止向 Nacos 注册 `0.0.0.0`。
- 依赖安装失败：保持锁定的大版本，禁止擅自换到 Python 3.13、Boot 4、Nacos 3 或 MySQL 9。

## 骨架自检

    Set-Location .\gateway
    mvn -q -DskipTests package

    # 在任一服务目录
    python -c "import app.main; print('import ok')"

    Set-Location ..\web
    pnpm build

若 Docker Desktop 引擎未运行，先启动引擎再执行容器与全链路验收。Nginx 镜像首次构建需要拉取 Node 24 和 Nginx 基础镜像。

## 目录

    D:\AICapabilityHub
    ├─ deploy/                       # Nginx、MySQL、Nacos、Sentinel
    │  └─ nginx/                     # Nginx 配置与前端多阶段构建文件
    ├─ gateway/                      # 唯一 Java 网关
    ├─ platform-py/service-template/ # Python 可复制基座
    ├─ services/                     # 四个 Python 服务
    ├─ web/                          # React 前端
    ├─ docs/api-contract/            # 接口契约模板
    ├─ CONTRIBUTING.md
    └─ AI能力开放平台-开发指南.md     # 权威规范（不修改）

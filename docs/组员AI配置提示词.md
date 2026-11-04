# 给组员的 AI 配置提示词

> 用法：把下面 **分割线之间的全部内容**（从「# 任务」到最后一个字）复制给组员的 AI 助手。
> 组员需要先把 `deploy/.env` 放到仓库目录里（由组长私下发送），其余全部由 AI 完成。

---

# 任务

你在一台 Windows 电脑上，替我把一个已经容器化的项目完整跑起来，并逐项验证它能用于录屏演示。
**验收标准是：真实调用一次上游模型成功、账单与积分对得上。** 不是"容器起来了"就算完成。

- 仓库：`https://github.com/magicapple123/AICapabilityHubPro.git`（分支 `main`，提交需 ≥ `9a70373`）
- 目标目录：`D:\AICapabilityHubPro`（若已存在则先确认是不是这个仓库，不要覆盖用户已有改动）
- 入口地址：`http://localhost`（容器内 Nginx 80 端口）
- 演示账号：`demo` / `demo123456`

# 背景（供你判断，不必向我复述）

6 个可独立部署的服务：网关（Java）、用户、能力目录、计费、AI 执行（4 个 Python）、前端（React），
加 MySQL / Nacos / Sentinel。全部由 `deploy/docker-compose.yml` 编排，前端产物打进 Nginx 镜像。

启动时会自动执行 `deploy/mysql/init/*.sql`，其中 `07_demo_seed.sql` 负责把演示数据整理好：
2 个供应商、4 个能力、demo 账号余额 100。**这些只在数据库卷首次创建时执行。**

# 硬性约束（违反任何一条，本次任务即失败）

1. **绝对不要自行创建或修改 `deploy/.env`**，尤其是不要改动 `PROVIDER_MASTER_KEY_V1`。
   该值必须与种子里的供应商密文匹配，改了会导致所有模型调用失败。
   如果文件不存在，停下来告诉我，让我放进去。
2. **绝对不要为了让检查通过而把 `USE_MOCK` 改成 `true`**。那会让平台返回假回复。
   真实调用失败就如实报告失败，不要伪造成功。
3. **不要执行 `docker compose down -v`**、不要删除数据卷、不要 `docker system prune`。
   除非我明确要求。
4. **不要修改仓库里的任何文件、不要 `git commit`、不要 `git push`**。
   需要临时脚本就放到仓库外的目录，任务结束后删除。
5. **不要在任何输出中打印完整密钥**。检查 `.env` 时只报告"存在/长度/前缀 6 位"，
   不要回显 `MODEL_API_KEY`、`JWT_SECRET`、`MYSQL_ROOT_PASSWORD` 的值。
6. 不要绕过失败步骤继续往下走。每一步有验收门，不过就停下报告。

# 执行步骤

## Step 0 · 环境自检

```powershell
docker version
docker compose version
```

再确认：Docker Desktop 已启动（命令不报错即视为已启动）、磁盘可用 ≥ 10 GB。

**验收门**：两条命令都有 Client 与 Server 版本输出。否则停下，让我启动 Docker Desktop。

## Step 1 · 获取代码

```powershell
git clone https://github.com/magicapple123/AICapabilityHubPro.git D:\AICapabilityHubPro
cd D:\AICapabilityHubPro
git log --oneline -1
```

若目录已存在：先 `git -C D:\AICapabilityHubPro status` 看是否有未提交改动；
有就先停下问我，不要 `reset` 或 `checkout`。

**验收门**：`git log -1` 的哈希以 `9a70373` 或更晚的提交开头。

## Step 2 · 检查配置文件

```powershell
Test-Path D:\AICapabilityHubPro\deploy\.env
```

不存在 → **停下**，告诉我"请把 deploy/.env 放到 deploy 目录"。

存在 → 只检查以下键是否**存在且非空**，不要打印值：

`MYSQL_ROOT_PASSWORD`、`JWT_SECRET`、`PROVIDER_MASTER_KEY_V1`、`USE_MOCK`、`MODEL_API_KEY`、`MODEL_NAME`、`OPENAI_COMPAT_MODEL_MAP`

并且确认 `USE_MOCK=false`（这一项可以显示）。

**验收门**：以上全部存在且非空，`USE_MOCK=false`。任何一项缺失 → 停下报告缺哪个。

## Step 3 · 构建并启动

```powershell
cd D:\AICapabilityHubPro\deploy
docker compose --env-file .env --profile app up -d --build
```

首次构建要拉 Maven / PyPI / npm 依赖，**10～25 分钟属正常**，不要中途中断。
如果超过 30 分钟没有进展，抓最后 40 行输出报告给我。

**验收门**：命令退出码为 0，且出现 `Container ... Started`。

## Step 4 · 等所有容器健康

```powershell
docker compose --env-file .env --profile app ps
```

**验收门**：9 个容器全部 `healthy`（`gateway` 最慢，最长等 3 分钟）。
若有容器是 `unhealthy` 或 `restarting`：

```powershell
docker compose --env-file .env --profile app logs --tail 60 <服务名>
```

把日志贴给我，**不要**自己删卷重来。

## Step 5 · 校验演示种子

```powershell
$dbpwd = (Select-String -Path .env -Pattern '^MYSQL_ROOT_PASSWORD=').Line -replace '^MYSQL_ROOT_PASSWORD=',''
docker exec -e MYSQL_PWD=$dbpwd aihub-pro-mysql mysql -uroot -N -e "SELECT COUNT(*) FROM ai_chat_db.t_model_provider WHERE is_deleted=0; SELECT COUNT(*) FROM capability_db.t_capability WHERE is_deleted=0; SELECT balance FROM user_db.t_points_account WHERE user_id=1;"
```

**验收门**：三行输出依次为 `2`、`4`、`100`。

若供应商是 0、能力是 3：说明数据库卷是旧的（种子只在首次建库执行）。
先问我，得到同意后再执行 `docker compose --env-file .env --profile app down -v` 重建。

## Step 6 · 业务冒烟（最关键，必须真实调用）

### 6.1 登录并创建 API Key

```powershell
$B = "http://localhost"
$login = Invoke-RestMethod -Method Post -Uri "$B/api/user/login" -ContentType "application/json" -Body '{"username":"demo","password":"demo123456"}'
$token = $login.data.token
$keyResp = Invoke-RestMethod -Method Post -Uri "$B/api/user/apikeys" -Headers @{Authorization="Bearer $token"} -ContentType "application/json" -Body '{"name":"video-demo"}'
$key = $keyResp.data.secret_key
"key prefix: " + $key.Substring(0,6)
```

若接口路径报 404，先查 `D:\AICapabilityHubPro\services\user-service\app\api\v1\apikeys.py` 确认实际路由，不要猜。

### 6.2 模型列表

```powershell
$models = Invoke-RestMethod -Uri "$B/v1/models" -Headers @{Authorization="Bearer $key"}
$models.data.id
```

**验收门**：只返回一个 `deepseek-chat`。
返回多个（如 `deepseek-flash`、`chat-completions`）说明 `.env` 里的 `OPENAI_COMPAT_MODEL_MAP` 没生效，报告我。
返回 HTML 或 405 说明 Nginx 没代理 `/v1`，检查镜像是否为最新代码（`git log -1`）。

### 6.3 真实对话

> 这里用英文提问，是为了避开 Windows PowerShell 5.1 传中文 body 时的编码坑；
> 验证的是链路是否真的通到上游，不是中文能力。

```powershell
$body = @{ model="deepseek-chat"; messages=@(@{role="user"; content="Say hello in one short sentence."}); max_tokens=60 } | ConvertTo-Json -Depth 5
$r = Invoke-RestMethod -Method Post -Uri "$B/v1/chat/completions" -Headers @{Authorization="Bearer $key"} -ContentType "application/json" -Body $body
$r.choices[0].message.content
$r.usage
```

**验收门**：返回非空内容、`usage.total_tokens > 0`，且不是固定模板 / "mock" / "暂时不可用" 之类的兜底话术。
命中兜底文案就**停下报告**，不要改配置硬凑。

### 6.4 账单与积分

```powershell
docker exec -e MYSQL_PWD=$dbpwd aihub-pro-mysql mysql -uroot -t -e "SELECT id,capability_id,model_name,cost,call_status,entrypoint FROM billing_db.t_call_record ORDER BY id DESC LIMIT 3; SELECT balance FROM user_db.t_points_account WHERE user_id=1;"
```

**验收门**：
- 最新一条账单 `call_status=success`、`cost=5`、`entrypoint=openai_compat`、`model_name` 非空
- `balance` 从 100 变成 95

### 6.5 流式（可选但建议）

```powershell
curl.exe -N -s -X POST "$B/v1/chat/completions" -H "Authorization: Bearer $key" -H "Content-Type: application/json" -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"hi"}],"stream":true}' | Select-String "data:"
```

**验收门**：能看到多行 `data:` 且包含 `[DONE]`。

## Step 7 · 输出报告

按下面格式给我，**每条都要附上你实际看到的输出片段**：

| 检查项 | 期望 | 实测 | 判定 |
|---|---|---|---|
| 代码版本 | ≥ 9a70373 | | |
| 容器健康 | 9/9 healthy | | |
| 供应商/能力 | 2 / 4 | | |
| demo 余额（调用前） | 100 | | |
| /v1/models | 仅 deepseek-chat | | |
| 真实对话 | 非 mock，tokens>0 | | |
| 账单 | success / 5 分 / openai_compat | | |
| 余额（调用后） | 95 | | |

最后再给三行：
1. 入口地址（含端口，若改过 `NGINX_PORT` 要说明）
2. 你创建的 Key 名称与掩码前缀（不要给完整值）
3. 仍需人工处理的事项（若有）

# 故障处置速查

| 现象 | 处理 |
|---|---|
| 端口 80 被占用 | 改 `deploy/.env` 的 `NGINX_PORT=8088`，`up -d`，入口变 `http://localhost:8088`；改完报告我 |
| gateway 一直不 healthy | `logs gateway --tail 80`；多为 Nacos 未就绪，等 2 分钟再看；仍失败则报告 |
| 对话返回 mock / 兜底文案 | 报告 `USE_MOCK` 与 `MODEL_API_KEY` 是否存在（不打印值），**不要**改配置重试 |
| `/v1/models` 返回 HTML | 镜像不是最新代码，`git log -1` 确认版本，重新 `up -d --build nginx` |
| 供应商 0 / 能力 3 | 旧数据卷，问我是否允许 `down -v` 重建 |
| 401 且所有请求都失败 | `JWT_SECRET` 缺失或不一致，报告我，不要自行生成 |

# 完成后不要做的事

- 不要输入 `git add` / `commit` / `push`
- 不要保留临时脚本（清理到仓库外并删除）
- 不要开始录屏前忘记告诉我：**录制前要重置演示数据**

---

（以下是给组长看的，不要执行）

录制前重置命令：

```powershell
cd D:\AICapabilityHubPro\deploy
docker compose --env-file .env exec -T mysql mysql -uroot -p你的密码 --default-character-set=utf8mb4 < mysql/init/07_demo_seed.sql
```

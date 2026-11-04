# Linux 部署

需要 Docker Engine、Docker Compose v2、Bash 4+ 与常见 GNU 工具（sha256sum、awk、id）。不需要宿主机安装 Python、Node、Java 或 PowerShell。内部服务端口默认绑定宿主机 loopback；生产环境应由 TLS 反向代理转发到 Nginx。

## 演示 / 录屏环境（Windows + Docker Desktop）

录屏、答辩这类「要在一台干净机器上把平台跑起来」的场景，不要走下面的 Linux 验收流程，
按 [docs/演示环境搭建-容器版.md](../docs/演示环境搭建-容器版.md) 操作：使用负责人提供的
`deploy/.env`（已含上游模型 Key 与固定主密钥）直接启动，首次建库会自动执行
`mysql/init/07_demo_seed.sql`，把供应商、能力、演示账号整理成可展示状态。

> ⚠️ 演示环境**不要**执行下面第 1 步的 `.env` 生成命令。它会重新生成
> `PROVIDER_MASTER_KEY_V1`，而 07 种子里的供应商密钥正是按原主密钥加密的；
> 换了主密钥就解不开，表现为能力调用失败（对话、摘要、生图全挂）。

## 四条命令：独立 Linux 验收栈

以下四条命令在已克隆仓库的根目录、同一个 Bash 终端依次运行。使用 aihub-pro-verify 项目、独立数据卷 aihub-verify-mysql-data 与验收端口；请先确认 8080、8081、8082、8083、8090、23307、28088、28848、29848、28858 均未占用。该流程不连接已有开发库或 opsdemo 业务库。

**1. 生成本地配置。** 随机口令只写入权限为 600 的 deploy/.env，不显示在终端；文件已存在时拒绝覆盖。已有部署沿用其配置并跳过本步，不能重新生成数据库口令或供应商主密钥。

    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/deploy:/out" python:3.12-slim python -c 'from pathlib import Path; import base64,os,secrets; os.umask(0o077); p=Path("/out/.env"); values={"MYSQL_ROOT_PASSWORD":secrets.token_hex(24),"JWT_SECRET":secrets.token_hex(32),"PROVIDER_MASTER_KEY_V1":base64.b64encode(secrets.token_bytes(32)).decode()}; lines=Path("/out/.env.template").read_text().splitlines(); content="\n".join((line.split("=",1)[0]+"="+values[line.split("=",1)[0]] if line.split("=",1)[0] in values else line) for line in lines)+"\n"; f=p.open("x"); f.write(content); f.close(); print("Created deploy/.env (secrets not echoed)")'

**2. 构建并等待九个容器健康。** 首次构建需要可用网络；等待 MySQL、Nacos、Sentinel、四个 Python 服务、Gateway 与 Nginx 的真实探针。

    docker compose --env-file deploy/.env -p aihub-pro-verify -f deploy/docker-compose.yml -f deploy/docker-compose.verify.yml --profile app up -d --build --wait --wait-timeout 600

**3. 执行迁移并创建管理员。** 首次交互输入至少 12 位管理员口令，不回显；已有管理员不重置口令。请保管口令，它不会写入日志。重复运行应显示 migrations applied=0。

    COMPOSE_PROJECT_NAME=aihub-pro-verify COMPOSE_OVERRIDE_FILE=deploy/docker-compose.verify.yml bash scripts/bootstrap_stack.sh

**4. 跑完整链路验收。** 脚本仅使用 urllib 标准库，无需安装 httpx 或任何包。Linux Docker Engine 的宿主网络允许 Python 容器访问 loopback 服务端口。脚本只在上述独立栈中对 demo 做一次 5 积分调用，不访问现有开发栈或 opsdemo 的账单、流水、日聚合。

    docker run --rm --network host -v "$PWD:/workspace:ro" python:3.12-slim python /workspace/scripts/acceptance_check.py

验收应显示“合计 9 项：PASS 9 / FAIL 0”。在服务器本机浏览器打开 http://127.0.0.1:28088，使用第 3 步的 admin 账号和口令登录。远程操作时先在自己的电脑执行 ssh -L 28088:127.0.0.1:28088 用户名@服务器，再打开同一 localhost 地址；验收 Nginx 端口仅绑定 loopback。首次构建耗时取决于网络，“四条命令”不承诺冷构建在五分钟内完成。

查看健康状态时，用第 2 步完整命令的项目和文件参数，将 up 及之后参数改为 ps；九行都应出现 healthy。原生 Windows Docker Desktop 的宿主网络语义不同，可在宿主机直接执行 python scripts/acceptance_check.py；上述四步的验收目标是 Linux。

正式部署去掉第 2 步的 -p aihub-pro-verify 与 -f deploy/docker-compose.verify.yml，第 3 步直接运行 bash scripts/bootstrap_stack.sh。默认项目名 aicapabilityhubpro、卷 aihub-pro-mysql-data、Nginx 端口 80。正式部署与验收使用不同卷，禁止对已有正式卷重播 seed；二者固定的内部宿主机端口重叠，不应直接在同一台主机并行启动。

## 构建镜像源

默认使用 Python、npm 与 Maven 官方源。弱网或内网镜像可在 `deploy/.env` 设置 `PIP_INDEX_URL`、`NPM_REGISTRY` 和 `MAVEN_MIRROR_URL`，然后重建对应镜像：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml --profile app build
```

Python 镜像只按 `requirements.lock.txt` 安装；平台专属依赖在 lock 中带系统标记。锁文件无法安装时构建会明确失败，不会退回未锁定依赖。

## 升级与备份

数据库增量迁移由 `scripts/bootstrap_stack.sh` 按 `service/file` 和 SHA-256 登记。重复运行会跳过已应用的相同文件；已应用文件的校验和发生变化时只告警，不会自动重放。`02_seed.sql` 是首次初始化样例，不作为升级迁移重放。迁移前先按 [runbook](../docs/runbook.md) 备份四个数据库。

容器更新后执行：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml --profile app up -d --build --wait --wait-timeout 600
bash scripts/bootstrap_stack.sh
```

回滚应用镜像时恢复前一版本并重建容器。数据库字段迁移应先用备份恢复到独立实例验证，再按对应 SQL 编写逆向迁移；不要删除数据库卷，也不要对已有卷重新导入 init seed。

## 常见问题

| 现象 | 检查 |
|---|---|
| Compose 提示 `MYSQL_ROOT_PASSWORD is required` | 完成首次启动第 1 步的环境生成；不要使用 `deploy/.env.example` 的空值 |
| `JWT_SECRET is required` | 设置至少 32 字节随机值，并确认 `user-service` 与 `gateway` 共用同一值 |
| 容器仍在 `starting` | `docker compose ps` 查看健康状态；`docker compose logs --tail=100 <service>` 查看该服务末尾日志 |
| 迁移显示 checksum changed | 对比服务 SQL 与 `schema_migration`，先备份并人工确认；脚本不会覆盖已登记版本 |
| lock 安装失败 | 查看具体 Python 版本/平台标记或镜像源可达性；修正并重新生成锁文件，不要改成未锁定回退 |

停止服务但保留数据：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml --profile app down
```

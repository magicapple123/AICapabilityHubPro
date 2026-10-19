# AICapabilityHub Pro

**AI 能力开放平台 Pro · 面向开发者的 AI 能力执行与计量平台**

按能力执行，让参数、费用与调用结果可追踪。

**开发入口：** [AICapabilityHub Pro 开发指南](AICapabilityHubPro-开发指南.md) · [文档索引](docs/README.md) · [跨成员共享契约](docs/api-contract/pro-shared.md)。原指南与旧阶段分工已归档，不再指导当前开发。

AICapabilityHub Pro 面向 AI 能力的接入、调试与调用核验。开发者选择能力后，平台读取该能力的最新状态、输入 Schema 和积分单价，通过受控的聊天或文本摘要执行器完成请求，并将能力 ID、实际费用、账单和积分流水串联到同一个 requestId。

本项目由前三周的 AICapabilityHub 基础版本演进而来。Pro 的重点是**能力目录驱动的执行闭环**：把“选择什么能力、提交哪些参数、消耗多少积分、在哪里核对结果”放到同一条链路中。当前处于团队集成阶段，已实现范围和待交接内容见下表。

## Pro 带来的变化

| 维度 | AICapabilityHub 基础版本 | AICapabilityHub Pro |
|---|---|---|
| 调用对象 | 通用聊天入口，与能力目录相对独立 | 按 capability_id 获取目录快照，再选择受控执行器 |
| 参数输入 | 主要使用聊天消息 | 调试台根据能力 Schema 展示输入，服务端再次校验 |
| 执行能力 | 对话与会话历史 | 聊天、文本摘要分别映射输入；未知执行器明确拒绝 |
| 计费依据 | 固定 POINTS_COST，未绑定具体能力 | 使用目录登记价预检余额并计量，关联真实能力 ID |
| 调用核验 | 日志、积分与用量信息分别查看 | 结果展示实际费用、账单编号、状态、耗时及 requestId |
| 身份治理 | JWT 与基本身份透传 | 清理伪造身份/角色头，精确配置兑换入口、限流和缓存策略 |
| 交付验证 | 各模块基础测试 | 隔离数据库、真实服务 E2E、桌面与手机浏览器验收 |
| 项目资源 | 原课程项目工作区与资源 | 独立仓库、容器命名和数据卷，可与原版本并行运行 |

## 当前功能与交付边界

| 模块 | 当前可用内容 | 状态 |
|---|---|---|
| 能力调试台 | 能力选择、Schema 表单、聊天/摘要输入、价格预览、历史会话 | 已实现 |
| 能力执行链 | 最新目录查询、上架状态/allowlist/Schema 校验、目录价预检、计量收据核验 | 已实现 |
| 计量与追踪 | capability_id、费用、账单、积分流水与 requestId 对齐；模型降级不收费 | 已实现并通过真实服务联调 |
| Gateway 治理 | 签名身份与角色转发、伪造头清理、内部路径隔离、兑换入口限流 | 已实现 |
| 目录内部接口 | 默认内部模式的调用客户端及失败关闭逻辑 | 调用侧已实现，目录服务端待成员交接 |
| 市场体验入口 | 调试台已支持 `/chat?capability_id=<id>` | 市场按钮传递选中 ID 待成员完成 |
| 角色与权限 | JWT role 可信传递 | 业务端实时管理员授权、角色数据与迁移待成员完成 |
| API Key 兑换 | Gateway 精确 POST 白名单、限流、no-store | Key 校验、有效期和短期 JWT 签发待成员完成 |

“已实现”描述本说明对应的 Pro 业务代码。PR #1/#2 已合入 main 的 1b89ce8，合并后 CI 9/9；其他成员尚未交付的权限、Key 兑换和内部目录接口不列为已完成能力。完整最终版尚未发布。

视觉理解、语音转写、知识检索等不属于本期可执行能力。平台只调用代码中明确允许的执行器，不执行用户传入的目标 URL，也不把目录中的 service/path 当作任意代理地址。

## 执行链路

```mermaid
flowchart LR
    A[选择能力与填写输入] --> B[Gateway 验证身份]
    B --> C[读取最新能力目录]
    C --> D[校验状态、执行器与 Schema]
    D --> E[按目录价格预检积分]
    E --> F[聊天 / 文本摘要执行器]
    F --> G[保存会话与执行结果]
    G --> H[记账与积分结算]
    H --> I[返回费用、账单与 requestId]
```

每次执行重新核对能力，价格由目录提供。下架、未知能力、未实现执行器、错误输入、禁用用户和余额不足会在模型前被拒绝。模型超时或坏响应按原契约降级，保留调用记录，实际费用为 0。

`USE_MOCK=true` 时执行本地模拟并明确返回 `mock=true`；摘要模拟结果来自输入文本的提取。真实模型模式使用服务端配置的兼容接口。模拟执行、HTTP 模型替身测试和真实供应商验收分别记录。

## 架构与技术栈

| 层级 | 组件 | 职责 |
|---|---|---|
| 工作台 | React 19.2、TypeScript、Vite、Tailwind CSS 4 | 能力选择、输入、结果与调用核验 |
| 统一入口 | Spring Cloud Gateway、JWT、Sentinel | 路由、可信身份、限流、内部接口隔离 |
| 业务服务 | Python 3.12、FastAPI、SQLAlchemy、JSON Schema | 用户积分、能力目录、调用执行与计量 |
| 中间件 | MySQL 8.4、Nacos 2.5.1、Sentinel Dashboard 1.8.10 | 数据存储、服务发现、配置与治理 |
| 静态入口 | Nginx 1.27-alpine | 托管前端构建并代理 /api 至 Gateway |
| 验证 | JUnit、pytest、Playwright、GitHub Actions | 单测、隔离数据库、服务与浏览器验收 |

Gateway 使用 JDK 21、Maven 3.9.x、Spring Boot 3.5 / Spring Cloud 2025；前端工具链使用 Node 24、pnpm 11。

四个服务分别拥有 `user_db`、`capability_db`、`billing_db`、`ai_chat_db`。服务间按契约调用，不跨库查询；浏览器统一通过 `/api/**` 访问 Gateway。

## 快速启动

以下为 Windows PowerShell 的 Pro 并行开发配置。先安装上述工具链并启动 Docker Desktop。若正在运行旧组件，先确认其所属项目；启动工具不会结束占用端口的进程。

### 1. 获取代码并初始化

```powershell
git clone https://github.com/magicapple123/AICapabilityHubPro.git
Set-Location AICapabilityHubPro
git switch main

python scripts/init_dev.py --install
.\scripts\Test-ProEnvironment.ps1
```

已经在 `D:\AICapabilityHubPro` 工作的机器直接从初始化命令开始。初始化只创建缺失配置，保留现有 `.env`，生成一致的 JWT/数据库配置；真实配置不纳入 Git。

### 2. 启动独立中间件

```powershell
python scripts/start_pro_local.py middleware
```

| 组件 | Pro 主机端口 | 资源说明 |
|---|---|---|
| MySQL | 3307 | `aihub-pro-mysql`，数据卷 `aihub-pro-mysql-data` |
| Nacos | 8849 / 9849 | `aihub-pro-nacos` |
| Sentinel Dashboard | 8859 | `aihub-pro-sentinel` |
| Gateway | 8080 | 本机 JVM |
| user / capability / billing / ai-chat | 8081 / 8082 / 8083 / 8090 | 本机独立 Python 环境 |
| Web | 5173 | Vite，绑定 localhost |

Pro Compose project 为 `aicapabilityhubpro`，不挂载原项目的数据卷。首次新建卷会执行初始化脚本；已有数据库升级不能靠清空卷或重复导入 seed 替代。详见 [双项目并行联调](docs/双项目并行联调.md)。

### 3. 分别启动六个组件

每条命令各占一个终端，工作目录均为项目根目录：

```powershell
python scripts/start_pro_local.py user-service
python scripts/start_pro_local.py capability-service
python scripts/start_pro_local.py billing-service
python scripts/start_leader_dev.py ai-chat-service --catalog-mode market
python scripts/start_leader_dev.py gateway
python scripts/start_leader_dev.py web
```

当前显式使用 `market` 兼容模式，读取旧目录的已上架详情，完成 Pro 的能力校验和计量闭环。默认 `internal` 模式要求 `GET /internal/capability/{id}` 已交接；接口缺失会失败关闭，不能把兼容模式通过写成内部接口已经验收。

内部接口就绪后，将 AI 命令改为 `python scripts/start_leader_dev.py ai-chat-service --catalog-mode internal`，并重跑对应 E2E。

### 4. 登录与体验

访问 `http://localhost:5173`，本地公开演示账号为 `demo / demo123456`。默认使用真实账号登录；模型模拟与占位登录是两个独立开关。

- 聊天：`/chat?capability_id=1`，演示目录价格 5 积分。
- 文本摘要：`/chat?capability_id=2`，演示目录价格 3 积分。
- 低余额场景：本地账号 `demopoor / demo123456`。

以执行时的目录单价为准。结果可查看实际费用、账单编号、状态、耗时和 requestId，并到调用记录/积分页面核对。已有组件不要重复启动；前台进程用 Ctrl+C 结束。

完整演示顺序见 [组长功能演示与交接](docs/组长功能演示与交接.md)。Nginx 部署、默认端口配置和故障排查见 [上手与联调](docs/上手与联调.md)及 [Web 说明](web/README.md)。

## 验证与交付证据

```powershell
# 公共检查与只读网关烟测
python scripts/contract_lint.py
python -m pytest tests/tooling -q
python scripts/smoke_check.py

# Gateway 与 Web
mvn -q -f gateway/pom.xml package
pnpm --dir web lint
pnpm --dir web build
pnpm --dir web exec node --experimental-strip-types --test tests/chat-schema.test.ts

# 独立环境的真实服务和浏览器验收
pnpm --dir web exec playwright install chromium --no-remove
python scripts/run_leader_e2e.py --catalog-mode market --browser
```

数据库 pytest 含测试行清理逻辑，应连接专用验收实例，不能直接使用开发数据库。CI 为四个服务提供隔离 MySQL，并用 `scripts/check_test_report.py` 拒绝空报告、跳过、失败和错误。E2E 单独创建数据库/进程/端口，模型端使用本地 HTTP 测试替身，测试后保留日志和数据卷以供复核。

2026-10-19 的已合并 main 基线 `1b89ce8`（业务来源 `3678cbb`，主分支 CI `39155554390`）已验证：

| 范围 | 结果 |
|---|---|
| 四个服务数据库测试 | 229 passed，零 skipped / failure / error |
| Gateway | 35 项通过 |
| 公共工具 / 前端输入 | 13 / 6 项通过 |
| 真实服务 E2E | 22 项通过 |
| 桌面 / 手机浏览器 | 7 项通过 |
| 该提交 GitHub Actions | 9 / 9 检查通过 |

这是明确提交的验收记录；后续修改以对应提交最新 CI 为准。工作流、报告和限制详见 [质量门禁](docs/质量门禁说明.md)、[业务完成记录](docs/组长业务完成记录-2026-10-19.md)及 [验收矩阵](docs/验收用例.md)。

## 项目目录

```text
AICapabilityHubPro/
├─ gateway/                       # 统一入口与可信身份
├─ services/
│  ├─ user-service/               # 账号、Key、积分
│  ├─ capability-service/         # 目录、Schema、价格与状态
│  ├─ billing-service/            # 计量、记账与用量
│  └─ ai-chat-service/            # 受控聊天/摘要执行
├─ web/src/features/chat/         # 能力调试与结果核验
├─ platform-py/service-template/  # Python 服务基础模板
├─ deploy/                       # 独立中间件与 Nginx
├─ scripts/                      # 初始化、启动、质量与 E2E 工具
└─ docs/                         # 契约、计划、验收与交接
```

## 协作与版本说明

黄岑果负责 Gateway、AI 执行链、调试台与集成；黄禹菲负责用户/计量、角色、Key 和设置；夏思凯负责目录、运营授权、Schema 与市场入口。当前边界和待办以 [实施看板](docs/升级实施看板.md) 为准。

当前从最新 origin/main 开发并提交目标 main 的 PR；develop 尚未同步这批 Pro 升级，主动同步确认前不作为成员起点。PR #1/#2 已在用户授权的单次 Review 例外下合并，原保护已恢复；例外不等于组员人工 Review，也不授权后续取消审批。原仓库、旧分支与原始数据保留。

项目统一名称、简介、About 和对外表达见 [项目定位与描述规范](docs/项目定位与描述规范.md)。详细协作流程见 [CONTRIBUTING](CONTRIBUTING.md)，接口以 [Pro 执行契约](docs/api-contract/ai-chat-service.md) 和各服务契约为准。

## 已知边界

- API Key 凭证兑换、业务端实时管理员授权和目录内部端点仍待对应成员实现；页面存在不代表这些升级已经完成。
- 会话本地事务与远端记账不构成分布式原子事务；远端成功、本地最终提交失败时按 requestId 对账，不能盲目重试模型。
- Pro 目前支持受控聊天与文本摘要，不包含任意插件执行、视觉/语音执行、SSE、真实支付或外部供应商可用性保证。
- 组长业务无需新增数据库列；其他成员的数据结构升级须提供保留旧数据的增量迁移。

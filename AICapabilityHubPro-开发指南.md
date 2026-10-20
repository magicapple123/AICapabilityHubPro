# AICapabilityHub Pro 开发指南

**定位：面向开发者的 AI 能力执行与计量平台。** 本指南适用于三人小组的 Pro 增量开发，更新日期为 **2026-10-19（Asia/Shanghai）**。它替代原版从零搭建指南，工作仓库为 `magicapple123/AICapabilityHubPro`，工作区示例为 `D:\AICapabilityHubPro`。

按能力执行，让参数、费用与调用结果可追踪。新增功能应围绕能力 ID、Schema、可信身份、目录价格、受控执行器、账单和 requestId 的一致性完成；不得退回“固定单价的通用聊天接口”或重新搭建现有工程。

## 1. 当前基线与文档使用

公共基础 PR #1 和组长业务/品牌 PR #2 已合入 `main`，合并基线为 `1b89ce8`，该提交的 9 项 CI 全部通过。`develop` 未同步这批升级，成员应从最新 `origin/main` 开始，PR 当前以 `main` 为目标。

| 现状 | 已实现 | 仍需成员交接 |
|---|---|---|
| Gateway | JWT/role 验证、伪造头清理、requestId、internal 隔离、兑换入口限流 | 新用户角色与 Key 兑换服务端由 user 提供 |
| AI 执行 | 新鲜目录查询、Schema/allowlist、聊天与摘要、按目录价预检和计量 | capability 内部详情服务端 |
| Web | 真实登录、能力调试、Schema 表单、费用/账单/追踪、历史会话 | 角色/Key/运营的服务端升级；市场传 ID 和界面整理见 10/20 前端记录 |
| user/billing | 基础账号、Key 管理、积分、幂等账单及个人用量 | 实时 admin 授权、短期 Token、单价存储与迁移 |

规则与事实分开维护：[共享契约](docs/api-contract/pro-shared.md)描述新增接口约定，[四服务契约](docs/README.md)逐项标明已实现/待交接，[实施看板](docs/升级实施看板.md)记录状态，[验收矩阵](docs/验收用例.md)记录证据。发现实现与契约不一致时列出缺口，不通过修改文档把缺失功能写成已实现。

现行文档入口见 [docs 索引](docs/README.md)。[历史归档](docs/archive/README.md)只用于追溯，不覆盖本指南、当前契约及已确认的 Pro 计划。

## 2. 技术栈与运行标识

| 层 | 基线 | 说明 |
|---|---|---|
| Gateway | JDK 21、Maven 3.9.x、Spring Boot 3.5 / Cloud 2025 | 唯一业务网关，WebFlux |
| Python | Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2、httpx | 每服务独立环境、独立数据库 |
| Web | Node 24、pnpm 11、React 19.2、Vite、TypeScript | 依赖以锁文件为准 |
| 中间件 | MySQL 8.4、Nacos 2.5.1、Sentinel 1.8.10 | Compose 独立 Pro 资源 |
| Schema/验收 | JSON Schema Draft 2020-12、pytest、JUnit、Playwright | 禁止远程 Schema 引用，数据库测试隔离 |

版本以 `gateway/pom.xml`、各服务 `requirements.txt`、`web/pnpm-lock.yaml` 和 Compose 为准；升级依赖单独说明必要性与验证。不因产品改名更改服务名、数据库名、JWT issuer、既有 API 或登录存储标识。

## 3. 架构与数据所有权

```text
Browser -> Vite / Nginx -> Gateway -> four FastAPI services
                                      | each owns its database
ai-chat -> capability detail -> user points check -> controlled adapter
        -> local messages -> billing record -> user points deduct
```

| 服务 | 端口 | 数据库 | 负责人 |
|---|---|---|---|
| Gateway | 8080 | 无 | 黄岑果 |
| user-service | 8081 | user_db | 黄禹菲 |
| capability-service | 8082 | capability_db | 夏思凯 |
| billing-service | 8083 | billing_db | 黄禹菲 |
| ai-chat-service | 8090 | ai_chat_db | 黄岑果 |

浏览器只请求 Gateway 的 `/api/**`。常规服务调用使用 `call_internal` 与 `/internal/**`，保留链路身份；不得跨库 join。唯一明确的过渡读取是 AI 显式 `market` 模式经服务发现访问目录的固定公开详情路径，不是任意 URL 代理。

新注册服务不等于新能力可执行。新增能力必须同时有受控 adapter、Schema、价格/状态约定、前端可用性和安全测试，不能仅靠登记一个 service/path 自动执行。

前端全站整理已按用户授权完成：市场传入选中能力 ID，设置分拆页签，交互与手机布局统一。证据见[前端改版与验收](docs/前端改版与验收-2026-10-20.md)。此项不代替内部目录、管理员授权或 Key 兑换的服务端交付。

## 4. 三人修改范围

| 负责人 | 主责目录与页面 | 本轮交付重点 |
|---|---|---|
| 黄岑果 | gateway、ai-chat、web/src/features/chat、Chat、共享 CI/脚本/文档 | 已合入；维护集成与最终验收 |
| 黄禹菲 | user/billing、Settings、相关 API/types/契约/迁移 | role、实时授权、Key exchange、积分/账单单价 |
| 夏思凯 | capability、Capabilities/Console 运营部分、目录组件/契约/SQL | internal 详情、管理员保护、Schema、市场选中 ID |

跨成员文件先确认接口和修改范围；共享 API 类型只增补已约定字段，不覆盖另一人的实现。AI 辅助开发也遵循相同边界：每人独立克隆/工作区、独立分支，先读现行文档和真实代码，不拿旧版指南或静态 Mock 代替业务实现。

文件优先保持单一职责和 300 行以内；超过 500 行必须拆分或说明限制。入口只做装配。先单独验证结构提取的行为等价，再引入业务变化，不删测试或降低检查让构建通过。

## 5. 标准启动与独立资源

在 Pro 根目录执行，Docker Desktop 引擎需已运行：

```powershell
Set-Location D:\AICapabilityHubPro
python scripts/init_dev.py --install
.\scripts\Test-ProEnvironment.ps1
python scripts/start_pro_local.py middleware
```

初始化仅创建缺失 `.env`，保持网关/user 签名密钥、MySQL 密码一致；不打印密钥，不覆盖现有配置。Pro 使用 `aihub-pro-*` 容器及 `aihub-pro-mysql-data`，不读取原项目数据卷。

| 模式 | MySQL | Nacos HTTP/gRPC | Sentinel |
|---|---|---|---|
| 推荐 Pro 并行模式 | 3307 | 8849 / 9849 | 8859 |
| 原始默认端口模式 | 3306 | 8848 / 9848 | 8858 |

以下命令各占一个终端，均在根目录：

```powershell
python scripts/start_pro_local.py user-service
python scripts/start_pro_local.py capability-service
python scripts/start_pro_local.py billing-service
python scripts/start_leader_dev.py ai-chat-service --catalog-mode market
python scripts/start_leader_dev.py gateway
python scripts/start_leader_dev.py web
```

访问 `http://localhost:5173`；公开本地账号 `demo / demo123456`，低余额账号 `demopoor / demo123456`。模型 Mock 与占位登录互不相同：前端真实登录默认开启，AI 可模拟执行并标注 `mock=true`。

默认 `CAPABILITY_CATALOG_MODE=internal` 要求内部详情端点已交接；当前显式 `market` 模式只查询已上架的公开详情，缺失内部接口不会自动回退。内部端点完成后改用 `--catalog-mode internal` 并重跑严格 E2E。端口占用时先核实来源，不结束未知进程；不要混用两种启动入口。

详见 [上手与联调](docs/上手与联调.md)、[并行资源](docs/双项目并行联调.md)、[Web/Nginx](web/README.md)。

## 6. HTTP、身份与错误约定

统一响应：

```json
{"code":0,"message":"success","data":{},"requestId":"gateway-generated-id"}
```

- `requestId` 为统一外层字段，业务字段用 snake_case；内部 `request_id` 和结果 `data.request_id` 必须与外层同值。
- Gateway 生成外部 requestId，清理 `X-User-*`、role 别名及调用方 requestId 后注入签名身份和角色；调用方不能伪造管理员。
- JWT role 仅为可信声明，不代替管理 API 查询当前用户状态/角色；该业务授权仍待成员实现。
- 登录、注册、市场和 health 按已实现规则放行；Key exchange 只精确放行 `POST /api/user/apikeys/exchange`，每直接地址每分钟 10 次，响应 no-store。
- 外部 `/internal/**` 及服务发现别名/编码路径保持 403。内部服务端口不作为公开认证入口，部署仍需限定内网可达范围。
- 业务错误通常 HTTP 200；网关认证 401、内部隔离 403、限流 429。`1001/1005` 身份/账号，`2001/2002/2008` 参数/状态/不支持执行器，`3001/3002` 余额/幂等冲突，`4002/4003/4004` 依赖/系统/会话。
- 模型 `5001/5002` 通过成功结果中的 `error_code` 表示降级，实际 cost=0；不能误写成模型成功收费。

内部管理员授权的新增约定、失败关闭及权限码见 [共享契约](docs/api-contract/pro-shared.md)。未完成端点不能标为可用。

## 7. 能力输入、价格与执行顺序

现行调用入口为 `POST /api/chat/completions`：

```json
{"capability_id":1,"input":{"messages":[{"role":"user","content":"你好"}]}}
```

```json
{"capability_id":2,"input":{"text":"待摘要材料","max_length":200}}
```

聊天 code 为 `chat-completions`，1–40 条消息，最后一条必须是 user，每条内容 1–12000 字符。摘要 code 为 `long-summary`，text 非空白且不超过 12000 字符，max_length 为 30–1000 整数，默认 200，不接受会话 ID。Schema 进一步缩小范围时遵守目录要求。

兼容顶层 messages 时缺省映射能力 1，仍重新查目录。`input` 与非空顶层 messages 互斥，`stream=true`、客户端单价和目标 URL 等未知字段拒绝。Schema 大小/深度受限，禁止 `$ref`、`$dynamicRef`、`$recursiveRef`、`$id`；不得触发网络或文件读取。

执行顺序：身份 → 最新目录 → online/allowlist/Schema/adapter 输入 → 按目录价预检积分 → 会话归属与用户消息 → 模型/Mock → 助手消息 → billing 收据核对 → 本地提交。失败在模型前应证明模型调用数为 0；本地保存错误回滚，不把状态拒绝写成成功计量。

结果包括 capability_id/code、price_per_call、cost、record_id、billing_status、duration_ms、request_id、catalog_source。登记价来自目录，正常 points=目录价，降级 points=0；`POINTS_COST` 不再作为 Pro 计价依据。

## 8. 跨成员接口与现行契约

| 接口 | 提供方 | 实现状态与要求 |
|---|---|---|
| GET /internal/user/check | user | 已有；校验当前账号和余额，返回 user_id/status/balance/points_cost/available |
| POST /internal/user/points/deduct | user | 已有；金额为正整数，requestId 幂等，保护当前用户 |
| POST /internal/billing/record | billing | 已有；接受 capability_id/points/status，核对收据 |
| GET /internal/capability/{id} | capability | AI 客户端已具备，服务端待交接；返回 ID/code/status/Schema/目录价 |
| GET /internal/user/authorization | user | 新增约定，待实现；当前状态/role/authorized 检查 |
| POST /api/user/apikeys/exchange | user | Gateway 配套已有，Key 校验/TTL/签发待实现 |

共享字段与实现边界见 [pro-shared.md](docs/api-contract/pro-shared.md)，四份服务契约必须同步说明兼容输入、错误语义、状态与测试。内部状态异常失败关闭；不采用“权限未做好先让所有登录用户写入”的过渡策略。

## 9. 数据库、迁移与幂等

每服务仅操作自己的 MySQL 库。通用字段 create_time/update_time/is_deleted，业务删除采用软删除。能力状态 draft/online/offline，分类 enabled/disabled，用户 normal/disabled，调用 success/degraded/failed；积分和价格为整数。

SQL 的实际表定义以各服务 `sql/01_init.sql` 为准；`deploy/mysql/init/` 用于新卷首次初始化。修改结构需提交增量迁移，先备份、说明重复运行/已有数据保留与核验方法；seed 会更新演示数据，不等同于迁移，也不能用清空数据卷升级。

user负责注册赠送及扣分requestId重放，billing负责账单占位/结算/日聚合并已拒绝关键字段冲突。user当前仍需补齐扣分重放参数冲突与GET check目标ID比较；这是明确待办，不在文档中伪造完成。同一内部requestId相同业务不重复扣分，浏览器再次请求会取得新ID，不宣称网络重试自动全局幂等。

AI 本地消息事务、billing 事务与 user 扣分不是分布式原子提交；远端成功而本地失败时按 requestId 对账，不能盲目重试模型。旧 capability_id=0 仅表示历史未关联能力；新 Pro 调用必须关联真实能力 ID。现有 billing 尚未独立存储 unit_price，新增列不得把历史未知单价伪造为真实数据。

数据库日期、主机业务日期需相互一致。E2E 会对齐测试 MySQL 的时间偏移；Windows 北京时间和 Linux UTC 可以分别工作，但不能在同一测试链混用不同“当天”。

## 10. 开发、PR 与保护规则

```powershell
git fetch origin
git switch -c feature/pro-自己的任务 origin/main
# 修改、自测与核对差异后，明确选择本次文件暂存
git push -u origin feature/pro-自己的任务
```

团队成员从当前 main 开发，PR 目标 main；develop 仅在主动同步并确认后使用，不从旧集成分支丢失 Pro 功能。常规合并采用 Squash，先确认依赖；基础 PR 被 Squash 后，后续分支可产生历史冲突，须核对完整文件树并保留双方功能，不能直接 force push 或用 ours/theirs 盲目覆盖。

main/develop 要求 PR、1 位审批者、最后 push 后审批、对话解决及原 8 项必需检查；管理员也受规则约束，禁止强推/删分支。新增真实服务 CI 为第 9 项，发布检查应全部核对。本次先前合并的单次 Review 例外已经使用并恢复，不构成后续自动取消保护的授权。

完成代码不等于人工 Review 完成，授权例外合并也不写成组员已审批。最终 Tag 需三人业务、迁移、严格内部链和评审完成，不把当前组长阶段当作最终版。

## 11. 测试与验收

```powershell
python scripts/contract_lint.py
python -m pytest tests/tooling -q
python scripts/smoke_check.py
mvn -q -f gateway/pom.xml package
pnpm --dir web lint
pnpm --dir web build
pnpm --dir web exec node --experimental-strip-types --test tests/chat-schema.test.ts
pnpm --dir web exec playwright install chromium --no-remove
python scripts/run_leader_e2e.py --catalog-mode market --browser
```

内部目录与授权服务就绪后执行 `python scripts/run_leader_e2e.py --catalog-mode internal --browser`，检查 summary 的 `member_internal_contract_verified=true`，并补齐管理员/Key/迁移验收。兼容链和替身单测不能代替这一结果。

数据库 pytest 含测试行清理，必须使用独立验收实例，不能连开发库。JUnit 需要实际执行、零 skipped/failure/error，使用 `scripts/check_test_report.py` 严格检查；离线门禁的跳过不能作为 DB 通过证据。真实服务 E2E 使用独立库、端口、进程和 Nacos group，模型端是本地 HTTP 替身，不冒称真实外部供应商已验收。

在业务基线 `1b89ce8` 上，四服务 229、Gateway 35、公共工具 13、前端输入 6、E2E 22、浏览器 7 项已通过，主分支 CI 运行 `39155554390` 为 9/9。新提交以自己的 CI/报告为准。记录见 [验收汇总](docs/联调验收记录-2026-10-19.md)。

## 12. 安全操作、配置与排障

- 修改前检查 Git 状态，备份已有文件；保留现有 .env 与未提交修改。删除/清理遵循工作区 AGENTS 与回收站规则，不运行 git clean、reset --hard 或删卷补救。
- 日志只保留必要身份、requestId、状态/耗时，不打印密码、Key secret/hash、JWT、模型凭据或原始用户输入。初始化/报告不输出真实配置。
- Nacos 用于配置和发现，不等于模型供应商已可用；服务 health 返回 UP 也不代表 DB/依赖已可完成业务链，需网关和实际调用验收。
- 返回 4002 时先查目录模式、依赖注册/路径和响应契约；不要把缺失内部接口伪装成空成功。
- 返回 1001 时核对 JWT、issuer 和共享签名密钥；当前用户账号禁用仍需业务实时检查。
- 前端只访问 /api；401/业务错误要保留追踪信息，不把计费成功后的历史列表刷新失败当作调用失败重新提交。

非目标仍为任意插件执行、视觉/语音执行、SSE、真实支付、分布式事务和模型训练。新增范围需评估三周交付约束、负责人和测试，不靠静态宣传扩大可用清单。

## 13. 完成定义与交接

一次任务同时交付：实现与契约、保留旧数据的迁移（如需）、正常/负向测试、明确的启动命令、同提交 CI、真实依赖验收、已知风险和另一位成员 Review。未完成依赖写明提供方与字段，不留“待确认”让 AI 自行选择不兼容方案。

新成员先读本指南、[文档索引](docs/README.md)、[共享契约](docs/api-contract/pro-shared.md)和本人任务槽位，再读对应代码。任务状态见 [team-tasks](docs/team-tasks.md)与[实施看板](docs/升级实施看板.md)；产品表述见[定位规范](docs/项目定位与描述规范.md)。

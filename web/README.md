# AICapabilityHub Pro · 开发者工作台

**选择能力、填写参数、核对费用与调用结果。**

本模块提供 Pro 的开发者界面：能力市场、Schema 驱动调试、聊天与文本摘要、会话历史、积分与用量查询。浏览器只访问 Gateway 的 `/api/**`，不直连 Python 服务。

PR #1/#2已合入main；当前开发入口为[Pro指南](../AICapabilityHubPro-开发指南.md)、[共享契约](../docs/api-contract/pro-shared.md)和[文档索引](../docs/README.md)，不再从旧develop或归档分工重建前端。

## 当前页面

| 页面 | 路径 | 当前范围 |
|---|---|---|
| 登录 / 注册 | `/login`、`/register` | 真实账号和 JWT |
| 工作台 | `/` | 真实余额、近 7 天用量、趋势、常用入口与最近调用 |
| 能力市场 | `/capabilities` | 分类/搜索、参数详情、执行器状态和选中 ID 直达调试 |
| 能力调试 | `/chat?capability_id=<id>` | 选择聊天/摘要、Schema 表单、价格、账单和 requestId |
| 调用记录 | `/usage` | 当前用户余额、用量和账单 |
| 开发者设置 | `/settings` | 现有资料、Key 管理和积分；短期 Token 兑换待负责人实现 |
| 运营控制台 | `/console` | 现有目录操作；实时管理员授权待业务服务升级 |

`src/features/chat/` 已实现受控能力输入与结果核验。页面读取执行器列表，未知或不兼容能力禁用提交。角色实时授权与 Key 凭证兑换仍待对应成员交付。市场选中能力的跳转、资料/积分/凭证页签及全站布局已在本轮完成，见[改版与验收记录](../docs/前端改版与验收-2026-10-20.md)。

## 本地启动

先按 [根 README](../README.md) 初始化并启动后端。在项目根目录执行：

```powershell
pnpm --dir web install --frozen-lockfile
python scripts/start_leader_dev.py web
```

默认访问 `http://localhost:5173`；`/api` 由 Vite 代理到 `VITE_DEV_GATEWAY_URL`，默认网关为 `http://localhost:8080`。Pro 并行开发使用 MySQL 3307、Nacos 8849/9849、Sentinel 8859，前端仍通过 Gateway 8080。

`VITE_USE_MOCK_LOGIN=false` 为默认值，使用真实演示账号 `demo / demo123456`。模型的 `USE_MOCK` 只控制执行方式，与占位登录无关。

AI 服务暂用显式 `market` 目录兼容模式；内部接口就绪后切回 `internal`。前端价格只是预览，服务端每次执行前重新核对目录，不信任客户端单价。

## 构建与验收

```powershell
pnpm --dir web lint
pnpm --dir web build
pnpm --dir web exec node --experimental-strip-types --test tests/chat-schema.test.ts
pnpm --dir web exec playwright install chromium --no-remove
python scripts/run_leader_e2e.py --catalog-mode market --browser
```

最后一条从项目根目录执行，依赖已打包 Gateway、四服务环境、Docker 和 Nacos。它在独立测试资源上验证真实 Web/网关/业务链，模型端使用本地 HTTP 测试替身。报告及桌面/手机截图保存到唯一 `artifacts/leader-e2e/<编号>/`。

## Nginx 入口

从项目根目录构建并启动前端容器：

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml -f deploy/docker-compose.pro-local.yml up -d --build nginx
```

Nginx 默认端口 80，按 `NGINX_PORT` 配置可调整；`/api/**` 转发到 `NGINX_GATEWAY_UPSTREAM`，默认宿主机 Gateway 8080。Nginx 是静态与同源代理入口，身份和限流仍由 Gateway 负责。

## 目录与命名

- `src/features/chat`：能力选择、Schema 输入、会话、执行收据与追踪。
- `src/api`：接口封装，`src/router`：路由和登录守卫。
- `src/pages`：页面入口，`src/components`：共享布局和 UI。
- `src/stores`：登录状态，`tests/`：输入和实际浏览器验收。

展示名统一为 **AICapabilityHub Pro / AI 能力开放平台 Pro**，包名为 `aicapabilityhub-pro-web`。旧版能力示意不作为已上线功能；产品文案遵循 [项目定位与描述规范](../docs/项目定位与描述规范.md)。

# 协作规范

本项目升级仓库为 `https://github.com/magicapple123/AICapabilityHubPro`。原 `AICapabilityHub` 仅作为历史基线保留，不再作为 Pro 的推送目标。

本文档是《AI能力开放平台-开发指南》第 10 章的执行摘要。开发动作以权威指南为准。

## 分支模型

| 分支 | 用途 | 规则 |
|---|---|---|
| `main` | 始终可运行的稳定版本 | 团队目标为保护分支，仅通过 Review 后的 PR 合并 |
| `develop` | 日常集成 | 团队目标为保护分支，只通过 Pull Request 合并 |
| `feature/服务-功能` | 功能开发 | 从最新 `develop` 创建 |
| `fix/服务-问题` | 缺陷修复 | 从最新 `develop` 创建 |

## 标准流程

```powershell
git checkout develop
git pull origin develop
git checkout -b feature/user-login

# 开发并完成本地自测后，小步提交。
git add .
git commit -m "feat(user): 实现登录接口与JWT签发"
git push -u origin feature/user-login
```

随后在 Pro GitHub 仓库创建目标为 `develop` 的 Pull Request。任何人不得直接推送到 `main` 或 `develop`，不得用强制推送覆盖他人提交。合并统一采用 Squash and merge；原仓库的旧分支不参与 Pro 开发。

当前新仓库的 GitHub 强制分支保护尚待组长在成员加入后配置。上述规定为团队协作要求，不代表平台已替团队强制执行。

## 提交信息

格式为 `<type>(<scope>): <简述>`：

- `type`：`feat`、`fix`、`docs`、`refactor`、`test` 或 `chore`。
- `scope`：`user`、`capability`、`billing`、`chat`、`gateway`、`web` 等模块名。
- 一次提交只完成一件事，不混入其他服务的无关改动。

示例：

```text
feat(billing): 增加按次扣分与幂等校验
fix(chat): 修复模型超时未降级问题
```

## 目录边界

- 成员只修改自己负责的服务目录。
- `gateway/`、`platform-py/`、`docs/api-contract/` 属于公共区域，修改前先同步组长。
- 服务只连接自己的数据库；跨服务数据必须调用 `/internal/**` 契约，禁止跨库查询。
- 地址、端口、密钥和开关必须来自环境变量或 Nacos；真实 `.env` 与密钥不得提交。

## Pull Request 要求

- 一个任务对应一个 Pull Request，标题沿用提交信息格式。
- 至少一人完成 Code Review；成员 PR 由组长批准，组长 PR 由其他成员批准。
- Review 必查统一响应、错误码、命名、数据库边界、硬编码配置和接口契约。
- 接口行为或字段变化时，同步更新 `docs/api-contract/`。

提交前至少完成以下检查：

- Python 服务能导入 `app.main`，并通过 `/docs` 与网关路径自测。
- 网关执行 `mvn -q test` 成功。
- 前端执行 `pnpm lint` 与 `pnpm build` 成功。
- 日志包含 `requestId`，且未输出密码、JWT 或 API Key。


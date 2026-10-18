# 黄岑果任务槽位

**负责人：** 黄岑果（组长）<br>
**状态：** 业务实现与本地验收完成，等待组员 Review 和依赖交接<br>
**主责目录：** `gateway/`、`services/ai-chat-service/`、聊天相关 `web/src/`、公共 README/CI/E2E

## 任务清单

- [x] Gateway 可信身份、角色头清理、Key exchange 精确 POST 白名单、限流与禁止缓存
- [x] ai-chat 内部详情客户端、allowlist、Schema 校验和按能力价格预检；未交接内部接口时严格拒绝
- [x] 聊天/摘要执行器与 billing 能力 ID、单价、requestId 联动；显式旧市场兼容模式完成真实服务闭环
- [x] Chat 页面能力选择、Schema 表单、价格、状态和追踪信息；支持市场传来的 capability_id URL
- [x] Gateway/ai-chat 单测、真实服务 E2E 与可复跑的浏览器验收
- [x] 在新 Pro 仓库配置 `main`/`develop` PR 保护、1 人 Review、8 项必需 CI、对话解决和禁止强推/删除
- [ ] 添加其余成员到 Pro 仓库并验证其 PR 权限
- [x] 组长部分集成、README、启动与演示/验收工具
- [ ] 三人完整业务最终集成后发布 Tag

## 领取记录

- 分支：`feature/pro-leader-business`（新 Pro 仓库）
- PR：组长业务 PR；以新仓库对应分支 PR 为准，公共基础依赖 PR #1
- 开始：2026-10-19
- 本轮范围：完成组长模块；其余两位成员的业务主责文件保持保留

## 实现记录

### 接口/数据变更

以 `docs/api-contract/ai-chat-service.md` 第 8 节为准。新增能力输入、执行器发现与调用追踪；不增加业务数据库列。内部目录模式默认严格，旧市场模式须显式选择，失败不自动降级目录来源。billing 沿用既有 capability_id/points，并附带 unit_price；其单价独立持久化留给负责人。

### 测试命令与结果

Gateway 35 项、ai-chat 56 项、公用工具 13 项、前端纯输入 6 项已通过。四服务 pytest 共 229 项，零跳过；真实四服务/Gateway/独立 MySQL 的 22 项闭环及 7 项桌面/手机浏览器验收通过。准确结果见 `artifacts/leader-e2e/20261019-014633-a17ba4/summary.json` 和 `browser/browser-summary.json`；首次未安装浏览器内核的失败报告保留，不计作通过。复跑命令见 `docs/组长功能演示与交接.md`。

### 阻塞和风险

- 夏思凯需交接内部详情接口与市场选中能力 URL；当前旧市场“开始体验”仍直接跳到 `/chat`，调试台内可选择具体能力。
- 黄禹菲需实现 role/实时 admin 授权、Key exchange/TTL 及 billing 的后续升级。Gateway role 只是可信传递，不等于其他业务 API 已有实时管理员保护。
- 其他两位成员的 GitHub 登录名尚未提供，不能准确邀请协作者或代替其 Review。
- 本轮不发布最终版 Tag，不绕过受保护分支；完整内部模式和成员业务联调通过后再发布。
- 未宣称跨服务事务原子性；远端记账成功、本地最终提交失败时需要按 requestId 对账。

### 完成确认

- [ ] 代码已 Review
- [x] 契约、测试、文档和无需本模块数据库迁移的说明已同步
- [x] 正常与失败场景均有证据；完整内部契约验收仍等待对应成员

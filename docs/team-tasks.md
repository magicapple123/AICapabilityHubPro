# AICapabilityHub Pro 三人任务与交接

更新日期：2026-10-19。PR #1/#2 已合入 main，基线 1b89ce8；组长业务已经交付，另外两位成员的升级仍待各自实现和实际验收。旧分工见[归档](archive/2026-09-原版团队任务.md)，不再指导当前修改范围。

先读 [Pro 开发指南](../AICapabilityHubPro-开发指南.md)和[共享契约](api-contract/pro-shared.md)，任务状态以[实施看板](升级实施看板.md)为准。

## 修改范围与交付

| 成员 | 代码和页面 | 当前重点 |
|---|---|---|
| 黄岑果 | Gateway、ai-chat、Chat/features/chat、公共脚本/CI/文档 | 已合入的可信身份、受控聊天/摘要、目录价计量；维护联合验收 |
| 黄禹菲 | user/billing、Settings、相关 API/types、契约/迁移 | role、实时 admin 授权、Key exchange、单价持久化、积分页面 |
| 夏思凯 | capability、Capabilities/Console 运营区、目录组件、契约/SQL | internal 详情、管理保护、Schema/价格、市场传 ID |

前端不再全部归组长独占；每人维护自己功能区，公共类型在契约一致后增量修改。不要重建项目或覆盖组长的已实现执行链。

## 黄禹菲交接清单

- user：注册默认 user，防自助提权；当前角色/账号状态的实时授权；Key secret 校验、禁用/过期、短期 JWT TTL 硬上限。
- 新增约定：GET /internal/user/authorization?user_id=<当前用户ID>&required_role=admin。成功 normal/admin/authorized=true，身份匹配；1001/1005/1007 或异常均拒绝，详细字段见共享契约。1006 保留现有 Key 不存在含义，纠正先前提示词的冲突建议。
- exchange 固定 POST /api/user/apikeys/exchange，Gateway 已配精确 POST/限流/no-store；凭证语义与创建接口保持一致，不能在 URL/日志传 secret。
- billing：保留 capability_id/points/requestId/状态/耗时，新增 unit_price 独立存储时保留旧数据并提供迁移；正常目录价收费，降级零费。
- 全局统计实时 admin 保护，个人余额/记录隔离；保持内部幂等，不宣称分布式原子性。
- Settings 分拆 Key/积分/资料，secret 只创建时显示，不写浏览器持久化存储。
- 覆盖角色撤销、账号禁用、Key 各状态、TTL、幂等冲突、余额不足、授权故障和旧库迁移。

详见[本人记录](implementation/member-黄禹菲.md)及[user](api-contract/user-service.md)/[billing](api-contract/billing-service.md)契约。

## 夏思凯交接清单

- 实现 GET /internal/capability/{id}，返回匹配 id、code、status、内联 param_schema、整数 price_per_call；未知/软删除 2002，状态如实返回。
- 普通用户不得写分类/能力或读取运营列表；通过实时授权接口校验，服务异常失败关闭。不得采用“尚未做好就允许所有登录用户”的策略。
- 分类 enabled/disabled、能力 draft/online/offline 依实际契约；聊天和摘要 code/Schema/价格与现有 AI adapter 对齐。
- 市场按钮传 /chat?capability_id=<id>；调试台已支持。未实现执行器禁用体验，不新增虚构延迟。
- 市场字段最小化，不返回内部 service/path/secret；草稿/下架不泄露存在性。
- internal 详情、参数边界、重复编码、授权撤销/故障、直接越权 API 和浏览器市场到 Chat 都需测试。

详见[本人记录](implementation/member-夏思凯.md)及[capability 契约](api-contract/capability-service.md)。

## 联调顺序

1. 两人先对齐共享授权契约，可并行实现用户数据/目录 Schema/UI。
2. user 授权接口交接后，capability 与 billing 做真实管理员保护联调。
3. 内部目录交接后，组长执行器由显式 market 切到 internal；执行严格 E2E。
4. 核对同 requestId 的能力 ID、目录价、实际账单、积分流水及余额，再验收 Key 兑换和管理员撤权。
5. 同一提交跑完整 CI、浏览器和迁移验收；Review 完成后才进入最终发布。

## Git 与 AI 协作

每人在独立工作区从最新 origin/main 创建 feature 分支，目标 main，不从滞后的 develop 起步。PR #1/#2 的单次 Review 例外已结束，不能复用；保护规则保持。

AI 先读取现行指南、本人契约/任务和实际代码，输出简短模块方案后在授权范围内推进。缺失跨成员端点应记录提供方、路径和失败结果，单测可替换边界但不能冒充真实联调。数据库测试使用专用实例，禁止删测试、跳测、清开发库或删卷。

交付须包含实现/契约、兼容与迁移、测试命令/证据、当前阻塞、恢复方式和另一位成员 Review。旧版静态分工、已过期任务日期和历史测试不代替当前结果。


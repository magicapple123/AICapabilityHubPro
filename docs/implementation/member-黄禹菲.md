# 黄禹菲任务与交接记录

负责人：黄禹菲。状态：Pro升级待负责人实际交付/核验，未收到已完成代码或PR。范围user/billing、Settings、相关API/契约/迁移，不代改Gateway/AI链/市场。

## 领取

- 基线：最新origin/main，不能从未同步Pro功能的develop起步。
- 建议分支：feature/pro-user-billing（负责人创建后填实际名称）。
- PR/提交/时间：负责人领取后填写；目标main，保留Review保护。
- 先读[开发指南](../../AICapabilityHubPro-开发指南.md)、[共享契约](../api-contract/pro-shared.md)、[user](../api-contract/user-service.md)及[billing](../api-contract/billing-service.md)。

## 待完成

- [ ] role=user/admin模型与保留旧账号的迁移，注册默认user、防自助提权、本地管理员初始化。
- [ ] GET /internal/user/authorization?user_id=<当前用户ID>&required_role=admin，当前DB状态/角色，身份一致。
- [ ] POST /api/user/apikeys/exchange，摘要/所有者/账号/Key禁用/过期、短JWT/TTL硬上限。
- [ ] secret只创建展示一次，列表/日志无secret/hash/JWT，凭证错误不枚举。
- [ ] billing保留capability_id/points/requestId，新增unit_price存储/查询与迁移，历史未知不伪造。
- [ ] 全局统计实时admin保护，个人隔离，授权失败关闭；user GET check比较query目标ID，扣分重放补齐字段冲突检查。
- [ ] Settings分组件完成角色/Key有效期/兑换说明/积分，secret不持久化。
- [ ] 独立DB、迁移、幂等/余额/角色撤销/授权故障/Key各状态/TTL与浏览器验收。
- [ ] 契约、测试、文档、实际CI和另一成员Review。

## 错误码纠正

现有1006用于API Key不存在/他人Key，继续保留；新增授权不足用1007。先前给AI的提示词曾建议1006权限不足，已在代码核对后纠正，请使用当前共享契约，两位成员同步该改动。

## 证据填写

记录真实分支/PR、迁移文件、执行命令、提交/CI/报告、正常与负例、requestId对账、未完成依赖与恢复方式。替身单测不冒称真实跨服务联调，DB skipped不算通过。

跨成员依赖：向夏思凯交付授权接口，向组长交付role/Key/billing兼容字段；当前AI已按目录价发送真实capability_id、unit_price、points、状态和耗时，不能改回固定POINTS_COST。

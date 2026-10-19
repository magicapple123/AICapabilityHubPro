# 夏思凯任务与交接记录

负责人：夏思凯。状态：Pro升级待负责人实际交付/核验，未收到已完成代码或PR。范围capability、市场/Console能力运营UI、目录契约/SQL，不代改user/billing/Gateway/AI执行链。

## 领取

- 基线：最新origin/main，不能从未同步Pro功能的develop起步。
- 建议分支：feature/pro-capability-market（负责人创建后填实际名称）。
- PR/提交/时间：负责人领取后填写；目标main，保留Review保护。
- 先读[开发指南](../../AICapabilityHubPro-开发指南.md)、[共享契约](../api-contract/pro-shared.md)与[目录契约](../api-contract/capability-service.md)。

## 待完成

- [ ] GET /internal/capability/{id}，匹配id/code/status/内联param_schema/整数price_per_call。
- [ ] 未知/软删除2002，真实draft/offline状态；公开市场不泄露其存在性。
- [ ] 分类/能力写、上下架和运营列表实时查询user授权，撤权/禁用/异常均拒绝。
- [ ] chat-completions与long-summary的Schema/登记价/状态与已实现adapter一致。
- [ ] 市场按钮传/chat?capability_id=<id>，显示真实价格/参数与可体验状态。
- [ ] Console明确权限/依赖错误，普通用户直接请求管理API也拒绝。
- [ ] 市场响应字段最小化，不带service/path/secret；未实现视觉等不能宣传可体验。
- [ ] 独立DB的内部详情/参数/价格边界、状态/软删除/重复编码、授权撤销/故障与浏览器测试。
- [ ] 内部目录真实E2E、契约、实际CI和另一成员Review。

## 共享依赖

授权固定GET /internal/user/authorization，参数user_id与required_role=admin，核对normal/admin/authorized=true及当前ID。由黄禹菲提供；未交接时运行必须失败关闭，不先允许所有登录用户。

权限不足新增1007，现有1006保留user的Key不存在；capability对外可映射2007。该纠正替代旧AI提示词的冲突码建议。

## 验收与证据

组长Chat已支持URL能力ID、Schema表单和目录价；内部客户端默认internal，当前market只是显式兼容。完成后运行scripts/run_leader_e2e.py --catalog-mode internal --browser，必须实际取得member_internal_contract_verified=true。

记录分支/PR、迁移、提交/报告、参数/权限负例、市场到Chat结果与恢复方式。不得改AI链自动回退或伪造通过；测试DB与开发库分离，seed不当作增量迁移。

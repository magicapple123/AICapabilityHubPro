# AICapabilityHub Pro 协作与交付规范

开发规则从 [Pro 开发指南](AICapabilityHubPro-开发指南.md)、[共享契约](docs/api-contract/pro-shared.md)和本人任务出发。原指南仅历史参考，不能要求重新搭建或降低 Pro 权限/计费标准。

## 分支与仓库

唯一 Pro 推送仓库为 magicapple123/AICapabilityHubPro，原仓库/分支保留。PR #1–#5 已集成 main，三人业务基线651275b；develop尚未同步这批Pro功能，当前从最新origin/main开发、PR目标main。

```powershell
git fetch origin
git switch -c feature/pro-自己的任务 origin/main
# 自测、检查git diff并明确选择文件暂存后提交
git commit -m "feat(user): implement current-role authorization"
git push -u origin feature/pro-自己的任务
```

不要从旧develop缺失Pro代码，也不要强推覆盖他人提交。成员各用独立工作区；本地有未提交修改先保留，不通过reset/clean解决。

## Review 与合并

- 常规协作要求PR、真实成员Review、最新提交CI和对话解决，禁止强推/删分支；合并策略须与当前规则及依赖历史一致。
- 工作流产生9项检查，交付须全部成功。当前main保护已由仓库所有者暂时关闭，不能把建议规则描述成仍然启用的必需contexts。
- 组长PR由另一成员Review，其他成员PR由适当负责人Review；AI验收与CI不能替代人工审批。
- 2026-10-20，所有者明确授权验证后合并PR #4/#5，并再次确认非部署收尾PR #6和候选Tag。代理未代签审批、未改保护或强推；该授权不外推到后续任务。
- 合并采用Squash，按依赖顺序；同步基础分支冲突时核对完整文件树与测试，不盲选ours/theirs、不强推。
- 正式最终Tag要求三人业务、迁移、严格内部模式和人工评审通过。本次仅创建经确认的候选v0.1.0-pro-rc.1，部署、现有库升级和人工签字另行记录。

## 修改范围

黄岑果：Gateway、ai-chat、Chat/features/chat、公共工具/CI/文档。
黄禹菲：user/billing、Settings、相关API/契约/迁移。
夏思凯：capability、市场/运营能力UI、目录契约/SQL。

公共类型和跨成员依赖先按[共享契约](docs/api-contract/pro-shared.md)对齐。不要重做已实现模块或以静态Mock替代待交接端点。用户于2026-10-20确认权限不足使用1006，Key不存在保留同码，按端点和消息区分；共享契约为准。

## 代码与数据

API→Service→Repository→Model/Schema单向职责；单文件优先≤300行，>500行先拆分或说明限制，入口只装配。数据库各服务独立，跨服务call_internal，不跨库。

配置来自环境/Nacos，现有.env保留，不提交真实Token/Key/口令。日志带requestId，但不打印凭证、摘要或原始用户输入。

结构升级提交可重复的增量迁移、旧数据核验和恢复说明；seed会改写演示数据，不能当迁移。数据库pytest使用专用实例，不清开发库。远端扣分/账单与消息本地事务不是分布式原子提交，失败按requestId对账。

## PR 交付

标题采用type(scope):具体行为，说明问题、实现、兼容/迁移、验证证据及剩余依赖。契约逐项区分已实现/待交接；只有实际依赖联调成功才勾为完成。

相关单测、Web lint/build、契约检查和真实链按改动执行；JUnit必须有实际执行、DB零跳过。禁止删测试、xfail/skip或降低类型/安全校验来让检查通过。

文档更新需检查链接、命令、代码块、原版误导语句与功能状态；历史记录移到[归档](docs/archive/README.md)，不伪造新测试。文件修改前扫描/备份，删除清理遵守AGENTS回收站规则。


# AICapabilityHub Pro 实施与交接记录

现行规范：[Pro开发指南](../../AICapabilityHubPro-开发指南.md)、[共享契约](../api-contract/pro-shared.md)、[实施看板](../升级实施看板.md)。

PR #1/#2已经合入main的1b89ce8，组长模块已交付，另两位成员升级待实现/实际验收。main/develop原保护已恢复；从最新origin/main创建个人分支，PR目标main，不从滞后develop丢失Pro功能。

## 成员记录

- [黄岑果](member-黄岑果.md)：Gateway、能力执行、Chat、CI/E2E与最终集成。
- [黄禹菲](member-黄禹菲.md)：role、实时授权、Key/短期JWT、billing与Settings。
- [夏思凯](member-夏思凯.md)：内部目录、Schema/单价、管理授权与市场入口。

每人更新自己的路径、PR、迁移、测试证据、依赖和人工Review状态。任务记录不是允许AI替代其他人业务的授权；遵循用户本轮实际授权与修改边界。

## 接口与证据

user授权采用共享路径；权限不足新增1007，保留1006的Key不存在。内部目录与Key端点必须区分“调用/Gateway已准备”和“服务端已交接”。

新增/变更先同步契约，独立DB验证，实际网关/浏览器联调后再标完成；Mock/HTTP模型替身与真实供应商分开，JUnit不能跳过。例外合并不等于人工Review。

## 模块资料

[公共工具](公共工具模块.md)和[组长模块](组长业务模块方案.md)描述已实现模块；实施前预估方案在[历史归档](../archive/README.md)。总体状态见[公共基础](../公共基础完成记录.md)与[组长记录](../组长业务完成记录-2026-10-19.md)，不要重新搭建已有基座。

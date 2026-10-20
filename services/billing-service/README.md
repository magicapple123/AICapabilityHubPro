# AICapabilityHub Pro · 调用计量与账单服务

billing-service拥有billing_db，按真实capability_id、目录unit_price、实际points和requestId记账，通过user服务结算积分。PR #4已合入main，三人业务基线651275b；单价独立存储和实时管理员保护已实现。

规范见[开发指南](../../AICapabilityHubPro-开发指南.md)、[计量契约](../../docs/api-contract/billing-service.md)与[共享约定](../../docs/api-contract/pro-shared.md)。

## 接口与计量

| 接口 | 当前行为 |
|---|---|
| POST /internal/billing/record | 链路身份/requestId校验，幂等明细、user扣分及日聚合 |
| GET /api/billing/records | 当前用户分页明细，返回nullable unit_price与实际cost |
| GET /api/billing/usage | 当前用户汇总、日与服务维度 |
| GET /api/billing/stat/overview | 全局统计，每次向user实时授权admin |
| GET /health、/api/billing/ping | health公开，ping需Gateway JWT |

unit_price是登记价，points映射实际cost；success有单价时费用须相等，degraded/failed为0。省略单价的旧调用兼容NULL，历史未知不回填猜测。capability_id=0只兼容历史未关联调用。

免费/降级不发正额扣分，但仍检查账号。普通用户读全局统计1006，账号禁用/不存在1005，授权依赖不明4002；不只信JWT role，不跨库。

## 幂等、事务与恢复

同requestId比较用户/服务/能力/费用/单价/模型/耗时/状态等关键字段，相同返回duplicated=true，不再扣分/累加；冲突3002。内部重放与浏览器新请求不同，不宣称自动全局幂等。

本地明细/聚合事务不包括远端user提交，扣分后本地失败按requestId对账，不能宣称全局原子回滚。summary/by_service与by_day的既有统计来源不在本轮改变。

## 启动、迁移与验收

```powershell
# 根目录初始化并确认Pro中间件/目标数据库后
python scripts/start_pro_local.py billing-service
```

监听8083，Pro DB3307/Nacos8849。已有库先备份核验，再于本服务目录由负责人运行`python -m app.migrate`增量添加nullable unit_price；重复执行无损，历史价格保留NULL，回退不DROP。seed不是迁移。本轮未升级现有环境。

main651275b的CI39420321602：billing87项零跳过/错误/失败，含单价/角色/迁移/余额/幂等与故障负例。夹具会清测试行，只准显式连接独立QA实例并严格检查JUnit；不能用开发.env或真实用户试扣。

真实内部摘要3分/单价持久化、实时管理员撤权与Key链已验证。新增管理员统计浏览器证据见[收尾记录](../../docs/验收收尾记录-2026-10-20.md)及[本人任务](../../docs/implementation/member-黄禹菲.md)。

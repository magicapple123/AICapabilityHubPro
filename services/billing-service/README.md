# AICapabilityHub Pro · 调用计量与账单服务

billing-service拥有billing_db，按真实capability_id、实际points与requestId记账，并通过user服务结算积分。Pro AI已按目录单价上报，不再固定POINTS_COST；unit_price独立存储与实时管理员统计保护仍待黄禹菲实现。

规范见[开发指南](../../AICapabilityHubPro-开发指南.md)、[计量契约](../../docs/api-contract/billing-service.md)与[共享约定](../../docs/api-contract/pro-shared.md)。

## 接口与计量

| 接口 | 当前行为 |
|---|---|
| POST /internal/billing/record | 校验链路身份与requestId，幂等写明细、调user扣分、日聚合 |
| GET /api/billing/records | 当前用户分页明细/日期/服务/状态筛选 |
| GET /api/billing/usage | 当前用户汇总、日与服务维度 |
| GET /api/billing/stat/overview | 全局统计；当前实时admin保护尚未实现，属于缺口 |
| GET /health、/api/billing/ping | health公开；ping经Gateway需JWT |

实际请求包含capability_id、unit_price、points、status、duration_ms。points→cost，正常目录价，degraded为0；Schema当前忽略额外unit_price，不能声称已独立保存登记单价。0能力ID只兼容历史未关联调用。

免费/降级不发正额扣分，但仍检查账号；查询通过user check拦截禁用，不跨库。运营授权需进一步实时authorization，不能只信JWTrole或前端隐藏按钮。

## 幂等和事务

重复requestId的用户/服务/能力/实际费用/状态一致返回duplicated=true，不再扣分/累加，balance_after当前为null；冲突3002。日聚合按日期/用户/能力唯一键累加。

本地明细和日聚合的事务不包括远端user提交；扣分后本地提交失败须requestId对账，不能宣称全局原子回滚。summary/by_service来自明细、by_day来自日聚合，当前双源口径如实保留。

## 启动与验收

根目录初始化及中间件就绪后：

```powershell
python scripts/start_pro_local.py billing-service
```

监听8083，Pro DB3307、Nacos8849。按[根README](../../README.md)启动其余服务再做真实链，不用生产/开发账号手工构造重复扣款作为自动化测试。

基线52项pytest，数据库夹具使用高位测试用户ID并清行，必须独立MySQL实例；生成JUnit并严格零跳过检查。依赖替身单测只证明本服务边界，真实user/billing联调由独立E2E验证。

## 待交接

- 实时admin保护全局统计，个人查询继续隔离；授权异常失败关闭。
- unit_price请求/存储/查询/幂等扩展及保留旧数据的增量迁移，不伪造历史价。
- 角色撤销、免费禁用账号、同requestId冲突、余额不足和跨服务故障边界测试。
- 新权限码1007，保留1006的Key不存在含义；公共接口以共享契约为准。

任务和证据见[黄禹菲任务](../../docs/implementation/member-黄禹菲.md)。sql/02_seed.sql仅示例数据，不是升级迁移。

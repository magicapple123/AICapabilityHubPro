# AICapabilityHub Pro · 用户与积分服务

user-service拥有user_db，为Pro提供账号、JWT、Key管理、余额预检和积分流水。当前角色数据、实时管理员授权与Key兑换短期JWT仍待负责人黄禹菲实现，不能把已有Key列表等同凭证兑换已完成。

规范从[Pro开发指南](../../AICapabilityHubPro-开发指南.md)、[用户契约](../../docs/api-contract/user-service.md)与[共享约定](../../docs/api-contract/pro-shared.md)读取。

## 当前接口

| 能力 | 路径 | 边界 |
|---|---|---|
| 注册/登录 | POST /api/user/register、/login | 公开，账号禁用/凭证错误按实际契约 |
| 资料 | GET/PUT /api/user/profile | 当前用户，修改仅现有允许字段 |
| Key | POST/GET /api/user/apikeys、PUT /{id}/disable | secret_key仅创建时返回；列表无secret/hash |
| 积分 | GET /api/user/points、/points/logs | 当前用户余额和分页流水 |
| 预检 | GET /internal/user/check | 当前账号/余额及必要头；query目标与调用者比较待补强 |
| 扣分 | POST /internal/user/points/deduct | 正金额、requestId幂等、余额条件更新 |
| 健康/透传 | GET /health、/api/user/ping | health公开，ping经网关需JWT |

1006已用于Key不存在或不属于当前用户，Pro新增管理员权限不足约定1007。role默认user、实时authorization及exchange的准确状态/字段见契约第7节，缺失端点不能伪造成功。

## 启动

根目录完成初始化和中间件后：

```powershell
python scripts/start_pro_local.py user-service
```

监听8081，Pro数据库主机3307，Nacos8849；JWT与Gateway使用一致共享配置。不要照搬原版root:root配置覆盖.env，也不向Nacos注册0.0.0.0。

## 数据与测试

t_user、t_api_key、t_points_account、t_points_log由sql/01_init.sql定义。secret_hash是当前校验基础，不因旧指南附录缺列而删除；secret_mask仅展示。

扣分按条件余额更新而非读version比较的版本锁。user现有requestId命中返回旧流水，尚需补齐重放字段冲突检查；billing已有关键字段冲突拒绝。GET check当前未比较query.user_id与调用者，按Pro目标补齐而非在文档标成已完成。更上层跨服务事务仍需对账。

基线67项pytest；在独立MySQL导入本服务结构，显式配置验收DB_URL后执行pytest生成JUnit，再用根scripts/check_test_report.py严格检查。夹具会清理qa前缀账号，禁止连接开发数据库运行；DB跳过不算通过。真实链和迁移验收见[质量门禁](../../docs/质量门禁说明.md)。

示例demo/demopoor/demodisabled口令demo123456，仅本地隔离演示。seed更新同名记录，不能代替业务库迁移。

## 待交接

实现role与迁移、GET /internal/user/authorization、POST /api/user/apikeys/exchange、TTL硬上限、失效Key拒绝和Settings。Gateway白名单/role配套已有，不改路径；覆盖撤权、禁用、错误凭证、过期、泄露和旧数据保留，按[本人任务](../../docs/implementation/member-黄禹菲.md)交付。

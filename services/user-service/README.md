# AICapabilityHub Pro · 用户与积分服务

user-service拥有user_db，提供账号/role、JWT、Key生命周期/短期JWT兑换、实时授权与积分。PR #4已合入main，三人业务基线651275b；不是“仅展示Key”的旧阶段。

规范见[开发指南](../../AICapabilityHubPro-开发指南.md)、[用户契约](../../docs/api-contract/user-service.md)与[共享约定](../../docs/api-contract/pro-shared.md)。

## 当前接口

| 能力 | 路径 | 边界 |
|---|---|---|
| 注册/登录 | POST /api/user/register、/login | 注册默认user，防自助提权；签名role不代替实时授权 |
| 资料 | GET/PUT /api/user/profile | 当前用户，仅允许昵称等约定字段 |
| Key | POST/GET /api/user/apikeys、PUT /{id}/disable | Secret仅创建时返回且no-store，列表无Secret/hash |
| 兑换 | POST /api/user/apikeys/exchange | 精确匿名JSON，校验摘要/所有者/状态/期限；默认900秒、最多3600秒且不晚于Key到期 |
| 积分 | GET /api/user/points、/points/logs | 当前用户余额/流水隔离 |
| 预检 | GET /internal/user/check | query目标必须与当前身份一致，不符先返回1001 |
| 授权 | GET /internal/user/authorization | 当前normal/admin且身份匹配；每次读数据库 |
| 扣分 | POST /internal/user/points/deduct | 正金额、条件余额更新、requestId关键字段幂等与冲突3002 |

授权不足1006；API Key不存在也保留1006，由端点/消息区分。无效兑换统一1003，不枚举；账号不存在/禁用1005，依赖异常失败关闭。

Key禁用阻止新兑换，不即时撤销已经签发的JWT。业务端仍实时校验当前账号状态/管理角色。一次性Secret不写持久化存储；普通登录JWT既有存储行为未改变。

## 启动、迁移与恢复

根目录初始化与Pro中间件就绪后：

```powershell
python scripts/start_pro_local.py user-service
```

监听8081，Pro DB3307/Nacos8849，与Gateway共享签名配置。不覆盖.env，不误连原项目3306。

已有库先备份核验，再由负责人在本服务目录运行`python -m app.migrate`；只增量添加role，旧账号默认user。离线`python -m app.admin <新账号>`隐藏输入密码、拒绝覆盖现有账号、新管理员积分0。本轮收尾未在现有库执行这些命令。

回退代码可保留新增列，不执行DROP；seed会更新示例账号，不能当业务库升级工具。

## 验收

main651275b的CI39420321602：user95项零跳过/失败/错误，含角色、Key、TTL、幂等、身份不匹配及保留旧数据的迁移回归。数据库夹具会清测试行，必须显式连接独立QA实例并严格检查JUnit，不能直接用开发.env。

真实Gateway兑换、签名JWT使用、撤权/禁用及3分计量已联调；本次新增Settings浏览器证据见[收尾记录](../../docs/验收收尾记录-2026-10-20.md)与[成员交接](../../docs/implementation/member-黄禹菲.md)。隔离通过不表示部署/真实供应商/人工签字完成。

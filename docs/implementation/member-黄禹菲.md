# 黄禹菲任务与交接记录

负责人：黄禹菲（GitHub `EGOIST-001`）。状态：user/billing、Settings已通过PR #4合入main；三人业务集成基线 `651275b`，不再等待capability授权接入。CI与真实验收不代替成员人工签字。

## 来源与范围

- 原分支 `feature/pro-user-billing`，原交付 `2f6f62c`；后续加入GET check身份保护及对应回归，分支末端 `56b4622`。
- PR #4合并提交 `bf85b8c`；与PR #5最终集成在main `651275b`。
- 范围：user/billing、Settings、相关API/契约/迁移；不重写Gateway/AI执行链。

## 已完成

- [x] role=user/admin模型与保留旧账号迁移；注册默认user，防注册/资料自助提权。
- [x] GET `/internal/user/authorization?user_id=<当前ID>&required_role=admin`，校验身份、当前账号和角色。
- [x] POST `/api/user/apikeys/exchange`：Secret摘要、账号/Key状态、到期与JWT TTL硬上限；精确JSON禁止多余字段。
- [x] Secret仅创建响应展示，列表无Secret/hash，Settings不写持久化存储；凭证失败统一1003、不枚举。
- [x] billing新增nullable unit_price，兼容旧调用NULL，保留实际cost/capability_id/requestId/状态/耗时。
- [x] 全局统计实时admin授权、个人隔离；身份/账号/依赖异常失败关闭。
- [x] GET check先拒绝身份/目标不符1001，再查当前账号；未知且身份匹配仍返回1005，未放宽断言。
- [x] user扣分与billing重放比较关键字段，冲突3002；余额不足与免费/降级账号状态校验。
- [x] Settings分组件完成资料、角色、积分、Key期限/禁用及兑换说明。

## 错误码与令牌边界

2026-10-20确认：授权不足使用1006；API Key不存在也保留1006，由端点/消息区分。capability映射2007。签名JWT的role不代替实时授权。

Key默认JWT TTL900秒、最多3600秒并受Key期限约束。Key禁用阻止新兑换，不能声称即时撤销已签发JWT；当前账号禁用/角色撤销仍在业务端实时检查。普通网页登录JWT的既有localStorage行为与一次性Secret不混为一谈。

## 证据

- main `651275b` 的CI `39420321602`：user95、billing87项，零失败/错误/跳过；包含旧库迁移与参数/权限/Key/幂等负例。
- 同次CI：market E2E22/internal21、原浏览器各9，内部契约标记均为true。
- 独立真实链9项：Key创建no-store/列表掩码、匿名兑换JWT经Gateway使用、身份不符拒绝、严格内部摘要3分与unit_price落库、实时角色/撤权、禁用账号/Key、错误与过期凭证。
- 原始成功与修复证据保存在 `artifacts/merge-to-main/20261020-51e9b42b-authorized/`；没有冒充真实模型供应商。
- 本次新增真实Settings和管理员Console浏览器场景、具体提交与结果见[收尾记录](../验收收尾记录-2026-10-20.md)。旧模拟写响应检查不能替代。

## 迁移、恢复与未代办事项

- user：`app/migrate.py`增量添加role；billing：`app/migrate.py`添加nullable unit_price。重复执行不删除数据；回退代码可保留新增列，不执行DROP。
- 离线管理员工具 `python -m app.admin <新账号>` 隐藏输入密码，拒绝覆盖已有账号，新建积分为0；本轮未在现有环境运行。
- 所有数据库pytest只允许显式配置的独立QA实例；夹具会清测试行，不能直接使用开发.env数据库。
- 现有业务库是否升级未确认，本轮未部署、迁移或重启；三人正式Review/签字未由AI代办，候选Tag不是正式发布。

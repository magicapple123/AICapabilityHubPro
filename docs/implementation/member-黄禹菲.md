# 黄禹菲任务与交接记录

负责人：黄禹菲。状态：已完成本分支实现，等待 PR Review 与跨服务联合验收。范围 user/billing、Settings、相关 API/契约/迁移，不代改 Gateway/AI 链/市场。

## 领取

- 基线：最新 origin/main；分支：`feature/pro-user-billing`；PR 目标 `main`，保留 Review 保护。
- 已阅读开发指南、共享契约、user/billing 契约及组长交接文档。

## 已完成

- [x] role=user/admin 模型与保留旧账号的迁移，注册默认 user、防注册/资料自助提权、本地管理员离线初始化。
- [x] GET `/internal/user/authorization?user_id=<当前用户ID>&required_role=admin`，校验链路身份、当前 DB 状态和角色。
- [x] POST `/api/user/apikeys/exchange`，摘要/所有者/账号/Key 状态与期限校验，短 JWT 与 TTL 硬上限。
- [x] secret 只创建展示一次，列表/日志/错误响应/测试报告无 secret、hash 或 JWT，凭证错误不枚举。
- [x] billing 保留 capability_id/points/requestId，新增 nullable unit_price 存储、查询与可重复迁移，历史未知为 NULL。
- [x] 全局统计实时 admin 保护，个人隔离，授权失败关闭；GET check 比较 query 目标 ID，扣分重放检查关键字段。
- [x] Settings 分组件完成角色、Key 有效期、兑换说明和积分展示，secret 不持久化。
- [x] 已添加独立数据库测试、迁移、幂等/余额/角色撤销/授权故障/Key 状态/TTL 用例；完整浏览器和跨服务验收待联调。
- [x] 契约、测试和文档已更新；CI/Review 在推送 PR 后执行。

## 错误码决策

用户于 2026-10-20 明确确认：管理员权限不足统一使用 **1006**。API Key 不存在也保留 1006，由端点上下文和消息区分；不得擅自改为 1007。

## 证据与恢复

迁移：`services/user-service/app/migrate.py`、`services/billing-service/app/migrate.py`；管理员初始化：`services/user-service/app/admin.py`。重复执行迁移不会删除数据；回退代码时保留新增列即可，不执行 DROP。纯单测与安全测试已通过；数据库测试须在独立 MySQL 实例执行，不能把替身测试冒称真实联调。

跨成员依赖：向夏思凯交付授权接口，向组长交付 role/Key/billing 兼容字段；capability-service 尚未接入授权端点，严格 internal 链及完整 Gateway/四服务联验仍阻塞。当前 AI 已按目录价发送真实 capability_id、unit_price、points、状态和耗时，不能改回固定 POINTS_COST。

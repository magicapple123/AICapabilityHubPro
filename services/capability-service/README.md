# AICapabilityHub Pro · 能力目录服务

capability-service拥有capability_db，维护能力ID、分类、Schema、单价和上架状态。本轮已提供内部详情与运营实时授权，AI 调用端默认 internal 模式可直接读取；user 授权端点尚未交付，缺失时运营操作失败关闭。

规范见[Pro开发指南](../../AICapabilityHubPro-开发指南.md)、[目录契约](../../docs/api-contract/capability-service.md)与[共享约定](../../docs/api-contract/pro-shared.md)。

## 现有与待实现

| 范围 | 当前 |
|---|---|
| 分类 | GET/POST categories，PUT/DELETE categories/{id}；enabled/disabled；写操作实时管理员授权 |
| 能力 | 登记、编辑、软删除、独立status入口；draft/online/offline；写操作实时管理员授权 |
| 市场 | list/categories/detail，只返回online；列表不含Schema，详情含param_schema |
| 运营列表 | `/api/capability/manage` 仅管理员可读；普通用户2007，依赖故障4002 |
| GET /internal/capability/{id} | 已实现；返回id/name/code/真实status/内联Schema/整数单价 |
| 市场体验按钮 | 已传 `/chat?capability_id=<id>`，Chat 已支持 |
| user 授权依赖 | 调用侧与码映射已实现；等待 user-service 提供 `/internal/user/authorization` |

公开market不泄露service_name/path/密钥、草稿或下架存在性。登记条目可见不等于有adapter；不能将任意service/path作为执行目标。

## Pro接入要求

内部详情每次实时读取，返回匹配id、name、code、status、内联param_schema和整数price_per_call；未知/软删除2002，草稿/下架保留真实状态，配置损坏4002。AI每次读取并检查online，价格改变下一次调用生效；严格internal模式不能靠market回退假装通过。

聊天code=chat-completions，Schema对应input.messages（1–40条、role三选一、content 1–12000、可选temperature 0–2）；摘要code=long-summary，对应text（1–12000）及可选max_length（30–1000）。禁止Schema远程引用，登记与内部详情共用同一组结构约束。视觉code未实现，不展示可体验或虚构延迟。

管理操作/列表每次调用user authorization，匹配当前用户、normal/admin/authorized=true才放行；依赖异常失败关闭，普通用户拒绝2007。共享契约新增user权限不足1007，1006保留Key不存在；授权端点对旧user构建返回的1006也仅作拒绝兼容。

## 启动和数据

```powershell
# 在Pro根目录初始化与启动中间件后
python scripts/start_pro_local.py capability-service
```

监听8082，Pro DB3307、Nacos8849。sql/01_init.sql定义表；seed中的聊天5分、摘要3分、视觉draft是本地示例，导入会更新同名记录，不能用于已有业务库的迁移。已有库请执行 `sql/03_align_executor_schema.sql`，它只补齐旧版简化Schema，不改价格与状态，重复执行安全。

## 验收

```powershell
cd services/capability-service
.\.venv\Scripts\python.exe -m pytest -q -rs
```

当前 `feature/pro-capability-market` 共118项用例：非DB用例77项，隔离MySQL 8.0上DB用例41项，全绿、零跳过。覆盖内部详情字段/状态/未知/软删除/身份、Schema引用与边界、价格边界、管理员/普通用户/撤权/依赖故障、字段最小化与重复编码。数据库夹具会清理 `qa-` 前缀测试数据，必须使用独立实例，不能用开发库。

内部端点完成后仍需运行组长严格模式 `python scripts/run_leader_e2e.py --catalog-mode internal --browser`，并以 `member_internal_contract_verified=true` 为真实链证据；user 授权接口交付后补真实管理员/撤权联调。服务端/admin/市场改造和增量迁移见[本人任务](../../docs/implementation/member-夏思凯.md)，不改组长已实现AI链或让前端直连服务绕开Gateway。

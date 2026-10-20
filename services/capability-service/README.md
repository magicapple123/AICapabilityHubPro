# AICapabilityHub Pro · 能力目录服务

capability-service拥有capability_db，维护能力ID、分类、Schema、单价和上架状态。本轮提供内部详情与运营实时授权调用侧；授权服务缺失或异常时运营操作失败关闭。user-service 提供端由 PR #4 实现，联合隔离环境已通过真实授权与 strict internal E2E；最终交付仍需双方 PR 的 CI/Review/合并。

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
| user 授权依赖 | 提供端由 PR #4 提交，隔离联合环境的真实管理授权9项已通过 |

公开market不泄露service_name/path/密钥、草稿或下架存在性。登记条目可见不等于有adapter；不能将任意service/path作为执行目标。

## Pro接入要求

内部详情每次实时读取，返回匹配id、name、code、status、内联param_schema和整数price_per_call；未知/软删除2002，草稿/下架保留真实状态，配置损坏4002。AI每次读取并检查online，价格改变下一次调用生效；严格internal模式不能靠market回退假装通过。

聊天code=chat-completions，Schema对应input.messages（1–40条、role三选一、content 1–12000、可选temperature 0–2）；摘要code=long-summary，对应text（1–12000）及可选max_length（30–1000）。禁止Schema远程引用，登记与内部详情共用同一组结构约束，并通过Draft 2020-12元Schema校验；非法关键字不会留到执行期才暴露。视觉code未实现，不展示可体验或虚构延迟。

管理操作/列表每次调用user authorization，匹配当前用户、normal/admin/authorized=true才放行；依赖异常失败关闭，普通用户拒绝2007。user-service PR #4 按最新共享契约用1006表示授权不足；该错误码只在授权端点上下文中映射，API Key 业务的1006仍按原语义处理。

上架（create时status=online或status接口切online）必须已有合法的对象Schema；草稿/下架可暂不填写，但线上能力不能把Schema清空，需先下架。这样市场不会展示必然在executor处失败的目录配置。

## 启动和数据

```powershell
# 在Pro根目录初始化与启动中间件后
python scripts/start_pro_local.py capability-service
```

监听8082，Pro DB3307、Nacos8849。sql/01_init.sql定义表；seed中的聊天5分、摘要3分、视觉draft是本地示例，导入会更新同名记录，不能用于已有业务库的迁移。已有库执行 `sql/03_align_executor_schema.sql` 前先备份受影响记录。迁移只识别完整匹配旧 seed 的默认 Schema，或 online 能力的空 Schema；不根据“缺少某个约束”猜测版本，因此保留含有自定义规则的 Schema。draft/offline 的空 Schema 保持为空；价格、状态不变，脚本可重复执行。

## 验收

```powershell
cd services/capability-service
.\.venv\Scripts\python.exe -m pytest -q -rs
```

原始 `feature/pro-capability-market` 有129项；增加迁移保护回归后，此修复分支在独立 MySQL 8.4.11 上共131项通过、零跳过。覆盖内部详情字段/状态/未知/软删除/身份、Schema引用/非法Draft关键字与边界、上架必须有合法Schema、价格边界、管理员/普通用户/撤权/依赖故障、自定义Schema迁移保留/旧默认Schema升级/幂等、字段最小化与重复编码。数据库夹具会清理 `qa-` 前缀测试数据，必须使用独立实例，不能用开发库。

CI 分别运行 `--catalog-mode market --browser` 和 `--catalog-mode internal --browser` 的完整真实服务链，严格 internal 报告必须同时满足 `passed`、`browser_verified`、`member_internal_contract_verified=true`。PR #4 已提交 user 实时授权提供端（其 CI 通过、待 Review），真实管理员成功/撤权/禁用和 Gateway/四服务联验须在包含双方代码的隔离运行中验证。服务端/admin/市场改造和增量迁移见[本人任务](../../docs/implementation/member-夏思凯.md)，不改组长已实现AI链或让前端直连服务绕开Gateway。

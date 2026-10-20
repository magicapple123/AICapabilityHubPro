# AICapabilityHub Pro · 能力目录服务

capability-service拥有capability_db，维护能力ID、分类、Schema、单价和上架状态。现有公开市场可供Pro的显式market兼容模式查询；内部详情、实时管理员授权和市场按钮传选中ID仍待夏思凯交接。

规范见[Pro开发指南](../../AICapabilityHubPro-开发指南.md)、[目录契约](../../docs/api-contract/capability-service.md)与[共享约定](../../docs/api-contract/pro-shared.md)。

## 现有与待实现

| 范围 | 当前 |
|---|---|
| 分类 | GET/POST categories，PUT/DELETE categories/{id}；enabled/disabled |
| 能力 | 登记、编辑、软删除、独立status入口；draft/online/offline |
| 市场 | list/categories/detail，只返回online；列表不含Schema，详情含param_schema |
| 运营列表/写入 | 基础接口存在，实时admin保护尚未实现，不能视为安全验收完成 |
| GET /internal/capability/{id} | Pro约定，AI调用端已实现，目录服务端待提供 |
| 市场体验按钮 | Chat已支持URL参数；按钮需改为/chat?capability_id=<id> |

公开market不泄露service_name/path/密钥、草稿或下架存在性。登记条目可见不等于有adapter；不能将任意service/path作为执行目标。

## Pro接入要求

内部详情返回匹配id、name、code、status、内联param_schema和整数price_per_call；未知/软删除2002。AI每次读取并检查online，价格改变下一次调用生效；严格internal模式不能靠market回退假装通过。

聊天code=chat-completions，Schema对应input.messages；摘要code=long-summary，对应text及可选max_length。禁止Schema远程引用，边界以共享契约为准。视觉code未实现，不展示可体验或虚构延迟。

管理操作/列表实时调用user authorization，匹配当前用户、normal/admin/authorized=true才放行；依赖异常失败关闭，普通用户拒绝2007。新增user权限不足1007，1006保留Key不存在。不要继续按旧“尚未确认就允许所有登录用户”开发。

## 启动和数据

```powershell
# 在Pro根目录初始化与启动中间件后
python scripts/start_pro_local.py capability-service
```

监听8082，Pro DB3307、Nacos8849。sql/01_init.sql定义表；seed中的聊天5分、摘要3分、视觉draft是本地示例，导入会更新同名记录，不能用于已有业务库的迁移。

## 验收与交接

基线54项pytest使用独立MySQL，fixture会清测试数据，DB跳过不能算通过。新增内部详情、状态/Schema/单价、管理员撤权/依赖故障、字段最小化与市场到Chat浏览器测试；内部端点完成后运行严格internal E2E。

服务端/admin/市场改造和增量迁移见[本人任务](../../docs/implementation/member-夏思凯.md)，不改组长已实现AI链或让前端直连服务绕开Gateway。

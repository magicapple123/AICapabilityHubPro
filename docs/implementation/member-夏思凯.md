# 夏思凯任务与交接记录

负责人：夏思凯。状态：能力目录、内部详情、Schema/价格对齐、运营实时授权调用侧与市场/运营 UI 已交付；修复迁移覆盖自定义 Schema 的问题后，联合 PR #4 的隔离本地环境已通过严格 internal E2E、浏览器与真实管理员授权验证。最终合并仍须 PR CI 与另一成员审批。范围capability、市场/Console能力运营UI、目录契约/SQL，不代改user/billing/Gateway/AI执行链。

## 领取

- 基线：最新origin/main `9181524`。
- 分支：`feature/pro-capability-market`，目标 main，保留 Review 保护。
- 先读[开发指南](../../AICapabilityHubPro-开发指南.md)、[共享契约](../api-contract/pro-shared.md)与[目录契约](../api-contract/capability-service.md)。

## 已完成

- [x] `GET /internal/capability/{id}`：返回匹配 id/name/code/真实 status/内联 param_schema/0–1000000 整数 price_per_call；不返回 service/path；每次实时读取不缓存。
- [x] 未知/软删除返回 2002；draft/offline 如实返回；DB 中 Schema/状态/价格损坏返回 4002 失败关闭。
- [x] 分类/能力写操作与运营列表实时调用 `GET /internal/user/authorization?user_id=<当前ID>&required_role=admin`；校验 ID、normal、admin、authorized=true；普通用户 2007，超时/缺失/格式异常 4002。
- [x] 不信任客户端 role/X-User-Role 头，无本地管理员白名单；分类列表保持“登录即可读”，供筛选栏使用。
- [x] chat-completions / long-summary 的登记 Schema 对齐执行器：messages 1–40、role 三选一、content 1–12000、可选 temperature 0–2；text 1–12000、max_length 30–1000 默认 200；无 `$ref/$dynamicRef/$recursiveRef/$id`。
- [x] 登记/编辑与内部详情共用 Schema 校验（对象根类型、≤32768 字节、深度≤20、节点≤2000、Draft 2020-12 元 Schema）；非法关键字在登记或内部详情处即失败，不留给执行期。
- [x] 上架必须有合法 Schema：直接登记为 online、从 draft/offline 切 online、以及线上能力清空 Schema 均返回 2001；草稿/下架仍可暂不填写。
- [x] 新增独立增量迁移 `sql/03_align_executor_schema.sql`：修复版仅匹配完整旧 seed 默认 Schema 或 online 空 Schema；保留自定义/已有其他约束，draft/offline 空 Schema 不动；价格/状态不改，可重复执行。seed 与 deploy 镜像已同步且明确不可替代迁移。
- [x] 市场字段最小化与 `price_per_call` 展示保持；市场按钮传 `/chat?capability_id=<id>`，浏览器验收新增“从市场卡片进入对应能力”。
- [x] 运营 UI 直接展示服务端 2007/4002 文案（无运营权限 / 授权服务不可用已拒绝），最终权限不由前端决定。

## 测试与证据

```powershell
cd services/capability-service
.\.venv\Scripts\python.exe -m pytest -q -rs
```

- 2026-10-20，隔离 MySQL 8.0（端口 3308，独立数据目录，非开发库）上 `129 passed`，零跳过。
- seed 与 `03_align_executor_schema.sql` 在同一隔离实例实际执行成功；`chat-completions` 返回 maxItems=40、`additionalProperties=false`，内部详情读取 seed 记录 code=0。
- Web：`pnpm --dir web lint`、`pnpm --dir web build`、`node --experimental-strip-types --test tests/chat-schema.test.ts`（6/6）通过。
- 新增用例覆盖：内部详情字段与 requestId、draft/offline、未知/软删除、身份缺失、Schema 缺失/引用/非法 Draft 关键字/深度/体积、上架必须有合法 Schema、线上不能清空 Schema、价格 0 与 1000000 及越界、重复编码、普通用户写/读、伪造 role 头、撤权后再请求、授权超时/异常/不可信响应、市场字段最小化。
- 独立 `test_schema_migration.py` 覆盖精确旧 Schema、Schema 自定义约束/描述保留、online NULL 修复、draft/offline NULL 保留、软删除行不变、价格/状态不变、deploy 镜像同步以及重复运行幂等。
- Web 新增 2 项纯函数测试，市场详情可展开聊天消息数量/角色/内容长度与摘要范围/默认值；`chat-schema.test.ts` 现为 8/8。
- 组长复核：修复版 capability 131、PR #4 user 93、billing 87、AI 56，共367项在独立 MySQL 8.4.11 通过，零跳过/失败/错误；Web lint/build、Schema 8项与公共工具13项通过。
- 本地联合提交 `94b882f`（`f9c677b` + PR #4 `2f6f62c`）严格 internal E2E 21项与浏览器9项通过，报告 `member_internal_contract_verified=true`；独立真实管理员授权链9项通过。证据保存在 `artifacts/capability-review-fix/20261020-4a8fb7eb/integration-worktree/artifacts/leader-e2e/`，属隔离验收，不表示已合并或已人工审批。

## 未完成 / 阻塞

- [x] 联合 PR #4 提供端，真实 Gateway/capability/user 管理链已验证普通用户及伪造头拒绝、管理员写成功、撤权拒绝、禁用拒绝、依赖中断不写入；仅操作隔离数据库。
- [ ] CI 分别运行 market/internal 两种完整真实服务与浏览器 E2E；internal 报告必须 `passed=true`、`browser_verified=true`、`member_internal_contract_verified=true`。管理员授权依赖属于独立检查，需另通过真实 capability 管理请求验证。浏览器验收使用普通用户账号，应明确预期运营拒绝。
- [ ] 最终三成员联合验收、迁移演练与 Tag 发布。

## 依赖与兼容

授权固定 `GET /internal/user/authorization`，参数 `user_id` 与 `required_role=admin`，调用带当前链路身份。user-service PR #4 按当前共享契约在授权上下文用 `1006` 表示权限不足，本服务映射对外 `2007`，并兼容拒绝旧版本 `1007`；任何错误码都不会获得授权。API Key 的 `1006` 按其各自接口语义解释。

## 恢复方式

- 迁移前按 `sql/03_align_executor_schema.sql` 注释备份 `id/code/param_schema`；回滚按备份 id 写回。
- 测试使用独立 MySQL 实例并只清理 `qa-` 前缀数据；不得清开发库或删除数据卷。
- 若授权依赖异常，接口预期返回 4002 且不执行写操作；恢复 user-service 后无需重启 capability-service。

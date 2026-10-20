# 夏思凯任务与交接记录

负责人：夏思凯。状态：Pro 能力目录、内部详情、Schema/价格对齐、运营实时授权调用侧与市场/运营验收已完成代码与测试；user 授权端点仍未交付，真实授权联调与严格 internal 浏览器 E2E 待该依赖及其运行环境就绪。范围capability、市场/Console能力运营UI、目录契约/SQL，不代改user/billing/Gateway/AI执行链。

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
- [x] 登记/编辑与内部详情共用 Schema 结构校验（对象根类型、≤32768 字节、深度≤20、节点≤2000）。
- [x] 新增独立增量迁移 `sql/03_align_executor_schema.sql`：只补齐旧版简化 Schema，不改价格与上下架状态，可重复执行；seed 已同步并明确不可当迁移。
- [x] 市场字段最小化与 `price_per_call` 展示保持；市场按钮传 `/chat?capability_id=<id>`，浏览器验收新增“从市场卡片进入对应能力”。
- [x] 运营 UI 直接展示服务端 2007/4002 文案（无运营权限 / 授权服务不可用已拒绝），最终权限不由前端决定。

## 测试与证据

```powershell
cd services/capability-service
.\.venv\Scripts\python.exe -m pytest -q -rs
```

- 2026-10-20，隔离 MySQL 8.0（端口 3308，独立数据目录，非开发库）上 `118 passed`，零跳过。
- seed 与 `03_align_executor_schema.sql` 在同一隔离实例实际执行成功；`chat-completions` 返回 maxItems=40、`additionalProperties=false`，内部详情读取 seed 记录 code=0。
- Web：`pnpm --dir web lint`、`pnpm --dir web build`、`node --experimental-strip-types --test tests/chat-schema.test.ts`（6/6）通过。
- 新增用例覆盖：内部详情字段与 requestId、draft/offline、未知/软删除、身份缺失、Schema 缺失/引用/深度/体积、价格 0 与 1000000 及越界、重复编码、普通用户写/读、伪造 role 头、撤权后再请求、授权超时/异常/不可信响应、市场字段最小化。

## 未完成 / 阻塞

- [ ] user-service `GET /internal/user/authorization` 尚未交付：本服务按共享契约实现调用与失败关闭，尚未做真实管理员/撤权/禁用联调。提供方：黄禹菲。复现：未启动 user-service 时运营接口返回 4002。
- [ ] `python scripts/run_leader_e2e.py --catalog-mode internal --browser` 未在本机执行：Docker 引擎不可用，且严格链需要四服务、Nacos、Gateway 与 Chromium。CI 的 `Leader real-service integration` 当前只跑 market 模式。需要具备 Docker 的环境或由组长在联调机执行，并核对 `summary.json` 的 `member_internal_contract_verified=true`。
- [ ] 最终三成员联合验收、迁移演练与 Tag 发布。

## 依赖与兼容

授权固定 `GET /internal/user/authorization`，参数 `user_id` 与 `required_role=admin`，调用带当前链路身份。共享契约新增权限不足 1007；本服务对外映射 2007。`1006` 仍表示 user 的 API Key 不存在；仅在该授权端点把旧 user 构建可能返回的 1006 视为拒绝，不会放行。若 user 最终实现码值不同，需双方同步契约后再改调用侧。

## 恢复方式

- 迁移前按 `sql/03_align_executor_schema.sql` 注释备份 `id/code/param_schema`；回滚按备份 id 写回。
- 测试使用独立 MySQL 实例并只清理 `qa-` 前缀数据；不得清开发库或删除数据卷。
- 若授权依赖异常，接口预期返回 4002 且不执行写操作；恢复 user-service 后无需重启 capability-service。

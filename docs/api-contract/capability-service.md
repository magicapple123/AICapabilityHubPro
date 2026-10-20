# AICapabilityHub Pro · capability-service 接口契约

**实现状态（2026-10-20，PR #4/#5已集成main `651275b`）：** 内部目录、实时授权双方实现与安全迁移已合入。主分支CI `39420321602` 为9/9，capability 131项零跳过，完整internal E2E21项与原浏览器9项通过；另有真实管理授权9项证据，不等同人工审批。新增管理员Console/市场联动浏览器验收见[收尾记录](../验收收尾记录-2026-10-20.md)。市场按钮传选中 ID 已随10/20前端调整完成，见[验收记录](../前端改版与验收-2026-10-20.md)。规则见 [Pro 开发指南](../../AICapabilityHubPro-开发指南.md)与[共享契约](pro-shared.md)。

> 负责人：夏思凯
> 服务名：`capability-service`
> 数据库：`capability_db`
> 端口：8082
> Pro 管理保护调用 user-service 的实时 authorization，禁止跨库读取角色；依赖不可用时拒绝运营操作。

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401。

## 0. 通用约定

- **登录要求**：除 `/api/capability/market/**` 与 `/health` 外，`/api/**` 全部需要网关 JWT。网关白名单已配置为 `/api/capability/market` 及其子路径。`/internal/capability/**` 只供服务间直连，网关对外一律 403，直连时仍校验链路 `X-User-Id`。
- **分页格式**：`data = {"list": [...], "total": 100, "page": 1, "page_size": 10}`；`page_size` 默认 10、最大 100。分类列表不分页（返回 `{"list": [...], "total": n}`），分类数量少且前端筛选栏需要一次取全。
- **软删除**：所有查询默认过滤 `is_deleted=0`；`DELETE` 均为软删除，不物理删除。
- **身份来源**：从网关注入的 `X-User-Id` / `X-User-Name` / `X-Request-Id` 读取，服务内不重复解析 JWT。
- **时间格式**：`create_time` / `update_time` 返回 `YYYY-MM-DD HH:MM:SS`（本地时区 Asia/Shanghai）。
- **金额语义**：`price_per_call` 为整数（每次调用消耗的积分数），不使用浮点，范围 0–1000000。
- **运营授权**：分类/能力的新增、修改、删除、上下架与运营列表，每次请求实时调用 user-service 授权接口；普通用户返回 `2007`，依赖超时/缺失/响应格式异常返回 `4002` 并拒绝操作。分类列表只需登录，供前端筛选栏使用。

## 1. 数据字典

### `t_capability_category`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `name` | VARCHAR(64) | NOT NULL | 分类名称，未删除范围内唯一 |
| `code` | VARCHAR(64) | NOT NULL | 分类编码，未删除范围内唯一 |
| `sort` | INT | NOT NULL DEFAULT 0 | 越小越靠前 |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'enabled' | 分类固定 enabled / disabled；与能力状态区分 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

### `t_capability`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 主键 |
| `category_id` | BIGINT | NOT NULL, INDEX | 所属分类 |
| `name` | VARCHAR(64) | NOT NULL | 能力名称 |
| `code` | VARCHAR(64) | NOT NULL | 能力编码，未删除范围内唯一 |
| `service_name` | VARCHAR(64) | NOT NULL | 承载能力的服务名，如 `ai-chat-service` |
| `path` | VARCHAR(255) | NOT NULL | 调用路径，如 `/api/chat/completions` |
| `param_schema` | JSON | NULL | 参数 Schema（JSON 对象）；draft/offline 可为空，online 必须有合法 Schema |
| `price_per_call` | INT | NOT NULL DEFAULT 0 | 每次调用积分单价 |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'draft' | `draft` / `online` / `offline` |
| `description` | VARCHAR(512) | NOT NULL DEFAULT '' | 能力描述 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

**索引**：`t_capability` 需建 `UNIQUE(code, is_deleted)` 等价唯一保护，以及 `INDEX(category_id, status)` 供市场筛选。

## 2. 分类接口

### `GET /api/capability/categories`

- 负责人：夏思凯
- 是否需要登录：是
- 查询参数：`status`（可选，`enabled` / `disabled`）、`keyword`（可选，按 `name` 模糊匹配）
- 成功 data：`{"list": [{"id": 1, "name": "语言处理", "code": "nlp", "sort": 10, "status": "enabled", "create_time": "...", "update_time": "..."}], "total": 1}`
- 错误码：`2001` 参数不符合 Schema
- 备注：按 `sort` 升序、`id` 升序返回。

### `POST /api/capability/categories`

- 负责人：夏思凯
- 是否需要登录：是
- 请求体：`{"name": "语言处理", "code": "nlp", "sort": 10}`
- 成功 data：`{"id": 1, "name": "语言处理", "code": "nlp", "sort": 10, "status": "enabled"}`
- 错误码：`2001` 参数不符合 Schema；`2004` 分类名称或编码已存在；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：`status` 默认 `enabled`；`code` 只允许小写字母、数字和连字符。需实时管理员授权。

### `PUT /api/capability/categories/{category_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`category_id`（int）
- 请求体：`{"name": "语言处理", "code": "nlp", "sort": 20, "status": "disabled"}`（字段均可选，仅提交需要变更的项）
- 成功 data：更新后的分类对象
- 错误码：`2001` 参数不符合 Schema；`2003` 分类不存在；`2004` 分类名称或编码已存在；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：幂等；重复提交同一变更不产生副作用。需实时管理员授权。

### `DELETE /api/capability/categories/{category_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`category_id`（int）
- 成功 data：`{"id": 1, "is_deleted": 1}`
- 错误码：`2003` 分类不存在；`2005` 分类下仍有能力，不可删除；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：软删除；删除前检查该分类下是否存在 `is_deleted=0` 的能力，存在则拒绝。需实时管理员授权。

## 3. 能力接口（需要登录）

### `POST /api/capability`

- 负责人：夏思凯
- 是否需要登录：是
- 请求体：

```json
{
  "category_id": 1,
  "name": "多轮对话",
  "code": "chat-completions",
  "service_name": "ai-chat-service",
  "path": "/api/chat/completions",
  "param_schema": {"type": "object", "properties": {"messages": {"type": "array"}}},
  "price_per_call": 5,
  "description": "多轮对话与文本生成",
  "status": "draft"
}
```

- 成功 data：登记后的能力对象（含 `id`、`create_time`）
- 错误码：`2001` 参数不符合 Schema；`2003` 分类不存在；`2006` 能力编码已存在；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：`status` 缺省为 `draft`；`price_per_call` 必须为 0–1000000 的整数；`code` 只允许小写字母、数字和连字符；`param_schema` 只接受对象根类型、合法 Draft 2020-12 的内联 JSON Schema，禁止 `$ref/$dynamicRef/$recursiveRef/$id`。`status=online` 时必须同时提供合法 Schema，否则 2001；draft/offline 可暂不提供。登记后默认不上架，需再由 `PUT /{id}/status` 上架。需实时管理员授权。

### `PUT /api/capability/{capability_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`capability_id`（int）
- 请求体：同 `POST /api/capability`，字段均可选（不含 `status`）
- 成功 data：更新后的能力对象
- 错误码：`2001` 参数不符合 Schema；`2002` 能力不存在；`2003` 分类不存在；`2006` 能力编码已存在；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：状态变更必须走 `PUT /{id}/status`，此接口忽略 `status` 字段；`param_schema` 边界同登记接口。online 能力不能把 `param_schema` 清空，需先下架。需实时管理员授权。

### `DELETE /api/capability/{capability_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`capability_id`（int）
- 成功 data：`{"id": 1, "is_deleted": 1}`
- 错误码：`2002` 能力不存在；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：软删除；`online` 能力删除前需先下架或由实现直接置为软删除（实现按"先下架再删除"处理，避免市场出现已删除条目）。需实时管理员授权。

### `PUT /api/capability/{capability_id}/status`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`capability_id`（int）
- 请求体：`{"status": "online"}`
- 成功 data：`{"id": 1, "status": "online", "update_time": "..."}`
- 错误码：`2001` 参数不符合 Schema（`status` 不在 `draft`/`online`/`offline` 内）；`2002` 能力不存在；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：上下架唯一入口；`online` 为市场可见状态，`offline` / `draft` 均不可见。切到 online 要求该能力已有合法 Schema，否则 2001。需实时管理员授权；状态改变在下一次内部详情读取时立即生效。

## 4. 市场与运营接口

### `GET /api/capability/market`

- 负责人：夏思凯
- 是否需要登录：**否（网关白名单）**
- 查询参数：`category_id`（可选）、`keyword`（可选，按 `name` / `description` 模糊匹配）、`page`、`page_size`
- 成功 data：

```json
{
  "list": [
    {
      "id": 1,
      "name": "多轮对话",
      "code": "chat-completions",
      "category_id": 1,
      "category_name": "语言处理",
      "description": "多轮对话与文本生成",
      "price_per_call": 5,
      "update_time": "2026-09-15 10:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

- 错误码：`2001` 参数不符合 Schema
- 备注：只返回 online 且未删除能力。列表不含 service_name/path/param_schema；详情另含 param_schema，仍不暴露 service/path/密钥。category_name 来自本库分类，不跨库。公开可见不等于有可执行 adapter。

### `GET /api/capability/market/categories`

- 负责人：夏思凯
- 是否需要登录：**否（网关白名单）**
- 成功 data：`{"list": [{"id": 1, "name": "语言处理", "code": "nlp"}], "total": 1}`
- 备注：仅返回存在 `online` 能力的分类，供前端市场页筛选按钮使用。**路由声明必须早于 `/market/{capability_id}`**，否则 `categories` 会被当作路径参数解析。

### `GET /api/capability/market/{capability_id}`

- 负责人：夏思凯
- 是否需要登录：**否（网关白名单）**
- 路径参数：`capability_id`（int）
- 成功 data：市场可见字段的能力详情（同列表项，另含 `param_schema`）
- 错误码：`2002` 能力不存在或已下线
- 备注：`draft` / `offline` / 已软删除的能力一律返回 `2002`，不暴露其存在性。

### `GET /api/capability/manage`

- 负责人：夏思凯
- 是否需要登录：是
- 查询参数：`status`（可选，`draft`/`online`/`offline`）、`category_id`（可选）、`keyword`（可选）、`page`、`page_size`
- 成功 data：分页结构，列表项为完整能力对象（含 `service_name`、`path`、`param_schema`、`status`、`category_name`）
- 错误码：`2001` 参数错误；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：运营列表，仅管理员可读，返回全部状态；更新时间倒序。

### `GET /internal/capability/{capability_id}`

- 负责人：夏思凯
- 是否需要登录：服务间接口。网关对外部 `/internal/**` 一律 403；直连服务时仍要求链路 `X-User-Id`，缺失返回 `1001`
- 路径参数：`capability_id`（int）
- 成功 data：

```json
{
  "id": 1,
  "name": "多轮对话",
  "code": "chat-completions",
  "status": "online",
  "param_schema": {"type": "object", "properties": {"messages": {"type": "array"}}},
  "price_per_call": 5
}
```

- 错误码：`1001` 链路身份缺失；`2002` 能力不存在或已软删除；`4002` 数据库中 Schema/状态/价格配置不合法
- 备注：每次调用实时读取，不缓存；状态改变在下一次读取立即生效。`draft` / `offline` 保留真实状态，由执行器拒绝。不返回 `service_name` / `path`，避免被当作任意代理目标。`price_per_call` 为 0–1000000 整数，`param_schema` 为对象根类型、通过 Draft 2020-12 元 Schema 校验的内联 Schema。

### `GET /api/capability/ping`、`GET /health`

- 现有健康接口保持。health 公开；ping 经 Gateway 需要 JWT，用于验证可信身份/requestId。health 为 UP 只表示应用存活，不代表目录配置、内部详情或授权依赖已可用。

## 5. 错误码（仅使用 2xxx 号段）

| code | message | 触发场景 |
|---|---|---|
| 2001 | 参数不符合 Schema | 必填缺失、类型错误、枚举非法、JSON 结构错误（基座统一处理）；上架缺少合法 Schema |
| 2002 | 能力不存在或已下线 | 能力 ID 不存在、已软删除、`draft`/`offline` 被外部访问 |
| 2003 | 分类不存在 | `category_id` 不存在或已软删除 |
| 2004 | 分类名称或编码已存在 | 分类 `name` / `code` 冲突 |
| 2005 | 分类下仍有能力，不可删除 | 删除前引用检查未通过 |
| 2006 | 能力编码已存在 | 能力 `code` 冲突 |
| 2007 | 无运营权限 | 非管理员访问运营列表/写接口，由实时授权结果决定 |

> `4002` 不属于业务 2xxx 号段，表示授权/目录依赖不可用或目录配置异常；出现时一律拒绝操作，不降级放行。

## 6. Pro 内部接口、授权与市场（本轮实现）

1. 运营列表与分类/能力全部写操作已接入 GET `/internal/user/authorization?user_id=<当前用户ID>&required_role=admin`。只有返回 ID 匹配、`normal`/`admin`/`authorized=true` 才放行；普通用户 `2007`，超时、端点缺失、响应格式异常 `4002` 失败关闭。Gateway 透传的 role 不作为授权依据，也不存在本地管理员白名单。
2. 授权码以[共享契约](pro-shared.md)和 user-service PR #4 为准：授权上下文中的 `1006` 表示权限不足，capability 映射为对外 `2007`。API Key 业务的 `1006` 仍保留原语义；错误码只在各自端点上下文解释。capability 为兼容分支/旧版本也会把 user 返回的 `1007` 视作拒绝，不能放行。
3. 已提供 GET `/internal/capability/{capability_id}`，成功 data 为匹配正整数 id、name、code、真实 status、内联 param_schema、0–1000000 整数 price_per_call。不返回可供任意代理的 URL；未知/软删除 `2002`，draft/offline 如实标识，AI 会拒绝。
4. AI 客户端、allowlist 和目录价计量已实现，默认 internal 缺失端点失败关闭。质量门禁分别运行 market 与 internal 两种模式的完整真实服务/浏览器验收；internal `summary.json` 必须同时记录 `passed=true`、`browser_verified=true`、`member_internal_contract_verified=true`。market 主链成功或单独探针不能替代完整 internal 验收。
5. code 固定 chat-completions / long-summary，对应 input.messages / input.text 与可选 max_length。Schema 按现有执行器内联结构（对象根类型、无 `$ref/$dynamicRef/$recursiveRef/$id`、大小≤32768、深度≤20、节点≤2000），登记与内部详情都通过 Draft 2020-12 元 Schema 校验；非法关键字在登记时返回 2001、在内部详情返回 4002，不会留到执行期。上架要求已有合法 Schema，避免市场展示必然失败的配置。状态/单价一改在下一次调用生效，不缓存旧状态。
6. 市场使用真实目录接口。按钮传 `/chat?capability_id=<id>`，Chat 已接受；未实现执行器的视觉等能力明确不可体验，不补虚构延迟或耗时。
7. 分类 enabled/disabled、能力 draft/online/offline、价格整数积分已定稿。注册记录的 service/path 不决定执行目标，新增 code 需真正 adapter 与安全验收。

## 7. 示例数据与验收

首次或明确的隔离示例库使用本服务 sql；seed 会更新同名演示记录，不是已有业务库的增量迁移：

- 2 个分类：`nlp`（语言处理）、`multimodal`（多模态）
- 3 个能力：
  - `chat-completions`（多轮对话，`ai-chat-service`，`/api/chat/completions`，`online`）— 支撑主闭环演示
  - `long-summary`（长文本摘要，`online`）
  - `vision-parse`（视觉理解，`draft`，用于验证市场不可见）
- 现有聊天价格 5、摘要 3；AI 验证目录状态/Schema/price，不按固定 POINTS_COST。演示数据不包含真实凭证。
- `chat-completions` / `long-summary` 的 `param_schema` 已与执行器约束对齐：聊天 `messages` 1–40 条、role 三选一、content 1–12000、可选 temperature 0–2；摘要 `text` 1–12000、可选 `max_length` 30–1000（默认 200）；使用布尔 `additionalProperties=false`。
- 已有业务库的结构升级使用独立增量脚本 `sql/03_align_executor_schema.sql`：只有 Schema 完整匹配历史 seed 默认值，或 online 能力的 Schema 为空时才应用适配器模板；不根据单个字段缺失推断“旧版”，以免覆盖自定义限制/元数据。draft/offline 的空 Schema 保持为空；单价与状态始终不改。执行前备份受影响行。`sql/02_seed.sql` 仅用于新环境或明确的隔离示例库。迁移可重复执行，迁移过滤规则另有真实 MySQL 回归测试。未知/自定义结构升级需由运营人员单独审阅，不做自动覆盖。
- 已覆盖内部详情、公开字段最小化、状态变化、未知/软删除、Schema 引用/非法 Draft 关键字/上架必须有合法 Schema/价格边界、重复编码、非管理员直接写/管理读取、授权撤销/故障、迁移保留自定义 Schema/升级旧 Schema/幂等以及市场选中 ID 的浏览器入口。集成main `651275b` 的CI中capability-service实际 `131 passed`、零跳过；迁移也已覆盖自定义Schema保留和重复运行。真实管理员授权、严格 internal 目录链与完整浏览器运行须依据最终 CI artifact 和 `summary.json` 分开核对，替身测试不当作真实联调。

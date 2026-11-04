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
| `openai_alias` | VARCHAR(64) | NULL, UNIQUE | OpenAI 兼容公开模型名；仅在线、`executor=chat` 且入参 Schema `required` 含 `messages` 的能力进入 `/v1/models` |
| `service_name` | VARCHAR(64) | NOT NULL | 承载能力的服务名，如 `ai-chat-service` |
| `path` | VARCHAR(255) | NOT NULL | 调用路径，如 `/api/chat/completions` |
| `param_schema` | JSON | NULL | 参数 Schema（JSON 对象）；draft/offline 可为空，online 必须有合法 Schema |
| `price_per_call` | INT | NOT NULL DEFAULT 0 | 每次调用积分单价 |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'draft' | `draft` / `online` / `offline` |
| `description` | VARCHAR(512) | NOT NULL DEFAULT '' | 能力描述 |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见Pro开发指南第9节及当前sql/01_init.sql |

**索引**：`t_capability` 使用 `uk_capability_active_code` 保证未删除 code 唯一，`uk_capability_openai_alias` 保证非空模型别名唯一，以及 `INDEX(category_id, status)` 供市场筛选。

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
  "openai_alias": "team-chat-v1",
  "service_name": "ai-chat-service",
  "path": "/api/chat/completions",
  "param_schema": {"type": "object", "properties": {"messages": {"type": "array"}}},
  "price_per_call": 5,
  "description": "多轮对话与文本生成",
  "status": "draft"
}
```

- 成功 data：登记后的能力对象（含 `id`、`create_time`）
- 错误码：`2001` 参数不符合 Schema；`2003` 分类不存在；`2006` 能力编码或对外模型名已存在；`2007` 非管理员；`4002` 授权依赖不可用
- 备注：`status` 缺省为 `draft`；`price_per_call` 必须为 0–1000000 的整数；`code` 只允许小写字母、数字和连字符；`param_schema` 只接受对象根类型、合法 Draft 2020-12 的内联 JSON Schema，禁止 `$ref/$dynamicRef/$recursiveRef/$id`。`status=online` 时必须同时提供合法 Schema，否则 2001；draft/offline 可暂不提供。登记后默认不上架，需再由 `PUT /{id}/status` 上架。需实时管理员授权。

### `PUT /api/capability/{capability_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`capability_id`（int）
- 请求体：同 `POST /api/capability`，字段均可选（不含 `status`）
- 成功 data：更新后的能力对象
- 错误码：`2001` 参数不符合 Schema；`2002` 能力不存在；`2003` 分类不存在；`2006` 能力编码或对外模型名已存在；`2007` 非管理员；`4002` 授权依赖不可用
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

### `GET /internal/capability/openai-models`

- 负责人：capability-service
- 是否需要登录：服务间接口；网关对外部 `/internal/**` 一律 403，直连服务时要求链路 `X-User-Id`
- 成功 data：`[{"id": 1, "openai_alias": "team-chat-v1"}]`；未配置别名但通过发布门禁的能力会以 `openai_alias: null` 返回，供兼容映射校验目标状态。
- 过滤条件：`status=online`、`executor=chat`、未软删除，且**入参 Schema 的 `required` 包含 `messages`**；不依赖市场展示开关
- 备注：只返回模型路由所需的最小字段，不包含供应商、地址或其他内部配置。只有非空 `openai_alias` 会进入动态别名表。第三条过滤是发布门禁：借 `chat` 执行器但入参不是 `messages` 的能力（如视觉类 `required: ["image_url"]`）不返回——兼容层永远拼不出它的必填字段，发布出去只会让客户端"选了再报参数错"。Schema 解析失败按不可发布处理。

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
  "openai_alias": "team-chat-v1",
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
| 2006 | 能力编码或对外模型名已存在 | 能力 `code` 或 `openai_alias` 冲突 |
| 2007 | 无运营权限 | 非管理员访问运营列表/写接口，由实时授权结果决定 |

> `4002` 不属于业务 2xxx 号段，表示授权/目录依赖不可用或目录配置异常；出现时一律拒绝操作，不降级放行。

## 6. Pro 内部接口、授权与市场（本轮实现）

1. 运营列表与分类/能力全部写操作已接入 GET `/internal/user/authorization?user_id=<当前用户ID>&required_role=admin`。只有返回 ID 匹配、`normal`/`admin`/`authorized=true` 才放行；普通用户 `2007`，超时、端点缺失、响应格式异常 `4002` 失败关闭。Gateway 透传的 role 不作为授权依据，也不存在本地管理员白名单。
2. 授权码以[共享契约](pro-shared.md)和 user-service PR #4 为准：授权上下文中的 `1006` 表示权限不足，capability 映射为对外 `2007`。API Key 业务的 `1006` 仍保留原语义；错误码只在各自端点上下文解释。capability 为兼容分支/旧版本也会把 user 返回的 `1007` 视作拒绝，不能放行。
3. 已提供 GET `/internal/capability/{capability_id}`，成功 data 为匹配正整数 id、name、code、真实 status、内联 param_schema、0–1000000 整数 price_per_call。不返回可供任意代理的 URL；未知/软删除 `2002`，draft/offline 如实标识，AI 会拒绝。
4. P2 新增 GET `/internal/capability/openai-models`，只返回在线 chat 能力 ID 与 `openai_alias`；动态别名在 ai-chat 复用 5 秒目录缓存，能力写入后通过既有失效接口清除。`OPENAI_COMPAT_MODEL_MAP` 中的兼容别名仅在目标仍是在线 chat 能力时返回。
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
- `chat-completions` / `long-summary` 的 `param_schema` 已与执行器约束对齐：聊天 `messages` 1–40 条、role 三选一、content 1–48000、可选 temperature 0–2；摘要 `text` 1–48000、可选 `max_length` 30–1000（默认 200）；使用布尔 `additionalProperties=false`。已有库的旧值用 `sql/11_raise_message_max_length.sql` 幂等提升。
- 已有业务库的结构升级使用独立增量脚本 `sql/03_align_executor_schema.sql`：只有 Schema 完整匹配历史 seed 默认值，或 online 能力的 Schema 为空时才应用适配器模板；不根据单个字段缺失推断“旧版”，以免覆盖自定义限制/元数据。draft/offline 的空 Schema 保持为空；单价与状态始终不改。执行前备份受影响行。`sql/02_seed.sql` 仅用于新环境或明确的隔离示例库。迁移可重复执行，迁移过滤规则另有真实 MySQL 回归测试。未知/自定义结构升级需由运营人员单独审阅，不做自动覆盖。
- 已覆盖内部详情、公开字段最小化、状态变化、未知/软删除、Schema 引用/非法 Draft 关键字/上架必须有合法 Schema/价格边界、重复编码、非管理员直接写/管理读取、授权撤销/故障、迁移保留自定义 Schema/升级旧 Schema/幂等以及市场选中 ID 的浏览器入口。集成main `651275b` 的CI中capability-service实际 `131 passed`、零跳过；迁移也已覆盖自定义Schema保留和重复运行。真实管理员授权、严格 internal 目录链与完整浏览器运行须依据最终 CI artifact 和 `summary.json` 分开核对，替身测试不当作真实联调。


## 8. 本轮增量：C2 双轨计费

### 8.1 计价字段与组合约束

新增 5 个字段（见第 1 节数据字典）。**校验在保存阶段完成**，不满足返回 `2001`：

| 模式 | 必须满足 | 说明 |
|---|---|---|
| `per_call` | `price_per_1k_input = price_per_1k_output = price_per_unit = 0` | 允许 `price_per_call = 0`（免费能力） |
| `per_token` | `price_per_1k_input > 0 或 price_per_1k_output > 0`，且 `price_per_call = 0` | 防止"按次 + 按 token"双重计价 |
| `per_unit` | `price_per_unit > 0` 且 `unit` 非空，且 `price_per_call = 0` | 单位必填，避免"3 积分/?" |

编辑接口按**改后整组**校验：只把 `billing_mode` 改成 `per_token` 而不把 `price_per_call` 清零会被拒绝。

### 8.2 出参变化（旧字段不动）

| 出参 | 新增字段 |
|---|---|
| `GET /internal/capability/{id}` | `billing_mode`、`price_per_1k_input`、`price_per_1k_output`、`price_per_unit`、`unit` |
| `GET /api/capability/market` | `billing_mode`、`unit`（仍不含 `service_name` / `path`） |
| `GET /api/capability/market/{id}` | 上述 + `price_per_1k_input`、`price_per_1k_output`、`price_per_unit` |
| `GET /api/capability/manage` | 全部 5 个计价字段 |

`price_per_call` 在所有出参中保留原语义，旧前端不感知新字段也能正常工作。

### 8.3 迁移

- 增量脚本：`services/capability-service/sql/04_add_billing_mode.sql`（可重复执行）。
- 迁移后旧两行（`chat-completions` / `long-summary`）仍是 `per_call`、单价 5 / 3，脚本末尾会打印自检结果。


## 9. 本轮增量：B1 运营审计

### 9.1 `t_operation_log`（只追加）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT | PK | 主键 |
| `operator_id` | VARCHAR(64) | NOT NULL | 操作人 user_id（网关注入，服务端可信） |
| `operator_name` | VARCHAR(64) | NOT NULL DEFAULT '' | 操作人名称快照 |
| `resource_type` | VARCHAR(32) | NOT NULL | `capability` / `category` / `user` / `points` / `apikey` |
| `resource_id` | VARCHAR(64) | NOT NULL DEFAULT '' | 自增 ID 或业务编码 |
| `action` | VARCHAR(32) | NOT NULL | `create` / `update` / `status` / `delete` / `rollback` |
| `before_json` | JSON | NULL | 变更前白名单字段快照（已脱敏） |
| `after_json` | JSON | NULL | 变更后白名单字段快照（已脱敏） |
| `request_id` | VARCHAR(64) | NOT NULL DEFAULT '' | 全链路 requestId |
| `create_time` / `is_deleted` | — | 通用字段 | `is_deleted` 不参与业务，审计不使用 |

**一库一张同构表**：capability 的写操作落 `capability_db`；user-service 的用户管理写操作在
批 5 落 `user_db` 的同构表。四库物理隔离，**不跨库查询**。

**只追加的保证（三层）**：接口只有 `GET`；`AuditService` 没有写方法；
repository 没有 update/delete 方法。写入由业务 repository 在**同一个 `commit`** 内完成。

**脱敏**：键名命中 `password/passwd/secret/api_key/apikey/token/cipher` 的值替换为 `***`。

### 9.2 `GET /api/capability/audit`

- 权限：`require_admin` 实时校验（普通用户 `2007`，依赖不可用 `4002`）
- 查询参数：`resource_type`、`resource_id`、`action`、`operator_id`、`start_date`、`end_date`、`page`、`page_size`
- 出参：标准分页 `{list,total,page,page_size}`，元素字段同 9.1（不含 `is_deleted`）
- 排序：`id` 倒序

### 9.3 埋点位置

| 资源 | 动作 | 位置 |
|---|---|---|
| 能力 | create / update / status / delete | `capability_service.*` → `capability_repository.*` |
| 分类 | create / update / delete | `category_service.*` → `category_repository.*` |

> 操作者来自 `require_admin` 写入的请求级上下文（ContextVar），service 不新增参数；
> 无操作者上下文（内部调用/测试直调）时跳过审计，不伪造 operator。


## 10. 本轮增量：D2 执行器抽象 / D4 输出上限

### 10.1 新增字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `executor` | VARCHAR(32) | `chat`（创建时） | `chat` / `summary` / `image-generate` / `embedding` |
| `provider_alias` | VARCHAR(64) | `''` | 供应商别名（在 ai_chat_db，跨库不建外键） |
| `max_output_tokens` | INT | 1024 | 单次输出上限，执行时取 `min(请求值, 本值)` |

### 10.2 保存阶段的绑定校验

- `executor` 必须是四个取值之一，否则 `2001`；
- `image-generate` / `embedding` **必须**绑定 `provider_alias`（否则 `2001`，避免"上架了但跑不了"）；
- 绑定别名时，capability 会调 ai-chat 的 `GET /internal/provider/{alias}` 确认协议：
  `chat`/`summary` → `openai-chat`，`image-generate` → `openai-image`，`embedding` → `openai-embedding`；
  别名不存在 `2001`，对端不可用 `4002`（失败关闭）。
- 编辑按"改后整组"校验，与计价字段同一套规则。

### 10.3 出参

内部详情、市场列表/详情、运营列表均新增 `executor`、`provider_alias`、`max_output_tokens`；
市场侧仍不含 `service_name` / `path`。旧字段不变。

### 10.4 迁移

`sql/06_add_executor.sql`：增 3 列，并按已知 code 回填 `chat-completions → chat`、
`long-summary → summary`（幂等，不猜测其它编码）。

## 11. 本轮增量：P2 OpenAI 动态模型别名

- `t_capability.openai_alias` 可空，格式为 `^[a-z][a-z0-9._-]{1,63}$`，非空值唯一；软删除时清空，避免占用可复用别名。
- 新建/编辑返回 `2006` 表示能力编码或对外模型名冲突；市场公开字段保持不变，运营列表与服务间目录包含该字段。
- `GET /v1/models` 从在线 chat 目录产生动态别名，并合并 `OPENAI_COMPAT_MODEL_MAP` 覆盖；兼容映射目标不在发布集合内时不展示。发布集合见文末「兼容层发布门禁」。
- 增量迁移：`services/capability-service/sql/10_add_openai_alias.sql`；新装 MySQL 基线由 `scripts/devtools/sync_mysql_baseline.py` 从服务 SQL 同步到 `deploy/mysql/init/03_capability_service.sql`。两者均可重复执行。

### P11 上游模型选择（2026-11-03）

平台 `/api/chat/completions` 的显式 `model` 优先于绑定供应商的 `default_model`；只有未绑定供应商时才回退全局 `MODEL_NAME`。绑定供应商但两者均为空时返回 `4002`，明确提示补默认模型，不静默发送全局名称。`/v1` 的 `model` 是平台能力别名，只用于解析能力，绝不作为上游模型名。相同规则适用于 chat、summary 与流式；图片仍由图片供应商配置决定。供应商编辑页在默认模型为空时给出调用限制提示。

### P1 供应商状态与错误码（2026-11-03）

`2008` 只表示执行器未实现，原文案保留。`2009` 表示绑定供应商不存在、未启用或被停用；运行期点名alias，OpenAI/Responses兼容层映射为HTTP503、type=api_error、code=platform_2009。保存绑定时仅接受enabled供应商，draft/disabled返回2001并提示先测试启用，状态缺失按4002失败关闭。供应商变更不改变一次调用一条账单、失败不扣分的口径。无新增表字段或接口。

### P3 对外模型名清单（2026-11-03）

新增 `GET /api/capability/models`（需登录，普通用户可读）：返回 `{"list":[{"alias","capability_id","name"}],"total":n}`，只包含 `status=online`、`executor=chat`、`openai_alias` 非空，且**入参 Schema `required` 含 `messages`** 的能力，顺序按 alias 升序。用途是设置页「使用方法」抽屉自动填充 `model`；抽屉按安全约定不读取 Secret，因此不能调 `/v1/models`。该接口不返回 `service_name` / `path` / `base_url` / 密钥 / 执行参数。未登录 `1001`；过滤口径必须与 `/v1/models` 一致（摘要、文生图与视觉均不出现）。

### P8/P9 能力登记表单字段（2026-11-03）

创建与更新接口的字段集已对齐（`executor` / `provider_alias` / `billing_mode` / `price_per_1k_input` / `price_per_1k_output` / `price_per_unit` / `unit` / `max_output_tokens` / `exposed_to_market`），本轮只补前端表单与"可执行性"判定：判定口径为 `executor = 能力.executor || CODE_TO_EXECUTOR[code]`，再判断 `executor ∈ /api/chat/executors.executors`。历史 executor 为空的能力靠 code→executor 回退，行为不变。供应商协议匹配仅作前端提示，最终仍由本服务 `2001` 拒绝。

**市场出参补字段（加法，2026-11-03）**：`GET /api/capability/market` 列表项新增 `executor`（`chat` / `summary` / `image-generate` / 空串）；`GET /api/capability/market/{id}` 详情此前已声明 `executor` / `provider_alias` / `max_output_tokens` 但 `from_row` 未赋值（运行期恒为空/1024），本轮补齐。市场仍不含 `service_name` / `path` / 密钥；列表新增的 `executor` 只表明"用哪个受控执行器跑"，不泄露上游地址。历史能力 `executor` 为空时原样返回空串，由前端 code 回退，不伪造值。

### 兼容层发布门禁（2026-11-04）

`GET /internal/capability/openai-models` 与 `GET /api/capability/models` 的过滤条件在原有 `status=online` + `executor=chat` + 未软删除之上，新增**入参 Schema 的 `required` 必须包含 `messages`**。

原因：`executor=chat` 只表示借用聊天执行器，不代表能承载 OpenAI Chat 协议。视觉类能力（`vision-parse`）的 Schema `required` 是 `["image_url"]`，而兼容层只会拼出 `messages`，一旦发布，客户端会"选得到但调不通"，返回 400 `platform_2001`（参数不符合 Schema），语义上误导成参数错误。加门禁后这类能力不再出现在 `/v1/models`，直接指定该别名返回 404 `model_not_found`——**未发布 ≠ 参数错误**。

约束：
- 对外模型名（`openai_alias`）仍允许填写，用于平台「模型服务」页展示与能力目录完整性；发布与否由 Schema 决定，不再由"是否填了别名"决定。
- Schema 缺失或无法解析时按**不可发布**处理（失败关闭），宁可少列一个，也不把必失败的模型推给客户端。
- 两个接口共用同一判定函数，口径必须一致；新增/修改能力后经 5 秒目录缓存生效。

对应实现：`app/repository/capability_repository.py::_accepts_chat_messages`；用例见 `tests/test_models_api.py::test_models_hides_non_chat_shape_even_with_alias`。

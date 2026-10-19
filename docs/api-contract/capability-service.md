# AICapabilityHub Pro · capability-service 接口契约

**实现状态（2026-10-19，main 1b89ce8）：** 分类、登记/上下架、公开市场与运营列表为现有基础实现；内部详情、实时管理员保护、市场按钮传选中 ID 为本轮待交接任务。AI 调用端和 Chat 已具备，不能重新决定“不做内部详情”。规则见 [Pro 开发指南](../../AICapabilityHubPro-开发指南.md)与[共享契约](pro-shared.md)。

> 负责人：夏思凯
> 服务名：`capability-service`
> 数据库：`capability_db`
> 端口：8082
> 当前基础实现无跨服务依赖；Pro 管理保护需调用 user-service 的实时 authorization，禁止跨库读取角色。

所有响应均为统一 `Result`：`{code, message, data, requestId}`；`requestId` 为唯一驼峰字段，其余业务字段使用 `snake_case`。业务错误 HTTP 200，由 `code` 区分；网关认证失败 HTTP 401。

## 0. 通用约定

- **登录要求**：除 `/api/capability/market/**` 与 `/health` 外，全部需要网关 JWT。网关白名单已配置为 `/api/capability/market` 及其子路径。
- **分页格式**：`data = {"list": [...], "total": 100, "page": 1, "page_size": 10}`；`page_size` 默认 10、最大 100。分类列表不分页（返回 `{"list": [...], "total": n}`），分类数量少且前端筛选栏需要一次取全。
- **软删除**：所有查询默认过滤 `is_deleted=0`；`DELETE` 均为软删除，不物理删除。
- **身份来源**：从网关注入的 `X-User-Id` / `X-User-Name` / `X-Request-Id` 读取，服务内不重复解析 JWT。
- **时间格式**：`create_time` / `update_time` 返回 `YYYY-MM-DD HH:MM:SS`（本地时区 Asia/Shanghai）。
- **金额语义**：`price_per_call` 为整数（每次调用消耗的积分数），不使用浮点。

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
| `param_schema` | JSON | NULL | 参数 Schema（JSON 对象） |
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
- 错误码：`2001` 参数不符合 Schema；`2004` 分类名称或编码已存在
- 备注：`status` 默认 `enabled`；`code` 只允许小写字母、数字和连字符。

### `PUT /api/capability/categories/{category_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`category_id`（int）
- 请求体：`{"name": "语言处理", "code": "nlp", "sort": 20, "status": "disabled"}`（字段均可选，仅提交需要变更的项）
- 成功 data：更新后的分类对象
- 错误码：`2001` 参数不符合 Schema；`2003` 分类不存在；`2004` 分类名称或编码已存在
- 备注：幂等；重复提交同一变更不产生副作用。

### `DELETE /api/capability/categories/{category_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`category_id`（int）
- 成功 data：`{"id": 1, "is_deleted": 1}`
- 错误码：`2003` 分类不存在；`2005` 分类下仍有能力，不可删除
- 备注：软删除；删除前检查该分类下是否存在 `is_deleted=0` 的能力，存在则拒绝。

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
- 错误码：`2001` 参数不符合 Schema；`2003` 分类不存在；`2006` 能力编码已存在
- 备注：`status` 缺省为 `draft`；`price_per_call` 必须为非负整数；`code` 只允许小写字母、数字和连字符。登记后默认不上架，需再由 `PUT /{id}/status` 上架。

### `PUT /api/capability/{capability_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`capability_id`（int）
- 请求体：同 `POST /api/capability`，字段均可选（不含 `status`）
- 成功 data：更新后的能力对象
- 错误码：`2001` 参数不符合 Schema；`2002` 能力不存在；`2003` 分类不存在；`2006` 能力编码已存在
- 备注：状态变更必须走 `PUT /{id}/status`，此接口忽略 `status` 字段。

### `DELETE /api/capability/{capability_id}`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`capability_id`（int）
- 成功 data：`{"id": 1, "is_deleted": 1}`
- 错误码：`2002` 能力不存在
- 备注：软删除；`online` 能力删除前需先下架或由实现直接置为软删除（实现按"先下架再删除"处理，避免市场出现已删除条目）。

### `PUT /api/capability/{capability_id}/status`

- 负责人：夏思凯
- 是否需要登录：是
- 路径参数：`capability_id`（int）
- 请求体：`{"status": "online"}`
- 成功 data：`{"id": 1, "status": "online", "update_time": "..."}`
- 错误码：`2001` 参数不符合 Schema（`status` 不在 `draft`/`online`/`offline` 内）；`2002` 能力不存在
- 备注：上下架唯一入口；`online` 为市场可见状态，`offline` / `draft` 均不可见。

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
- 错误码：2001 参数错误；2007 为 Pro 待实现的运营权限拒绝，当前权限缺口见第 6 节，不能标为已完成授权。
- 备注：运营列表，返回全部状态；更新时间倒序。

### `GET /api/capability/ping`、`GET /health`

- 现有健康接口保持。health 公开；ping 经 Gateway 需要 JWT，用于验证可信身份/requestId。health 为 UP 不代表内部详情或管理员授权已实现。

## 5. 错误码（仅使用 2xxx 号段）

| code | message | 触发场景 |
|---|---|---|
| 2001 | 参数不符合 Schema | 必填缺失、类型错误、枚举非法、JSON 结构错误（基座统一处理） |
| 2002 | 能力不存在或已下线 | 能力 ID 不存在、已软删除、`draft`/`offline` 被外部访问 |
| 2003 | 分类不存在 | `category_id` 不存在或已软删除 |
| 2004 | 分类名称或编码已存在 | 分类 `name` / `code` 冲突 |
| 2005 | 分类下仍有能力，不可删除 | 删除前引用检查未通过 |
| 2006 | 能力编码已存在 | 能力 `code` 冲突 |
| 2007 | 无运营权限 | Pro 待实现：非管理员访问 manage/写接口，由实时授权结果决定 |

> 当前基础实现缺少第 6 节要求的管理授权，这是待修复缺口，不是“先允许所有登录用户”的开发指令。目标行为必须由服务端实时授权和失败关闭保证。

## 6. Pro 待交接接口、授权与市场

1. 管理列表与分类/能力全部写操作需实时调用 GET `/internal/user/authorization?user_id=<当前用户ID>&required_role=admin`。成功必须匹配 ID、normal/admin/authorized=true；普通用户拒绝、依赖异常失败关闭。Gateway role 已可信传递，但不替代此检查。
2. user 原码 1006 继续表示 Key 不存在，新增授权不足为 1007；capability 可映射对外 2007。规范以[共享契约](pro-shared.md)为准，不使用旧提示词里冲突的 1006，也不本地硬编码管理员白名单。
3. 必须提供 GET `/internal/capability/{capability_id}`，成功 data 为匹配正整数 id、name、code、真实 status、内联 param_schema、0–1000000 整数 price_per_call。不返回可供任意代理的 URL；未知/软删除 2002，内部如返回 draft/offline 须如实标识，AI 会拒绝。
4. AI 客户端、allowlist 和目录价计量已实现，默认 internal 缺失端点失败关闭；当前显式 market 联调不等同于内部端点完成。交接后必须通过 `--catalog-mode internal --browser` 的真实 E2E。
5. code 固定 chat-completions / long-summary，对应 input.messages / input.text 与可选 max_length。Schema 按现有执行器内联结构，不含远程引用；状态/单价一改必须在下一次调用生效，不能缓存旧上架状态执行。
6. 市场已使用真实目录接口，不能再按“硬编码假数据页面”重做。按钮传 `/chat?capability_id=<id>`，Chat 已接受；未实现的视觉等能力不可体验，不补虚构延迟列或静态耗时。
7. 分类 enabled/disabled、能力 draft/online/offline、价格整数积分已定稿。注册记录的 service/path 不决定执行目标，新增 code 需真正 adapter 与安全验收。

## 7. 示例数据与验收

首次或明确的隔离示例库使用本服务 sql；seed 会更新同名演示记录，不是已有业务库的增量迁移：

- 2 个分类：`nlp`（语言处理）、`multimodal`（多模态）
- 3 个能力：
  - `chat-completions`（多轮对话，`ai-chat-service`，`/api/chat/completions`，`online`）— 支撑主闭环演示
  - `long-summary`（长文本摘要，`online`）
  - `vision-parse`（视觉理解，`draft`，用于验证市场不可见）
- 现有聊天价格 5、摘要 3；AI 验证目录状态/Schema/price，不按固定 POINTS_COST。演示数据不包含真实凭证。
- 需验证内部详情、公开字段最小化、状态变化、未知/软删除、参数/价格边界、重复编码、非管理员直接写/管理读取、授权撤销/故障以及市场到 Chat 的选中 ID。测试使用独立数据库，不清开发库。

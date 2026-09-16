# capability-service 接口契约

> 负责人：夏思凯
> 服务名：`capability-service`
> 数据库：`capability_db`
> 端口：8082
> 上游依赖：无（capability-service 不调用任何其他服务）

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
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'enabled' | `enabled` / `disabled`（待确认，见第 5 节） |
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

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
| `create_time` / `update_time` / `is_deleted` | — | 通用字段 | 见指南 5.5 |

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
- 备注：**只返回 `status='online'` 且 `is_deleted=0` 的能力**；严禁输出 `service_name`、`path`、`param_schema` 之外的内部配置或任何密钥；`category_name` 由本服务的分类表关联得出，不跨库。

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
- 错误码：`2001` 参数不符合 Schema；`2007` 无运营权限（待确认，见第 5 节）
- 备注：运营列表，返回全部状态；更新时间倒序。

### `GET /api/capability/ping`、`GET /health`

- 已由骨架实现，保持不变。`ping` 用于验证 `X-User-Id` / `X-User-Name` / `X-Request-Id` 透传；`/health` 返回 `{"status": "UP"}`。

## 5. 错误码（仅使用 2xxx 号段）

| code | message | 触发场景 |
|---|---|---|
| 2001 | 参数不符合 Schema | 必填缺失、类型错误、枚举非法、JSON 结构错误（基座统一处理） |
| 2002 | 能力不存在或已下线 | 能力 ID 不存在、已软删除、`draft`/`offline` 被外部访问 |
| 2003 | 分类不存在 | `category_id` 不存在或已软删除 |
| 2004 | 分类名称或编码已存在 | 分类 `name` / `code` 冲突 |
| 2005 | 分类下仍有能力，不可删除 | 删除前引用检查未通过 |
| 2006 | 能力编码已存在 | 能力 `code` 冲突 |
| 2007 | 无运营权限 | 非运营身份访问 `/manage` 或写接口（**待确认**） |

> `2007` 依赖第 6 节的权限方案，未确认前实现先按"已登录即可访问"处理，并保留该分支位置。

## 6. 待确认事项（需在契约 Review 时与组长确认）

1. **运营权限方案**：`JwtIdentity` 当前只有 `userId` / `userName`，平台尚无角色体系。`/api/capability/manage` 与分类/能力的写接口如何区分普通开发者与运营？候选方案：① 网关新增角色 Claim；② 本服务用 `.env` 配置运营用户白名单；③ 本期全部登录用户均可写。**未确认前不实现 2007 判定。**
2. **分类 `status` 枚举取值**：本契约暂定 `enabled` / `disabled`。指南只统一了能力状态 `draft`/`online`/`offline`，未定义分类状态，请确认是否复用 `online`/`offline`。
3. **`price_per_call` 精度与单位**：暂定为整数积分数（与指南 5.5 "积分用整型存储"一致）。需与黄禹菲确认 billing 计费流水中的 `cost` 是否同口径。
4. **是否需要 `/internal/**` 接口**：本期 ai-chat 使用配置化的固定单价上报计费，未按 `capability_id` 查单价。若后续要求"计费以 capability 登记单价为准"，需新增 `GET /internal/capability/{capability_id}` 供 ai-chat 调用。**本期不实现，作为演进项登记。**
5. **前端市场页字段对齐**：`web/src/pages/CapabilitiesPage.tsx` 当前为硬编码假数据，使用了 `latency`（延迟）字段，而数据字典中无此字段。需与组长确认：① 前端改为使用本契约字段；② 或新增 `t_capability.latency_ms` 字段。**建议方案 ①，本期不新增字段。**

## 7. 测试数据计划

按指南 13.2，提供可重复导入的初始化数据（放在本服务 `sql/`）：

- 2 个分类：`nlp`（语言处理）、`multimodal`（多模态）
- 3 个能力：
  - `chat-completions`（多轮对话，`ai-chat-service`，`/api/chat/completions`，`online`）— 支撑主闭环演示
  - `long-summary`（长文本摘要，`online`）
  - `vision-parse`（视觉理解，`draft`，用于验证市场不可见）
- 脚本需可重复执行（`INSERT` 前先判断或使用固定 `code` + 唯一约束），不得包含真实密钥。

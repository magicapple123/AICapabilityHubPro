# 批 1「计量底座」契约冻结清单

> 冻结日期：2026-11-02　｜　适用范围：升级批 1（C1 → C2 → A1 → A2）
> 依据：`docs/升级需求清单-2026-11-02.md` 第 3 节，以及冻结当日工作区代码事实
> （`ai-chat-service/app/service/model_client.py`、`pricing.py`、`capability_adapters.py`、
> `completion_result.py`、`chat_service.py`、`conversation_store.py`、
> `billing-service/app/schemas/internal.py`、`billing_service.py`、
> `capability-service/app/schemas/capability.py`、四个服务 `app/db/session.py`）。
>
> **本文件是批 1 的唯一契约。** 文中用「必须 / 禁止 / 恒为」表述的条目为硬约束，
> 实施时不得自行放宽；代码与本文不一致时以本文为准，除非先在本文追加「变更记录」。
> 本文不含「建议 / 可以考虑」类表述。

---

## C1　token 用量修正

### C1.1 `ModelReply` 最终形态

文件：`services/ai-chat-service/app/service/model_client.py`（`@dataclass(frozen=True)`）

| 字段 | 类型 | 默认值 | 语义 |
|---|---|---|---|
| `content` | `str` | 无默认（必填） | 助手回复正文；降级时为 `DEGRADED_REPLY` |
| `call_status` | `str` | 无默认（必填） | `success` / `degraded` / `failed`，取值同 `CallStatus` |
| `model_name` | `str` | 无默认（必填） | 上游回显的 `model`，缺失时回落到请求的 `model` |
| `prompt_tokens` | `int` | `0` | **输入侧 token 数**，只来自上游 `usage`；非上游来源按 C1.2 处理 |
| `completion_tokens` | `int` | `0` | **输出侧 token 数**，只来自上游 `usage`；非上游来源按 C1.2 处理 |
| `usage_source` | `str` | `"missing"` | 取值只能是 `upstream` / `mock` / `missing`（枚举 `TokenSource`） |
| `error_code` | `int \| None` | `None` | 仅降级时有值，取 `ModelErrorCode` |
| `mock` | `bool` | `False` | 是否走 `USE_MOCK=true` 分支，响应 `mock` 字段沿用 |
| `total_tokens`（`@property`） | `int` | — | 恒等于 `prompt_tokens + completion_tokens`，**不是字段**、不可赋值 |
| `degraded`（`@property`） | `bool` | — | `call_status == "degraded"` |

硬约束：

1. **删除 `token_count` 字段。** `ModelReply` 上不再有 `token_count`；所有原
   `reply.token_count` 的读取点一律改为 `reply.total_tokens`。
2. **禁止**在 `ModelReply` 上保存"字符数"这类非 token 量。`prompt_tokens` /
   `completion_tokens` 的语义只允许是 token 数。
3. `usage_source` 必须在构造 `ModelReply` 的**每一处**显式给出：
   - `ModelClient._parse` 成功分支 → `normalize_usage()` 的返回值；
   - `ModelClient._degraded` → `"missing"`；
   - `capability_adapters.execute_prepared` 的 Mock 分支 → `"mock"`。
   禁止依赖默认值隐式落成 `"missing"`（默认值只是防御，不是实现）。

构造点全集（实施后不得遗漏）：
`model_client.ModelClient._parse`、`model_client.ModelClient._degraded`、
`capability_adapters.execute_prepared`（Mock 分支）、`tests` 内的替身。

### C1.2 上游 `usage` 缺失 / 畸形的降级语义

判定函数（模块级，`model_client.py`）：

```
def normalize_usage(body: object) -> tuple[int, int, str]
def _non_negative_int(value: object) -> int | None
```

`normalize_usage` 判定顺序（顺序不可调整）：

1. `body` 不是 `dict` → `(0, 0, "missing")`
2. `body["usage"]` 不是 `dict` → `(0, 0, "missing")`
3. `prompt = _non_negative_int(usage["prompt_tokens"])`；为 `None` 时再试
   `_non_negative_int(usage["input_tokens"])`（Responses 协议归一化）
4. `completion = _non_negative_int(usage["completion_tokens"])`；为 `None` 时再试
   `_non_negative_int(usage["output_tokens"])`
5. `prompt is None or completion is None` → `(0, 0, "missing")`
6. `prompt + completion <= 0` → `(0, 0, "missing")`（真实调用不可能 0 token，
   把"没给"记成"用了 0"会污染 per_token 计价）
7. 否则 → `(prompt, completion, "upstream")`

`_non_negative_int` 口径（**禁止放宽**）：`bool` 视为非法（`True` 不是 1）；
`float` 视为非法（`1.0` 不做静默截断）；`int` 且 `>= 0` 才返回，其余返回 `None`。

降级后的行为矩阵（三模式 × 三来源）：

| `usage_source` | `call_status` | token 值 | `per_call` 计费 | `per_token` 计费 | 标记 |
|---|---|---|---|---|---|
| `upstream` | `success` | 上游原值 | 全额 `price_per_call` | 按 C2.3 公式 | `usage_source="upstream"` |
| `mock` | `success` | 本地估算（约 2 字符 1 token） | 全额 `price_per_call` | **0 分**（Mock 不参与 token 计价） | `mock=true`、`usage_source="mock"` |
| `missing` | `success` | `0 / 0` | 全额 `price_per_call` | **0 分**（失败关闭，不猜测） | `usage_source="missing"`、`billing_detail.unbilled_reason="token_usage_missing"` |
| 任意 | `degraded` | `0 / 0` | 0 分（沿用"降级不计费"） | 0 分 | `call_status="degraded"`、`error_code` 有值 |

补充硬约束：

- **禁止**用字符数回填 token：`len(content)` / `sum(len(m.content))` 一律不得再进入
  `prompt_tokens` / `completion_tokens` / `t_chat_message.token_count`。
- `usage_source != "upstream"` 且能力为 `per_token` 时，**必须**打一条
  `logger.warning("token_usage_missing capability_id={} request_id={} source={}")`，
  日志中禁止出现正文（沿用指南 5.7）。
- Mock 分支的 token 估算函数固定为
  `_mock_tokens(text: str) -> int = max(1, len(text) // 2)`，只允许出现在
  `capability_adapters.py`，且必须配 `usage_source="mock"`。

### C1.3 归一化函数签名

```
# services/ai-chat-service/app/service/model_client.py
def normalize_usage(body: object) -> tuple[int, int, str]:
    """(prompt_tokens, completion_tokens, usage_source)"""

def _non_negative_int(value: object) -> int | None: ...
```

- 入参 `body` 是**整个上游响应体**（不是 `usage` 子对象），因为 Responses 协议
  的 usage 字段既可能平铺也可能嵌套，统一在函数内取 `body["usage"]`。
- 返回值第 3 项只能是 `TokenSource` 的三值字符串，禁止返回 `None`。
- **禁止**让 `normalize_usage` 抛异常：任何异常路径都折算为 `(0, 0, "missing")`
  （当前实现通过类型检查天然满足，改造时不得引入 `KeyError` / `TypeError`）。
- 该函数是 `ModelClient._parse` 的唯一 token 来源，`_parse` 内不得再出现
  `usage.get(...)` 直读。

### C1.4 `t_call_record` 新增列与上报 JSON

DDL（`services/billing-service/sql/03_usage_tokens.sql`）。
**重复执行安全**使用与 C2.1 相同的 `information_schema.columns` 判存 +
`PREPARE/EXECUTE` 写法（`@has_col` 判定 `column_name = 'prompt_tokens'`，
判定成立时执行下面的全部 `ADD COLUMN`，否则 `SELECT 'skipped'`）：

```sql
ALTER TABLE t_call_record
  ADD COLUMN prompt_tokens INT NOT NULL DEFAULT 0
    COMMENT '输入侧 token 数；usage_source=mock/missing/unknown 时无意义',
  ADD COLUMN completion_tokens INT NOT NULL DEFAULT 0
    COMMENT '输出侧 token 数；usage_source=mock/missing/unknown 时无意义',
  ADD COLUMN usage_source VARCHAR(16) NOT NULL DEFAULT 'unknown'
    COMMENT 'token 来源 upstream上游真值 mock本地估算 missing上游未给 unknown历史未记录',
  ADD COLUMN billing_mode VARCHAR(16) NOT NULL DEFAULT 'per_call'
    COMMENT '计价模式 per_call按次 per_token按token per_unit按件',
  ADD COLUMN units INT NOT NULL DEFAULT 1
    COMMENT '本次计件数量，仅 per_unit 有意义，其余恒为 1',
  ADD COLUMN price_per_1k_input INT NOT NULL DEFAULT 0
    COMMENT '计价时使用的每千输入 token 单价快照',
  ADD COLUMN price_per_1k_output INT NOT NULL DEFAULT 0
    COMMENT '计价时使用的每千输出 token 单价快照';
```

| 列 | 类型 | NULL | 默认值 | 语义 |
|---|---|---|---|---|
| `prompt_tokens` | `INT` | NOT NULL | `0` | 输入 token；仅当 `usage_source='upstream'` 可信 |
| `completion_tokens` | `INT` | NOT NULL | `0` | 输出 token；同上 |
| `usage_source` | `VARCHAR(16)` | NOT NULL | `'unknown'` | 四值枚举，**历史行为 `unknown`**（区别于"上游没给"的 `missing`） |
| `billing_mode` | `VARCHAR(16)` | NOT NULL | `'per_call'` | 计价模式快照，历史行即真实值 |
| `units` | `INT` | NOT NULL | `1` | 计件数量；非 `per_unit` 恒 1 |
| `price_per_1k_input` | `INT` | NOT NULL | `0` | 单价快照，便于事后复算 |
| `price_per_1k_output` | `INT` | NOT NULL | `0` | 单价快照，便于事后复算 |

`unit_price` 列语义（**不新增列，改写语义并写入注释**）：

- `per_call`：等于 `price_per_call`（行为与今日完全一致）；
- `per_unit`：等于 `price_per_unit`；
- `per_token`：恒为 `0`（不适用，明细看 `price_per_1k_*` 与 tokens）；
- 历史未知仍为 `NULL`。

`POST /internal/billing/record` 请求体新增字段（JSON 名 = Python 字段名）：

| JSON 字段 | 类型 | 必填 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|
| `prompt_tokens` | int | 否 | `0` | `0 ≤ x ≤ 10_000_000` | 输入 token |
| `completion_tokens` | int | 否 | `0` | `0 ≤ x ≤ 10_000_000` | 输出 token |
| `usage_source` | str | 否 | `"unknown"` | 枚举 `upstream`/`mock`/`missing`/`unknown` | token 来源 |
| `billing_mode` | str | 否 | `"per_call"` | 枚举 `per_call`/`per_token`/`per_unit` | 计价模式 |
| `units` | int | 否 | `1` | `1 ≤ x ≤ 1000` | 计件数量 |
| `price_per_1k_input` | int | 否 | `0` | `0 ≤ x ≤ 1_000_000` | 下单时的输入单价 |
| `price_per_1k_output` | int | 否 | `0` | `0 ≤ x ≤ 1_000_000` | 下单时的输出单价 |

兼容：`ai-chat-service` 全量上报新字段；任何未携带新字段的旧调用方仍按
`unknown / per_call / 1 / 0 / 0` 落库，幂等重放不因缺字段而被判 3002（见 C2.6）。

`t_usage_daily` **本批不改**（不加 token 累加列）。理由：C3 预算按积分聚合，
token 明细在 `t_call_record` 可逐条查；加聚合列会牵连 UPSERT 与统计契约，
不属于批 1。

### C1.5 `t_chat_message.token_count` 语义变更

| 项 | 冻结值 |
|---|---|
| 列是否保留 | 保留，不改名、不改类型（`INT NOT NULL DEFAULT 0`） |
| 助手消息写入值 | `reply.total_tokens`（= `prompt_tokens + completion_tokens`），**不是字符数** |
| 助手消息 `usage_source != "upstream"` 时 | 仍写 `reply.total_tokens`（Mock 估算或 0），区分来源靠响应字段，不在消息表加列 |
| 用户消息写入值 | **`0`**（`_persist_user_message` 现在是 `len(last_user_content)`，必须改为 `0`） |
| 原因 | 用户消息未经过模型，没有 token 事实；写字符数会让"token 数"这一列失去唯一口径 |
| 失败占位消息写入值 | `0`（见 A1.2） |
| 是否新增列 | 不新增。消息表不保存 `prompt`/`completion` 拆分，拆分只在 `t_call_record` 与响应 `usage` |

### C1.6 兼容策略：旧记录 `prompt_tokens` 为 0 / NULL

1. **数据侧**：迁移脚本只 `ADD COLUMN`，不做任何回填。历史行的
   `prompt_tokens = 0`、`usage_source = 'unknown'`、`billing_mode = 'per_call'`、
   `units = 1`。历史 `token_count` 里的字符数**原样保留，不修正**。
2. **判定"未记录"的唯一规则**（接口、前端、导出统一使用）：
   `usage_source == 'unknown' OR (prompt_tokens + completion_tokens) == 0`
   → 视为 token 明细缺失。
3. **展示**：命中规则 2 时，token 列显示 `—`，**禁止**显示 `0 tokens`；
   `cost`、`call_count`、`total_cost` 等以积分与次数为口径的字段**照常显示**，
   不受影响。
4. **接口**：`GET /api/billing/records` 的 `prompt_tokens` / `completion_tokens`
   照常返回 `0`（不返回 `null`），由前端按规则 2 渲染 `—`；
   `usage_source` 一并返回，作为唯一判定依据。
5. **统计**：任何"平均 token 数 / 总 token 数"类统计**必须**先按规则 2 过滤，
   再对样本求值；样本数为 0 时返回 `null` 而不是 `0`。
6. **契约文档**：`docs/api-contract/ai-chat-service.md` 第 4 节现有一句
   "prompt_tokens 当前按传入有效消息字符数估算"必须删除并替换为 C1.3 口径。

### C1.7 `completion_result()` 出参（收据字段，C1 + C2 共用）

`usage` 三字段全部取自 `reply`，**禁止**再出现 `sum(len(...))`：

```json
{
  "usage": {"prompt_tokens": 4, "completion_tokens": 10, "total_tokens": 14},
  "usage_source": "upstream",
  "billing_mode": "per_token",
  "billing_detail": {
    "billing_mode": "per_token",
    "unit_price": 0,
    "units": 1,
    "price_per_1k_input": 1,
    "price_per_1k_output": 2,
    "prompt_tokens": 4,
    "completion_tokens": 10,
    "cost": 1,
    "billable": true,
    "unbilled_reason": null
  }
}
```

- `billing_detail` 为 `object | null`：`enable_internal_chain=false`（未上报）时
  **必须**为 `null`，其余情况为对象。
- `unbilled_reason` 取值只允许 `null` / `"degraded"` / `"token_usage_missing"`。
- `unit_price` 按 C1.4 的 `unit_price` 语义（`per_call`→`price_per_call`，
  `per_unit`→`price_per_unit`，`per_token`→`0`）。
- 既有顶层字段 `price_per_call` / `cost` / `record_id` / `billing_status` /
  `catalog_source` **保持不变**（前端与 E2E 已依赖）。

---

## C2　双轨计费

### C2.1 `t_capability` 新增列 DDL

文件：`services/capability-service/sql/04_billing_mode.sql`。
**重复执行安全的具体写法**（照抄即可，不要换成"看报错就当已存在"）：

```sql
USE capability_db;

SET @has_col := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = 'capability_db' AND table_name = 't_capability'
    AND column_name = 'billing_mode'
);
SET @ddl := IF(@has_col = 0,
  'ALTER TABLE t_capability
     ADD COLUMN billing_mode VARCHAR(16) NOT NULL DEFAULT ''per_call''
       COMMENT ''计价模式 per_call按次 per_token按token per_unit按件'',
     ADD COLUMN price_per_1k_input INT NOT NULL DEFAULT 0
       COMMENT ''每 1000 输入 token 的积分单价，仅 per_token 使用'',
     ADD COLUMN price_per_1k_output INT NOT NULL DEFAULT 0
       COMMENT ''每 1000 输出 token 的积分单价，仅 per_token 使用'',
     ADD COLUMN price_per_unit INT NOT NULL DEFAULT 0
       COMMENT ''计件单价，仅 per_unit 使用'',
     ADD COLUMN unit VARCHAR(16) NOT NULL DEFAULT ''''
       COMMENT ''计件单位（张/次/千字），仅 per_unit 使用'',
     ADD CONSTRAINT ck_capability_billing_mode
       CHECK (billing_mode IN (''per_call'',''per_token'',''per_unit'')),
     ADD CONSTRAINT ck_capability_billing_consistency
       CHECK (
         (billing_mode = ''per_call''
           AND price_per_1k_input = 0 AND price_per_1k_output = 0
           AND price_per_unit = 0 AND unit = '''')
      OR (billing_mode = ''per_token''
           AND price_per_call = 0 AND price_per_unit = 0 AND unit = ''''
           AND (price_per_1k_input > 0 OR price_per_1k_output > 0))
      OR (billing_mode = ''per_unit''
           AND price_per_call = 0
           AND price_per_1k_input = 0 AND price_per_1k_output = 0
           AND price_per_unit > 0 AND unit <> '''')
       )',
  'SELECT ''t_capability.billing_mode already exists'' AS skipped');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
```

同上语义的列定义（便于阅读，正式以脚本为准）：

| 列 | 类型 | NULL | 默认 | 取值范围 | 语义 |
|---|---|---|---|---|---|
| `billing_mode` | `VARCHAR(16)` | NOT NULL | `'per_call'` | 三值枚举 | 计价模式 |
| `price_per_1k_input` | `INT` | NOT NULL | `0` | `0..1_000_000` | 每 1000 输入 token 的积分单价 |
| `price_per_1k_output` | `INT` | NOT NULL | `0` | `0..1_000_000` | 每 1000 输出 token 的积分单价 |
| `price_per_unit` | `INT` | NOT NULL | `0` | `0..1_000_000` | 计件单价 |
| `unit` | `VARCHAR(16)` | NOT NULL | `''` | 长度 ≤16 的短名 | 计件单位，展示用 |
| `price_per_call` | 既有 `INT` | NOT NULL | `0` | `0..1_000_000` | 按次单价；`per_token`/`per_unit` 必须为 0 |

**ENUM vs CHECK 取舍（已定）**：用 `VARCHAR(16) + CHECK`，不用 MySQL `ENUM`。
理由：既有 `status` / `call_status` 全部是 `VARCHAR + 应用层枚举`，
统一风格；`ENUM` 加值需 `ALTER TABLE` 重建定义，且 SQLAlchemy `Mapped[str]`
映射会引入额外转换。**CHECK 是唯一 DB 层兜底，应用层必须再做一次同规则校验。**

MySQL 版本要求：`>= 8.0.16`（CHECK 真正生效的版本）；本项目 8.4 满足。

### C2.2 三个出参/入参暴露哪些计价字段

`CapabilityInternalOut`（服务间内部详情，**必须全暴露，否则 ai-chat 无法计价**）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `billing_mode` | `Literal["per_call","per_token","per_unit"]` | 新增 |
| `price_per_call` | `int` (`0..1_000_000`) | 既有 |
| `price_per_1k_input` | `int` (`0..1_000_000`) | 新增 |
| `price_per_1k_output` | `int` (`0..1_000_000`) | 新增 |
| `price_per_unit` | `int` (`0..1_000_000`) | 新增 |
| `unit` | `str` (`max_length=16`) | 新增 |

- `from_row()` 必须显式列出这 6 个字段；`id/name/code/status/param_schema` 不变。
- 服务端仍**不**返回 `service_name` / `path`（安全边界不变）。
- 交叉校验（`per_token` 价格全 0、`per_unit` 无 `unit` 等）失败 → 沿用
  `BizException(4002, "能力目录配置不完整或价格无效")` 的**失败关闭**语义：
  在 `CapabilityInternalOut` 加 `@model_validator(mode="after")`，校验规则与
  C2.1 的 CHECK 逐条一致。

`CapabilityMarketOut` / `CapabilityMarketDetailOut`（公开市场，**必须暴露**，
否则用户看不到真实计价方式）：

新增 `billing_mode`、`price_per_1k_input`、`price_per_1k_output`、
`price_per_unit`、`unit`；保留 `price_per_call`。
**不暴露**：`service_name`、`path`、`status`、`param_schema`（`DetailOut` 例外，
既有行为不变）。

`CapabilityManageOut`（运营，**必须暴露**）：与 `InternalOut` 同一组 6 个字段，
叠加既有全部字段。

`CapabilityCreateRequest` / `CapabilityUpdateRequest`：

| 字段 | Create | Update |
|---|---|---|
| `billing_mode` | `= "per_call"` | `int \| None`，省略即不改 |
| `price_per_call` | `= 0` | 既有 |
| `price_per_1k_input` | `= 0` | 同上 |
| `price_per_1k_output` | `= 0` | 同上 |
| `price_per_unit` | `= 0` | 同上 |
| `unit` | `= ""` | 同上 |

- Create/Update 的 `model_validator(mode="after")` 必须**合并最终值**再校验
  （Update 是部分更新，必须先用请求值覆盖库值，再跑 C2.1 的 CHECK 同规则），
  违反时返回 `BizException(2001, "计价配置不一致：<具体原因>")`。
- `CapabilityUpdateRequest.check_partial_update` 的 `non_nullable` 白名单
  **追加** `billing_mode` / `price_per_1k_input` / `price_per_1k_output` /
  `price_per_unit` / `unit`（显式传 `null` 视为参数错误，不能靠默认值静默覆盖）。
- `update_capability` 中"线上能力改价"**允许**（现状已允许，改价立刻生效是既有
  契约，批 1 不引入缓存）。

前端展示模板（**契约，不是建议**）：

| 模式 | 展示文案模板 |
|---|---|
| `per_call` | `{price_per_call} 积分/次` |
| `per_token` | `{price_per_1k_input} 积分/千输入 tokens + {price_per_1k_output} 积分/千输出 tokens` |
| `per_unit` | `{price_per_unit} 积分/{unit}` |

### C2.3 计价公式（三套，含取整与 0 token 边界）

常量：`TOKENS_PER_PRICE_UNIT = 1000`（ai-chat 与 billing **两侧同名同值**）。
口径：**1000 tokens = 1 积分**，即 `price_per_1k_input = 1` 表示每千输入 token 收 1 积分。

唯一实现入口：

- ai-chat：`app/service/pricing.py` → `preflight_points()` / `call_cost()` /
  `units_for()` / `_ceil_div()`
- billing：`app/service/pricing_rules.py` → `expected_cost()`（供
  `validate_price` 复算，函数名与签名自此冻结）

```
def _ceil_div(numerator: int, denominator: int) -> int   # 整数向上取整，numerator<=0 时返回 0
def units_for(billing_mode: str, units: int | None) -> int  # 非 per_unit 恒 1；非法/None 按 1
def preflight_points(definition, *, units: int = 1) -> int
def call_cost(definition, *, prompt_tokens=0, completion_tokens=0, units=1, billable=True) -> int
def expected_cost(*, billing_mode, unit_price, price_per_1k_input, price_per_1k_output, units, prompt_tokens, completion_tokens, status) -> int
```

公式（`billable = (status == "success")`；`billable=False` 三模式一律 `0`）：

| 模式 | 公式 | 取整 | 0 token / 0 unit 边界 |
|---|---|---|---|
| `per_call` | `cost = price_per_call` | 无（整数） | 与 token 无关；`price_per_call=0` → 免费能力 `cost=0` |
| `per_token` | `cost = ceil((prompt_tokens * price_per_1k_input + completion_tokens * price_per_1k_output) / 1000)` | `_ceil_div(weighted, 1000)`，即 `-(-weighted // 1000)` | `weighted == 0` → `cost = 0`（**不扣分**，不设最低 1 分）；仅一侧为 0 时照常按另一侧算 |
| `per_unit` | `cost = price_per_unit * units_for(mode, units)` | 无（整数乘法） | `units` 缺失或 `<1` → 按 `1`；`price_per_unit=0` → `cost=0` |

硬约束：

1. **禁止浮点**：不得出现 `math.ceil(a / b)`、`* 0.001`、`float` 中间量；
   只用整数除法与 `-(-a // b)`。
2. **禁止**在 `chat_service` / `execution_billing` / `billing_service` 里再次
   书写乘法公式；只能调用上面 4 个函数。
3. `per_token` 且 `usage_source != "upstream"` → 强制 `cost = 0`，
   `unbilled_reason = "token_usage_missing"`（C1.2）。Mock 来源同样为 0。
4. 降级/失败（`call_status != "success"`）→ `cost = 0`，`unbilled_reason = "degraded"`。

**冻结向量表**（两侧测试必须逐行断言，表是唯一口径）：

| # | mode | price_per_call | p1k_in | p1k_out | ppu | units | prompt | completion | source | status | cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | per_call | 5 | 0 | 0 | 0 | 1 | 0 | 0 | missing | success | 5 |
| 2 | per_call | 3 | 0 | 0 | 0 | 1 | 120 | 300 | upstream | success | 3 |
| 3 | per_call | 5 | 0 | 0 | 0 | 1 | 0 | 0 | missing | degraded | 0 |
| 4 | per_token | 0 | 1 | 2 | 0 | 1 | 1000 | 0 | upstream | success | 1 |
| 5 | per_token | 0 | 1 | 2 | 0 | 1 | 0 | 500 | upstream | success | 1 |
| 6 | per_token | 0 | 1 | 1 | 0 | 1 | 4050 | 0 | upstream | success | 5 |
| 7 | per_token | 0 | 1 | 1 | 0 | 1 | 4050 | 0 | missing | success | 0 |
| 8 | per_token | 0 | 1 | 1 | 0 | 1 | 0 | 0 | upstream | success | 0 |
| 9 | per_token | 0 | 2 | 4 | 0 | 1 | 1000 | 1000 | upstream | success | 6 |
| 10 | per_token | 0 | 3 | 3 | 0 | 1 | 1 | 1 | upstream | success | 1 |
| 11 | per_unit | 0 | 0 | 0 | 8 | 2 | 0 | 0 | missing | success | 16 |
| 12 | per_unit | 0 | 0 | 0 | 8 | 1 | 0 | 0 | missing | degraded | 0 |

（#6 即需求验收用例：4050 tokens → 4.05 → 向上取整 5 分。#10 验证"不足 1 分按 1 分"。）

### C2.4 预检门槛公式

`check_points(user_id, price)` 的 `price` 传入 `pricing.preflight_points(definition)`：

| 模式 | 门槛 | 说明 |
|---|---|---|
| `per_call` | `price_per_call` | 与今日**完全相同**，旧能力零回归 |
| `per_token` | `max(1, max(price_per_1k_input, price_per_1k_output))` | 至少够 1 个计价单位（1k tokens）在**较贵方向**的价格；下界 1 分，避免低价方向把门槛压成 0 |
| `per_unit` | `price_per_unit * units_for(mode, units)` | `units` 在执行前已知（聊天/摘要执行器恒 1） |

- `units` 来源：本批只有 `chat-completions` / `long-summary` 两个执行器，
  `units` **恒为 1**；`per_unit` 能力的真实 `units` 由未来 `image-generate`
  执行器提供（D3），本批不实现。
- 门槛只是**下界**，不是预扣；真实扣分仍按 `call_cost()` 结算，因此
  `per_token` 能力存在"预检通过但结算余额不足 → 3001"的合法路径，
  必须在响应错误码上如实返回 `3001`，**禁止**在预检阶段预留/冻结积分。
- 预检调用点保持在 `check_points(...)`，参数由 `definition.price_per_call`
  改为 `pricing.preflight_points(definition)`；**禁止**改 `/internal/user/check`
  的契约（仍是 `points_cost` 单值）。

### C2.5 `BillingRecordRequest` 新增字段与 `validate_price` 新规则

新增字段（`app/schemas/internal.py`）：

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `billing_mode` | `Literal["per_call","per_token","per_unit"]` | `"per_call"` | — |
| `units` | `int` | `1` | `ge=1, le=1000` |
| `prompt_tokens` | `int` | `0` | `ge=0, le=10_000_000` |
| `completion_tokens` | `int` | `0` | `ge=0, le=10_000_000` |
| `usage_source` | `Literal["upstream","mock","missing","unknown"]` | `"unknown"` | — |
| `price_per_1k_input` | `int` | `0` | `ge=0, le=1_000_000` |
| `price_per_1k_output` | `int` | `0` | `ge=0, le=1_000_000` |

`validate_price` 新规则（顺序执行，任一不符即 `ValueError`）：

1. **`unit_price is None`**（旧调用方）：不校验 `points`，保留历史语义
   （现状行为，零回归）；但仍校验规则 5。
2. `status != success` → `points` 必须 `== 0`（降级/失败不计费，与现状一致）。
3. `status == success` 且 `unit_price is not None`，按 `billing_mode`：
   - `per_call`：`points == unit_price`（**现状规则，逐字保留**）；
   - `per_unit`：`points == unit_price * units`；
   - `per_token`：`unit_price` 必须 `== 0`，且
     `points == expected_cost(...)`（用 `prompt_tokens` / `completion_tokens` /
     `price_per_1k_*` 复算，见 C2.3）。`price_per_1k_input` 与
     `price_per_1k_output` 同时为 0 → 拒绝（无法自证价格）。
4. 错误信息文案固定为 `"实际费用与登记单价/状态不一致"`（沿用现有），
   便于既有测试断言；细分原因写日志，不改文案。
5. `billing_mode == "per_unit"` 且 `units < 1` → 拒绝；
   `billing_mode != "per_unit"` 且 `units != 1` → 拒绝（防止越界计价）。

### C2.6 幂等判定 `_is_same_call` 改动

追加比较字段（在原有 8 项之后），任一不等 → `BizException(3002)`：

```
existing.prompt_tokens    == payload.prompt_tokens
existing.completion_tokens == payload.completion_tokens
existing.billing_mode     == payload.billing_mode
existing.units            == payload.units
existing.price_per_1k_input  == payload.price_per_1k_input
existing.price_per_1k_output == payload.price_per_1k_output
```

**不比较**：`usage_source`、`remark`、`create_time`。

- 理由 1（不比较 `usage_source`）：`unknown`（旧调用方缺省）与 `upstream`
  在同一次重放中可能语义等价，比较它会制造 3002 误报；token 数值已比较，
  真值不同必然被发现。
- 理由 2：`remark` 允许文案微调，`create_time` 由 DB 生成。

兼容要求：旧调用方重放时新字段全取默认值（`0/0/per_call/1/0/0`），
历史行同列默认值也是 `0/0/per_call/1/0/0`（C2.1 DDL 默认值），因此
**旧调用方的幂等重放不会因新增字段被判 3002**——这是 DDL 默认值选择的
直接约束，不得随意改默认值。

### C2.7 收据响应新增字段

`BillingRecordOut`（`POST /internal/billing/record` 的 `data`）新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `billing_mode` | `str` | 计价模式 |
| `units` | `int` | 计件数量 |
| `prompt_tokens` | `int` | 输入 token（未记录为 0） |
| `completion_tokens` | `int` | 输出 token（未记录为 0） |
| `usage_source` | `str` | token 来源 |
| `price_per_1k_input` | `int` | 单价快照 |
| `price_per_1k_output` | `int` | 单价快照 |

既有字段 `record_id / request_id / user_id / capability_id / service_name /
unit_price / cost / call_status / duplicated / balance_after / stat_date /
call_count / total_cost` **全部保留**，顺序不变。

`GET /api/billing/records` 的 `CallRecordOut` 新增
`billing_mode / units / prompt_tokens / completion_tokens / usage_source /
price_per_1k_input / price_per_1k_output`（与 `t_call_record` 新增列一一对应）。

ai-chat 侧收据一致性断言（`execution_billing.report_execution`）必须扩展为：
`record_id` 合法、`request_id` / `user_id` / `capability_id` / `call_status` 相同、
`cost == points`、`billing_mode == definition.billing_mode`、`units == 请求 units`、
`prompt_tokens == reply.prompt_tokens`、`completion_tokens == reply.completion_tokens`，
不一致 → `BizException(4002, "计费收据与当前能力调用不一致，请按 requestId 核对")`
（文案不变）。

### C2.8 旧能力零回归的保证方式

1. **数据**：`02_seed.sql` 的两条旧能力**不新增任何列值**（走 DDL 默认值），
   迁移脚本末尾加显式断言段（执行时人眼可读）：
   `SELECT id, code, billing_mode, price_per_call, price_per_1k_input,
   price_per_1k_output, price_per_unit, unit FROM t_capability WHERE id IN (1,2);`
   → 必须输出 `per_call / 5 / 0 / 0 / 0 / ''` 与 `per_call / 3 / 0 / 0 / 0 / ''`。
2. **代码**：`CapabilityDefinition` 的 5 个新字段全部有默认值
   （`per_call` / `0` / `0` / `0` / `''`），且 `extra="ignore"` 保持，
   因此 internal 详情若因灰度未带新字段，解析仍成功且退回 `per_call`。
3. **计价**：`per_call` 分支直接返回 `price_per_call`，不经过任何换算或取整。
4. **测试（硬性）**：
   - capability：`test_internal_capability.py` / `test_api.py` 断言能力 1、2 的
     `price_per_call` 与 `billing_mode == "per_call"`；
   - ai-chat：`test_execution_chain.py` 断言 `capability_id=1` 的 `cost == 5`、
     `capability_id=2` 的 `cost == 3`（与今日断言完全一致，不改数字）；
   - billing：向量表 #1–#3 覆盖 `per_call`，其中 #1 直接对应旧能力 1 的金额。
5. **回归口径**：批 1 完成后，旧能力一次调用的 `cost` 与 `price_per_call`
   **必须逐字节等于**批 1 前基线（用一次真实调用比对 `t_call_record.cost`）。

---

## A1　模型调用移出事务

### A1.1 事务切分点

文件：`services/ai-chat-service/app/service/chat_service.py`。
**方案：单 `Session`（沿用 `get_db` 的依赖注入）、两次 `commit`。**
机制依据：`Session.commit()` 提交后事务结束、连接**归还连接池**；下一次
使用该 `Session` 时才重新 `checkout` 连接。因此模型调用期间不持有连接，
无需新建 `SessionLocal()`，也不需要 `db.close()`。

| 段 | 事务 | 起止（现有函数名） | 说明 |
|---|---|---|---|
| S0 前置 | 无事务 | `capability_client.fetch()` → `prepare_execution()` → `check_points()` | 只读 + 远程调用；`check_points` 的入参改为 `pricing.preflight_points(definition)`（C2.4） |
| **T1** | 事务 1 | `self._prepare_session(db, user_id, effective)` → `self._persist_user_message(db, session, effective, user_id)` → **`db.commit()`** | 提交后 `session.id` / 用户消息 `id` 已确定；`expire_on_commit=False` 保证属性仍可读 |
| **S2** | **无事务** | `execute_prepared(execution, runtime=..., model_client=...)` | 3–10 秒模型调用。**禁止**在本段出现任何 `db.` 访问、`db.commit()`、`db.refresh()`、ORM 属性懒加载 |
| **T2** | 事务 2 | `self._persist_assistant_message(db, session_id, reply, ...)` → `report_execution(...)` → **`db.commit()`** | 先远程上报（幂等键 `request_id`），再本地提交；顺序与今日一致 |
| 出口 | — | `completion_result(...)` | 必须在 T2 `commit()` **之后**组装（需要 `message_id`） |

精确约束：

1. **跨段只传标量**：S2 与 T2 之间只允许传递 `session_id: int`、
   `is_new_session: bool`、`reply: ModelReply`。禁止把 `ChatSession` /
   `ChatMessage` ORM 实例跨 T1/S2 传入 T2 并在 T2 中触发懒加载
   （`expire_on_commit=False` 让它在同 Session 下"看起来能用"，一旦连接已归还
   再触碰未加载关系就会在 S2 窗口内隐式 `checkout`，把 A1 收益抹掉）。
2. `_prepare_session` 签名与返回 `(ChatSession, bool)` **不变**；调用方在
   `db.commit()` 之后立即取 `session_id = session.id`、`is_new = is_new`。
3. `_persist_assistant_message` 签名改为
   `(db, *, session_id: int, reply: ModelReply, user_id: str, is_new_session: bool) -> ChatMessage`；
   内部改用新增的 `chat_repository.touch_session_by_id(db, session_id, now=...)`
   （`UPDATE t_chat_session SET last_message_time=:now WHERE id=:id`），
   不再接收 `ChatSession` 对象。
4. `chat_repository.touch_session(db, session, *, now)` **保留**（其他调用点不变），
   新增 `touch_session_by_id` 并在 A1 内使用。
5. T1 的 `except` 分支：`db.rollback()` + 原样抛出（无副作用，因为未落任何数据）。
6. T2 的 `except` 分支：`db.rollback()` + 原样抛出。
7. S2 **必须**包一层 `try/except Exception`，其唯一职责是 A1.2 分支 B 的
   失败标记落库，之后**必须 `raise`** 原异常；**禁止**在该 `except` 里吞异常、
   改写错误码或返回 200。超时/坏响应已被 `execute_prepared` 折算成 `degraded`
   返回值，不会进入该分支；进入该分支的只有编程错误与未预期异常。

骨架（照此实现，段间注释保留，便于 code review 核对连接持有窗口）：

```python
async def complete(self, db: Session, request: ChatCompletionRequest, user: UserContext) -> dict:
    user_id = self._require_user(user)
    started_at = time.perf_counter()
    # S0：无事务
    definition = await capability_client.fetch(request.capability_id)
    execution = prepare_execution(definition, request)
    if settings.enable_internal_chain:
        await check_points(user_id, preflight_points(definition), call_internal=call_internal)
    effective = execution.request
    # T1：事务 1
    try:
        session, is_new = self._prepare_session(db, user_id, effective)
        self._persist_user_message(db, session, effective, user_id)
        db.commit()                      # 连接在此归还连接池
    except Exception:
        db.rollback()
        raise
    session_id = session.id
    # S2：无事务、无连接
    try:
        reply = await execute_prepared(
            execution, runtime=model_runtime_config.snapshot(), model_client=model_client,
        )
    except Exception as exc:
        self._persist_failure(db, session_id, user_id, definition, exc, is_new)  # A1.2 分支 B
        raise
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    # T2：事务 2
    try:
        message = self._persist_assistant_message(
            db, session_id=session_id, reply=reply, user_id=user_id, is_new_session=is_new,
        )
        receipt = None
        if settings.enable_internal_chain:
            receipt = await report_execution(
                user_id, definition, reply, duration_ms, call_internal=call_internal,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    # 出口
    return completion_result(
        definition=definition, session_id=session_id, message_id=message.id, reply=reply,
        duration_ms=duration_ms, receipt=receipt,
    )
```

`self._persist_failure(...)` 为 A1.2 分支 B 的收敛函数（`chat_service.py` 内私有方法），
签名 `(db, session_id: int, user_id: str, definition, exc: BaseException, is_new: bool) -> None`，
内部按 A1.2 的顺序执行"提交失败消息 → best-effort 上报 → 记 ERROR"，**不抛异常**。

### A1.2 模型失败 / 异常时的落库内容

两个**必须区分**的分支：

**分支 A：降级（`reply.degraded == True`，正常返回值）**

- 走正常 T2：助手消息 `content = DEGRADED_REPLY`、`call_status = "degraded"`、
  `token_count = 0`；`report_execution` 上报 `points = 0`、`status = "degraded"`；
  响应 200，`billing_detail.unbilled_reason = "degraded"`。
- 行为与今日完全相同，不改。

**分支 B：S2 抛异常（未预期失败）**

必须落"失败标记"，字段级定义：

| 落库对象 | 字段 | 取值 |
|---|---|---|
| `t_chat_message`（新行） | `session_id` | T1 得到的 `session_id` |
| | `user_id` | 当前用户 |
| | `role` | `"assistant"` |
| | `content` | **`FAILED_REPLY`**（新增常量：`"本次调用失败，未产生回复，请稍后重试。"`） |
| | `call_status` | `"failed"` |
| | `token_count` | `0` |
| `t_chat_session` | `last_message_time` | `datetime.now()`（用 `touch_session_by_id`） |
| `POST /internal/billing/record` | `points` | `0` |
| | `status` | `"failed"` |
| | `billing_mode` / `unit_price` / `units` | 与本次能力一致 |
| | `prompt_tokens` / `completion_tokens` | `0` |
| | `usage_source` | `"missing"` |
| | `remark` | `f"{definition.code} failed={type(exc).__name__}"` |

执行顺序与容错（**best-effort，不得掩盖原异常**）：

1. 开 T2'：写 `FAILED_REPLY` 助手消息 + `touch_session_by_id` + `db.commit()`。
2. 若 `enable_internal_chain`：`report_execution(...)` 上报失败记录
   （**必须在 T2' commit 之后**，避免本地回滚连账单一起丢）。
3. 上述两步任一步失败：`logger.error` 记录 `request_id` / `session_id`，
   **不再抛新异常**。
4. 最后 `raise` 原异常（未捕获异常由全局处理器转 `4003 "系统内部错误"`，
   现状行为，不改错误码）。

会话状态**不新增**"失败"状态枚举：`t_chat_session` 无 `status` 列，
失败语义只由 `call_status="failed"` 的助手消息承载。
**禁止**只提交用户消息而不写失败标记（就是需求点名禁止的"静默丢失"）。

验收对应：模型失败的用例必须能查到 ① 用户消息（T1 已提交）
② `call_status="failed"` 的助手消息 ③ `t_call_record` 一条 `status=failed, cost=0` 行。

### A1.3 新事务写助手消息失败时的补偿语义

场景：`report_execution` 已成功（billing 已扣分并提交），随后 T2 的
`db.commit()` 失败（DB 抖动/连接断）。

冻结处理：

1. `db.rollback()`；日志
   `logger.error("billing_reconcile_required request_id={} record_id={} session_id={}", ...)`
   （必须含 `request_id` 与 `record_id`，这是对账的唯一入口）。
2. 异常上抛 → 全局处理器返回 `4003`；响应**不**包含 `record_id`（拿不到完整响应）。
3. 用户消息保留（T1 已提交），会话列表可见该用户消息、无助手消息。
4. 对账口径（写进契约文档，不做自动重试）：以 `request_id` 为键比对
   `t_call_record` 与 `t_chat_message`；命中"有账单无助手消息"时，人工核对后
   按 `request_id` 补记或退款，**禁止**自动重试模型（会二次计费）。
5. **禁止**把 `report_execution` 改到 `db.commit()` 之后来"规避"该场景：
   那样会变成"有消息无账单"，而账单侧有幂等键与扣分，恢复成本远高于
   消息侧；保持"先上报后提交"是既有契约（`docs/api-contract/ai-chat-service.md`
   第 4 节已登记该取舍）。

### A1.4 对 `completion_result()` 入参的影响

| 入参 | 变更 | 取值来源 |
|---|---|---|
| `definition` | 不变 | S0 |
| `session` → **`session_id: int`** | 改为标量 | T1 后取 `session.id` |
| `message` → **`message_id: int`** | 改为标量 | T2 commit 后的 `message.id` |
| `reply` | 不变 | S2 |
| `prompt_tokens` | **删除**（已删） | 由 `reply.prompt_tokens` 提供（C1.7） |
| `duration_ms` | 不变 | 进入函数前计时 |
| `receipt` | 不变（`dict \| None`） | `report_execution` 返回值 |

组装时机硬约束：`completion_result` 只能在 T2 `commit()` 之后调用；
若在 T2 之前调用，`message_id` 未生成。`receipt=None` 时
`billing_detail` 必须为 `null`（C1.7）。

---

## A2　连接池参数化 + 多 worker

### A2.1 环境变量名与默认值（四个服务统一）

四个服务 `app/core/config.py` 的 `Settings` 各新增同样 5 个字段
（`pydantic_settings` 名称映射：字段名大写即环境变量名）：

| 环境变量 | 字段 | 类型 | 默认值 | 约束 | 说明 |
|---|---|---|---|---|---|
| `DB_POOL_SIZE` | `db_pool_size` | `int` | `5` | `ge=1, le=50` | 常驻连接数 |
| `DB_MAX_OVERFLOW` | `db_max_overflow` | `int` | `5` | `ge=0, le=50` | 峰值额外连接 |
| `DB_POOL_TIMEOUT` | `db_pool_timeout` | `float` | `5.0` | `gt=0` | 取连接等待上限（秒） |
| `DB_POOL_RECYCLE` | `db_pool_recycle` | `int` | `1800` | `ge=60` | 连接回收秒数，防 MySQL `wait_timeout` 断连 |
| `DB_POOL_PRE_PING` | `db_pool_pre_ping` | `bool` | `true` | — | 取连接前探活，保持现有 `pool_pre_ping=True` 行为 |
| `UVICORN_WORKERS` | — | — | `4` | `ge=1, le=16` | **只被启动脚本读取**，不进 `Settings` |

`app/db/session.py`（四个服务逐字相同）：

```python
engine = create_engine(
    settings.db_url,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)
```

- 数字全部来自 `settings`，**禁止**任何字面量留在 `create_engine`。
- `pool_size` 默认值从 `5` 保持为 `5`（不放大），`max_overflow` 从 `10` 收到 `5`：
  见 A2.4 的容量核算。
- 每个服务的 `.env.example` 追加上述 5 行 + `UVICORN_WORKERS=4`，
  并在 `deploy/.env.example` 同步（`scripts/contract_lint.py` 会校验模板存在性）。

容量核算（**上线前必须对得上**）：

```
单 worker 最大连接 = DB_POOL_SIZE + DB_MAX_OVERFLOW = 5 + 5 = 10
单服务最大连接     = 10 × UVICORN_WORKERS(4) = 40
四服务最大连接     = 40 × 4 = 160
MySQL max_connections 需求 = 160 + 余量(管理员/工具/迁移) ≥ 300   ✅ 300 足够
```

### A2.2 uvicorn worker 启动方式与默认值

| 落点 | 改动 |
|---|---|
| `scripts/start_dev.py:45`（**唯一** uvicorn 命令构造点） | `command` 追加 `"--workers", str(int(values.get("UVICORN_WORKERS", "4")))`；`values` 已合并服务 `.env` 与注入环境 |
| `scripts/start_pro_local.py` | **不改**：非 middleware 分支只是把组件名转发给 `start_dev.py`（第 53 行），worker 由上面单点生效 |
| `scripts/start-pro-stack.ps1` / `scripts/one-click-start.ps1` | **不改**：都通过 `start_pro_local.py` → `start_dev.py` 拉起服务 |
| `deploy/docker-compose*.yml` | 不起 Python 服务，**不改**（只改 MySQL 段，见 A2.3） |
| 服务 `app/main.py` | **不改**（无 `uvicorn.run`，不硬编码 worker） |

- 默认 worker 数：**4**（`UVICORN_WORKERS` 缺省值，四个服务一致）。
- **禁止**在 `--workers > 1` 时同时使用 `--reload`（uvicorn 直接报错）。
- 已知限制（必须写入 runbook / 契约文档）：`--workers > 1` 下每个进程
  **独立**维护 Nacos 注册与 `model_runtime_config` 热更新快照，配置变更
  生效存在进程间毫秒级不一致；本批不引入进程间广播。内存态数据
  （未来 A4 的令牌桶）同样按进程计数。

### A2.3 MySQL `max_connections` 配置落点

**落点：compose 的 MySQL `command` 参数，不引入 `my.cnf`。**

`deploy/docker-compose.yml` 的 `mysql.command` 列表追加：

```yaml
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --max-connections=${MYSQL_MAX_CONNECTIONS:-300}
```

`deploy/docker-compose.pro-local.yml` 的 mysql 段做同样追加（该文件端口不同，
参数必须同步，否则两套栈行为不一致）。

- 理由：与既有 `--character-set-server` 保持同一机制；避免新增挂载文件、
  避免 `docker-entrypoint-initdb.d` 执行顺序与权限问题。
- 默认值 `300`（可被 `MYSQL_MAX_CONNECTIONS` 覆盖），**不得低于 300**。
- 校验命令（验收脚本用）：
  `SHOW VARIABLES LIKE 'max_connections';` → `300`；
  `SHOW STATUS LIKE 'Threads_connected';` → 稳态 `< 0.6 × max_connections`。
- 若宿主机 MySQL 非容器（`start_pro_local.py` 连本机 3307），需在启动前
  执行 `SET GLOBAL max_connections = 300;` 并写入 runbook；此项**不**由代码执行。

### A2.4 与 A1 的相互作用

| 顺序 | 影响 | 结论 |
|---|---|---|
| A1 先、A2 后（本批顺序） | 连接持有时间从 3–10 s 降到 ~50 ms，单 worker 并发需求从 ~15 降到 ~1–2 | `pool_size=5 + max_overflow=5` = 10/worker 足够，无需 15/worker |
| A2 先、A1 后（若并行顺序颠倒） | 模型调用期间仍占连接，10 连接/worker × 4 worker = 40 会被 3–10 s 的持有时间迅速打满 | 在此顺序下必须临时把 `DB_POOL_SIZE` 调到 `15`、`DB_MAX_OVERFLOW` 调到 `15`，并把 `max_connections` 提到 `4×4×30=480`；A1 落地后**必须**回落到 5/5 与 300 |

因此本批硬约束：**A2 的最终值只能是 5/5 + worker 4 + `max_connections` 300，
且必须在 A1 验收通过之后才允许合并 `UVICORN_WORKERS=4` 的默认值变更。**

---

## 影响面

### 会被波及的测试文件

| 文件 | 原因 |
|---|---|
| `services/ai-chat-service/tests/test_api.py:116` | 断言 `assistant["token_count"] > 0`：语义已变为 `usage` 推导值，需改为断言 `usage.prompt_tokens/completion_tokens` 与 `usage_source` |
| `services/ai-chat-service/tests/test_api.py:220` | 用 `token_count=len(DEGRADED_REPLY)` 构造 `ModelReply`：该字段已删除，构造必须改为 `prompt_tokens=0, completion_tokens=0, usage_source="missing"` |
| `services/ai-chat-service/tests/test_execution_chain.py` | 上报 payload 与收据断言需覆盖 C2.5/C2.7 新字段；`per_call` 金额断言（5/3）必须保持不变 |
| `services/ai-chat-service/tests/test_openai_compat.py:29` | 上游 `usage {3,6,9}` 断言 → 必须同时断言 `usage_source="upstream"` 与 `billing_detail` |
| `services/ai-chat-service/tests/test_capability_client.py` | `CapabilityDefinition` 新增 5 字段：详情缺省时须解析为 `per_call`；`extra="ignore"` 行为要被显式覆盖 |
| `services/ai-chat-service/tests/test_capability_validation.py` | 执行器入参校验不变，但若新增 `units` 语义需补边界用例（`per_unit` 未实现时应断言不可达） |
| `services/ai-chat-service/tests/conftest.py` | 若测试替身构造 `ModelReply` 或伪造上游响应，需按 C1.1/C1.2 更新；引擎改为读 `settings` 后，测试的 engine 参数断言需同步 |
| `services/billing-service/tests/test_schemas.py` | `validate_price` 规则全面放宽（C2.5），现有 `points/unit_price` 用例需按三模式扩表；`BillingRecordRequest` 新字段默认值须断言 |
| `services/billing-service/tests/test_api.py` | 收据响应新增 7 字段（C2.7），响应体断言需补 |
| `services/billing-service/tests/test_billing_db.py` | `t_call_record` 新增 7 列（C1.4），建表断言/列清单需更新 |
| `services/billing-service/tests/test_pro_db.py` | 同上（Pro 库结构断言） |
| `services/capability-service/tests/test_internal_capability.py` | 内部详情从 6 字段变 11 字段（C2.2），`test_internal_detail_returns_contract_fields` 与价格边界用例需重写；新增 `per_token` 价格全 0 → 4002 的失败关闭用例 |
| `services/capability-service/tests/test_catalog_db.py` | `t_capability` 新增 5 列 + 2 个 CHECK（C2.1），DDL 对齐断言需更新 |
| `services/capability-service/tests/test_schema_migration.py` | 需覆盖新迁移脚本（04）可重复执行、CHECK 生效、旧行默认值正确 |
| `services/capability-service/tests/test_schemas.py` | Create/Update 新字段与交叉校验（C2.2） |
| `services/capability-service/tests/test_api.py` | 市场/运营出参新增计价字段，且"不暴露内部配置"用例需确认新字段不在屏蔽名单内 |
| `services/user-service/tests/conftest.py`（及三个服务的 `conftest.py`） | `app/db/session.py` 改为读 `settings` 后，测试引擎构造若覆盖了参数需同步；`DB_POOL_SIZE` 等环境变量需在测试环境有默认值 |
| `scripts/Assert-ProjectBaseline.ps1` / `scripts/Invoke-QualityGate.ps1` / `scripts/gate.sh` | 质量门禁会跑 pytest 与 `contract_lint`，本批新增迁移脚本与契约章节后需确认门禁清单不遗漏 |
| `scripts/contract_lint.py` | 校验 `.env.example` 存在与契约文档章节关键词；新增 `DB_POOL_*` / `UVICORN_WORKERS` 后模板必须同步，否则 lint 失败 |

### 会被波及的契约文档章节

| 文档 | 章节 | 为什么 |
|---|---|---|
| `docs/api-contract/ai-chat-service.md` | 第 4 节「执行顺序与响应」 | 现有"prompt_tokens 按字符数估算"必须删除；`usage_source` / `billing_mode` / `billing_detail` 需入示例；执行顺序需改为 T1/S2/T2 三段 |
| `docs/api-contract/ai-chat-service.md` | 第 6 节「配置」 | 新增 `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` / `DB_POOL_PRE_PING` / `UVICORN_WORKERS` 六行 |
| `docs/api-contract/ai-chat-service.md` | 第 7 节「错误与验收」 | A1 失败标记（`failed` 助手消息 + `cost=0` 账单）与"先上报后提交"的对账语义需登记 |
| `docs/api-contract/billing-service.md` | 第 1 节「数据字典」 | `t_call_record` 新增 7 列 + `unit_price` 语义改写（C1.4） |
| `docs/api-contract/billing-service.md` | 第 2 节「`POST /internal/billing/record`」 | 请求/响应新增字段、`validate_price` 新规则、幂等比较字段（C2.5/C2.7） |
| `docs/api-contract/billing-service.md` | 第 3 节「调用明细」 | `CallRecordOut` 新增 7 字段与"未记录 token 显示 `—`"规则（C1.6） |
| `docs/api-contract/billing-service.md` | 第 5 节「错误码」 | `3002` 触发条件扩到新字段；`3001` 在 `per_token` 下可能由结算（非预检）触发 |
| `docs/api-contract/capability-service.md` | 第 1 节「数据字典 `t_capability`」 | 5 列 + 2 个 CHECK + `price_per_call` 在非 `per_call` 模式必须为 0 |
| `docs/api-contract/capability-service.md` | 第 3 节「`POST/PUT /api/capability`」 | 入参新增 5 字段与交叉校验错误 `2001` |
| `docs/api-contract/capability-service.md` | 第 4 节「市场与运营接口」+「`/internal/capability/{id}`」 | 三个出参新增计价字段，内部详情从 6 字段到 11 字段 |
| `docs/api-contract/capability-service.md` | 第 7 节「示例数据与验收」 | 新增迁移脚本 04 与"旧能力 `per_call` 断言输出" |
| `docs/api-contract/openai-compat.md` | 「与原生接口的差异」 | `usage` 口径变化（现在来自上游真值）+ 新增 `usage_source`；Responses 的 `input_tokens/output_tokens` 归一化说明 |
| `docs/api-contract/pro-shared.md` | 幂等与计量约定 | `request_id` 幂等键在新增比较字段后的行为、`1000 tokens = 1 积分` 换算比例定标 |
| `docs/升级实施日志.md` | 批 1 条目 | 需登记 C1/C2/A1/A2 的落地口径、`TOKENS_PER_PRICE_UNIT=1000` 的定标决定、多 worker 已知限制 |
| `docs/升级需求清单-2026-11-02.md` | C2 的「待定：换算比例」 | 已定标为 `1000 tokens = 1 积分`，需从"待定"改为"已定" |
| `docs/验收用例.md` | 计量相关用例 | 4050 tokens → 5 分的验收用例、A1 失败标记用例、A2 并发不超扣用例 |

### 前端波及（契约性，非本文件交付物）

| 文件 | 原因 |
|---|---|
| `web/src/api/chat.ts` | `usage` 类型不变，新增 `usage_source` / `billing_mode` / `billing_detail` |
| `web/src/features/chat/ExecutionReceipt.tsx` | 收据需展示 token 明细与 `unbilled_reason` |
| `web/src/features/chat/useConversation.ts` | 消息 meta 的 `token_count` 展示改为"未记录显示 `—`" |
| `web/src/api/capability.ts` / `web/src/features/console/CapabilityEditor.tsx` | 计价字段表单（三模式联动校验）与展示模板（C2.2） |
| `web/src/features/market/CapabilityCard.tsx` / `CapabilityDetail.tsx` | 价格展示按 C2.2 模板分模式渲染 |
| `web/src/api/billing.ts` / `web/src/features/usage/RecordTable.tsx` / `exportRecords.ts` | 明细新增 7 字段；导出列与页面口径一致；`—` 规则 |

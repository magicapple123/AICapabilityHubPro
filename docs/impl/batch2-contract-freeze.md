# 批 2「可观测与运维」契约冻结清单（B1–B4）

> 批次：批 2（依赖批 1）
> 冻结日期：2026-11-02
> 上游依据：`docs/升级需求清单-2026-11-02.md` 第 3 节 B1–B4、第 5 节红线、第 8.4 节「先冻结契约再并行」
> 下游使用方：工程师（按本文件实现）、QA（按本文件写断言）
> **冻结后不得再改**：表名、字段名、枚举值、接口路径、指标名、label 名、HTTP 状态码、原因码。
> 需要变更时，先改本文件并显式标注「变更日期 + 变更原因 + 波及文件」，再改代码。

---

## 0. 本文件的效力与工作区对齐

### 0.1 冻结范围

| 条目 | 冻结产物 |
|---|---|
| B1 审计 | `t_operation_log` DDL 全文、动作/资源枚举、快照与脱敏规则、查询接口契约、只追加的四层保证 |
| B2 readiness | `/health/ready` 路径、200/503、响应 JSON 结构、原因码枚举、各服务依赖清单、超时与不缓存约束 |
| B3 metrics | `/internal/metrics` 暴露面、9 个指标名 + label 集 + bucket、高基数防护、provider 占位口径、checkout 采集方式 |
| B4 对账 | 落点（独立脚本 + billing_db 两张结果表）、三类差异 SQL 口径、幂等去重算法、输出与触发方式 |

本文件**不含**批 1（C1/C2/A1/A2）与批 3/5 的实现内容；批 5（F1 用户管理）只冻结它对审计表的**结构性预留**（见 §1.9）。

### 0.2 与工作区现有实现的差异（工程师必须按本文件改这 6 处）

冻结时工作区已有 B1 的部分实现（`services/capability-service/app/{models/audit.py,core/audit_context.py,service/audit_service.py,schemas/audit.py,api/v1/audit.py}`、`sql/05_add_operation_log.sql`、`api/v1/deps.py`、两个 repository、`capability_service.py`、`main.py`）。**结构与方向一致，以下 6 处与冻结契约不符，必须改：**

| # | 位置 | 现状 | 冻结要求 |
|---|---|---|---|
| 1 | `capability_service.create_capability()` | `after=payload.model_dump(mode="json")`（请求体） | 改为**落库后的白名单快照** `snapshot(capability, CAPABILITY_AUDIT_FIELDS)`，与 `update` 的 `after` 同构（否则 D5 版本回滚拿不到同构字段集） |
| 2 | `schemas/audit.py::AuditLogOut` | 继承 `BaseModel`，`create_time` 输出 ISO `2026-11-02T16:40:00` | 继承 `app.schemas.common.BaseOut`，输出 `YYYY-MM-DD HH:MM:SS`（契约第 0 节，全平台只此一种时间格式） |
| 3 | `api/v1/audit.py` | `page_size` 默认 10；`resource_type`/`action` 为自由字符串；未校验时间区间 | 默认 20、上限 100；两个筛选参数改 `Enum`，非法值 2001；`start_date > end_date` 返回 2001 |
| 4 | `sql/05_add_operation_log.sql` | 只有 `CREATE TABLE` | 追加 `BEFORE UPDATE` / `BEFORE DELETE` 触发器（§1.2.2），这是「无法通过任何手段改写历史」的库级保证 |
| 5 | `sql/01_init.sql` | 未包含 `t_operation_log` | 新环境靠 01 建表，既有环境靠 05；两处 DDL 必须逐字一致 |
| 6 | `models/audit.py` | `is_deleted` 注释「逻辑删除，审计不使用」 | 结构与默认值**不改**，注释改为「恒为 0：无任何写入路径，保留列仅为与全库表结构族一致」 |

### 0.3 本批文件清单（逐个全路径）

**新增**

```
services/capability-service/sql/05_add_operation_log.sql          ← 已存在，需补触发器
services/capability-service/app/models/audit.py                   ← 已存在
services/capability-service/app/service/audit_service.py          ← 已存在
services/capability-service/app/schemas/audit.py                  ← 已存在，需改
services/capability-service/app/api/v1/audit.py                   ← 已存在，需改
services/capability-service/app/core/audit_context.py             ← 已存在
services/capability-service/app/core/health.py                    （新）健康检查实现
services/capability-service/app/api/v1/health.py                  （新）GET /health/ready
services/capability-service/app/core/metrics.py                   （新）指标定义 + 中间件 + 池事件
services/capability-service/app/api/v1/metrics.py                 （新）GET /internal/metrics
services/capability-service/tests/test_audit.py                   （新）
services/capability-service/tests/test_health_ready.py            （新）
services/capability-service/tests/test_metrics.py                 （新）

services/user-service/app/core/health.py / api/v1/health.py / core/metrics.py / api/v1/metrics.py
services/user-service/tests/test_health_ready.py / test_metrics.py
services/billing-service/app/core/{health.py,metrics.py} / app/api/v1/{health.py,metrics.py}
services/billing-service/tests/test_health_ready.py / test_metrics.py
services/billing-service/sql/04_add_reconcile_tables.sql          （新）
services/ai-chat-service/app/core/{health.py,metrics.py} / app/api/v1/{health.py,metrics.py}
services/ai-chat-service/tests/test_health_ready.py / test_metrics.py / test_metric_points.py

services/user-service/sql/03_add_operation_log.sql                （批 5 执行，本批只冻结文件与 DDL）

scripts/reconcile_billing.py                                       （新）
tests/tooling/test_reconcile.py                                    （新）
docs/impl/batch2-contract-freeze.md                                （本文件）
```

**修改**

```
services/{user,billing,capability,ai-chat}-service/app/main.py         挂载 health/metrics 路由 + 注册中间件
services/{user,billing,capability,ai-chat}-service/app/core/result.py  ok()/fail() 写业务码 ContextVar
services/{user,billing,capability,ai-chat}-service/app/db/session.py   绑定池 checkout 事件
services/{user,billing,capability,ai-chat}-service/app/core/config.py  readiness_timeout_seconds / model_provider_alias
services/{user,billing,capability,ai-chat}-service/requirements.txt    prometheus-client
services/{user,billing,capability,ai-chat}-service/.env.example        新配置项
services/capability-service/{sql/01_init.sql, repository/capability_repository.py, repository/category_repository.py,
    service/capability_service.py, service/category_service.py, schemas/__init__.py, models/__init__.py, api/v1/__init__.py}
services/user-service/app/service/{user_service.py, points_service.py}  批 5 埋点位置预留，本批不改
docs/api-contract/{capability-service,user-service,billing-service,ai-chat-service,pro-shared}.md
docs/升级实施日志.md
scripts/gate.sh                                                        批 2 门禁补 contract-lint 与 gateway-test
scripts/smoke_check.py                                                 +4 条 readiness 断言 +1 条 metrics 403 断言
gateway/src/main/java/com/aicapabilityhub/gateway/filter/AuthGlobalFilter.java  isHealthPath 放宽 /health/ready
gateway/src/test/java/com/aicapabilityhub/gateway/...                  +readiness 透传 / +metrics 403 / +白名单对照组用例
web/src/api/{capability.ts,types.ts}、web/src/pages/ConsolePage.tsx    「操作审计」页签（§5.5）
deploy/.env.example
```

---

## 1. B1 运营审计

### 1.1 落点决策：一库一张同构表

**决策：一库一张同构表。** `capability_db.t_operation_log` 与 `user_db.t_operation_log` 字段逐字相同、各自独立。

理由（三条，均为硬约束，不是偏好）：

1. `scripts/contract_lint.py::check_service_boundaries` 用 AST 扫描 `services/*/app/**/*.py`，除自身库名外的 `user_db|billing_db|capability_db|ai_chat_db` 一律报错。集中一张表放在任一库，都会让另外三个服务的写入代码出现跨库引用，**直接门禁红**。
2. 服务不使用分布式事务（`pro-shared.md` 第 7 节已定：每服务本地事务不是分布式原子提交）。跨库写会引入"业务写完但审计没写"或相反的半成功状态，无法回滚。
3. 审计必须与业务写在**同一个本地事务**内提交，才能保证「改了必留痕」。一库一表是该保证的唯一实现方式。

被否决的方案：

| 方案 | 否决原因 |
|---|---|
| 汇总表放 `capability_db`，其他服务远程写 | 跨库；capability 挂掉则 user 的调分/禁用无法留痕；需新增跨服务写接口，与"服务只暴露 internal 读"的现状冲突 |
| 汇总表放独立 `ops_db` + 独立审计服务 | 新增第 5 个服务与库，批 2 工期 5 天内不可行；且同样需要分布式一致性 |
| 只写日志文件不落库 | 不满足 B1 验收「改价后能查到操作人、时间、改前改后」与筛选分页；日志无法查询 |
| 用 binlog / 通用 CDC | 拿不到 `operator_id` 与 `requestId`，无法回答"谁改的" |

**本批建表范围**：只建 `capability_db`。`user_db` 同构表在批 5（F1）建，DDL 与文件号本文件已预留（§1.10）。billing-service 与 ai-chat-service **不建审计表**：本批与批 5 中这两个服务没有运营写操作（`/api/billing/admin/*`、`/api/chat/*` 全部只读）。

### 1.2 DDL 全文

#### 1.2.1 建表（`services/capability-service/sql/05_add_operation_log.sql` 与 `01_init.sql` 逐字相同）

```sql
SET NAMES utf8mb4;
-- capability-service 增量迁移（B1 运营审计）。
-- 只建新表，不动任何既有表与数据；重复执行安全。
-- 应用层只追加：无 update / delete 接口，repository 无对应方法，库层由触发器拒绝。
-- user-service 的同类表在批 5（F1）以同构字段建立；四库物理隔离，不跨库查询。
USE capability_db;

CREATE TABLE IF NOT EXISTS t_operation_log (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，单调递增 = 写入顺序',
  operator_id VARCHAR(64) NOT NULL COMMENT '操作人 user_id，取网关注入的 X-User-Id 原值',
  operator_name VARCHAR(64) NOT NULL DEFAULT '' COMMENT '操作人名称快照，取 X-User-Name，不 join 用户表',
  resource_type VARCHAR(32) NOT NULL COMMENT '资源类型 capability/category/user/points/apikey',
  resource_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '资源标识：自增 id 的十进制串，或业务编码 code',
  action VARCHAR(32) NOT NULL COMMENT '动作 create/update/status/delete/rollback/adjust_points/export',
  before_json JSON NULL COMMENT '变更前白名单快照（已脱敏）；create 为 NULL',
  after_json JSON NULL COMMENT '变更后白名单快照（已脱敏）；delete 为删除前快照 + is_deleted=1',
  request_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '全链路 requestId，与本次响应 requestId 一致',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '写入时间，库时区（Asia/Shanghai）',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '恒为 0：无任何写入路径，保留列仅为与全库表结构族一致',
  PRIMARY KEY (id),
  KEY idx_operation_log_resource (resource_type, resource_id, id),
  KEY idx_operation_log_operator (operator_id, id),
  KEY idx_operation_log_time (create_time),
  KEY idx_operation_log_request (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='运营操作审计（只追加）';
```

设计取舍（已定，不再讨论）：

- **不加 `update_time`**：`ON UPDATE CURRENT_TIMESTAMP` 在只追加表上是语义噪音，且与"拒绝 UPDATE"的触发器自相矛盾。
- **`request_id` 不建唯一索引**：一次请求可能写多行（如 D5 回滚同时记 `rollback` 与被回滚资源的 `update`），唯一索引会撞键。requestId 只用于溯源，不作幂等键。
- **`resource_id` 用 `VARCHAR(64)` 而非 `BIGINT`**：同时承载自增 id 与 `code`（能力编码、分类编码都是业务键），避免为两类资源建两套列。
- **`before_json`/`after_json` 用原生 `JSON` 列**（MySQL 8.4 已支持）：便于用 `JSON_EXTRACT` 做定点排查；不用 `TEXT` 以免出现非法 JSON 存进去。
- **`operator_name` 冗余存快照，不 join `t_user`**：审计行必须在用户改名/删除后仍能读懂；且 user 表在别的库，join 就是跨库。

#### 1.2.2 只追加的库级保证（触发器，追加在 05 迁移文件末尾）

```sql
-- 只追加的库级兜底：任何 UPDATE / DELETE 都被数据库拒绝。
-- 应用层与其测试用不到这两个触发器，但它是「无法通过任何手段改写历史」的最后一道防线。
-- MySQL 8 不支持 CREATE TRIGGER IF NOT EXISTS，因此先 DROP 再建，保证可重复执行。
DROP TRIGGER IF EXISTS trg_operation_log_no_update;
DROP TRIGGER IF EXISTS trg_operation_log_no_delete;

DELIMITER $$
CREATE TRIGGER trg_operation_log_no_update
BEFORE UPDATE ON t_operation_log
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 't_operation_log is append-only: UPDATE is forbidden';
END$$

CREATE TRIGGER trg_operation_log_no_delete
BEFORE DELETE ON t_operation_log
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 't_operation_log is append-only: DELETE is forbidden';
END$$
DELIMITER ;
```

已知边界（写清，避免验收争议）：`TRUNCATE TABLE` 不触发 `BEFORE DELETE`。清空历史只可能由持有 DDL 权限的 DBA 直接执行，不属于应用层能力，验收口径为「无法通过任何**接口**修改历史记录」。

### 1.3 字段级语义

| 字段 | 类型 | 可空 | 来源 | 语义与边界 |
|---|---|---|---|---|
| `id` | `BIGINT AI` | 否 | 库 | 单调递增即写入顺序；列表排序用 `id DESC`，不用 `create_time`（同秒多行时顺序不确定） |
| `operator_id` | `VARCHAR(64)` | 否 | `X-User-Id` | 字符串原值，不转 int（保持与 `UserContext.user_id: str` 一致）；无操作人身份时**不写审计行** |
| `operator_name` | `VARCHAR(64)` | 否 | `X-User-Name` | 允许空串（网关未注入时）；不做任何校验，不做长度截断以外的加工 |
| `resource_type` | `VARCHAR(32)` | 否 | 埋点处常量 | 见 §1.4，7 个动作对应的资源类型只有 5 个取值 |
| `resource_id` | `VARCHAR(64)` | 否 | 落库后的自增 id 或业务 code | create 场景由 repository 在 `flush()` 之后回填（此时才有 id）；`""` 表示不适用 |
| `action` | `VARCHAR(32)` | 否 | 埋点处常量 | 见 §1.4 |
| `before_json` | `JSON` | 是 | 白名单快照 | 见 §1.5；create 恒为 `NULL` |
| `after_json` | `JSON` | 是 | 白名单快照 | 见 §1.5；update 恒为「合并后的完整快照」 |
| `request_id` | `VARCHAR(64)` | 否 | `UserContext.request_id` | 与响应 `requestId` 一致，便于从一次报障追到一条审计 |
| `create_time` | `DATETIME` | 否 | 库 `CURRENT_TIMESTAMP` | 由库生成，应用层不传；对外输出 `YYYY-MM-DD HH:MM:SS` |

### 1.4 动作与资源类型枚举（冻结）

```python
# services/capability-service/app/service/audit_service.py（批 5 在 user-service 复制同构常量）
ACTION_CREATE = "create"          # 登记能力 / 新增分类
ACTION_UPDATE = "update"          # 编辑能力 / 编辑分类
ACTION_STATUS = "status"          # 上架、下架、启用、禁用
ACTION_DELETE = "delete"          # 软删除能力 / 软删除分类
ACTION_ROLLBACK = "rollback"      # D5 版本回滚（批 7）
ACTION_ADJUST_POINTS = "adjust_points"  # F1 管理员手工调分（批 5）
ACTION_EXPORT = "export"          # F1 用户/用量数据导出（批 5）

RESOURCE_CAPABILITY = "capability"
RESOURCE_CATEGORY = "category"
RESOURCE_USER = "user"
RESOURCE_POINTS = "points"
RESOURCE_APIKEY = "apikey"
```

`ACTION_*` 与 `RESOURCE_*` 一旦冻结即为契约，新增必须同时改 `docs/api-contract/*.md` 与查询接口的 `Enum`；不允许出现未登记的魔法字符串。

### 1.5 `before_json` / `after_json` 序列化与脱敏约定

#### 1.5.1 快照字段白名单（不做全表快照）

```python
CAPABILITY_AUDIT_FIELDS = (
    "category_id", "name", "code", "service_name", "path", "param_schema",
    "price_per_call", "billing_mode", "price_per_1k_input", "price_per_1k_output",
    "price_per_unit", "unit", "status", "description",
)
CATEGORY_AUDIT_FIELDS = ("name", "code", "sort", "status")
```

- **不用 `obj.__dict__`**：会把 `is_deleted`、内部列、懒加载关系一并写进审计，既噪音又可能泄漏。
- **快照只含白名单字段**，取不到的字段（未落库对象）落 `None`，不允许抛异常。
- **白名单不含任何 `datetime` 列**。后续若新增时间列，必须先 `strftime("%Y-%m-%d %H:%M:%S")` 再落库，与契约第 0 节统一（pydantic `mode="json"` 产出的是 ISO `T` 格式，**不得**直接使用）。

#### 1.5.2 三种场景的快照取值

| 场景 | `before_json` | `after_json` |
|---|---|---|
| `create` | `NULL` | 落库对象的白名单快照（**含** `status`、计价字段、`param_schema`） |
| `update` | 改前白名单快照 | **合并后的完整快照**（`{**before, **{k: v for k, v in values.items() if k in FIELDS}}`），不是增量 diff |
| `status` | `{"status": "online"}` | `{"status": "offline"}`（只记 status 两个键，不记全快照——避免每次上下架写整行） |
| `delete` | 删除前白名单快照 | `{"is_deleted": 1}`，若同时把 online 置 offline 则 `{"is_deleted": 1, "status": "offline"}` |

`after_json` 为**合并后完整快照**是本冻结的关键决定：D5「回滚到此版本」直接用某一行的 `after_json` 作为 `PUT` 请求体，不需要回放一串 diff。若只存增量，回滚必须重放历史，任何一次脏数据都会永久污染结果。

#### 1.5.3 脱敏

```python
SENSITIVE_KEYWORDS = ("password", "passwd", "secret", "api_key", "apikey", "token", "cipher")
MASK = "***"
```

规则（递归生效，含嵌套 dict 与 list[dict]）：

1. 键名（小写后）包含任一敏感关键词 → 值替换为 `"***"`，**不保留长度、不保留前后缀**；
2. 其余键的值原样保留（`param_schema` 是目录配置，不是用户数据，可整段落库）；
3. `operator_name`、`resource_id`、`request_id` 不参与脱敏；
4. **会话正文永不进审计**（F1 已定边界：正文不出 ai-chat）。本批 capability/user 的写操作字段中不存在正文，若未来新增，必须在埋点处显式排除，不得依赖关键词黑名单。

`CAPABILITY_AUDIT_FIELDS` 内没有敏感字段，`SENSITIVE_KEYWORDS` 是防"未来有人把 `api_key` 加进白名单"的兜底，两者互为冗余。

### 1.6 埋点清单（逐接口逐动作，不多不少）

| 接口 | 资源 | 动作 | 位置 |
|---|---|---|---|
| `POST /api/capability` | capability | create | `CapabilityService.create_capability` |
| `PUT /api/capability/{id}` | capability | update | `CapabilityService.update_capability` |
| `PUT /api/capability/{id}/status` | capability | status | `CapabilityService.update_status` |
| `DELETE /api/capability/{id}` | capability | delete | `CapabilityService.delete_capability` |
| `POST /api/capability/categories` | category | create | `CategoryService.create_category` |
| `PUT /api/capability/categories/{id}` | category | update | `CategoryService.update_category` |
| `DELETE /api/capability/categories/{id}` | category | delete | `CategoryService.delete_category` |
| 批 5：`PUT /api/user/admin/users/{id}/status` | user | status | `UserService`（批 5） |
| 批 5：`POST /api/user/admin/users/{id}/points` | points | adjust_points | `PointsService`（批 5） |
| 批 5：`GET /api/user/admin/users/export` | user | export | 批 5 |
| 批 7：回滚 | capability | rollback | D5 |

**明确不埋点**：全部 GET 接口、市场接口、`/internal/**` 内部接口、`/ping`、`/health*`、`/internal/metrics`、登录/注册、API Key 自助增删（属用户自己的数据，已有 `t_api_key` 行），以及**系统扣分**（`biz_type=call` 的扣分已由 `t_points_log` 逐条留痕，再写一条审计是重复记账，且它是系统行为、没有 operator）。

#### 1.6.1 事务边界

审计行与业务写**同一个 `db.commit()`**（`repository.create/update_fields/soft_delete` 各自接收 `audit` 关键字参数并 `db.add()`）。

- `create` 场景必须 `db.flush()` 后再回填 `resource_id`，否则审计行拿到空 id。
- **审计写失败 → 整个操作回滚并返回 4003**（失败关闭）。不允许"改价成功但没留痕"。这是有意的取舍：留痕是合规要求，宁可拒绝写操作。
- **无操作人身份时不写审计、也不报错**：`build_entry()` 返回 `None`，repository 直接跳过。这样既有单测（直接调 service、无 `X-User-Id`）与内部调用不会因审计而变红。

### 1.7 查询接口

#### 1.7.1 路径与鉴权

```
GET /api/capability/audit        审计列表
```

- 前缀 `/api/capability`，网关 `Path=/api/capability/**` 已覆盖，**网关无需改动**。
- 鉴权：`Depends(require_admin)`，即每次请求实时调 `GET /internal/user/authorization?required_role=admin`，依赖异常失败关闭（4002）。不使用 JWT role、不使用前端隐藏按钮。
- 注册顺序：必须放在含路径参数的写路由**之前**（现 `main.py` 已如此），否则 `/audit` 会被 `/{capability_id}` 抢占并返回 2001/2002。
- **只有 GET**。不存在 `POST/PUT/DELETE /api/capability/audit`。

user-service 侧：`GET /api/user/admin/audit`（批 5，同结构、同参数、同出参，仅数据源换成 `user_db.t_operation_log`）。

#### 1.7.2 筛选参数（冻结）

| 参数 | 类型 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| `resource_type` | `AuditResourceType \| None` | 否 | `None`（全部） | 非法值 2001 |
| `resource_id` | `str \| None` | 否 | `None` | `max_length=64` |
| `action` | `AuditAction \| None` | 否 | `None`（全部） | 非法值 2001 |
| `operator_id` | `str \| None` | 否 | `None` | `max_length=64` |
| `start_date` | `date \| None` | 否 | `None` | `YYYY-MM-DD`，含当日 `00:00:00` |
| `end_date` | `date \| None` | 否 | `None` | `YYYY-MM-DD`，含当日至次日 `00:00:00` 前 |
| `page` | `int` | 否 | `1` | `ge=1, le=10000` |
| `page_size` | `int` | 否 | **`20`** | `ge=1, le=100` |

- `start_date > end_date` → **2001**「时间区间不合法」。
- 排序：`create_time DESC, id DESC`（时间相同按写入顺序倒序，结果确定可重放）。
- 不提供「按 resource_type 全量导出」——审计查询不出 CSV（本批不做导出，避免审计数据外流）。

#### 1.7.3 出参（分页，`data` 内结构）

成功 `HTTP 200`：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "list": [
      {
        "id": 1024,
        "operator_id": "1",
        "operator_name": "opsdemo",
        "resource_type": "capability",
        "resource_id": "2",
        "action": "update",
        "before_json": {"category_id": 1, "name": "多轮对话", "code": "chat-completions",
                        "price_per_call": 5, "billing_mode": "per_call",
                        "price_per_1k_input": 0, "price_per_1k_output": 0,
                        "price_per_unit": 0, "unit": "", "status": "online",
                        "service_name": "ai-chat-service", "path": "/api/chat/completions",
                        "param_schema": {"type": "object"}, "description": ""},
        "after_json":  {"category_id": 1, "name": "多轮对话", "code": "chat-completions",
                        "price_per_call": 8, "billing_mode": "per_call",
                        "price_per_1k_input": 0, "price_per_1k_output": 0,
                        "price_per_unit": 0, "unit": "", "status": "online",
                        "service_name": "ai-chat-service", "path": "/api/chat/completions",
                        "param_schema": {"type": "object"}, "description": ""},
        "request_id": "0f1d…",
        "create_time": "2026-11-02 16:40:07"
      }
    ],
    "total": 137,
    "page": 1,
    "page_size": 20
  },
  "requestId": "3c9a…"
}
```

`before_json` / `after_json` 为 `null` 时字段保留（`null`），不省略键——前端按键渲染 diff。

错误码：`2007` 非管理员 / `4002` 授权依赖不可用 / `2001` 参数非法 / `1001` 未认证。**不新增错误码**。

### 1.8 「应用层只允许追加」的四层保证（验收对象）

| 层 | 保证手段 | 可执行断言 |
|---|---|---|
| 接口层 | 路由文件 `api/v1/audit.py` 只有 `@router.get`；`main.py` 只 `include_router` 一次 | 遍历 `app.routes`，凡 `path` 以 `/api/capability/audit` 开头者，`methods ⊆ {"GET", "HEAD"}` |
| 服务层 | `AuditService` 只有 `list_logs`；模块内不存在 `update_*`、`delete_*`、`remove`、`purge`、`soft_delete` 成员 | 反射断言 `not hasattr(audit_service, name)` 对 `("update","delete","remove","purge","soft_delete","append")` 全部成立（写入不属于 service） |
| 仓储层 | 审计写入只经 `_attach_audit(db, audit, resource_id)`，挂在业务事务里；无独立 audit repository | 反射断言 `CapabilityRepository` / `CategoryRepository` 不存在 `update_operation_log` / `delete_operation_log` |
| 库层 | `BEFORE UPDATE` / `BEFORE DELETE` 触发器 `SIGNAL 45000` | 连隔离库执行 `UPDATE t_operation_log SET action='x'` 断言抛 `OperationalError`（`TEST_DB_TRIGGERS=1` 时执行，默认跳过，因为测试库由 ORM `create_all` 建表不带触发器） |

触发器的用例门控写清：默认测试库由 SQLAlchemy metadata 建表，**不含**触发器，所以该断言必须显式执行迁移 SQL 或按环境变量门控，不得因为「跑不到」而删掉。

### 1.9 批 5 预留：`user_db` 同构表

文件：`services/user-service/sql/03_add_operation_log.sql`，内容 = §1.2.1 的 DDL 与 §1.2.2 的触发器，仅两处不同：

1. `USE user_db;`
2. 表注释与注释文字里的服务名改为 `user-service`

批 5 的 user-service 侧约束（现在冻结，批 5 照做）：

- 手工调分：`t_points_log` 插一行（`biz_type='admin_adjust'`，需在批 5 扩展该枚举）+ 审计一行 `action=adjust_points`，**同一事务**；调分必须带 `remark`（原因），单次 `|amount| <= 10000`，余额不得为负。
- 禁用/启用：`action=status`，`resource_type=user`，`before/after` 只记 `{"status": ...}`。
- 导出：`action=export`，`resource_type=user`，`after_json` 记 `{"filters": {...}, "row_count": N}`，**不记导出的行内容**。

---

## 2. B2 readiness 健康检查

### 2.1 路径与暴露面

```
GET /health/ready      四个服务各一份，实现逐字一致（仅 service 名与依赖清单不同）
```

- **不在 `/api/**` 下**：不经业务路由，不经服务内鉴权，不占用任何业务前缀。
- 外部可达路径：`http://<gateway>/<service-name>/health/ready`（如 `/capability-service/health/ready`，由 `spring.cloud.gateway.discovery.locator` 提供，与现有 `scripts/smoke_check.py` 检查 `/{name}/health` 的用法一致）。
- **网关必须改一行**：`AuthGlobalFilter.isHealthPath()` 目前只认 `normalized.equals("/health") || normalized.endsWith("/health")`，`/{service}/health/ready` 不匹配 → 会先被 JWT 校验拦成 401。冻结要求扩展为：

  ```java
  private boolean isHealthPath(String path) {
      String normalized = normalizePath(path);
      return normalized.equals("/health")
              || normalized.endsWith("/health")
              || normalized.endsWith("/health/ready");
  }
  ```

  注意 `isInternalPath` 的判断在 `isWhitePath` **之前**，因此这次放宽不会顺带放开 `/{service}/internal/metrics`（403 不变）。
- **`/ping` 与 `/health` 一个字都不改**（红线：不改变现有对外契约）。`/health` 继续返回 `{"code":0,...,"data":{"status":"UP"}}`，定位为 liveness（进程活着），不查库。
- 响应头固定 `Cache-Control: no-store`、`Pragma: no-cache`。

### 2.2 状态码与响应结构

**本接口不走 `Result` 包装**（冻结决定）：探针的语义载体是 HTTP 状态码，把 503 塞进 `{"code":0}` 会让所有编排器与监控误判。这是新增接口，不违反「不改变现有对外契约」。

成功 `HTTP 200`：

```json
{
  "status": "ready",
  "degraded": false,
  "service": "capability-service",
  "checked_at": "2026-11-02 16:40:07",
  "reason": null,
  "checks": [
    {"name": "db", "kind": "hard", "status": "up", "latency_ms": 3},
    {"name": "user-service", "kind": "soft", "status": "up", "latency_ms": 11}
  ]
}
```

失败 `HTTP 503`：

```json
{
  "status": "not_ready",
  "degraded": false,
  "service": "capability-service",
  "checked_at": "2026-11-02 16:40:07",
  "reason": "db_unavailable",
  "checks": [
    {"name": "db", "kind": "hard", "status": "down", "latency_ms": 0, "detail": "OperationalError"},
    {"name": "user-service", "kind": "soft", "status": "up", "latency_ms": 11}
  ]
}
```

字段级约束（冻结）：

| 字段 | 取值 | 约束 |
|---|---|---|
| `status` | `"ready"` / `"not_ready"` | 由 hard 检查全通过决定，**仅**两种 |
| `degraded` | `bool` | 任一 soft 检查 `down` 为 `true`；**不影响** `status` 与 HTTP 码 |
| `service` | `settings.service_name` | 固定字符串 |
| `checked_at` | `YYYY-MM-DD HH:MM:SS` | 契约第 0 节格式，非 ISO-T |
| `reason` | 原因码或 `null` | ready 时恒为 `null`；not_ready 时取**第一个 hard 失败项**按 `checks` 顺序 |
| `checks[].name` | `db` / `user-service` / `capability-service` | 依赖名即 Nacos 服务名，`db` 用小写保留字 |
| `checks[].kind` | `hard` / `soft` | hard 决定状态码，soft 只报告 |
| `checks[].status` | `up` / `down` | 不设 `skipped`（所有检查每次都跑） |
| `checks[].latency_ms` | `int` | 实际耗时（含超时后的实际等待），不裁剪 |
| `checks[].detail` | `str`，可选 | **只允许**异常类名，形式 `"OperationalError"` 或 `"OperationalError:(2006)"`；**禁止** `str(exc)`（可能含 host/user/password） |

### 2.3 原因码枚举（冻结，3 个）

| 原因码 | 触发条件 | 对应动作 |
|---|---|---|
| `db_unavailable` | DB 连接/查询失败：`OperationalError`、`InterfaceError`、`(2006) server has gone away`、`(1045) Access denied`、连接被拒 | 按 runbook「DB 不可用」处置 |
| `db_timeout` | 检查在 `READINESS_TIMEOUT_SECONDS` 内未返回（`asyncio.TimeoutError`） | 查连接池/慢查询；重点看 `pro_db_pool_checkout_seconds` |
| `config_invalid` | ai-chat：`USE_MOCK=false` 且（`MODEL_BASE_URL` 为空 或 `MODEL_API_KEY` 为空/仍为 `replace-me`）；其余服务不会产生此码 | 补环境变量后重启 |

只有这 3 个。soft 依赖失败**不产生原因码**（只置 `degraded`）。新增原因码必须改本节与 `docs/api-contract/*.md`。

### 2.4 各服务检查哪些依赖

| 服务 | hard 检查 | soft 检查 | 依据 |
|---|---|---|---|
| user-service | `db`：`SELECT 1` | 无 | 无下游服务依赖 |
| capability-service | `db`：`SELECT 1` | `user-service`：`GET {base}/health` 期望 HTTP 200 且 `code==0` | 授权是运营写/读的前置，但市场读取不依赖它 |
| billing-service | `db`：`SELECT 1` | `user-service`：同上 | 扣分依赖 user，但明细查询不依赖 |
| ai-chat-service | `db`：`SELECT 1`；`config`：`config_invalid` 判定 | `capability-service`：`GET /health` | 目录查询失败会走降级，不应让整个服务下线；`billing` 不作检查（记账失败在调用结束后才发生，检查它会导致 chat 整体不可用） |

**hard/soft 的划分原则（冻结，供后续 review）**：只有「缺失即无法提供任何请求」的依赖算 hard。user-service 挂掉时 capability 的市场读取仍可用，若判 hard，则一次下游故障会把上游全部摘流量，故障放大。这条取舍写进 runbook。

### 2.5 超时策略

| 配置项 | 默认 | 约束 | 作用 |
|---|---|---|---|
| `READINESS_TIMEOUT_SECONDS` | `2.0` | `gt=0, le=10` | **单项**检查超时上限 |
| `READINESS_TOTAL_TIMEOUT_SECONDS` | `3.0` | `gt=0, le=15` | 整个 handler 的超时上限；到点直接返回 503 + 已完成项的现状 |
| `INTERNAL_CALL_TIMEOUT`（复用既有） | `10.0` | — | soft 检查不用它，改用上面两项（10 秒远超探针周期） |

- 所有检查**并发**执行（`asyncio.gather`），不是串行，避免 2 个 soft + 1 个 hard 叠加到 6 秒。
- 超时的检查项 `status="down"`、`latency_ms` 记录真实等待值。
- 探针周期定为 10 秒、`timeoutSeconds` 3、`failureThreshold` 3（写进 runbook；本批不改编排文件，因为批 6 的 compose 才引入探针）。

### 2.6 「停 MySQL 变 503 / 恢复自动 200」如何保证（不得缓存状态）

六条实现约束，缺一条都可能出现"状态粘住"：

1. **每次请求都真查一次库**：`SELECT 1`，用 `SessionLocal()` 新建会话，`finally` 里 `close()`。不复用任何单例会话。
2. **禁止缓存健康结果**：不得用 `@lru_cache`、模块级变量、`functools.cache`、Redis 记住上一次结论。查询接口的 `get_settings()` 用 `lru_cache` 是配置缓存，**不得**沿用到健康检查。
3. **禁止缓存 HTTP 响应**：响应头 `Cache-Control: no-store`，否则反向代理/浏览器会把 503 或 200 粘住。
4. **保留 `pool_pre_ping=True`**（四服务 `db/session.py` 已启用，B2 不得移除）：MySQL 重启后池中死连接在 checkout 时被预检丢弃并重建，因此恢复后**第一次**探测就能 200，不需要等 `pool_recycle`（1800 秒）。
5. **失败时不 `engine.dispose()`**：`dispose()` 会销毁全池，探针失败本来只是"这一条连接坏了"，dispose 会把正常流量也打断，且在 MySQL 短暂抖动时造成重连风暴。依赖 `pool_pre_ping` 逐条淘汰即可。
6. **只在状态变化时打日志**：进程内保留「上次结论」**仅用于日志去重**，不得参与响应计算。代码里必须能一眼看出这个变量不参与返回（变量名 `_last_logged_status`，并在注释中声明）。

失败→恢复的因果链（写清，避免"为什么恢复后还是 503"的排查时间）：
停掉 MySQL → 池中连接检查时 `pool_pre_ping` 发 `SELECT 1` 收到 `(2013) Lost connection` → 丢弃并尝试新建 → 连接被拒 → `OperationalError` → 503 `db_unavailable`。
MySQL 恢复 → 新建连接成功 → `SELECT 1` 返回 1 → 200 `ready`。**无任何缓存介入**，一次探测周期内翻转。

### 2.7 实现骨架（四服务照抄，只改依赖清单）

```python
# app/core/health.py
import asyncio, time
from datetime import datetime
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

async def check_db(timeout: float) -> dict:
    started = time.perf_counter()
    def _probe() -> None:
        session = SessionLocal()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
    try:
        await asyncio.wait_for(run_in_threadpool(_probe), timeout=timeout)
    except asyncio.TimeoutError:
        return {"name": "db", "kind": "hard", "status": "down",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "detail": "TimeoutError", "_reason": "db_timeout"}
    except Exception as exc:                      # 只取类名与 errno，禁止 str(exc)
        return {"name": "db", "kind": "hard", "status": "down",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "detail": _safe_detail(exc), "_reason": "db_unavailable"}
    return {"name": "db", "kind": "hard", "status": "up",
            "latency_ms": int((time.perf_counter() - started) * 1000)}
```

`_safe_detail(exc)` 返回 `type(exc).__name__` + 可选 `:(errno)`（从 `exc.orig.args[0]` 取 int）。**同步 DB 调用必须走 `run_in_threadpool`**，否则一次慢查询会阻塞整个 worker 的 event loop，把探针变成故障源。

### 2.8 验收断言（可执行）

| # | 断言 | 手段 |
|---|---|---|
| B2-1 | 正常态 4 个服务 `/health/ready` 均 HTTP 200、`status=="ready"`、`reason is None` | pytest |
| B2-2 | `Session.execute` 被 monkeypatch 抛 `OperationalError` → HTTP 503、`reason=="db_unavailable"`、`detail` 不含连接串 | pytest |
| B2-3 | 探测超时（patch 让探针 `sleep` 超过 timeout）→ HTTP 503、`reason=="db_timeout"` | pytest |
| B2-4 | 同一进程内先失败后成功，两次响应不同（证明无缓存） | pytest，连续两次 `TestClient` 调用，第二次换掉 patch |
| B2-5 | 响应头含 `Cache-Control: no-store` | pytest |
| B2-6 | soft 依赖失败 → HTTP 200、`status=="ready"`、`degraded is True` | pytest（patch user-service `/health` 抛异常） |
| B2-7 | 真实停 MySQL：`net stop mysql` 后 503，启动后 ≤10 秒回到 200 | 手工，写进 `docs/升级实施日志.md` 证据 |
| B2-8 | `/{svc}/health/ready` 经网关可达且注入 `X-Request-Id` | 网关 JUnit |
| B2-9 | `/ping` 与 `/health` 响应体逐字段与批 1 基线一致（零回归） | pytest 快照断言 |

---

## 3. B3 Prometheus 指标

### 3.1 端点、鉴权与暴露面

```
GET /internal/metrics     四个服务各一份，Content-Type: text/plain; version=0.0.4; charset=utf-8
```

**冻结决定：路径必须带 `internal` 段。** 原因：`gateway/src/main/java/.../security/InternalPaths.java` + `AuthGlobalFilter` 已实现「任意层级出现 `internal` 段即 403」，因此**网关零改动**就能保证 `/metrics` 不被外部访问，也不依赖运维记得"别反代它"。Nginx 只反代 `/api/`，同样覆盖。

- **鉴权：无。** 直连服务端口即可抓取；不引入 token，避免 Prometheus 配置里出现凭据（红线：密钥不出服务）。
- 抓取地址：`http://127.0.0.1:8081/internal/metrics`（user）、`:8082`（capability）、`:8083`（billing）、`:8090`（ai-chat）。
- 交付证据：`/{service-name}/internal/metrics` 经网关必须 **403 + `code=1001`**，进网关 JUnit。

### 3.2 指标清单（名称、类型、label、bucket 全部冻结）

指标名前缀统一 `pro_`（项目名，短、不与 client 默认指标冲突）。

| # | 指标名 | 类型 | label 集 | 埋点位置 |
|---|---|---|---|---|
| 1 | `pro_http_requests_total` | Counter | `service, route, method, status, code` | HTTP 中间件（四服务） |
| 2 | `pro_http_request_duration_seconds` | Histogram | `service, route, method` | 同上 |
| 3 | `pro_model_calls_total` | Counter | `service, model, provider, status` | `ai-chat-service` `ModelClient.complete` |
| 4 | `pro_model_call_duration_seconds` | Histogram | `service, model, provider` | 同上 |
| 5 | `pro_model_errors_total` | Counter | `service, model, provider, error_code` | 同上，仅错误时 +1 |
| 6 | `pro_points_deduct_total` | Counter | `service, result` | `user-service` `PointsService.deduct` |
| 7 | `pro_capability_query_total` | Counter | `service, result` | `ai-chat-service` 目录查询调用点 |
| 8 | `pro_db_pool_checkout_seconds` | Histogram | `service` | `db/session.py` 池事件（四服务） |
| 9 | `pro_service_call_total` | Counter | `service, target, method, result` | `call_internal` 封装（四服务） |

bucket（冻结，写在 `app/core/metrics.py` 常量里，四个进程必须完全一致）：

```python
HTTP_BUCKETS   = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
MODEL_BUCKETS  = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0)
POOL_BUCKETS   = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
```

选择依据（写清，避免后续"再调一下 bucket"）：

- HTTP：`0.005` 下限覆盖内部接口与网关转发；`5/10/30/60` 覆盖 chat 同步调用（模型 3–10 秒），否则 p95 全落在 `+Inf`，压测报告算不出拐点。
- 模型：下限 `0.1`（本地 mock 会更快，快于 0.1 无区分价值）；上限 `120` 覆盖 provider 级 60 秒超时（D3 文生图）。
- 池：`0.001` 起，因为正常 checkout 是微秒级；`30` 上限对齐 `DB_POOL_TIMEOUT` 默认 30 秒（超出即报错，不会更长）。

label 取值枚举（冻结）：

| label | 取值 |
|---|---|
| `service` | `settings.service_name`，四值之一：`user-service` / `capability-service` / `billing-service` / `ai-chat-service` |
| `route` | FastAPI 路由模板（`request.scope["route"].path`），如 `/api/capability/{capability_id}`；未匹配任何路由记 `"<unmatched>"` |
| `method` | 大写的 HTTP 方法 |
| `status` | HTTP 状态码字符串，如 `"200"` / `"503"` |
| `code` | 平台业务码字符串，如 `"0"` / `"2007"`；响应无业务码时 `"-"` |
| `model` | 见 §3.3 折叠规则 |
| `provider` | 本批恒为 `"default"`（§3.4） |
| `status`（模型） | `success` / `degraded` / `failed` |
| `error_code` | `"5001"`–`"5005"` |
| `result`（扣分） | `success` / `duplicated` / `insufficient` / `unavailable` / `rejected` / `error` |
| `result`（目录） | `success` / `not_found` / `config_invalid` / `unavailable` |
| `target` | 被调服务名（`user-service` / `capability-service` / `billing-service`） |
| `result`（内部调用） | `success` / `biz_error` / `unavailable` / `timeout` |

`pro_capability_query_total` 的映射（按调用点判定，不按错误码猜——`4002` 同时表示"网络不可用"和"目录配置异常"）：

| 结果 | 判定 |
|---|---|
| `success` | 拿到合法 `CapabilityInternalOut` |
| `not_found` | 下游返回 `2002` |
| `config_invalid` | 下游返回 `4002` 且消息为「能力目录配置不完整或价格无效」 |
| `unavailable` | 其余 `4002`、超时、DNS/Nacos 发现失败、非法 JSON |

### 3.3 高基数防护（硬规则，加 label 前必读）

**绝对禁止进 label**：`request_id`、`user_id`、`capability_id`、`session_id`、`api_key`/`access_key`、`base_url`/`host`、真实 URI（`request.url.path`）、`operator_id`、任何用户输入的自由文本。

**`route` 必须模板化**：从 `request.scope.get("route")` 取 `.path`；不得用 `request.url.path`。若不模板化，`/api/capability/1234` 与 `/api/capability/5678` 会产生两条时间序列，1000 个能力就是 1000 倍膨胀。

**`model` 折叠**：`model` 来自上游请求，值是用户可控的字符串（OpenAI 兼容层客户端可随便填）。规则：

1. 值 ∈ 已知集合（`settings.model_name` ∪ 能力目录登记的模型名）→ 原样；
2. `USE_MOCK=true` → `"mock"`；
3. 其余 → `"other"`。

集合大小上限 20；超出部分一律折叠为 `other`。批 3 引入 `t_model_provider` 后，已知集合改由 provider 表提供，label 名不变。

**`route` 与 `status`/`code` 的组合上限**：路由数 ≈ 40，状态码 ≈ 8，业务码 ≈ 20，理论最大 6400 条序列，可接受。若将来超过 5 万条，改用 exemplar 或抽样，不得删 label。

### 3.4 provider 占位口径（本批无 provider 表）

本批的"上游"是唯一一份全局配置（`MODEL_BASE_URL` / `MODEL_API_KEY` / `MODEL_NAME`），没有 provider 维度。冻结做法：

1. 新增配置 `MODEL_PROVIDER_ALIAS`，默认 `"default"`，只作为 label 值来源，**不参与任何业务逻辑**；
2. `provider` label 恒为 `settings.model_provider_alias`；
3. `model` label 取 `settings.model_name`（覆盖 §3.3 规则 1 的退化情形）；
4. 批 3（D1）落地后：`provider` 改读 `t_model_provider.name`，`model` 改读 `provider.default_model`。**指标名、label 名、bucket 全部不变**，只改取值来源 → 看板与 PromQL 不用改。

**上游错误率口径（本批即可用，批 3 自动按 provider 拆分）**：

```promql
# 按 provider 的上游错误率（5 分钟窗口）
sum by (service, provider) (rate(pro_model_errors_total[5m]))
/
clamp_min(sum by (service, provider) (rate(pro_model_calls_total[5m])), 1e-9)
```

分母用 `pro_model_calls_total`（含成功），分子用 `pro_model_errors_total`（只含 `5001`–`5005`）。本批 `provider` 只有一个取值，因此等价于全局错误率；这个口径的**唯一**假设是「每个进程都在打点」，批 3 不需要重写查询。

`degraded` 不计入错误率分母扣减：降级调用计入 `pro_model_calls_total{status="degraded"}`，其 `error_code` 同时进 `pro_model_errors_total`，因此降级率与错误率可从同一组指标分别算出。

### 3.5 连接池 checkout 等待怎么采

用 SQLAlchemy 的 `checkout` 事件 + `ContextVar` 记起点。`checkout` 事件在**拿到连接之后**才触发，事件本身不提供等待时长，所以必须在请求进入时埋一个起点。

```python
# app/core/metrics.py
from contextvars import ContextVar
from sqlalchemy import event
from sqlalchemy.engine import Engine

_pool_wait_start: ContextVar[float | None] = ContextVar("pool_wait_start", default=None)

DB_POOL_CHECKOUT_SECONDS = Histogram(
    "pro_db_pool_checkout_seconds",
    "Time a request waited to obtain a DB connection from the pool",
    ["service"], buckets=POOL_BUCKETS,
)

def mark_pool_wait_start() -> None:
    _pool_wait_start.set(time.perf_counter())

def bind_pool_metrics(engine: Engine) -> None:
    @event.listens_for(engine, "checkout")
    def _on_checkout(dbapi_connection, connection_record, connection_proxy):  # noqa: ANN001
        started = _pool_wait_start.get()
        if started is None:            # 本次请求已记过一次，或不是请求线程
            return
        DB_POOL_CHECKOUT_SECONDS.labels(service=SERVICE).observe(
            time.perf_counter() - started
        )
        _pool_wait_start.set(None)     # 每次请求只记第一次 checkout
```

```python
# app/db/session.py
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    mark_pool_wait_start()    # Session 是惰性的，第一次 execute 才 checkout
    try:
        yield db
    finally:
        db.close()

bind_pool_metrics(engine)     # 模块导入时注册一次
```

冻结语义：**观测值 = 从 `get_db()` 进入，到本次请求首次 checkout 完成**，包含 `pool_pre_ping` 的预检耗时（预检正是池压力的来源之一，必须计入）。一次请求内后续的 checkout（如 A1 的"新事务写助手消息"）不再重复计时，避免把正常的多事务请求算成高等待。

`pool_timeout` 超时（`TimeoutError: QueuePool limit ...`）不会触发 `checkout` 事件，因此**不会**出现在这个直方图里；它由 `pro_http_requests_total{status="500"}` + 日志 `TimeoutError` 体现。这条已知边界写进 runbook。

### 3.6 业务码如何进 `code` label

中间件拿不到响应体的 `code`（解析 body 代价高且会破坏流式响应）。冻结做法：用 `ContextVar` 由 `Result.ok/fail` 写值，中间件读值。

```python
# app/core/result.py 追加（四个服务一致）
from app.core.metrics import set_result_code

class Result(BaseModel):
    @classmethod
    def ok(cls, data=None, message="success", request_id=""):
        set_result_code(0)
        return cls(code=0, message=message, data=data, request_id=request_id)

    @classmethod
    def fail(cls, code: int, message: str, request_id=""):
        set_result_code(code)
        return cls(code=code, message=message, data=None, request_id=request_id)
```

```python
# app/core/metrics.py
_result_code: ContextVar[str] = ContextVar("result_code", default="-")

def set_result_code(code: int) -> None:
    _result_code.set(str(code))

def reset_result_code() -> None:
    _result_code.set("-")
```

中间件在请求入口 `reset_result_code()`，出口读 `_result_code.get()`。**兜底 `"-"`**：网关 401/403、`/v1/**` 流式响应、未捕获异常、静态路径都没有 `Result`，记 `-` 是对的，不要伪造 0。

**成立前提（不可破坏）**：业务处理函数必须是 `async def`。`ContextVar` 的写入只在同一个 task 的上下文内可见；四个服务现有 endpoint 全是 `async def`（`get_db` 是同步生成器，但由 FastAPI 在事件循环内驱动），因此可读。若将来有人把某个 endpoint 改成同步 `def`（FastAPI 会丢到 `run_in_threadpool`），该请求的 `code` 会退化成 `"-"`——这是可接受的降级，**不得**为了修它去解析响应体。

**中间件注册顺序（必须照做）**：`register_metrics(app)` 必须在 `register_request_logging(app)` **之后**调用。Starlette 的 `add_middleware` 把新中间件插到最外层，后注册者最先执行、最后退出——只有这样才能统计到 401/403/422 与异常处理器产出的响应。

中间件本体约束：

- 全 `try/except/finally`，打点异常**不得**影响请求（`except Exception: logger.warning(...)` 后继续）；
- 统计 `pro_http_requests_total` 与 `pro_http_request_duration_seconds` 时 `service` 恒定、`route` 取模板、`status` 取真实响应码；
- 流式响应（`/v1/chat/completions` SSE）在中间件里按「响应头已发出」计时，不等待流结束（否则 SSE 会把 duration 拉到分钟级，污染 p95）。规则：`status` 仍记 200，duration 记首字节时间。这条要在契约文档里写明，避免后人以为指标漏统计。

### 3.7 多 worker 与 multiprocess

A2 已把 `UVICORN_WORKERS` 参数化（生产 4）。多进程下各进程独立 `REGISTRY`，直接抓取会只看到一个 worker 的数据。

冻结方案：**prometheus_client 的 multiprocess 模式**。

```python
# app/core/metrics.py
import os
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest, multiprocess

def render_metrics() -> bytes:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest(REGISTRY)
```

启动层约定：

- `UVICORN_WORKERS > 1` 时，启动脚本必须设 `PROMETHEUS_MULTIPROC_DIR=<repo>/artifacts/prom/<service>`，并在**启动前清空该目录**（残留 mmap 文件会产出过期序列）；
- `UVICORN_WORKERS == 1` 时不设该变量，走默认 registry（本机开发、测试、批 2 门禁都是这条路径）；
- 该环境变量必须在进程启动时设置（`prometheus_client` 在模块导入期读它），**不允许**运行时改；
- `artifacts/` 已在 `.gitignore`，不会误提交。

已知限制（写进契约文档）：multiprocess 模式下 `Histogram` 的 `_created` 语义与单进程不同，`rate()` 计算不受影响；`Counter` 的 `_total` 后缀正常。

### 3.8 关键 PromQL（交付给 runbook 与压测报告）

```promql
# 接口 p95（按路由）
histogram_quantile(0.95, sum by (le, route) (rate(pro_http_request_duration_seconds_bucket[5m])))

# 错误率（业务码非 0 的占比）
sum(rate(pro_http_requests_total{code!="0",code!="-"}[5m])) / sum(rate(pro_http_requests_total[5m]))

# 扣分失败率
sum(rate(pro_points_deduct_total{result=~"insufficient|unavailable|error"}[5m]))
/ clamp_min(sum(rate(pro_points_deduct_total[5m])), 1e-9)

# 目录查询失败率
sum(rate(pro_capability_query_total{result!="success"}[5m])) / clamp_min(sum(rate(pro_capability_query_total[5m])), 1e-9)

# 池等待 p95（连接池是否成为瓶颈）
histogram_quantile(0.95, sum by (le, service) (rate(pro_db_pool_checkout_seconds_bucket[5m])))

# 模型调用 p95（按模型）
histogram_quantile(0.95, sum by (le, model) (rate(pro_model_call_duration_seconds_bucket[5m])))

# 上游错误率（按 provider）——见 §3.4
```

### 3.9 验收断言（可执行）

| # | 断言 | 手段 |
|---|---|---|
| B3-1 | 四服务 `GET /internal/metrics` HTTP 200 且 body 含全部 9 个指标名 | pytest |
| B3-2 | 发一次业务请求后，`pro_http_requests_total` 出现 `route="/api/capability/{capability_id}"`（模板）而非 `/api/capability/2` | pytest，断言 body 中不含 `"/api/capability/2{"` |
| B3-3 | 业务失败请求的 `code` label 为真实业务码（如 `"2007"`），不是 `"0"` 也不是 `"-"` | pytest |
| B3-4 | 无 `Result` 的响应（404）`code="-"`、`route="<unmatched>"` | pytest |
| B3-5 | `pro_points_deduct_total{result="insufficient"}` 在 3001 场景 +1 | pytest（user） |
| B3-6 | `pro_capability_query_total{result="unavailable"}` 在 Nacos 发现失败场景 +1 | pytest（ai-chat） |
| B3-7 | `pro_db_pool_checkout_seconds_count` 随请求增长，且 `_bucket{le="0.001"}` 有值 | pytest |
| B3-8 | `/{svc}/internal/metrics` 经网关 403 + `code=1001` | 网关 JUnit |
| B3-9 | 压测时能采到 `pro_http_request_duration_seconds` 的 p95 并写进报告（A5 引用） | 手工，证据进实施日志 |

---

## 4. B4 自动对账

### 4.1 落点决策：独立运维脚本 + `billing_db` 两张结果表

**决策：`scripts/reconcile_billing.py` 独立脚本，双只读连接分别读 `billing_db` 与 `user_db`，差异结果写回 `billing_db` 的 `t_reconcile_run` / `t_reconcile_diff`。**

理由：

1. **服务不许跨库**：`contract_lint.py` 会扫 `services/*/app/**/*.py`。若把对账放进 billing-service，它必须读 `user_db` → 门禁直接红；若放进 user-service 则必须读 `billing_db` → 同样红。`scripts/` 不在扫描范围内，脚本不是服务，不受该约束。
2. **对账是运维动作，不是业务链路**：它不参与任何请求，不能因为对账慢/挂而影响记账。放在服务内会引入一个能拖慢主库的定时任务。
3. **为什么结果落 `billing_db` 而不是 `user_db`**：`t_call_record` 是账本主档（收入的凭据），差异是账本的衍生结论，跟账本同库便于 DBA 一次备份一致；`user_db` 是余额的权威，不能被运维结论污染。
4. **不落 `ai_chat_db` / 新库**：新增第 5 个库要改 compose、备份脚本、运维文档，收益为零。

**被否决的方案**

| 方案 | 否决原因 |
|---|---|
| billing-service 提供 `/internal/billing/reconcile` 接口 | 服务内需读两个库，违反边界 lint；且对账耗时（全窗口扫描）会占满服务连接池 |
| user-service 提供接口 | 同上，方向相反 |
| 纯内存/纯文件、不落库 | 无法实现「连跑两次不重复告警」的持久幂等（进程退出即丢状态） |
| 用 MySQL `FEDERATED` 引擎跨库 join | 需改 MySQL 配置并引入跨库耦合，且 `contract_lint` 之外新增了运维复杂度；窗口扫描量小，Python 比对足够 |

**脚本红线**：只对 `t_reconcile_run` / `t_reconcile_diff` 两张表有 INSERT/UPDATE 权限；对 `t_call_record` / `t_points_log` **只 SELECT**。脚本内不得出现 `UPDATE t_call_record`、`DELETE`、`INSERT INTO t_points_log` 等语句；review 时以 grep 断言。

### 4.2 DDL 全文（`services/billing-service/sql/04_add_reconcile_tables.sql`）

```sql
SET NAMES utf8mb4;
-- billing-service 增量迁移（B4 自动对账）。
-- 只建新表，不动既有表与数据；重复执行安全。由 scripts/reconcile_billing.py 写入。
USE billing_db;

-- 每次对账运行一行，用于「连跑两次」的幂等判定与报告溯源。
CREATE TABLE IF NOT EXISTS t_reconcile_run (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  run_id VARCHAR(32) NOT NULL COMMENT '运行标识 run-YYYYMMDDTHHMMSSZ（UTC）',
  window_start DATETIME NOT NULL COMMENT '扫描窗口起（含）',
  window_end DATETIME NOT NULL COMMENT '扫描窗口止（不含）',
  billing_scanned BIGINT NOT NULL DEFAULT 0 COMMENT '扫描的账单行数',
  points_scanned BIGINT NOT NULL DEFAULT 0 COMMENT '扫描的流水行数',
  new_count INT NOT NULL DEFAULT 0 COMMENT '本次新增差异数（= 告警数）',
  open_count INT NOT NULL DEFAULT 0 COMMENT '本次仍存在（含历史）差异数',
  resolved_count INT NOT NULL DEFAULT 0 COMMENT '本次标记为已消失的差异数',
  status VARCHAR(16) NOT NULL DEFAULT 'success' COMMENT 'success成功 failed执行失败',
  detail VARCHAR(255) NOT NULL DEFAULT '' COMMENT '失败原因摘要，不含连接串',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_reconcile_run (run_id),
  KEY idx_reconcile_run_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对账运行记录';

-- 差异明细：diff_key 唯一，保证同一条差异只占一行，重跑只累加 occurrences。
CREATE TABLE IF NOT EXISTS t_reconcile_diff (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  diff_key CHAR(64) NOT NULL COMMENT 'sha256(category|request_id)，差异的稳定指纹',
  category VARCHAR(32) NOT NULL COMMENT 'missing_points_log/missing_call_record/field_mismatch',
  request_id VARCHAR(64) NOT NULL COMMENT '差异定位键，全链路 requestId',
  user_id BIGINT NOT NULL DEFAULT 0 COMMENT '账单侧 user_id，缺失时取流水侧',
  billing_cost BIGINT NULL COMMENT '账单侧 cost，缺失为 NULL',
  billing_status VARCHAR(16) NULL COMMENT '账单侧 call_status，缺失为 NULL',
  points_amount BIGINT NULL COMMENT '流水侧 amount，缺失为 NULL',
  points_user_id BIGINT NULL COMMENT '流水侧 user_id，缺失为 NULL',
  detail_json JSON NULL COMMENT '两侧完整字段快照（已脱敏，不含任何正文）',
  first_seen_run VARCHAR(32) NOT NULL COMMENT '首次检出本次差异的 run_id',
  last_seen_run VARCHAR(32) NOT NULL COMMENT '最近一次检出该差异的 run_id',
  first_seen_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次检出时间',
  last_seen_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最近检出时间',
  occurrences INT NOT NULL DEFAULT 1 COMMENT '累计检出次数（重跑只增不重报）',
  status VARCHAR(16) NOT NULL DEFAULT 'open' COMMENT 'open仍有差异/resolved已消失',
  resolved_run VARCHAR(32) NOT NULL DEFAULT '' COMMENT '标记 resolved 的 run_id',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_reconcile_diff_key (diff_key),
  KEY idx_reconcile_diff_status (status, last_seen_run),
  KEY idx_reconcile_diff_request (request_id),
  KEY idx_reconcile_diff_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对账差异明细';
```

`update_time ON UPDATE` 在这两张表上是**正确的**：它们不是审计表，状态机需要 `last_seen_time`/`status` 变更。这与 §1.2 的「审计表不设 update_time」不矛盾，不要互相类推。

### 4.3 三类差异的判定口径与 SQL 片段

前置约定：

- **时区**：两侧 `create_time` 都由同一个 MySQL 实例的 `CURRENT_TIMESTAMP` 生成，同为库本地时区，可直接比较。脚本以 `DATETIME` 字符串传参，不做时区换算。
- **窗口**：默认最近 7 天，**向前多取 1 天作为重叠区**（`start = now - 8d`, `end = now`）。重叠区用于兜住「账单晚到 1 天」（A1 之后账单在第二个事务里落库，极端情况下跨零点）。重复扫描的重复差异由 `diff_key` 唯一键吸收，不会重复告警。
- **分页**：按 `id` 游标分页（`id > :last_id ORDER BY id LIMIT 5000`），不用 `OFFSET`（深翻页会慢）。单次 run 扫描行数上限 `RECON_MAX_ROWS`（默认 200000），超限则截断并在报告里 `truncated: true`。

#### 4.3.1 账单侧候选集（billing_db，只读）

```sql
SELECT id, request_id, user_id, cost, call_status, create_time
FROM t_call_record
WHERE is_deleted = 0
  AND cost > 0
  AND id > :last_id
  AND create_time >= :window_start
  AND create_time <  :window_end
ORDER BY id
LIMIT :limit;
```

**必须 `cost > 0`**：降级与失败调用按契约 `cost=0` 且不产生 `t_points_log` 行，把它们纳入候选会把每次降级都误报成「有账单无流水」。不加 `call_status='success'` 过滤是**故意**的：若某条 `degraded`/`failed` 记录 `cost>0`，它确实违反了「降级不计费」，应该被检出为差异（`detail_json` 里带 `call_status` 供人判断）。

#### 4.3.2 流水侧候选集（user_db，只读）

```sql
SELECT id, request_id, user_id, amount, direction, biz_type, balance_after, create_time
FROM t_points_log
WHERE is_deleted = 0
  AND direction = 'out'
  AND biz_type = 'call'
  AND id > :last_id
  AND create_time >= :window_start
  AND create_time <  :window_end
ORDER BY id
LIMIT :limit;
```

**必须限定 `biz_type='call'`**：`register` 是注册赠送（`in`，无账单），`admin_adjust` 是批 5 手工调分（无账单），纳入会产生规律性误报。

#### 4.3.3 三类差异判定（Python 内必对，不跨库 join）

两侧各拉成 `dict[request_id] = row`，然后：

| # | `category` | 判定 | `detail_json` 内容 |
|---|---|---|---|
| 1 | `missing_points_log` | `request_id ∈ billing` 且 `request_id ∉ points` | `{"billing": {cost, call_status, user_id, create_time}}` |
| 2 | `missing_call_record` | `request_id ∈ points` 且 `request_id ∉ billing` | `{"points": {amount, user_id, balance_after, create_time}}` |
| 3 | `field_mismatch` | 两侧都有，且 `billing.cost != points.amount` **或** `billing.user_id != points.user_id` | `{"billing": {...}, "points": {...}, "diff_fields": ["cost","user_id"]}` |

- `request_id` 为空串的行**跳过**：`t_call_record.request_id` 非空约束已存在，`t_points_log.request_id` 同理；空串代表落库缺陷，由唯一索引拦截，不在这里重复处理。
- 同一 `request_id` 在记账侧理论上唯一（`uk_call_record_request`），若出现重复（历史脏数据），取 `id` 最小的那条并额外记 `duplicate_in_billing: true`，不新建差异类别（避免类别爆炸）。
- `field_mismatch` 第三类即需求里的「requestId 不一致」：语义是「同一个 requestId 两侧数据对不上」。真正的「requestId 不同」在结构上表现为前两类（一边找不到另一边），无需第四类。

#### 4.3.4 幂等去重（连跑两次不重复告警）

`diff_key = sha256(f"{category}|{request_id}")`，十六进制小写，`CHAR(64)`。

写入用 `INSERT ... ON DUPLICATE KEY UPDATE`，并靠受影响行数区分「新增」与「已存在」：

```sql
INSERT INTO t_reconcile_diff
  (diff_key, category, request_id, user_id, billing_cost, billing_status,
   points_amount, points_user_id, detail_json,
   first_seen_run, last_seen_run, first_seen_time, last_seen_time, occurrences, status)
VALUES
  (:diff_key, :category, :request_id, :user_id, :billing_cost, :billing_status,
   :points_amount, :points_user_id, :detail_json,
   :run_id, :run_id, NOW(), NOW(), 1, 'open')
ON DUPLICATE KEY UPDATE
  last_seen_run   = VALUES(last_seen_run),
  last_seen_time  = NOW(),
  occurrences     = occurrences + 1,
  billing_cost    = VALUES(billing_cost),
  billing_status  = VALUES(billing_status),
  points_amount   = VALUES(points_amount),
  points_user_id  = VALUES(points_user_id),
  detail_json     = VALUES(detail_json),
  status          = 'open',
  resolved_run    = '';
```

判定规则（冻结）：

- `cursor.rowcount == 1` → **本次新增** → 计入 `new_count`，进入告警输出；
- `cursor.rowcount >= 2` → 已存在 → **不告警**，只累加 `occurrences` 与刷新 `last_seen_*`；
- 本次扫描窗口内未再出现的 `status='open'` 行（`last_seen_run != :run_id`）→ 置 `resolved`：
  ```sql
  UPDATE t_reconcile_diff SET status = 'resolved', resolved_run = :run_id
  WHERE status = 'open' AND last_seen_run <> :run_id
    AND category IN (:scanned_categories);
  ```
  计入 `resolved_count`。
- 因此**第二次运行同一窗口：`new_count == 0`** —— 这正是验收条件「连跑两次不重复报警」的客观判定式。

**置 `resolved` 的两个前提条件（缺一不可，否则会误关差异）**：

1. `AND category IN (:scanned_categories)`：用了 `--category` 时只关本次实际扫描的类别。不加这一条，`--category missing_points_log` 会把其它两类的 open 差异全部误标为 resolved。
2. **本次运行未截断**（`truncated == false`）。命中 `--max-rows` 上限说明没扫全，此时**整轮跳过 resolve**（`resolved_count` 记 0，报告里 `resolve_skipped: "truncated"`），否则窗口尾部的真实差异会被误判为"已消失"。

`field_mismatch` 的金额从 8 变成 9 时，`diff_key` 不变（只含 category+request_id），行为"刷新 detail_json、occurrences+1、不再告警"。这是有意选择：同一条业务差异的数值变化不应产生新告警，否则每次修数都会重新刷屏。

### 4.4 输出格式

#### 4.4.1 stdout（人读）

```
[reconcile] run=run-20261102T164000Z window=2026-10-25 16:40:00 ~ 2026-11-02 16:40:00
[reconcile] scanned billing=1832 points=1830
[reconcile] diffs: new=1 open=3 resolved=2

NEW  missing_points_log  request_id=7f3a…  user_id=12  billing_cost=5 status=success
     first_seen=2026-11-02 16:40:00
NEW  field_mismatch      request_id=9c11…  billing_cost=5 points_amount=3
     diff_fields=cost,user_id

[reconcile] report: artifacts/reconcile/reconcile-run-20261102T164000Z.json
```

#### 4.4.2 stdout（`--json`，机器读）

```json
{
  "run_id": "run-20261102T164000Z",
  "window": {"start": "2026-10-25 16:40:00", "end": "2026-11-02 16:40:00"},
  "scanned": {"billing": 1832, "points": 1830},
  "counts": {"new": 1, "open": 3, "resolved": 2, "truncated": false, "resolve_skipped": null},
  "new_diffs": [
    {"category": "missing_points_log", "request_id": "7f3a…", "user_id": 12,
     "billing_cost": 5, "billing_status": "success", "points_amount": null}
  ],
  "status": "success"
}
```

#### 4.4.3 报告文件

路径：`artifacts/reconcile/reconcile-<run_id>.json`（`artifacts/` 已 gitignore，避免把生产差异提交进仓库）。内容 = 4.4.2 的 JSON + `open_diffs` 全量列表。

#### 4.4.4 退出码（冻结，供调度与 CI 判定）

| 退出码 | 含义 |
|---|---|
| `0` | 运行成功且**本次无新增差异**（历史未消除的差异不影响 0） |
| `2` | 运行成功且**本次有新差异**（= 需要人看的告警） |
| `1` | 运行失败（连不上库、DDL 缺失、参数非法），`status='failed'` 已落 `t_reconcile_run` |

`--dry-run` 时仍按上述返回 `0/2`，只是不写任何表、不落报告文件，stdout 输出前加 `[dry-run]`。

### 4.5 手动触发与定时触发

```bash
# 必填：两个库的连接串（脚本不读 services/*/.env，避免误连生产）
export RECON_BILLING_DB_URL="mysql+pymysql://recon_ro:***@127.0.0.1:3307/billing_db?charset=utf8mb4"
export RECON_USER_DB_URL="mysql+pymysql://recon_ro:***@127.0.0.1:3307/user_db?charset=utf8mb4"

# 默认：最近 7 天（含 1 天重叠）
python scripts/reconcile_billing.py

# 指定窗口
python scripts/reconcile_billing.py --start "2026-11-01 00:00:00" --end "2026-11-02 00:00:00"

# 只看不写（上线前演练、排查、CI）
python scripts/reconcile_billing.py --days 7 --dry-run --json

# 只报某一类
python scripts/reconcile_billing.py --days 7 --category missing_points_log
```

命令行参数（冻结）：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--days` | `7` | 与 `--start/--end` 互斥；实际窗口 `now - (days+1)d` ~ `now`（含重叠） |
| `--start` / `--end` | 无 | `YYYY-MM-DD HH:MM:SS`，`end` 不含；`start >= end` 退出码 1 |
| `--dry-run` | 关 | 不写库、不写报告 |
| `--json` | 关 | stdout 只输出 JSON |
| `--category` | 全部 | `missing_points_log` / `missing_call_record` / `field_mismatch`，其余值退出码 1 |
| `--limit` | `5000` | 单页行数 |
| `--max-rows` | `200000` | 单侧扫描上限，超限截断并置 `truncated` |

环境变量：`RECON_BILLING_DB_URL`、`RECON_USER_DB_URL`（缺失 → 退出码 1 并打印用法，**不回退**到任何 `.env`）。

**对账账号权限（写进 runbook，交付时建号）**：

```sql
-- billing_db：读账单 + 写两张结果表
GRANT SELECT ON billing_db.t_call_record TO 'recon_ro'@'%';
GRANT SELECT, INSERT, UPDATE ON billing_db.t_reconcile_run  TO 'recon_ro'@'%';
GRANT SELECT, INSERT, UPDATE ON billing_db.t_reconcile_diff TO 'recon_ro'@'%';
-- user_db：只读
GRANT SELECT ON user_db.t_points_log TO 'recon_ro'@'%';
```

定时（默认**每日 03:10**，避开业务高峰与备份窗口）：

- Linux/macOS cron：`10 3 * * * cd /opt/aicapabilityhub && /usr/bin/python3 scripts/reconcile_billing.py >> artifacts/reconcile/cron.log 2>&1`
- Windows 计划任务：`schtasks /create /tn "Pro-Reconcile" /tr "cmd /c cd /d D:\AICapabilityHubPro && python scripts\reconcile_billing.py" /sc daily /st 03:10`
- 退出码 2 时由 runbook 的「对账出现新差异」处置路径接手（看 `t_reconcile_diff` → 定位 requestId → 查账单与流水 → 人工定责，**不得自动补账**）。

### 4.6 验收断言（可执行）

| # | 断言 | 手段 |
|---|---|---|
| B4-1 | 构造一条只有账单没有流水的数据 → `category="missing_points_log"` 被检出，退出码 2 | `tests/tooling/test_reconcile.py`（双隔离库） |
| B4-2 | 构造一条只有流水没有账单的数据 → `category="missing_call_record"` 被检出 | 同上 |
| B4-3 | 构造金额不一致（账单 5 / 流水 3）→ `category="field_mismatch"`、`diff_fields=["cost"]` | 同上 |
| B4-4 | **连续跑两次**：第一次 `new_count=1`，第二次 `new_count=0` 且 `occurrences=2`、退出码 0 | 同上（核心验收） |
| B4-5 | 删除差异数据后重跑 → `status='resolved'`、`resolved_count=1` | 同上 |
| B4-6 | `--dry-run` 后两张表行数不变 | 同上 |
| B4-7 | `cost=0` 的 degraded 记录**不**被报为 `missing_points_log` | 同上 |
| B4-8 | `biz_type='register'` 的赠送流水**不**被报为 `missing_call_record` | 同上 |
| B4-9 | 脚本源码中不含 `UPDATE t_call_record` / `DELETE` / `INSERT INTO t_points_log` | 同上，读源码 grep 断言 |
| B4-10 | 缺 `RECON_*_DB_URL` → 退出码 1，且不抛 traceback 给 stdout | 同上 |
| B4-11 | `--category missing_points_log` 单类运行时，其它两类的 open 差异**不被**置 resolved | 同上 |
| B4-12 | 命中 `--max-rows`（`truncated=true`）时 `resolved_count=0`、报告含 `resolve_skipped:"truncated"` | 同上 |

---

## 5. 影响面

### 5.1 服务端 pytest（不得减少用例数）

| 服务 | 新增 | 修改（必须跟着改） |
|---|---|---|
| capability | `tests/test_audit.py`（埋点 7 场景 + 只追加 4 层断言 + 分页筛选 + 2001 边界）、`tests/test_health_ready.py`（B2-1~6、9）、`tests/test_metrics.py`（B3-1~4、7） | `tests/conftest.py`（建 `t_operation_log`；`require_admin` 后设置审计操作者的 fixture）、`tests/test_api.py`（写操作后断言审计行；路由集合断言）、`tests/test_catalog_db.py`（repository 新增 `audit=` 关键字参数）、`tests/test_schemas.py`（`AuditLogOut` 时间格式） |
| user | `tests/test_health_ready.py`、`tests/test_metrics.py` | `tests/test_api.py`（`/ping`、`/health` 零回归快照） |
| billing | `tests/test_health_ready.py`、`tests/test_metrics.py` | `tests/test_pro_db.py`（新增两张对账表不影响既有断言时需要 `create_all` 覆盖） |
| ai-chat | `tests/test_health_ready.py`、`tests/test_metrics.py`、`tests/test_metric_points.py`（模型指标 3 个 + 目录查询 4 种 result 映射） | `tests/test_execution_chain.py`（`ModelClient.complete` 增加打点后断言不变） |
| 根 | `tests/tooling/test_reconcile.py`（B4-1~10，双隔离库） | — |

新增用例预估：capability ≈ +38、user ≈ +12、billing ≈ +12、ai-chat ≈ +16、tooling ≈ +10。

### 5.2 网关 JUnit（35 项基础上新增，不得改旧断言）

- `AuthGlobalFilterTest`：`/{service}/health/ready` **免鉴权通过**（200，不被 401 拦截）；对照组 `/{service}/health/readiness-x` 仍 401（证明白名单是按后缀精确放宽，不是通配）。
- `AuthGlobalFilterTest`：`/{service}/internal/metrics` → 403 + `code=1001`（复用现有 internal 段规则，`InternalPaths` 无需改动）。
- `TrustedIdentityHeadersTest` / 路由测试：`/{service}/health/ready` 透传并注入 `X-Request-Id`。

网关 Java 改动只有一处：`AuthGlobalFilter.isHealthPath()` 增加 `normalized.endsWith("/health/ready")`（§2.1 给了完整方法）。`InternalPaths` 与路由配置零改动；若要动它们，先回写本文件。

### 5.3 工具与冒烟

- `scripts/smoke_check.py`：新增 4 条 `(f"/{name}/health/ready", 200, ?)`。注意该脚本的 `verify_payload` 断言 `{code,message,data,requestId}` 四字段，而 readiness **不走 Result** → 这 4 条必须走独立的 `verify_ready(status, body)` 分支（断言 `status=="ready"`），不能塞进 `checks` 列表的现有循环。同时新增一条 `({svc}/internal/metrics, 403, 1001)`。
- `scripts/gate.sh` 的 `2)` 分支需追加 `contract-lint` 与 `gateway-test`：本批新增 4 个接口 + 1 个指标端点 + 网关新用例，只跑 pytest + smoke 会漏掉契约与网关回归。
- `scripts/contract_lint.py`：**不改**。它是边界护栏，本批所有代码不得让它报错（尤其 `audit_service.py` 里 `capability_db`/`user_db` 只允许出现在 docstring 中——`check_service_boundaries` 对 docstring 行有豁免，这是现有实现依赖的既有行为，改动代码时不要把这些名字搬到注释以外的代码行）。

### 5.4 契约文档

| 文档 | 新增章节 |
|---|---|
| `docs/api-contract/capability-service.md` | `## 9. 运营审计`（DDL、动作枚举、`GET /api/capability/audit` 全参数与出参、只追加四层保证）；`## 10. 健康检查与指标`（`/health/ready`、`/internal/metrics`） |
| `docs/api-contract/user-service.md` | `## 10. 运营审计（批 5 预留）`（同构表 + `GET /api/user/admin/audit`）；`## 11. 健康检查与指标` |
| `docs/api-contract/billing-service.md` | `## 对账结果表`（两张表 DDL 摘要 + 三类差异口径）；`## 健康检查与指标` |
| `docs/api-contract/ai-chat-service.md` | `## 健康检查与指标`（含 `provider="default"` 占位口径、模型指标 label） |
| `docs/api-contract/pro-shared.md` | 新增 `## 8. 可观测与运维约定`：readiness 的 200/503 与 3 个原因码、hard/soft 划分原则、`/internal/metrics` 的内部性约定（不得反代）、9 个指标名与 label 白名单、审计的动作/资源枚举、对账退出码语义 |

四份契约文档都必须继续包含 `code`/`message`/`data`/`requestId` 与 `/internal/` 字样（`contract_lint` 的 `check_contracts` 会校验），新增章节不要删掉旧字样。

### 5.5 前端（B1 要求"运营后台列表页"）

- `web/src/pages/ConsolePage.tsx`：`TABS` 增加 `{ key: 'audit', label: '操作审计', icon: ScrollText }`（`lucide-react`，与现有 `SlidersHorizontal/FolderTree/BarChart3` 同源），`tab === 'audit'` 渲染 `<AuditLog />`。
- 新增 `web/src/features/console/AuditLog.tsx`（与现有 `features/console/PlatformUsage.tsx` 同目录 —— 运营后台"页签内容"归 `features/console/`，`components/` 只放跨页面复用的通用件）：筛选栏（资源类型 / 动作 / 操作人 / 日期区间）+ 表格（时间、操作人、资源、动作、requestId、展开行显示 before/after 键值 diff）+ 分页。
- `web/src/api/capability.ts` + `web/src/api/types.ts`：`listAuditLogs(params)` 与 `AuditLogItem` 类型；出参 `page_size`（蛇形）与既有接口一致，不要用 camelCase。
- 前端**不提供**任何编辑/删除入口（与只追加一致），只读表格 + 展开详情。
- 影响既有浏览器用例：Console 的 12 项断言里若有「页签数量/顺序」断言，需要同步 +1。

### 5.6 配置、依赖、部署

- `requirements.txt`（四份）：追加 `prometheus-client>=0.20,<1.0`（无其它新依赖；对账脚本只用 `PyMySQL`，已在依赖内）。实测 `services/capability-service/.venv` 已装 `prometheus_client 0.26.0`，其余三个 venv 需补装。
- `.env.example`（四份 + `deploy/.env.example`）：追加 `READINESS_TIMEOUT_SECONDS=2.0`、`READINESS_TOTAL_TIMEOUT_SECONDS=3.0`、`MODEL_PROVIDER_ALIAS=default`（仅 ai-chat 需要后两项中的 provider alias；四服务统一写入便于排查）。
- `deploy/docker-compose.yml`（批 6 用，本批只登记需求）：需为 4 服务挂 `PROMETHEUS_MULTIPROC_DIR` 卷，并加 Prometheus 抓取 `:8081-8090/internal/metrics`。
- 数据库：`capability_db` 执行 `05_add_operation_log.sql`；`billing_db` 执行 `04_add_reconcile_tables.sql`；`user_db` 的三号迁移批 5 建。**执行前备份**（红线 4），两份迁移均可重复执行。
- MySQL 需 `TRIGGER` 权限才能建触发器；`deploy/mysql/init` 以 root 执行，无额外授权动作。

### 5.7 实施日志

`docs/升级实施日志.md` 追加 B1/B2/B3/B4 四行（状态、改动文件全路径、关键决策、门禁结果、新增契约、失败尝试），并在「契约冻结清单」节引用本文件。门禁命令用 `bash scripts/gate.sh 2`（改造后）+ 手工 `python scripts/reconcile_billing.py --days 7 --dry-run`。

---

## 6. 本批红线（与需求清单第 5 节对齐，逐条落到实现）

1. **审计不得成为泄漏源**：`before_json/after_json` 只存白名单字段；会话正文永不进审计；`detail`（readiness）不得输出 `str(exc)`。
2. **只追加不得被绕过**：接口只有 GET、service 无写方法、库层触发器拒绝 UPDATE/DELETE、测试有反射断言。任何一层缺失都算未完成。
3. **`/ping` 与 `/health` 零改动**：B2 只新增 `/health/ready`。契约兼容是硬要求。
4. **不给 `/metrics` 加业务 label**：`user_id`/`capability_id`/`request_id` 进 label 会打爆 Prometheus，任何"临时加一个方便排查"的做法都禁止。
5. **对账不自动改账**：脚本只写两张结果表，绝不 UPDATE 账单或流水。差异由人定责。
6. **不降低门禁标准**：不得为了让新用例变绿而删旧断言、加 skip/xfail；readiness/trigger 这类依赖真实 DB 的用例用环境变量门控时必须写清门控条件并保留在 CI 可开。
7. **不污染演示数据**：所有验证用隔离库（`TEST_DB_ISOLATED=1`）与独立账号；`opsdemo` 的调用记录、积分流水、日聚合不得改动。

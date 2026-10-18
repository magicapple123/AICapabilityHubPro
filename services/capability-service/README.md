# AICapabilityHub Pro · 能力目录服务

`capability-service` 维护 Pro 执行所需的能力 ID、Schema、登记价格和上架状态。现有公开市场详情可供显式 `market` 兼容模式读取；内部详情端点、实时管理员授权及市场体验按钮传 ID 仍待本模块负责人完成。

模块状态以 [根 README](../../README.md)、[实施看板](../../docs/升级实施看板.md)和当前接口契约为准；不能把现有目录展示等同于所有登记能力均可执行。

能力目录服务（FastAPI）。负责能力分类与能力登记、上下架、公开能力市场和运营列表，
独立使用 `capability_db`，不依赖也不调用其它服务。

当前进度：**models、schemas、repository、service、api 五层已实现**，12 个接口可用；
字段、错误码与幂等语义以 `docs/api-contract/capability-service.md` 为准。

## 启动

1. 将 .env.example 复制为 .env，并按本机环境修改。
2. 执行 `python -m pip install -r requirements.txt`。
3. 执行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8082`。

`GET /health` 返回统一 Result 且 `data.status` 为 UP；`GET /api/capability/ping` 可验证
`X-User-Id`、`X-User-Name`、`X-Request-Id` 透传。Nacos 可用时服务每 5 秒发送心跳；
Nacos 暂不可用时服务仍可启动并在后台持续重试。

## 建库建表与演示数据

在仓库根目录执行（`01_init.sql` 会建 `capability_db`、业务表和索引，`02_seed.sql` 导入
可重复执行的演示数据）：

```powershell
$dbPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { 'root' }
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)   # 避免 PowerShell 5.1 向管道注入 BOM
Get-Content .\services\capability-service\sql\01_init.sql -Raw -Encoding UTF8 |
  docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot --default-character-set=utf8mb4
Get-Content .\services\capability-service\sql\02_seed.sql -Raw -Encoding UTF8 |
  docker exec -i -e MYSQL_PWD=$dbPassword aihub-mysql mysql -uroot --default-character-set=utf8mb4
```

## 数据表

| 表 | 说明 |
|---|---|
| `t_capability_category` | 能力分类：`name`、`code`、`sort`、`status(enabled/disabled)` |
| `t_capability` | 能力目录：`category_id`、`name`、`code`、`service_name`、`path`、`param_schema`、`price_per_call`、`status(draft/online/offline)`、`description` |

两表均含 `create_time`、`update_time`、`is_deleted` 通用字段，所有查询默认过滤
`is_deleted=0`；`name` / `code` 在未删除范围内唯一。

## 接口一览

| 方法 | 路径 | 是否需要登录 |
|---|---|---|
| GET / POST | `/api/capability/categories` | 是 |
| PUT / DELETE | `/api/capability/categories/{category_id}` | 是 |
| POST | `/api/capability` | 是 |
| PUT / DELETE | `/api/capability/{capability_id}` | 是 |
| PUT | `/api/capability/{capability_id}/status` | 是 |
| GET | `/api/capability/manage` | 是 |
| GET | `/api/capability/market` | 否（网关白名单） |
| GET | `/api/capability/market/categories` | 否（网关白名单） |
| GET | `/api/capability/market/{capability_id}` | 否（网关白名单） |
| GET | `/api/capability/ping`、`/health` | 否 |

市场接口只返回 `status='online'` 且未软删除、所属分类也未软删除的能力，且不输出
`service_name`、`path` 等内部配置；未上架能力对市场统一返回 `2002`。

业务错误码只用 2xxx 号段：`2001` 参数不符合 Schema、`2002` 能力不存在或已下线、
`2003` 分类不存在、`2004` 分类名称或编码已存在、`2005` 分类下仍有能力不可删除、
`2006` 能力编码已存在。

## 测试

| 测试文件 | 用例数 | 覆盖内容 | 依赖数据库 |
|---|---|---|---|
| `tests/test_schemas.py` | 18 | 入参校验：code 正则、部分更新拒绝显式 null、状态枚举、价格非负、市场出参不泄露内部字段、时间序列化 | 否 |
| `tests/test_api.py` | 18 | 8 个受保护路由的 `1001` 鉴权、4 类 `2001` 参数错误、分页边界、路由注册顺序 | 否 |
| `tests/test_catalog_db.py` | 18 | 筛选（分类 / 关键字 / 中文）、上下架流转、软删除、重复名称与编码、删除前引用检查、PUT 幂等、运营列表与越权现状 | **是** |

数据库行为测试必须连接真实 MySQL：业务表由 `sql/01_init.sql` 创建，SQLAlchemy 模型不建表，
用 SQLite 替代测不到组合唯一索引与 utf8mb4 行为。数据统一用 `qa-` 前缀创建，用例前后物理清理，
不会污染 `02_seed.sql` 的演示数据；数据库不可用时整组自动跳过而不是失败。

## 自测

```powershell
# 全量测试：36 个不依赖数据库的用例 + 18 个数据库行为用例（共 54）
# 数据库不可用时，数据库用例会自动跳过，不会导致失败
.\.venv\Scripts\python.exe -m pytest -q

# 启动后自测；市场接口无需身份头，其余接口需手动补 X-User-Id（模拟网关注入）
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8082
curl.exe http://localhost:8082/api/capability/market
curl.exe http://localhost:8082/api/capability/market/categories
curl.exe -H "X-User-Id: 1" http://localhost:8082/api/capability/manage
```

FastAPI 自带文档：<http://localhost:8082/docs>。

## 分层约束

按 models、schemas、repository、service、api 分层扩展，路由层不写 SQL 与业务逻辑。
服务间调用必须通过 `app.core.service_call.call_internal` 访问 `/internal/**`，
不得写死其它服务地址。状态取值统一来自 `app.core.constants`，禁止魔法字符串。

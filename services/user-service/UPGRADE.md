# 用户 / 计费升级与验证

停止 user/billing 写入并使用运维工具备份两个数据库（保留数据卷）。确认 DB_URL 指向 Pro 服务各自的库；不连接原项目。首次部署先执行对应 `sql/01_init.sql`。已有库必须运行迁移，单纯重跑 CREATE TABLE IF NOT EXISTS 不会补列。

在各服务目录，使用该服务 Python 环境依次执行：

```powershell
# services/user-service
python -m app.migrate
python -m app.migrate
# services/billing-service
python -m app.migrate
python -m app.migrate
```

迁移仅增加 `t_user.role VARCHAR(16) NOT NULL DEFAULT 'user'` 与 `t_call_record.unit_price BIGINT NULL`，不改写密码、Key、余额、流水或历史费用。旧账号全部默认 user；已有 admin 不会被第二次执行降权。历史未知单价为 NULL，不能从 cost 猜价格。MySQL DDL 自动提交，暂停写入、单进程执行；发现不兼容的已有列需人工核查。核对迁移前后 COUNT(*)、余额、流水和账单；查询 `SHOW COLUMNS FROM t_user LIKE 'role'` 与 `SHOW COLUMNS FROM t_call_record LIKE 'unit_price'`。回退代码时可保留新增列，不需 DROP；数据恢复仅由运维基于备份执行。

本地管理员由拥有数据库运维权限的人在 user-service 目录执行 `python -m app.admin <独立管理员用户名>`。口令在终端隐藏输入两次，不通过参数、注册接口或源码传入；已存在账户拒绝覆盖。创建的账户余额 0，不赠送虚构流水。不提供公开提权接口。撤销管理员使用受控 SQL `UPDATE t_user SET role='user' WHERE id=<已核实ID>`；已有 JWT 的 role 不影响实时授权判定。

`.env` 增加 `API_KEY_JWT_TTL_SECONDS=900`（1–3600，超范围拒绝启动），沿用 Gateway 相同 JWT_SECRET / JWT_ISSUER。Key 截止时间按北京时间存储；携带时区输入先归一化。JWT 截止时间按 UTC 返回。Key 禁用阻止新兑换；已签 JWT 至过期仍有效，业务继续校验账户状态、管理接口继续实时授权。

## 测试

数据库测试会清理测试数据，必须使用独立 MySQL 实例。CI 的 GitHub Actions service container 是独立实例；本地须自行启动独立实例并建立 `qa_user_db` / `qa_billing_db`，按 init SQL 在该专用实例初始化（库名按实际测试配置调整），再运行迁移。不得复用开发端口/数据卷。

```powershell
$env:TEST_DB_ISOLATED='1'
$env:DB_URL='<该服务独立测试实例的 SQLAlchemy URL>'
python -m pytest -q --junitxml=test-results.xml
python ../../scripts/check_test_report.py test-results.xml
```

无数据库时仅运行纯单测文件 `tests/test_api.py tests/test_schemas.py tests/test_pro_security.py`，它们不做数据库验收声明。完整数据库组在缺少显式隔离确认/数据库不可用时失败，不再自动跳过。迁移测试使用独立 MySQL 的随机临时旧版表，不清理开发数据库。

单测中的 Repository / 授权 HTTP 替身用于故障注入，不代表真实服务联合验收。夏思凯负责 capability 管理接口接入 `GET /internal/user/authorization`；组长负责 Gateway/执行链联合验收。授权不可用、非明确 true、ID/状态/角色错误均拒绝全局统计。

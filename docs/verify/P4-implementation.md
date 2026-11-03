# P4 审计表格实施与实机证据

- 时间：2026-11-03 15:43–15:50（Asia/Shanghai），约 7 分钟。
- 状态：产品实现、前端检查、真实浏览器实测通过；公共 `gate.sh all` 与 `acceptance_check.py` 由主代理统一执行，尚不能据此标记整项最终完成。
- 文件所有权：本子代理仅修改 AuditLogPanel 及其新增独立样式、P4 专用验证脚本和本文档。未修改共享 dashboard.css、接口、数据库结构、主实施日志；未提交。

## 文件与恢复

1. `D:\AICapabilityHubPro\web\src\features\console\AuditLogPanel.tsx`（191 行）。
2. `D:\AICapabilityHubPro\web\src\features\console\audit-log.css`（新增，45 行）。
3. `D:\AICapabilityHubPro\scripts\verify\p4_audit.mjs`（新增，真实浏览器验收）。
4. `D:\AICapabilityHubPro\docs\verify\P4-implementation.md`（本文档）。

原组件已先备份到 `D:\AICapabilityHubPro\artifacts\verify-2026-11-03\source-backup-P4-20261103-154309\AuditLogPanel.tsx`。备份保留本轮之前所有未提交修改；恢复时仅回填本组件，不执行仓库 reset/clean。没有删除任何源码或测试文件。

## 决策

- 使用 `.data-table--audit` 唯一修饰类；所有表格规则限定在该类下，不修改其它六张表的全局布局。
- colgroup 固定时间 96、操作人 80、资源 88、动作 52、requestId 96、操作 64px，其余分配给变更。
- 每行只计算一次 diff；默认前三个字段、两行式展示，字符串超过 40 字符摘要，对象显示字段数。完整 before/after JSON 放在原生可键盘操作的 details 区域，展开后可滚动阅读全文。
- requestId 显示前 8 / 后 4 位，title 保留全值，复用既有 CopyButton 写入完整 UUID。时间拆为日期与时分秒。
- 900px 以下隐藏操作人列，资源 title 保留操作者；767px 以下转卡片并恢复显式操作者信息。
- 没有新增字段、接口、错误码或数据库迁移。

## 命令原文与结果

### 改前基线（旧部署版本）

```powershell
$env:P4_BASELINE_ONLY='1'
node scripts/verify/p4_audit.mjs
```

`P4_RESULT=BASELINE`。在独立验收库创建专用草稿能力 338（`p4-live-5aedd700`），长快照 3483 字符，12 个 synthetic Schema 字段。只记录合成验收数据，不读取/打印用户输入或密钥。

| 视口 | 审计容器 clientWidth | scrollWidth | 横向溢出 | 行布局 |
|---|---:|---:|---:|---|
|1440|1142|1693|551px|table-row|
|1280|982|1693|711px|table-row|
|1024|764|1693|929px|table-row|
|375|341|1693|1352px|table-row|

### 实现检查与部署

```powershell
pnpm --dir web lint
pnpm --dir web build
node --check scripts/verify/p4_audit.mjs
docker compose --env-file deploy/.env -p aihub-pro-verify --profile app -f deploy/docker-compose.yml -f deploy/docker-compose.verify.yml up -d --build --no-deps nginx
```

- lint：exit 0；没有 eslint-disable。
- build：exit 0，`✓ 3431 modules transformed`、`✓ built in 8.16s`；既有大 chunk 提示仍保留，没有降低构建约束。
- node --check：exit 0。
- 验收 nginx：镜像构建成功，`Container aihub-verify-nginx Started`；仅更新独立验收 nginx，数据库卷未重建。容器内生产构建也通过，`✓ built in 5.91s`。

### 改后（生产 Nginx 28088，最终证据）

```powershell
$env:P4_BASELINE_ONLY='0'
$env:P4_WEB_URL='http://127.0.0.1:28088'
node scripts/verify/p4_audit.mjs
```

输出：

```text
P4_COPY uuid_length=36 equal=true request_id=e47b088e-7753-4376-a421-f99ab8811739; expanded_schema_fields=12
P4_AUDIT capability_id=340 request_id=d09dce27-07cc-46db-9a37-9508ac0ce9b7 mode=after
P4_RESULT=PASS
```

注意：`P4_AUDIT request_id` 是发给网关的合成请求头；网关会重建可信 requestId，实际落库并成功复制的是 `P4_COPY request_id=e47b088e-7753-4376-a421-f99ab8811739`。

| 视口 | 审计容器 clientWidth | scrollWidth | 横向溢出 | document client/scroll | 行布局 |
|---|---:|---:|---:|---|---|
|1440|1142|1142|0|1440 / 1440|table-row|
|1280|982|982|0|1280 / 1280|table-row|
|1024|763|763|0|1024 / 1024|table-row|
|375|341|341|0|375 / 375|block（卡片）|

四档均有可见截图，1024/375/完整快照图已实际打开目视复核。requestId 复制读取系统剪贴板，严格断言完整 36 位相等；展开 after 快照严格断言含 `verification_field_11`，确认 12 个字段完整保留。

## SQL 查询与输出（仅独立验收实例）

容器 `aihub-verify-mysql`、宿主端口 23307。凭证仅在容器进程环境使用，未打印。

```sql
SELECT id,resource_id,action,CHAR_LENGTH(request_id),
       CHAR_LENGTH(CAST(after_json AS CHAR))
FROM capability_db.t_operation_log
WHERE resource_type='capability' AND resource_id IN (338,339,340);
SELECT COUNT(*),COALESCE(SUM(cost),0)
FROM billing_db.t_call_record WHERE capability_id IN (338,339,340);
```

```text
884  338  create  36  3483
885  339  create  36  3483
886  340  create  36  3483
0    0
```

P4 只创建验收草稿与审计，不执行收费调用，三条验收能力账单 0 条 / 0 积分。未连接开发库 3307，没有修改 opsdemo 的账单、流水、日聚合。

## 失败与返工

- 没有验收失败轮次。首次实现实测四档均无溢出；目视复核发现手机卡片中的用户 ID / 资源 ID 因 grid 子项换到了标签列，已将值包装为一个 div，再用生产容器重测通过。
- 首次 preview 的 96px 摘要高度略截第三个字段值，缩小行高与行间距后，最终截图完整显示前三个字段。
- 两个只读探测命令用到了不存在的 capability.py 和 Windows 不支持的 glob 路径；已改用实际 API 类型/确切模型文件，未据这些命令宣称验证成功。
- 全程没有删测试、降断言、skip/xfail 或关闭检查。

## 截图索引

以下路径均以 `D:\AICapabilityHubPro\artifacts\verify-2026-11-03\` 为根：

| 文件 | 验收项 |
|---|---|
|`P4-before-5aedd700-1440.png`|旧版1440横向溢出551px基线|
|`P4-before-5aedd700-1280.png`|旧版1280横向溢出711px基线|
|`P4-before-5aedd700-1024.png`|旧版1024横向溢出929px基线|
|`P4-before-5aedd700-375.png`|旧版375仍为宽表，横向溢出1352px|
|`P4-after-70917f97-1440.png`|Vite初次实测1440无横滚|
|`P4-after-70917f97-1280.png`|Vite初次实测1280无横滚|
|`P4-after-70917f97-1024.png`|Vite初次实测1024无横滚|
|`P4-after-70917f97-375.png`|手机ID排版优化前中间证据，最终见7b80799d|
|`P4-after-70917f97-expanded.png`|首次完整JSON快照可展开|
|`P4-after-7b80799d-1440.png`|**最终生产Nginx**1440无横滚|
|`P4-after-7b80799d-1280.png`|**最终生产Nginx**1280无横滚|
|`P4-after-7b80799d-1024.png`|**最终生产Nginx**1024无横滚、requestId可见|
|`P4-after-7b80799d-375.png`|**最终生产Nginx**375卡片，无页面/表格横滚|
|`P4-after-7b80799d-expanded.png`|**最终生产Nginx**完整快照展开，已复制36位requestId|

## 主代理下一步

立即运行该条公共门禁 `bash scripts/gate.sh all`（GATE_DB_PORT=23307）及 `python scripts/acceptance_check.py`，按实际结果追加主实施日志；本文档不能代替主代理公共门禁。无需再改P4产品代码。

本代理额外启用过 Vite 28173 仅作中间调试，现已停止；最终验收来自 28088。未修改默认开发端口、配置或其它服务。

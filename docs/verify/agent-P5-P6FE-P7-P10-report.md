# 交付报告 · P5 / P6（前端）/ P7 / P10（前端）

执行者：agent-b-console-ui　日期：2026-11-03　范围：仅 web 前端，后端与 gateway 未改动。

## 1. 改动文件（绝对路径）

**新增**

- `D:\AICapabilityHubPro\web\src\features\console\UserUsagePanel.tsx`（243 行）
- `D:\AICapabilityHubPro\web\src\features\console\UserUsageTable.tsx`（58 行）
- `D:\AICapabilityHubPro\web\src\features\console\UserDetailDrawer.tsx`（199 行）
- `D:\AICapabilityHubPro\web\src\features\console\PointsAdjustModal.tsx`（111 行）
- `D:\AICapabilityHubPro\web\src\features\console\PlatformStatCards.tsx`（18 行，统计卡抽成共享组件）
- `D:\AICapabilityHubPro\web\src\features\console\userUsage.ts`（61 行，join / 排序 / 错误文案的纯函数模块）

**修改**

- `D:\AICapabilityHubPro\web\src\pages\ConsolePage.tsx`（6 页签 → 5 页签 + 旧 tab 重定向）
- `D:\AICapabilityHubPro\web\src\api\admin.ts`（新增 `setAdminUserBudget`）
- `D:\AICapabilityHubPro\web\src\api\billing.ts`（`CallRecordItem` 增 `api_key_id` / `entrypoint`；`AdminCallRecordQuery` 增 `api_key_id`；新增 `fetchAdminUserAggregates` / `fetchAdminUserKeyUsage` 与 4 个类型）
- `D:\AICapabilityHubPro\web\src\features\usage\RecordTable.tsx`（新增「来源」列；详情弹窗补「来源」「调用 Key」）
- `D:\AICapabilityHubPro\web\src\features\usage\exportRecords.ts`（导出增加「来源」「Key 编号」，null 写 `—`）
- `D:\AICapabilityHubPro\web\src\styles\dashboard.css`（新增 P5/P7 样式：趋势高度、行可点、调分弹窗、`.button-primary.is-danger`、窄屏 `.ant-modal` 92vw）
- `D:\AICapabilityHubPro\web\src\styles\account.css`（删除死样式 `.ranking-list` 共 5 条规则）
- `D:\AICapabilityHubPro\web\src\components\navigation.ts`（运营后台描述文案「分类、能力和平台用量」→「分类、能力与用户用量」）

**删除**

- `D:\AICapabilityHubPro\web\src\features\console\PlatformUsage.tsx`（P5 第 7 条：Top10 卡片与页签一并删除；确认无其它引用）
- `D:\AICapabilityHubPro\web\src\features\console\UserAdminPanel.tsx`（内容被 `UserUsagePanel` + `UserDetailDrawer` + `PointsAdjustModal` 完整取代；确认无其它引用）

## 2. 关键决策

### 2.1 P5 页签合并与旧链接兼容

- 页签：`capabilities / categories / users-usage / audit / models`，`platformUsage` 与 `userAdminPanel` 两个组件不再存在。
- `LEGACY_TABS = { statistics: 'users-usage', users: 'users-usage' }`，命中时直接 `<Navigate to="/console?tab=users-usage" replace />`，旧书签不会 404 也不会落到默认 `capabilities`。用精确等值匹配（`users-usage !== users`），避免新页签被误判成旧 key。

### 2.2 join、排序、分页（A1 方案）

- 一次并发三个请求：`GET /api/user/admin/users?page_size=2000`、`GET /api/billing/admin/users/usage`、`GET /api/billing/stat/overview`（统计卡与趋势）。
- `joinUserUsage()`（`userUsage.ts`）以 user 列表为骨架，billing 聚合按 `user_id` 覆盖 `call_count / total_cost / last_call_at`；billing 无记录 → 0 / 0 / null。
- **反向兜底**：聚合里有、user 列表里没有的 `user_id` 会补一行 `user: null`，界面显示 `#663 资料缺失`，只给「详情」，不给禁用/调分。整行不会消失。
- **排序在 join 后的全量数据上做**（`sortUserUsage`），再切片分页（20/页）；页面上会显式写「排序作用于 join 后的全量 N 人，不是当前页的前 20 人」。三种排序：消耗降序（默认，等于原积分消耗排行）/ 调用次数降序 / 注册时间降序（资料缺失行排末尾）。
- **2000 上限的处理**：`USER_FETCH_LIMIT = 2000` 与后端 `ADMIN_USER_PAGE_SIZE_MAX` 对齐，代码注释里写明「A1 只在用户总数 ≤ 2000 时成立」，并写了 A2 升级路径（billing 主导分页排序 → user-service 批量补资料 → 零调用用户补尾页）。当 `users.total > list.length` 时页面额外提示「已达到 2000 用户上限，还有 N 人未载入」，避免静默截断。
- 搜索：`keyword` 原样透传后端（ID 精确 + 用户名/昵称模糊），前端 350ms 防抖；状态走后端参数，**角色是纯前端过滤**（billing/user 都没有角色维度）。

### 2.3 权限提示口径统一（为兼容既有浏览器用例）

- 普通用户访问合并页时三个请求都会失败，但码不同：user-service 是 `2007 无运营权限…`，billing `/stat/overview` 是 `1006 权限不足`。谁先 reject 不确定，直接显示 `message` 会出现两种说法。
- `describeLoadError()` 把 `2007/1006` 收敛成「权限不足：仅管理员可访问「用户与用量」。」——只改错误文案，**没有在前端做任何权限拦截**，请求照发，服务端仍是唯一判定方。这样 `web/tests/console-browser.ts:32-35` 对 `.error-note` 的 `/权限不足/` 断言在页签合并后依然成立（该用例未改动）。

### 2.4 抽屉拆分与 P6/P10 入口

- 抽屉独立成文件，接收 `{ row, days }`；面板用 `key={row.user_id}` 让切换用户时重置「Key 筛选 / 预算草稿」。
- 近 N 天趋势 + 最近 10 条调用 + Key 列表 + **按 Key 调用分布**（`/users/{id}/keys-usage`），Key 名从该用户 Key 列表按 id 映射，查不到显示 `Key #id`；历史无 Key 身份的调用不进该表并在标题里说明。
- 「最近 10 条调用」右上角加了 Key 下拉（全部 Key / 具体 Key），切换即带 `api_key_id` 重新查询，导出明细 CSV 也带当前 Key 筛选。
- P10 日预算在抽屉里**内联编辑**（未单独做 Modal）：`InputNumber(min=0, max=1_000_000)` + 保存，`0` 语义在输入框旁、当前值行、提示文案三处都写成「不限」，`0` 不会被当成非法值；列表列保持只读。保存走 `PUT /api/user/admin/users/{id}/budget`，用后端返回的 `daily_points_limit` 提示并刷新抽屉与列表。

### 2.5 P7 调分弹窗

- `window.prompt/alert/confirm` 在 web/src 全量清零（仅剩注释里提到历史实现）。
- 结构与校验按需求实现：当前余额 / `InputNumber(precision=0, step=10)` + 6 个快捷按钮 / 调整后实时计算（负数 `.is-negative` 标红）/ 原因 `TextArea maxLength=200 + showCount + 示例占位`；`amount=0` → 「不能为 0」，`|amount| > 1_000_000` → 「单次上限 1,000,000」（按 `admin_service.MAX_ADJUST_AMOUNT` 代码值，不是文档里的 10000），扣减超余额 → 「最多可扣 X」且按钮禁用，`reason.trim()` 为空 → 字段级错误且不发请求。原因少于 4 字只给软提示，不阻断。
- 负数时主按钮 `button-primary is-danger`（实心 `--bad`）且文案「确认扣减 50」；提交中禁用输入、快捷按钮与取消；成功用后端返回 `balance` 提示「已调整 +50，当前余额 220」并刷新列表；失败把后端 message（如 3001）渲在表单顶部 `ErrorNote`。
- Enter 提交用 `<form onSubmit>` + `footer` 里 `type="submit" form="points-adjust-form"` 实现（`ui.tsx` 的 `Modal` footer 在 form 外）。

### 2.6 与需求文字的偏差（3 处，均为有意为之）

1. `ui.tsx` 的 `Field` 只渲染 `<input>`，无法承载 `InputNumber` / `TextArea`；且 `dashboard.css` 里有 `.field input {…}` 会破坏 antd 输入框样式。因此调分弹窗**只复用 `Modal`**，两个字段用等价的 `.points-field / .points-label` 结构，视觉与 `Field` 一致。
2. `.ranking-list` 死样式实际在 `web/src/styles/account.css:90-94`（不在 `dashboard.css`），已从 account.css 删除；`dashboard.css` 里的 `.data-table` 全局定义**未触碰**。新增样式集中在 `dashboard.css` 末尾，均带 `P5` / `P7` 前缀注释。
3. 名单列按需求去掉「注册时间」列（需求给的 8 列不含它），但保留「注册时间降序」排序项。

## 3. 自测与门禁

执行（工作目录 `D:\AICapabilityHubPro`）：

```
pnpm --dir web lint
> aicapabilityhub-pro-web@0.1.0 lint
> eslint .
（无告警，exit 0）
```

补做了一次类型检查（未跑 `pnpm build`，未跑 `gate.sh`）：

```
cd web && pnpm exec tsc --noEmit -p tsconfig.app.json
（无输出，exit 0；tsconfig.app.json 的 include 是 ["src"]，strict: true）
```

## 4. 未完成 / 需主代理注意

1. **未做真实页面验证**：`pnpm build` 与 `gate.sh` 交主代理；本次没有登录 `http://127.0.0.1:28088` 抓图（该地址跑的是上一次构建产物，前端口径未生效，登录也没有可用管理员口令）。P5/P7/P10 的界面验收仍需在 build 后由主代理按附录 C 抓图。
2. **`web/tests/console-browser.ts` 未改**：刻意保持原样——`?tab=statistics` 走重定向后，管理员用例断言（`平台调用趋势` 标题 + `平台调用` 卡等于 `summary.call_count`）与普通用户用例断言（`/权限不足/`）都仍然成立。若主代理后续改了错误文案映射，这两处会一起受影响。
3. **`scripts/verify/ui_shots.mjs` / `ui_shots_round2.mjs` 仍引用旧页签文案**（「平台用量」「用户管理」）：它们是截图脚本、不在 `gate.sh` 内，未改动。需要的话把 `09/12` 两张改成一张「用户与用量」。
4. **A2 路径未实现**（用户数 > 2000）：按需求仅要求写清边界与升级路径，已在代码注释与页面提示中说明；`POST /api/user/admin/users/batch` 前端也没有接。
5. 抽屉宽度仍为 760（沿用旧值）：375px 下 antd Drawer 会占满视口，内部表格靠 `.data-table-wrap` 横向滚动，未做卡片化（不在本次四条需求范围内）。

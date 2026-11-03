# P8 + P9 实施报告（agent-c-capability-ui）

日期：2026-11-03 ｜ 范围：能力登记/编辑表单 + 前端"可执行"判断口径

## TL;DR

- P8：创建/编辑 payload 收敛为**同一份字段定义**；表单补齐 执行器 / 供应商 / 计价模式 / 输出上限 / 市场展示；三处"可执行"判断（市场卡片+详情、调试台、表单提示）统一为 `executor = detail.executor || CODE_TO_EXECUTOR[detail.code]` 后再判 `executor ∈ executors`。
- P9：Schema 模板标签改为标准标签行（不折行）、加「格式化」+ 失焦校验、错误分字段并保留底部汇总、服务名/路径预填并折叠进"高级/兼容字段"、分类为空给创建入口、初始状态选「已上架」做可执行性预检、弹窗 720px + 375px 单列无横向滚动。
- 自测：`pnpm --dir web lint`、`tsc --noEmit` 均通过（真实输出见文末）。
- **一个依赖需要 F2 负责人配合**：`CapabilityMarketDetailOut.from_row` 没有把 `executor/provider_alias/max_output_tokens` 写进出参，不修则新 code 的市场卡片仍会走 code 回退（详见"未完成项"）。
- **一处测试交互修正**：`web/tests/console-browser.ts` 加 1 行（展开折叠的"高级/兼容字段"），断言与用例数量均未改动。

## 改动文件（绝对路径）

新增：

- `D:\AICapabilityHubPro\web\src\features\capabilities\executorResolver.ts`：`CODE_TO_EXECUTOR`、`resolveExecutor`、`supportedExecutors`、`isExecutorSupported`、`executorProtocols`、`protocolMatches`、`EXECUTOR_OPTIONS`、`requiresProvider`。
- `D:\AICapabilityHubPro\web\src\features\capabilities\capabilityFormModel.ts`（240 行）：表单态、`initialForm`、`validateCapabilityForm`（分字段错误）、`buildPayload`（按计价模式归一）、`checkSchemaText`、`schemaProblem`、`executorHint`、`summarizeErrors`。
- `D:\AICapabilityHubPro\web\src\features\capabilities\editorUi.tsx`：`EditorModal`（720px）、`FieldError`、`FormSection`。
- `D:\AICapabilityHubPro\web\src\features\capabilities\ExecutionFields.tsx`：执行器 / 供应商 / 输出上限。
- `D:\AICapabilityHubPro\web\src\features\capabilities\PricingFields.tsx`：计价三选一 + 对应价格。
- `D:\AICapabilityHubPro\web\src\features\capabilities\SchemaFields.tsx`：模板行、格式化、失焦校验。
- `D:\AICapabilityHubPro\web\src\styles\capability-editor.css`：只新增 `.cap-*` / `.capability-editor-modal` 规则，由 `CapabilityEditor.tsx` 直接 import（未改 `styles.css` / `dashboard.css`）。

修改：

- `D:\AICapabilityHubPro\web\src\features\console\CapabilityEditor.tsx`（199 行，重写）：编排 + 提交 + 分组渲染。
- `D:\AICapabilityHubPro\web\src\api\capability.ts`：新增 `BillingMode`、`CapabilityWritableFields`；`CapabilityCreatePayload = CapabilityWritableFields & { status? }`、`CapabilityUpdatePayload = Partial<CapabilityWritableFields>`；`MarketCapability` 增加可选 `executor` / `billing_mode` / `unit`。
- `D:\AICapabilityHubPro\web\src\features\chat\ChatWorkspace.tsx`：`codes.includes(detail.code)` → `isExecutorSupported(catalog.executors, resolveExecutor(detail))`。
- `D:\AICapabilityHubPro\web\src\pages\CapabilitiesPage.tsx`：卡片与详情共用 `isSupported(capability)`。
- `D:\AICapabilityHubPro\web\src\components\CapabilityManager.tsx`：一行传参（`executorCodes` → `executorCatalog={executors.data}`）+ 注释。
- `D:\AICapabilityHubPro\web\tests\console-browser.ts`：+2 行（注释 + `editor.locator('summary').first().click()`），因为服务名/调用路径默认收起了。

未触碰：`web/src/features/console/` 其它文件、`pages/ConsolePage.tsx`、`api/admin.ts`、`api/billing.ts`、`styles/dashboard.css`、`components/ui.tsx`、任何后端 / gateway / deploy / 实施日志。

## 关键决策

### 1. payload 只有一套定义（P8.1）

`CapabilityWritableFields` 是唯一字段源：创建 = 全字段 + 可选 `status`，编辑 = `Partial<同一份>`，编辑不再声明 `status`（状态变更仍走 `updateCapabilityStatus`）。

### 2. CODE_TO_EXECUTOR 映射表内容（与 ai-chat `EXECUTORS[*].legacy_codes` 一致）

| 旧 code | executor |
|---|---|
| `chat-completions` | `chat` |
| `long-summary` | `summary` |
| `text-to-image` | `image-generate` |

`resolveExecutor()` 先取 `executor`，为空才查表；`initialForm()` 编辑旧数据时也用它回填，保存即完成字段迁移。

### 3. 三处口径统一，目录未就绪时不误报

`isExecutorSupported()` 在目录为 `null/undefined` 时返回 `false`（与改造前 `!!executors.data?.codes.includes()` 的保守语义一致，不把未知当可执行）。若 `/chat/executors` 只返回旧字段 `codes`（老后端），`supportedExecutors()` 用 `CODE_TO_EXECUTOR` 反推，避免整页被判成"无执行器"。

### 4. 协议匹配取「目录 ∪ 本地权威表」（重要）

- 保存阶段的权威是 capability-service `EXECUTOR_PROTOCOLS`（`services\capability-service\app\core\constants.py:47-53`）：chat/summary → `openai-chat` + `openai-responses`；image-generate → `openai-image` + `dashscope-image`。
- `/api/chat/executors` 的 `executor_protocols` 来自 `EXECUTORS[*].protocols`（`services\ai-chat-service\app\service\capability_adapters.py:47-67`），chat 只列 `openai-chat`。
- 单用后者会把**后端允许**的 `chat + openai-responses` 误判为不匹配并拦住保存，因此 `executorProtocols()` 取并集：仍以 `executor_protocols` 为主，用本地表兜住保存阶段的放行项。
- 结论：`image-generate` 只能选 `openai-image / dashscope-image`（两处一致）；前端只做提前反馈（禁用保存 + 字段提示），最终仍以后端 2001 为准。

### 5. 供应商字段的管理员降级

`useAuthStore.role` 已知且不是 `admin` 时**不发** `/chat/providers`，直接渲染只读输入（空值显示"全局默认"）+ 说明"保存时以后端校验为准（2007）"。角色未知（占位登录）时照常请求，失败同样降级为只读。

### 6. 计价字段按模式归一

`buildPayload()` 只保留当前模式的价格，其它一律提交 `0` / `""`（`per_token` 时 `price_per_call=0`；`per_unit` 才保留 `unit`）。这是后端 `validate_billing_fields` 的硬约束，属 payload 形状而非规则复制。

### 7. 前端校验边界（不复制后端组合规则）

只做：必填与格式（名称/编码/分类/对外模型名/输出上限/价格整数范围）、执行器是否已接入、供应商是否存在且 `enabled`、协议是否匹配、Schema JSON 合法性与结构约束（沿用原有 32768 字节 / 禁 `$ref` / 对象根类型）、服务名非空与路径以 `/` 开头；`per_token` 只对"当前模式必填"给提示，`per_unit` 只判"单价 > 0 + 单位非空"。
其它组合规则（如 `price_per_call` 必须为 0）交后端；后端 2001 原文由底部 `ErrorNote` 展示。

### 8. 新建默认 `executor = chat`

与后端 `CapabilityCreateRequest.executor` 的缺省值一致，保持改造前的创建行为，也避免 E2E 用例必须显式选执行器。"未选执行器"只在用户手动清空下拉时出现，此时表单提示 + 禁止选「已上架」。

### 9. 可执行性预检（P9.6）

`executorReady = isExecutorSupported(catalog, form.executor)`；为 false 时「已上架」选项 `disabled`、文案改为"需先选择并接入执行器"，并用 `useEffect` 把已选中的 `online` 回退成 `draft`，避免提交必然失败的能力。

### 10. 720px 弹窗不改 `ui.tsx`

`EditorModal` 直接用 antd `Modal`（`width={720}`、`centered`、body 可滚动），复刻 `ui.tsx` 的 body 样式；窄屏由 antd 自带 `max-width: calc(100vw - 32px)` + 本模块 `@media (max-width: 767px)` 单列兜底。

## 自测（实际执行）

```
PS D:\AICapabilityHubPro> pnpm --dir web lint
$ eslint .
（无输出）
LINT_EXIT=0

PS D:\AICapabilityHubPro\web> npx tsc --noEmit -p tsconfig.app.json
（无输出）
TSC_EXIT=0
```

按要求**未**执行 `pnpm build` / `gate.sh`。单文件最大 240 行（`capabilityFormModel.ts`），均 < 300。

## 未完成项 / 依赖（需主代理决策）

1. **后端市场出参缺 `executor`（阻塞 P8 验收的一半）**
   `CapabilityMarketDetailOut` 声明了 `executor/provider_alias/max_output_tokens`（`services\capability-service\app\schemas\capability.py:315-317`），但 `from_row`（同文件 `:319-338`）没有赋值，运行期恒为 `""` / `1024`。
   影响：新 `code`（如 `contract-review`，executor=chat）在市场详情里拿不到 executor，前端只能走 `CODE_TO_EXECUTOR` 回退 → 仍显示"暂无执行器"。市场**列表**出参 `CapabilityMarketOut`（`:272-305`）也没有 executor，卡片判断同样只能靠回退。
   建议（F2 负责人）：`from_row` 补三个字段（1 个字段 3 行）；若希望新能力在**列表卡片**上就正确，需给 `CapabilityMarketOut` 增加 `executor`（对外契约加法）。
   在补齐前：旧 3 个能力（1/2/2169）判定与文案不变；新 code 的判定与后端真实执行能力存在偏差——这正是 P8 剩下的那一半。
2. **E2E 影响（已把兼容成本降到最低，仍有两处需注意）**
   - 已改：服务名/调用路径默认折叠，用例里补 1 行 `editor.locator('summary').first().click()` 再填值。
   - 已保持兼容：字段标签保留 `能力名称/能力编码/所属分类/每次调用积分/服务名/调用路径/初始状态/输入 Schema` 原文（`getByLabel` 用子串匹配）；`输入 Schema` 仍用 `aria-label`；底部汇总现在带"首个问题原文"，`console-browser.ts:89` 的 `Schema 不能使用` 断言仍成立；新建默认 executor=chat，用例不必显式选择。
   - 待同步：`console-browser.ts:136/146`（"新 code 必须显示暂无执行器"）编码的是**当前后端的缺陷现状**。等第 1 条补齐后，这个新建的 chat 能力会显示"支持调试"，该断言需改为正向断言（这也是 P8 的验收目标）。
3. **无浏览器实机验证**：未启动 web/后端、未截 1440/375 两档图（避免与主代理并行构建打架）。建议门禁阶段按附录 C 的 P8/P9 两行补截图。
4. 市场卡片价格仍固定渲染"积分 / 次"，`per_token / per_unit` 的价格展示不在 P8/P9 范围，未改动（`MarketCapability` 已补可选类型，方便后续单独修）。

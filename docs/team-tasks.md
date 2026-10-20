# AICapabilityHub Pro 三人任务与交接

更新日期：2026-10-20。PR #1–#5 已合入 main，三人业务集成基线 `651275b`；两位成员实现及跨服务依赖均已交付。旧分工见[归档](archive/2026-09-原版团队任务.md)，不能继续据此重建模块。

先读[Pro开发指南](../AICapabilityHubPro-开发指南.md)、[共享契约](api-contract/pro-shared.md)及[非部署收尾记录](验收收尾记录-2026-10-20.md)。实际测试、部署和人工评审分开记录。

## 负责人及已交付范围

| 成员 | 代码和页面 | 当前状态 |
|---|---|---|
| 黄岑果 | Gateway、ai-chat、Chat、公共脚本/CI/文档 | 可信身份、受控聊天/摘要、目录价计量及联合验收已集成 |
| 黄禹菲 | user/billing、Settings、相关API/types/契约/迁移 | PR #4已合并；role、实时授权、Key兑换、单价及设置已交付 |
| 夏思凯 | capability、市场/Console运营区、契约/SQL | PR #5已合并；内部详情、管理保护、Schema与市场入口已交付 |

共享类型按契约增量修改，不覆盖其他成员功能。GitHub账号 `EGOIST-001`、`xsk-os` 的仓库读写权限已于2026-10-20通过只读API核实；不等于他们已执行人工Review。

## 黄禹菲交接结果

- 注册默认user，防注册/资料自助提权；登录/资料返回role，已有账号迁移默认普通用户。
- `GET /internal/user/authorization?user_id=<当前ID>&required_role=admin` 查询当前角色和账号状态；匹配身份、normal/admin/authorized=true才授权。
- 权限不足1006；API Key不存在也保留1006，由端点/消息区分。1001身份错误、1005禁用/不存在、依赖异常失败关闭。
- `POST /api/user/apikeys/exchange` 校验Secret摘要、所有者/账号/Key状态和期限；TTL默认900秒、硬上限3600秒且不晚于Key到期。
- Settings提供资料、积分和Key生命周期；Secret仅创建展示一次、不持久化。登录JWT的既有localStorage行为未改，不与Secret混淆。
- billing独立保存nullable unit_price，历史未知保留NULL；全局统计实时admin授权，个人数据隔离。
- user check在查库前拒绝query目标与当前身份不符；扣分及账单requestId重放比较关键字段，冲突3002。
- main基线user95/billing87项零跳过；真实兑换/计量/撤权/禁用链证据见[本人记录](implementation/member-黄禹菲.md)。

## 夏思凯交接结果

- `GET /internal/capability/{id}` 返回匹配ID/code/status、合法内联Schema和整数价格；未知/软删除2002，草稿/下架状态如实返回，由执行器拒绝。
- 分类/能力写与运营列表实时调用user授权；普通用户2007、依赖异常4002，无“未做好先放行”策略。
- chat-completions/long-summary的Schema/价格对齐实际执行器，未知code不能因登记service/path而自动执行。
- 市场仅公开已上架记录，字段最小化；按钮携带选中ID到Chat，Console展示真实服务端拒绝。
- `03_align_executor_schema.sql`仅升级完整旧默认Schema或online空Schema；保留自定义、草稿/下架空Schema、价格/状态与软删除行。
- main基线capability131项零跳过、完整internal E2E及真实授权通过，见[本人记录](implementation/member-夏思凯.md)。

## 本次非部署收尾

1. 保持原Chat浏览器场景不变，先提取模块并取得提交 `255508e` 的9/9 CI。
2. 新增隔离QA账号准备与22项单测；公共工具共35项。
3. 增加真实Settings与管理员Console浏览器场景，源码882bb5b的CI39446101405已通过9/9、每模式32项，具体证据见[收尾记录](验收收尾记录-2026-10-20.md)；最终合并提交仍另核CI，不沿用旧模拟写响应报告。
4. 同步当前文档、验收矩阵、演示和恢复说明；验证后合入main，仅创建已确认候选Tag。

## 仍不属于本次自动交付

- 现有开发/生产数据库升级、环境部署与重启；未执行迁移不表示其现有Schema已经就绪。
- 真实外部模型供应商验收：E2E模型端是本地HTTP测试替身。
- 三人正式人工Review/签字与最终正式版本；不能由AI或候选Tag代签。

## Git与安全协作

从最新origin/main创建独立分支，PR目标main，develop未主动同步前不作起点。常规Review要求仍保留；仓库所有者于2026-10-20暂时关闭main保护并明确授权本轮验证后合并，不外推到后续任务。

交付须有实现/契约、兼容迁移、同提交CI和真实依赖证据、已知限制及恢复位置。保留旧代码、原始证据和.env；数据库测试只用隔离实例，不删测试、跳测、清开发库或删卷。

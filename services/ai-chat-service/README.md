# AICapabilityHub Pro · 受控能力执行服务

ai-chat-service连接目录、Schema、聊天/摘要adapter和计量，拥有ai_chat_db。已经随PR #2合入main；内部目录服务端已交付并通过strict internal真实链；market仅保留显式兼容，不自动回退。

主规范见[开发指南](../../AICapabilityHubPro-开发指南.md)、[能力执行契约](../../docs/api-contract/ai-chat-service.md)及[共享契约](../../docs/api-contract/pro-shared.md)。

## 入口与行为

- POST /api/chat/completions：capability_id与input；旧顶层messages缺省能力1，仍重新校验目录。
- GET /api/chat/executors：已实现code与当前目录模式，不保证所有登记条目可执行。
- GET /api/chat/sessions、/sessions/{id}/messages：仅当前用户，会话越权4004。
- GET /health公开；/api/chat/ping经Gateway需登录。

执行顺序：身份→目录→状态/code/Schema/adapter输入→积分→会话/用户消息→模型→助手消息→收据→本地提交。

聊天1–40条、末条user、内容1–12000；摘要text非空白≤12000、max_length整数30–1000默认200，不续接session。stream=true和客户端价格/URL等拒绝。未知adapter2008，不执行登记service/path。

目录价贯穿预检与points，degraded=0，结果返回真实能力ID、价格、费用、账单与requestId。POINTS_COST只留历史配置，不决定Pro费用。

## 启动

根目录初始化、并行中间件和user/capability/billing就绪后：

```powershell
python scripts/start_leader_dev.py ai-chat-service --catalog-mode internal
```

使用Pro DB3307/Nacos8849，监听8090。默认internal要求GET /internal/capability/{id}；缺失失败关闭，不自动换来源。该端点已在main交付，两种模式分别有完整E2E；已有库需先备份核验成员增量迁移，本轮未操作现有环境。

ENABLE_INTERNAL_CHAIN=false仅测试，仍查目录/校验输入，结果not_reported，不得作为计费通过。真实登录和模型Mock开关彼此独立。

## 模型与事务

USE_MOCK=true时聊天模拟回复、摘要从输入提取并标明mock，不访问外部模型。真实模式使用服务端MODEL_BASE_URL/MODEL_API_KEY；超时5001或坏响应5002成为degraded结果，实际费用0，仍留记录。

Nacos热更新仅use_mock/model_base_url/model_api_key，通过不可变快照保持并发一致；凭据不打印、不写SDK配置缓存。提示词、超时、最大tokens等由部署配置提供，不把未知配置写成支持。

本地消息回滚不能撤销远端已提交账单/扣分；按requestId对账，不宣称分布式原子性，不盲目重试模型。此模块没有新增表列，schema以sql/01_init.sql为准。

## 验收

当前业务基线AI56项，覆盖目录、输入、计量、回滚和失败关闭。fixture会清990001/990002测试用户会话，必须独立MySQL，JUnit零跳过；真实服务E2E使用独立库和HTTP模型替身。

main651275b的CI39420321602为9/9，四服务369项零跳过，market/internal E2E22/21、原浏览器各9，内部契约为true。本轮新增真实Settings/Console验收见[收尾记录](../../docs/验收收尾记录-2026-10-20.md)，不代替部署/真实供应商或正式签字。

# ai-chat-service

对话能力服务：独立使用 ai_chat_db，提供多轮对话（Mock / OpenAI 兼容真实模型）、会话与消息落库查询，以及 user/billing 内部链路（校验积分 → 执行能力 → 上报计费）。

## 启动

1. 将 .env.example 复制为 .env，并按本机环境修改。
2. 执行 python -m pip install -r requirements.txt。
3. 执行 python -m uvicorn app.main:app --host 127.0.0.1 --port 8090。

GET /health 返回统一 Result 且 data.status 为 UP；GET /api/chat/ping 可验证 X-User-Id、X-User-Name、X-Request-Id 透传。Nacos 可用时服务每 5 秒发送心跳；Nacos 暂不可用时服务仍可启动并在后台持续重试。

## Nacos 模型配置热更新

服务默认监听 dataId `ai-chat-service-model.json`、group `DEFAULT_GROUP`。JSON 仅包含以下三个字段：

```json
{
  "use_mock": true,
  "model_base_url": "https://api.example.com/v1",
  "model_api_key": "replace-me"
}
```

启动时会先通过 Nacos 配置接口拉取配置，之后每 5 秒检查一次变更；发布有效变更后，新的请求直接读取更新后的运行时快照，无需重启。配置读取不启用 SDK 磁盘快照，不把模型 Key 写入工作区缓存。`.env` 中的 `USE_MOCK`、`MODEL_BASE_URL`、`MODEL_API_KEY` 是安全回退，Nacos 暂不可用、配置为空或格式无效时继续使用本地值或最近一次有效配置。

Windows PowerShell 发布示例：

```powershell
$modelConfig = @{
    use_mock = $true
    model_base_url = 'https://api.example.com/v1'
    model_api_key = 'replace-me'
} | ConvertTo-Json -Compress
Invoke-RestMethod `
    -Method Post `
    -Uri 'http://localhost:8848/nacos/v1/cs/configs' `
    -ContentType 'application/x-www-form-urlencoded' `
    -Body @{ dataId = 'ai-chat-service-model.json'; group = 'DEFAULT_GROUP'; type = 'json'; content = $modelConfig } |
    Out-Null
Write-Host 'Nacos 模型配置发布请求已提交，未输出配置内容。'
```

示例只使用 `replace-me`，不要在命令输出、应用日志或仓库中展示真实模型 Key。

## 分层约束

按 models、schemas、repository、service、api 分层扩展。服务间调用必须通过 app.core.service_call.call_internal 访问 /internal/**，不得写死其它服务地址。

POST /api/chat/completions 接受 OpenAI 风格 messages，`session_id` 为空时新建会话，传入时续接当前用户自己的会话（他人会话返回 `4004`）。USE_MOCK=true 时返回固定 Mock 回复且不访问外部模型；false 时调用 Nacos 配置的 OpenAI 兼容接口，超时（`5001`）或响应异常（`5002`）按指南 3.4 返回兜底话术并标记 `degraded`，闭环不中断。

## 落库与事务

- 每次对话写入 `t_chat_session`（新建或刷新 `last_message_time`）与两条 `t_chat_message`（用户消息 + 助手消息，含 `call_status`、`token_count`）；
- 会话标题取自首条用户消息，超过 30 字截断；
- 全流程共用一个事务：积分不足（3001）、下游不可用（4002）等异常会整体回滚，不留半成功状态；
- 降级调用不扣积分（上报 `points=0`），但照常写调用流水，便于运营观察失败率。

GET `/api/chat/sessions` 与 GET `/api/chat/sessions/{id}/messages` 读取当前用户的软删除过滤数据，会话列表按 `last_message_time` 倒序。

联调 user-service 与 billing-service 时保持 `ENABLE_INTERNAL_CHAIN=true`（默认值）：服务会按“校验用户积分 → 执行 Mock 或模型 → 上报计费”顺序调用 `/internal/**`，并透传当前 requestId；单独调试本服务时可设为 `false`，Mock 对话将不依赖任何下游。

## 测试

    python -m pytest -q

不依赖数据库的用例（健康检查、参数校验）始终执行；落库与内部链路用例需要可用的 `ai_chat_db`（已执行 `sql/01_init.sql`），数据库不可用时自动跳过。测试使用固定数字用户 990001/990002，用例前后物理清理，不影响演示数据。

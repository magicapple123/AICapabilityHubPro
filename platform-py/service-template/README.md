# AICapabilityHub Pro · Python 微服务模板

本模板统一 Pro 服务的配置、响应、日志、服务发现和内部调用边界，为能力执行与计量链提供基础设施。它本身不是新增的可执行 AI 能力，复制后仍须实现并验收业务。

复制整个目录后，配置独立服务名、端口和数据库地址，再按 `models -> schemas -> repository -> service -> api` 分层填入业务。服务名和接口属于兼容标识，产品文案遵循[项目定位与描述规范](../../docs/项目定位与描述规范.md)。

## 本地启动

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099
```

启动后访问 `http://localhost:8099/health`。Nacos 可用时，服务会注册为 `demo-service` 并每 5 秒发送一次心跳；Nacos 暂不可用不会阻止本地服务启动，后台线程会继续重试。

## Nacos 模型配置热更新

按 `.env.example` 启动时，模板默认每 5 秒通过 Nacos 配置接口检查 dataId `demo-service-model.json`、group `DEFAULT_GROUP`。配置读取不启用 SDK 磁盘快照，不把模型 Key 写入工作区缓存。配置内容是 JSON，且仅支持三个字段：

```json
{
  "use_mock": true,
  "model_base_url": "https://api.example.com/v1",
  "model_api_key": "replace-me"
}
```

应用启动后会先拉取该配置，再监听后续变更；发布有效配置后运行时快照自动更新，无需重启。复制 `.env.example` 得到的本地 `.env` 是安全回退，Nacos 暂不可用、内容为空或 JSON 无效时会继续使用本地值或最近一次有效配置。

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
    -Body @{ dataId = 'demo-service-model.json'; group = 'DEFAULT_GROUP'; type = 'json'; content = $modelConfig } |
    Out-Null
Write-Host 'Nacos 模型配置发布请求已提交，未输出配置内容。'
```

示例只使用 `replace-me`。不要在命令输出、日志或仓库文件中展示真实模型 Key；真实 `.env` 也不得提交。

## 分层约束

- `api` 只负责参数接收、依赖注入与 `Result` 封装。
- `service` 承载业务流程，`repository` 只负责数据访问。
- 服务间调用只能通过 `call_internal` 访问 `/internal/**`，不得写死其它服务地址。
- 所有接口返回 `Result{code,message,data,requestId}`；业务错误使用 HTTP 200 和业务错误码区分。
- 配置仅从 `.env` 或 Nacos 获取，真实 `.env`、密码、JWT 和模型密钥不得提交或写入日志。

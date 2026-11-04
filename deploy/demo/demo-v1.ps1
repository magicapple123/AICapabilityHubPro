# 演示用：打印模型列表 + 发一次真实对话。
# Key 从同目录 demo-key.txt 读取，不出现在命令行、也不上镜。
# 用法（在 deploy\demo 目录）：
#   powershell -ExecutionPolicy Bypass -File .\demo-v1.ps1
# 端口不是 80 时（例如直连网关 8080）：
#   powershell -ExecutionPolicy Bypass -File .\demo-v1.ps1 -BaseUrl http://localhost:8080

param([string]$BaseUrl = "http://localhost")

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd("/")
$keyFile = Join-Path $PSScriptRoot "demo-key.txt"

if (-not (Test-Path $keyFile)) {
    Write-Host "缺少 demo-key.txt：把 sk_ 开头的 Secret 粘进去（与本脚本同目录）" -ForegroundColor Yellow
    exit 1
}

$key = (Get-Content $keyFile -Raw).Trim()
if ($key -notmatch '^sk_') {
    Write-Host "demo-key.txt 的内容不像 Secret（应以 sk_ 开头）" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== GET /v1/models ===" -ForegroundColor Cyan
curl.exe -s -H "Authorization: Bearer $key" "$base/v1/models"
Write-Host ""

Write-Host "=== POST /v1/chat/completions ===" -ForegroundColor Cyan
$payload = '{"model":"deepseek-chat","messages":[{"role":"user","content":"用一句话介绍你自己"}],"max_tokens":60}'
$tmp = Join-Path $env:TEMP "demo-chat-body.json"
# 用 UTF-8（无 BOM）写临时文件，避免命令行传中文时的编码问题
[IO.File]::WriteAllText($tmp, $payload, (New-Object System.Text.UTF8Encoding($false)))
curl.exe -s -X POST "$base/v1/chat/completions" `
    -H "Authorization: Bearer $key" `
    -H "Content-Type: application/json" `
    --data-binary "@$tmp"
Write-Host ""
Write-Host ""

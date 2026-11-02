# F4 备份与恢复
#
# 为什么用 mysqldump 而不是冷拷贝：四个库都在同一个 MySQL 实例里，
# 冷拷贝需要停实例，成本高于 dump；dump 还能单独恢复某一个库。
#
# 用法：
#   powershell -File scripts/backup_db.ps1
#   powershell -File scripts/backup_db.ps1 -OutDir D:\backup
#
# 产出：<OutDir>\<yyyyMMdd-HHmmss>\<db>.sql，外加 manifest.json（含行数与大小）。
# 连接参数优先取环境变量，其次取这里的默认值（仅本机开发实例）。

param(
    [string]$OutDir = "artifacts/db-backup",
    [string]$DbHost = $(if ($env:GATE_DB_HOST) { $env:GATE_DB_HOST } else { "127.0.0.1" }),
    [int]$Port = $(if ($env:GATE_DB_PORT) { [int]$env:GATE_DB_PORT } else { 3307 }),
    [string]$User = "root",
    [string]$Password = $env:MYSQL_ROOT_PASSWORD,
    [string]$MysqlBin = "D:\MySQL\MySQL Server 8.4\bin"
)

$ErrorActionPreference = "Stop"
$databases = @("user_db", "capability_db", "billing_db", "ai_chat_db")

if (-not $Password) {
    throw "缺少密码：请设置 MYSQL_ROOT_PASSWORD 环境变量，或用 -Password 传入（不要写进仓库）。"
}

$dump = Join-Path $MysqlBin "mysqldump.exe"
if (-not (Test-Path $dump)) { throw "找不到 mysqldump：$dump" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $OutDir $stamp
New-Item -ItemType Directory -Force -Path $target | Out-Null

$manifest = @()
foreach ($db in $databases) {
    $file = Join-Path $target "$db.sql"
    # 关键：用 mysqldump 自己的 --result-file 写文件，不经 PowerShell 管道。
    # 管道会按控制台编码解码子进程输出，UTF-8 中文注释会被转成乱码并写坏 SQL。
    & $dump --host=$DbHost --port=$Port --user=$User "--password=$Password" `
        --single-transaction --quick --routines --default-character-set=utf8mb4 `
        --skip-add-drop-database "--result-file=$file" $db 2>$null
    if ($LASTEXITCODE -ne 0) { throw "备份失败：$db" }

    $size = (Get-Item $file).Length
    $manifest += [pscustomobject]@{ database = $db; file = "$db.sql"; bytes = $size }
    Write-Host ("[backup] {0} -> {1} ({2:N0} bytes)" -f $db, $file, $size)
}

$manifest | ConvertTo-Json -Depth 3 | Out-File -FilePath (Join-Path $target "manifest.json") -Encoding utf8
Write-Host ("备份完成：{0}" -f $target)

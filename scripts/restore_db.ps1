# F4 恢复（含演练）
#
# 默认恢复到**临时库名**（<db>_restore_check），不会覆盖生产库；
# 确认无误后再用 -TargetSuffix "" 原地恢复。
#
# 用法：
#   # 演练：恢复到 <db>_restore_check 并比对表数量，验证完自动删除临时库
#   powershell -File scripts/restore_db.ps1 -BackupDir artifacts/db-backup/20261102-171500 -Verify
#
#   # 真实恢复（危险）：覆盖原库
#   powershell -File scripts/restore_db.ps1 -BackupDir <dir> -TargetSuffix "" -Confirm

param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [string]$TargetSuffix = "_restore_check",
    [switch]$Verify,
    [switch]$Confirm,
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
if (-not $Confirm -and $TargetSuffix -eq "") {
    throw "原地恢复会覆盖现有数据：请加 -Confirm 明确确认。"
}

$mysql = Join-Path $MysqlBin "mysql.exe"
$dump = Join-Path $MysqlBin "mysqldump.exe"
if (-not (Test-Path $mysql)) { throw "找不到 mysql 客户端：$mysql" }

function Invoke-Sql([string]$sql) {
    & $mysql --host=$DbHost --port=$Port --user=$User "--password=$Password" -N -B -e $sql 2>$null
}

foreach ($db in $databases) {
    $source = Join-Path $BackupDir "$db.sql"
    if (-not (Test-Path $source)) { throw "缺少备份文件：$source" }
}

# 清空目标库再导入 dump（dump 自带 CREATE DATABASE 原库名，需要改写语句）
foreach ($db in $databases) {
    $target = "$db$TargetSuffix"
    Invoke-Sql "DROP DATABASE IF EXISTS ``$target``; CREATE DATABASE ``$target`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" | Out-Null
    Write-Host "[restore] 准备目标库 $target"

    $source = Join-Path $BackupDir "$db.sql"
    # dump 不含 CREATE DATABASE / USE（备份时未用 --databases），
    # 直接导入已建好的目标库即可，无需改写 SQL 文本、不碰编码。
    $sourceForMysql = $source -replace '\\', '/'
    & $mysql --host=$DbHost --port=$Port --user=$User "--password=$Password" `
        --default-character-set=utf8mb4 $target -e "source $sourceForMysql"
    if ($LASTEXITCODE -ne 0) { throw "恢复失败：$target" }
}

if ($Verify) {
    $report = @()
    foreach ($db in $databases) {
        $target = "$db$TargetSuffix"
        $tables = (Invoke-Sql "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$target'").Trim()
        $sourceTables = (Invoke-Sql "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$db'").Trim()
        $report += [pscustomobject]@{ database = $target; tables = $tables; source_tables = $sourceTables }
        Write-Host ("[verify] {0}: {1} 张表（原库 {2} 张）" -f $target, $tables, $sourceTables)
    }
    $mismatch = $report | Where-Object { $_.tables -ne $_.source_tables }
    if ($mismatch) { throw "恢复校验失败：表数量不一致" }
    Write-Host "[verify] 表数量一致，演练通过；清理临时库"
    foreach ($db in $databases) { Invoke-Sql "DROP DATABASE IF EXISTS ``$db$TargetSuffix``;" | Out-Null }
}
else {
    Write-Host "恢复完成（未校验）。如需演练请加 -Verify。"
}

<#
.SYNOPSIS
    AICapabilityHub Pro 首次部署引导：等库就绪 → 应用四个库迁移 → 建管理员 → 导入能力目录 → 初始化积分。

.DESCRIPTION
    幂等：每一步都先查状态再决定动不动作，重复执行不会重复建表、重复建账号、
    重复发积分。可安全地在每次部署/重启后跑一遍。

    数据访问统一走 `docker exec`（容器内 mysql 客户端），不依赖宿主机装 mysql 客户端，
    也不把口令写进命令行参数（用 MYSQL_PWD 环境变量传入，ps/日志里看不到）。

    迁移登记表：每个库建 `schema_migration`，按「服务名/文件名」记录已应用的脚本，
    重跑时打印 SKIP。这是唯一能区分「新机器」与「已初始化机器」的依据。

.PARAMETER MysqlContainer
    MySQL 容器名，默认 aihub-pro-mysql（deploy/docker-compose.yml 里的 container_name）。

.PARAMETER RootPassword
    MySQL root 口令；缺省从 deploy/.env 的 MYSQL_ROOT_PASSWORD 读，读不到再读仓库根 .env。

.PARAMETER AdminUsername
    管理员登录名；缺省读 deploy/.env 的 BOOTSTRAP_ADMIN_USERNAME，再缺省 admin。

.PARAMETER AdminPassword
    管理员口令；缺省读 BOOTSTRAP_ADMIN_PASSWORD。两者都为空时**随机生成 16 位并打印**（不设内置默认口令）。
    脚本只在账号不存在时写入，已存在不会重置口令。

.PARAMETER AdminPoints
    管理员初始积分；缺省读 BOOTSTRAP_ADMIN_POINTS，再缺省 1000。账户已存在时不改余额。

.PARAMETER WaitSeconds
    等 MySQL 就绪的最长秒数，默认 120。

.PARAMETER SkipSeed
    只建表/建账号，不补能力目录种子（已有生产目录时用）。

.PARAMETER Check
    只做前置检查（docker / 容器 / 库连通 / 配置是否齐全），不改任何数据。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_stack.ps1 -Check

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_stack.ps1

.NOTES
    退出码：0 全部就绪 / 10 前置检查失败 / 20 MySQL 未就绪 / 30 迁移失败 / 40 账号或积分失败
    文件编码：UTF-8 with BOM（PowerShell 5.1 解析中文必需）
#>
[CmdletBinding()]
param(
    [string]$MysqlContainer = 'aihub-pro-mysql',
    [string]$RootPassword,
    [string]$AdminUsername,
    [string]$AdminPassword,
    [int]$AdminPoints = 0,
    [int]$WaitSeconds = 120,
    [switch]$SkipSeed,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
} catch {
    Write-Output '（提示）当前终端不允许切换输出编码，中文可能显示为乱码，不影响执行。'
}

$script:Root = Split-Path -Parent $PSScriptRoot

# ---------------------------------------------------------------------------
# 输出助手：每步一行状态，便于人工核对与日志留痕
# ---------------------------------------------------------------------------
function Write-Step([string]$Text) { Write-Output ''; Write-Output "== $Text ==" }
function Write-Ok([string]$Text) { Write-Output "  [OK]      $Text" }
function Write-Skip([string]$Text) { Write-Output "  [SKIP]    $Text" }
function Write-Warn([string]$Text) { Write-Output "  [WARN]    $Text" }
function Write-Detail([string]$Text) { Write-Output "            $Text" }

function Stop-With([int]$Code, [string]$Message) {
    Write-Output ''
    Write-Output "== 失败：$Message =="
    exit $Code
}

# ---------------------------------------------------------------------------
# 配置解析：deploy/.env 优先（compose 读的就是它），仓库根 .env 兜底
# ---------------------------------------------------------------------------
function Read-DotEnv([string]$Path) {
    $values = @{}
    if (-not (Test-Path $Path)) { return $values }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $index = $trimmed.IndexOf('=')
        if ($index -lt 1) { continue }
        $key = $trimmed.Substring(0, $index).Trim()
        $value = $trimmed.Substring($index + 1).Trim()
        if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'") -and $value[0] -eq $value[-1]) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

$deployEnv = Read-DotEnv (Join-Path $script:Root 'deploy\.env')
$rootEnv = Read-DotEnv (Join-Path $script:Root '.env')

if (-not $RootPassword) { $RootPassword = $deployEnv['MYSQL_ROOT_PASSWORD']; if (-not $RootPassword) { $RootPassword = $rootEnv['MYSQL_ROOT_PASSWORD'] } }
if (-not $AdminUsername) { $AdminUsername = $deployEnv['BOOTSTRAP_ADMIN_USERNAME']; if (-not $AdminUsername) { $AdminUsername = 'admin' } }
if (-not $AdminPassword) { $AdminPassword = $deployEnv['BOOTSTRAP_ADMIN_PASSWORD'] }
if (-not $AdminPassword) {
    # 安全红线：不提供任何内置默认口令。缺失时随机生成一次并打印，部署方须自行保存并尽快改掉。
    # 用 Create()+GetBytes 而不是静态 Fill()：后者在 Windows PowerShell 5.1（.NET Framework）上没有。
    # 循环兜底：base64 里的 + / = 被剔除后仍要保证 16 位。
    do {
        $bytes = [byte[]]::new(18)
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $AdminPassword = ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', '')
    } while ($AdminPassword.Length -lt 16)
    $AdminPassword = $AdminPassword.Substring(0, 16)
    $script:GeneratedAdminPassword = $true
}
if ($AdminPoints -le 0) {
    $AdminPoints = 1000
    if ($deployEnv['BOOTSTRAP_ADMIN_POINTS'] -match '^\d+$') { $AdminPoints = [int]$deployEnv['BOOTSTRAP_ADMIN_POINTS'] }
}

# 服务 → 数据库。顺序即迁移顺序：先有用户与目录，再计费，最后对话。
$Services = [ordered]@{
    'user-service'       = 'user_db'
    'capability-service' = 'capability_db'
    'billing-service'    = 'billing_db'
    'ai-chat-service'    = 'ai_chat_db'
}

# ---------------------------------------------------------------------------
# docker / mysql 调用封装
# ---------------------------------------------------------------------------
function Resolve-DockerCli {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'))) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

$script:Docker = Resolve-DockerCli

<#
.SYNOPSIS
    在容器里执行一条 SQL，返回制表符分隔的纯文本（-N -B）。
.DESCRIPTION
    口令用 MYSQL_PWD 环境变量传入，不出现在进程参数里。
    任何非 0 退出码都转成异常，由调用方决定是致命还是可忽略。
#>
function Invoke-Mysql([string]$Database, [string]$Sql, [switch]$AllowFailure) {
    $arguments = @('exec', '-e', "MYSQL_PWD=$RootPassword", $MysqlContainer,
        'mysql', '-uroot', '--default-character-set=utf8mb4', '-N', '-B')
    if ($Database) { $arguments += @('-D', $Database) }
    $arguments += @('-e', $Sql)
    $output = & $script:Docker @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($AllowFailure) { return $null }
        throw "MySQL 语句执行失败（库 $Database）：$($output -join ' ')"
    }
    return ($output | Out-String).Trim()
}

<#
.SYNOPSIS
    把 SQL 文件拷进容器再 `mysql < file` 执行。
.DESCRIPTION
    不用 PowerShell 管道喂文件：管道会经历一次编码转换，中文注释与 DELIMITER
    块存在被破坏的风险；docker cp + 容器内重定向是逐字节复制，最稳。
    迁移脚本本身都是「重复执行安全」的（见各文件头注释）。
#>
function Invoke-SqlFile([string]$ServiceName, [string]$Path) {
    $name = Split-Path -Leaf $Path
    $remote = "/tmp/aichub-migrate-$([guid]::NewGuid().ToString('N').Substring(0, 8)).sql"
    & $script:Docker cp $Path "${MysqlContainer}:${remote}" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "拷贝迁移文件失败：$name" }
    try {
        $output = & $script:Docker exec -e "MYSQL_PWD=$RootPassword" $MysqlContainer `
            sh -c "mysql -uroot --default-character-set=utf8mb4 < $remote" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "执行迁移失败：$ServiceName/$name`n$($output -join ' ')" }
    } finally {
        & $script:Docker exec $MysqlContainer rm -f $remote 2>&1 | Out-Null
    }
}

function ConvertTo-Pbkdf2Hash([string]$Password) {
    # 与 services/user-service/app/core/password.py 完全一致：
    # pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>，SHA256，24 万次迭代，16 字节盐。
    $iterations = 240000
    $salt = New-Object byte[] 16
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($salt) } finally { $rng.Dispose() }
    $kdf = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
        [System.Text.Encoding]::UTF8.GetBytes($Password), $salt, $iterations,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256)
    try { $digest = $kdf.GetBytes(32) } finally { $kdf.Dispose() }
    $saltHex = ([System.BitConverter]::ToString($salt) -replace '-', '').ToLowerInvariant()
    $digestHex = ([System.BitConverter]::ToString($digest) -replace '-', '').ToLowerInvariant()
    return "pbkdf2_sha256`$$iterations`$$saltHex`$$digestHex"
}

# ---------------------------------------------------------------------------
# 1/6 前置检查
# ---------------------------------------------------------------------------
Write-Step '1/6 前置检查'
if (-not $script:Docker) { Stop-With 10 '未找到 docker.exe，请先安装 Docker Desktop 并重开终端' }
Write-Ok "docker CLI  $script:Docker"
if (-not $RootPassword) { Stop-With 10 '缺少 MYSQL_ROOT_PASSWORD：请先 cp deploy/.env.template deploy/.env 并填写' }

$containerState = & $script:Docker inspect -f '{{.State.Status}}' $MysqlContainer 2>$null
if ($LASTEXITCODE -ne 0 -or -not $containerState) {
    Stop-With 10 "容器 $MysqlContainer 不存在：先执行 docker compose -f deploy/docker-compose.yml up -d"
}
Write-Ok "MySQL 容器   $MysqlContainer（$containerState）"
Write-Ok "管理员账号   $AdminUsername（初始积分 $AdminPoints，仅在不存在时创建）"

if ($Check) {
    Write-Step '前置检查结果'
    Write-Ok '配置齐全，容器存在（-Check 模式未改任何数据）'
    exit 0
}

# ---------------------------------------------------------------------------
# 2/6 等 MySQL 就绪（容器 running 不等于能连）
# ---------------------------------------------------------------------------
Write-Step '2/6 等待 MySQL 就绪'
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$ready = $false
while ((Get-Date) -lt $deadline) {
    # 只 ping 不够：mysql:8.4 首次初始化时会先起一个临时实例跑 init 脚本，
    # 那个实例对 ping 有响应但 root 口令还没生效，此时建表会 Access denied。
    # 因此用「带口令的 SELECT 1」作为就绪判据，只有真正可写才往下走。
    $probe = & $script:Docker exec -e "MYSQL_PWD=$RootPassword" $MysqlContainer `
        mysql -uroot -N -B -e 'SELECT 1;' 2>&1
    if ($LASTEXITCODE -eq 0 -and ($probe | Out-String).Trim() -eq '1') { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Stop-With 20 "MySQL 在 $WaitSeconds 秒内未就绪：docker logs $MysqlContainer --tail 50 查看，常见原因是数据卷损坏或口令与 .env 不一致"
}
$version = Invoke-Mysql '' 'SELECT VERSION();' -AllowFailure
Write-Ok "MySQL 可连接  version=$version"

# ---------------------------------------------------------------------------
# 3/6 逐个库应用迁移（登记表去重）
# ---------------------------------------------------------------------------
Write-Step '3/6 应用数据库迁移'
$applied = 0
$skipped = 0
foreach ($service in $Services.Keys) {
    $database = $Services[$service]
    $sqlDir = Join-Path $script:Root "services\$service\sql"
    if (-not (Test-Path $sqlDir)) { Stop-With 30 "缺少迁移目录：services\$service\sql" }

    # 新机器上库还不存在：先建库再建登记表（01_init.sql 里也有 CREATE DATABASE，
    # 这里提前建是为了让登记表有落点，两边都是 IF NOT EXISTS，重复执行安全）。
    $null = Invoke-Mysql '' "CREATE DATABASE IF NOT EXISTS $database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    $null = Invoke-Mysql $database @"
CREATE TABLE IF NOT EXISTS schema_migration (
  version VARCHAR(160) NOT NULL COMMENT '服务名/迁移文件名',
  checksum CHAR(64) NOT NULL DEFAULT '' COMMENT '文件 SHA256，用于发现「已应用但文件被改」',
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='迁移登记表，由 bootstrap_stack.ps1 维护';
"@

    $files = Get-ChildItem -Path $sqlDir -Filter '*.sql' | Sort-Object Name
    Write-Output "  -- $service（$database，$($files.Count) 个脚本）"
    foreach ($file in $files) {
        # 02_seed.sql 是空库初始化样例，不是升级迁移；Docker 首次启动已处理。
        # 重放它可能覆盖演示用户/账单，因此只在后续的空目录检查中决定是否导入 capability seed。
        if ($file.Name -eq '02_seed.sql') {
            Write-Skip "$service/$($file.Name)（初始化 seed，不作为增量迁移重放）"
            continue
        }
        $version = "$service/$($file.Name)"
        $checksum = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $recorded = Invoke-Mysql $database "SELECT checksum FROM schema_migration WHERE version='$version';" -AllowFailure
        if ($recorded) {
            if ($recorded -ne $checksum) {
                Write-Warn "$version 已应用，但文件内容已变（checksum 不一致）；不会自动重跑，需要时手工处理"
            } else {
                Write-Skip $version
            }
            $skipped++
            continue
        }
        try {
            Invoke-SqlFile $service $file.FullName
        } catch {
            Stop-With 30 ($_.Exception.Message)
        }
        $null = Invoke-Mysql $database "INSERT INTO schema_migration (version, checksum) VALUES ('$version', '$checksum') ON DUPLICATE KEY UPDATE checksum=VALUES(checksum);"
        Write-Ok $version
        $applied++
    }
}
Write-Detail "本次应用 $applied 个，跳过 $skipped 个（已登记）"

# ---------------------------------------------------------------------------
# 4/6 管理员账号（不存在才建）
# ---------------------------------------------------------------------------
Write-Step '4/6 管理员账号'
$existing = Invoke-Mysql 'user_db' "SELECT id FROM t_user WHERE username='$AdminUsername' AND is_deleted=0 LIMIT 1;" -AllowFailure
if ($existing) {
    $role = Invoke-Mysql 'user_db' "SELECT role FROM t_user WHERE id=$existing;"
    Write-Skip "账号已存在 id=$existing role=$role（不重置口令）"
    if ($role -ne 'admin') {
        Write-Warn "该账号 role=$role，不是 admin；需要运营权限请手工改为 admin 或换一个用户名"
    }
} else {
    $hash = ConvertTo-Pbkdf2Hash $AdminPassword
    $null = Invoke-Mysql 'user_db' @"
INSERT INTO t_user (username, password_hash, role, nickname, status)
SELECT '$AdminUsername', '$hash', 'admin', '系统管理员', 'normal' FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM t_user WHERE username='$AdminUsername' AND is_deleted=0);
"@
    $adminId = Invoke-Mysql 'user_db' "SELECT id FROM t_user WHERE username='$AdminUsername' AND is_deleted=0 LIMIT 1;"
    Write-Ok "已创建管理员 $AdminUsername（id=$adminId，role=admin）"
}

# ---------------------------------------------------------------------------
# 5/6 能力目录种子
# ---------------------------------------------------------------------------
Write-Step '5/6 能力目录'
$online = Invoke-Mysql 'capability_db' "SELECT COUNT(*) FROM t_capability WHERE status='online' AND is_deleted=0;"
if (-not $online) { Stop-With 40 '读取能力目录失败：capability_db 迁移可能未完成' }
if ([int]$online -gt 0) {
    Write-Skip "已有 $online 个上架能力，不覆盖（目录由运营维护）"
} elseif ($SkipSeed) {
    Write-Warn '目录为空，但按 -SkipSeed 跳过种子导入'
} else {
    $seed = Join-Path $script:Root 'services\capability-service\sql\02_seed.sql'
    if (-not (Test-Path $seed)) { Stop-With 40 '缺少种子文件 services\capability-service\sql\02_seed.sql' }
    Invoke-SqlFile 'capability-service' $seed
    $online = Invoke-Mysql 'capability_db' "SELECT COUNT(*) FROM t_capability WHERE status='online' AND is_deleted=0;"
    Write-Ok "已导入种子，当前上架能力 $online 个"
}
Write-Detail (Invoke-Mysql 'capability_db' "SELECT CONCAT(id, ' ', code, ' ', status, ' ', price_per_call, '分') FROM t_capability WHERE is_deleted=0 ORDER BY id;" | Out-String).Trim()

# ---------------------------------------------------------------------------
# 6/6 管理员积分
# ---------------------------------------------------------------------------
Write-Step '6/6 初始化积分'
$adminId = Invoke-Mysql 'user_db' "SELECT id FROM t_user WHERE username='$AdminUsername' AND is_deleted=0 LIMIT 1;"
if (-not $adminId) { Stop-With 40 '管理员账号不存在，无法初始化积分' }
$hasAccount = Invoke-Mysql 'user_db' "SELECT balance FROM t_points_account WHERE user_id=$adminId;"
if ($hasAccount -ne $null -and $hasAccount -ne '') {
    Write-Skip "积分账户已存在 balance=$hasAccount（不覆盖）"
} else {
    $null = Invoke-Mysql 'user_db' @"
INSERT INTO t_points_account (user_id, balance, frozen, version)
SELECT $adminId, $AdminPoints, 0, 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM t_points_account WHERE user_id=$adminId);

INSERT INTO t_points_log (user_id, direction, amount, balance_after, biz_type, request_id, remark)
SELECT $adminId, 'in', $AdminPoints, $AdminPoints, 'adjust', 'bootstrap-$AdminUsername', '引导脚本初始化管理员积分' FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM t_points_log WHERE request_id='bootstrap-$AdminUsername' AND is_deleted=0);
"@
    Write-Ok "已初始化管理员积分 balance=$AdminPoints（流水 request_id=bootstrap-$AdminUsername）"
}
$demoBalance = Invoke-Mysql 'user_db' "SELECT p.balance FROM t_points_account p JOIN t_user u ON u.id=p.user_id WHERE u.username='demo' AND u.is_deleted=0;"
if ($demoBalance) { Write-Detail "演示账号 demo 当前余额 $demoBalance（压测/演示前可用 scripts/set_user_points.py 调整）" }

Write-Step '完成'
Write-Ok "迁移 应用=$applied 跳过=$skipped"
if ($script:GeneratedAdminPassword) {
    Write-Warn "管理员 $AdminUsername 的初始口令是随机生成的：$AdminPassword"
    Write-Warn '该口令只在此处显示一次，请立即保存并在首次登录后修改（deploy/.env 里的 BOOTSTRAP_ADMIN_PASSWORD 可预先指定）。'
}
Write-Ok '下一步：docker compose -f deploy/docker-compose.yml --profile app up -d --build'
Write-Detail '然后执行 python scripts/acceptance_check.py --no-call 做交付验收'
exit 0

<#
.SYNOPSIS
    AICapabilityHub Pro 本地全栈一键启动（中文交互层）。

.DESCRIPTION
    本脚本只承担「人机交互」职责：中文开场提示、只读环境自检、前端端口解析、
    启动结果汇总与失败指引。真正的启动逻辑全部委托给 scripts\start-pro-stack.ps1。
    后者是唯一的启动真相源，本文件刻意不复制其中任何一行启动代码，
    避免两份逻辑漂移（双真相源是本项目已经踩过的坑）。

    可安全重复执行：已就绪的组件由 start-pro-stack.ps1 判定为 SKIP，
    不会重启正在运行的服务。

.PARAMETER Check
    只做环境自检，并把 -Check 透传给 start-pro-stack.ps1（打印解析出的
    root / python / docker 路径）。不启动任何服务、不打开浏览器。

.PARAMETER NoOpen
    完整启动但不自动打开浏览器，便于自动化验证、CI 或不想被打断的场景。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\one-click-start.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\one-click-start.ps1 -Check

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\one-click-start.ps1 -NoOpen

.NOTES
    退出码：0 一切就绪 / 10 环境自检未通过 / 20 启动脚本失败 / 30 启动后校验未通过
    文件编码：UTF-8 with BOM（PowerShell 5.1 需要 BOM 才能正确解析源码中的中文）
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$NoOpen
)

# ---------------------------------------------------------------------------
# 控制台编码：让中文在 cmd.exe 窗口里正常显示而不是乱码。
# start.cmd 已先执行 chcp 65001，这里再把 .NET 侧的输出编码对齐到无 BOM 的
# UTF-8，两者一致时中文才是「字节上是 UTF-8、控制台按 UTF-8 渲染」。
# 个别受限终端不允许改编码，此时退化为控制台默认编码，不应因此中断启动。
# ---------------------------------------------------------------------------
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
} catch {
    Write-Output '（提示）当前终端不允许切换输出编码，中文可能显示为乱码，但不影响启动。'
}

# ---------------------------------------------------------------------------
# 常量与路径
# ---------------------------------------------------------------------------
$script:Root = Split-Path -Parent $PSScriptRoot
$script:StackScript = Join-Path $script:Root 'scripts\start-pro-stack.ps1'
$script:WebEnvFile = Join-Path $script:Root 'web\.env'
$script:LogDir = Join-Path $script:Root 'logs\runtime'
# 前端端口的唯一真相源是 web\.env 的 VITE_PORT；这里的 5174 只是兜底值。
# 之所以不用 5173：本机 5173 已被另一个项目（ResumeForge）占用。
$script:DefaultWebPort = 5174
# 页面里必须出现这个关键字，才算「这个端口上跑的是本项目前端」，
# 而不是「端口上有个别人的服务」。与 start-pro-stack.ps1 保持一致。
$script:WebMarker = 'AICapabilityHub'
$script:ServiceMap = @(
    [pscustomobject]@{ Id = 'gateway';          Label = 'gateway (网关)';         Port = 8080 },
    [pscustomobject]@{ Id = 'user-service';     Label = 'user-service (用户服务)'; Port = 8081 },
    [pscustomobject]@{ Id = 'capability-service'; Label = 'capability-service (能力服务)'; Port = 8082 },
    [pscustomobject]@{ Id = 'billing-service';  Label = 'billing-service (计费服务)'; Port = 8083 },
    [pscustomobject]@{ Id = 'ai-chat-service';  Label = 'ai-chat-service (AI 对话)'; Port = 8090 }
)

# ---------------------------------------------------------------------------
# 只读辅助函数（全部是「检测」，不含任何启动动作）
# ---------------------------------------------------------------------------

<#
.SYNOPSIS
    在本项目中定位 Python 解释器（只读探测，不启动任何服务）。
.DESCRIPTION
    解析顺序与 start-pro-stack.ps1 保持一致：环境变量 PYTHON → 项目自带 venv →
    PATH 上的 python / python3。这样自检结论与真正启动时使用的解释器不会打架。
#>
function Resolve-ProjectPython {
    if ($env:PYTHON -and (Test-Path $env:PYTHON)) { return $env:PYTHON }
    $venvPython = Join-Path $script:Root 'services\user-service\.venv\Scripts\python.exe'
    if (Test-Path $venvPython) { return $venvPython }
    foreach ($name in 'python', 'python3') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

<#
.SYNOPSIS
    定位 docker CLI 可执行文件（只读探测）。
.DESCRIPTION
    先查 PATH，再查 Docker Desktop 的两个常见安装位置。找不到 docker.exe 时
    调用方应给出「请安装 Docker Desktop」的中文建议并中止。
#>
function Resolve-DockerCliPath {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    return $null
}

<#
.SYNOPSIS
    探测 Docker 引擎是否已经在运行（只读，不拉起 Docker Desktop）。
#>
function Test-DockerEngineRunning {
    param([string]$DockerCli)
    if (-not $DockerCli) { return $false }
    $null = & $DockerCli info 2>&1
    return ($LASTEXITCODE -eq 0)
}

<#
.SYNOPSIS
    判断端口是否处于监听状态。
.DESCRIPTION
    优先用 Get-NetTCPConnection；极少数精简系统没有 NetTCPIP 模块时，
    退回 System.Net.Sockets.TcpClient 探测，避免自检直接抛错。
#>
function Test-PortListening {
    param([int]$Port)
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        return [bool]$connection
    }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

<#
.SYNOPSIS
    判断该端口上是否真的在提供本项目的前端页面。
.DESCRIPTION
    仅「端口在监听」不足以证明前端就绪：别的项目也可能占着这个端口。
    这里要求 HTTP 200 且页面内容包含 AICapabilityHub 关键字。
    ProgressPreference 局部压低，避免 Invoke-WebRequest 的进度条文字插入输出。
#>
function Test-WebPage {
    param([int]$Port)
    if (-not (Test-PortListening -Port $Port)) { return $false }
    $previousProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$Port" -UseBasicParsing -TimeoutSec 5
        return ($response.StatusCode -eq 200 -and $response.Content -match $script:WebMarker)
    } catch {
        return $false
    } finally {
        $ProgressPreference = $previousProgress
    }
}

<#
.SYNOPSIS
    从 web\.env 解析 VITE_PORT，读不到时回退到兜底端口。
.DESCRIPTION
    正则 ^\s*VITE_PORT\s*=\s*(\d+) 与 start-pro-stack.ps1 保持一致，
    保证「汇总里显示的地址」与「启动脚本实际监听的端口」是同一个数。
#>
function Get-WebPort {
    $port = $script:DefaultWebPort
    if (Test-Path $script:WebEnvFile) {
        $match = Select-String -Path $script:WebEnvFile -Pattern '^\s*VITE_PORT\s*=\s*(\d+)' -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($match) { $port = [int]$match.Matches[0].Groups[1].Value }
    }
    return $port
}

<#
.SYNOPSIS
    输出一行带缩进的中文说明。
#>
function Write-Detail {
    param([string]$Text)
    Write-Output "  $Text"
}

# ---------------------------------------------------------------------------
# 开场
# ---------------------------------------------------------------------------
Write-Output '========================================================'
Write-Output '  AICapabilityHub Pro · 本地一键启动'
if ($Check) {
    Write-Output '  模式：环境自检（只检查环境，不启动任何服务）'
} else {
    Write-Output '  正在启动 AICapabilityHub Pro 本地全栈，首次启动约需 2-3 分钟'
    Write-Output '  已就绪的组件会自动跳过，重复执行是安全的'
}
Write-Output '========================================================'

# ---------------------------------------------------------------------------
# 1/4 环境自检（快速、只读）
# ---------------------------------------------------------------------------
Write-Output ''
Write-Output '== 1/4 环境自检 =='

$failures = New-Object System.Collections.Generic.List[string]

$dockerCli = Resolve-DockerCliPath
if ($dockerCli) {
    Write-Detail "[OK]   Docker CLI        $dockerCli"
} else {
    Write-Detail '[缺失] Docker CLI        未找到 docker.exe'
    $failures.Add('未找到 Docker CLI。请安装 Docker Desktop for Windows，安装后确认 docker 命令在 PATH 中（重开终端或重启后生效）。')
}

$pythonPath = Resolve-ProjectPython
if ($pythonPath) {
    Write-Detail "[OK]   Python            $pythonPath"
} else {
    Write-Detail '[缺失] Python            未找到 python / python3'
    $failures.Add('未找到 Python 3。请安装 Python 3.11+ 并在安装时勾选 "Add python.exe to PATH"，或设置环境变量 PYTHON 指向 python.exe 的完整路径。')
}

$nodeModules = Join-Path $script:Root 'web\node_modules'
if (Test-Path $nodeModules) {
    Write-Detail '[OK]   前端依赖          web\node_modules 已安装'
} else {
    Write-Detail '[缺失] 前端依赖          web\node_modules 不存在'
    $failures.Add('前端依赖未安装。请先执行：cd web 然后 pnpm install（或 npm install）。')
}

if (Test-Path $script:StackScript) {
    Write-Detail '[OK]   启动脚本          scripts\start-pro-stack.ps1'
} else {
    Write-Detail '[缺失] 启动脚本          scripts\start-pro-stack.ps1 不存在'
    $failures.Add('缺少 scripts\start-pro-stack.ps1。请确认当前目录是本项目根目录，且文件完整（没有被安全软件隔离）。')
}

# Docker 引擎没起不算致命：start-pro-stack.ps1 会自己拉起 Docker Desktop。
if ($dockerCli) {
    if (Test-DockerEngineRunning -DockerCli $dockerCli) {
        Write-Detail '[OK]   Docker 引擎       已在运行'
    } else {
        Write-Detail '[提示] Docker 引擎       未运行，启动时脚本会自动拉起 Docker Desktop（约 30-60 秒）'
    }
}

if ($failures.Count -gt 0) {
    Write-Output ''
    Write-Output '== 环境自检未通过，已中止（没有启动任何服务）=='
    foreach ($failure in $failures) {
        Write-Output "  · $failure"
    }
    Write-Output ''
    Write-Output '  处理完上面几项后重新双击 start.cmd 即可。'
    exit 10
}

# ---------------------------------------------------------------------------
# -Check：只透传，不启动
# ---------------------------------------------------------------------------
if ($Check) {
    Write-Output ''
    Write-Output '== 2/4 启动脚本路径自检（-Check 透传给 start-pro-stack.ps1）=='
    & $script:StackScript -Check | ForEach-Object { Write-Detail $_.ToString() }
    $stackCheckExit = $LASTEXITCODE
    if ($null -eq $stackCheckExit) { $stackCheckExit = 0 }
    if ($stackCheckExit -ne 0) {
        Write-Output ''
        Write-Output "== 失败：scripts\start-pro-stack.ps1 -Check 返回退出码 $stackCheckExit =="
        exit 20
    }
    Write-Output ''
    Write-Output '== 环境自检完成：一切正常，未启动任何服务 =='
    Write-Output '  正式启动请直接双击 start.cmd（或执行 start.cmd -NoOpen 不弹浏览器）。'
    exit 0
}

# ---------------------------------------------------------------------------
# 2/4 调用既有启动逻辑（唯一真相源，本脚本不含任何启动代码）
# ---------------------------------------------------------------------------
$webPort = Get-WebPort

Write-Output ''
Write-Output '== 2/4 启动本地全栈（以下为启动脚本的原始输出）=='
$startedAt = Get-Date
& $script:StackScript 2>&1 | ForEach-Object {
    if ($_ -is [System.Management.Automation.ErrorRecord]) {
        Write-Output ('  ! ' + $_.ToString())
    } else {
        Write-Output ('  ' + $_.ToString())
    }
}
$stackExit = $LASTEXITCODE
if ($null -eq $stackExit) { $stackExit = 0 }
$elapsedSeconds = [int]((Get-Date) - $startedAt).TotalSeconds
Write-Output "  （启动脚本耗时 $elapsedSeconds 秒，退出码 $stackExit）"

# ---------------------------------------------------------------------------
# 3/4 启动后校验：不轻信退出码，实际探测端口与页面
# ---------------------------------------------------------------------------
Write-Output ''
Write-Output '== 3/4 服务状态确认 =='

$allReady = $true
foreach ($service in $script:ServiceMap) {
    if (Test-PortListening -Port $service.Port) {
        Write-Output "  [OK]   $($service.Label)   端口 $($service.Port)"
    } else {
        Write-Output "  [DOWN] $($service.Label)   端口 $($service.Port) 未监听"
        $allReady = $false
    }
}

if (Test-WebPage -Port $webPort) {
    Write-Output "  [OK]   前端页面 (web)   端口 $webPort（已确认页面属于本项目）"
} elseif (Test-PortListening -Port $webPort) {
    Write-Output "  [WARN] 前端页面 (web)   端口 $webPort 被其它程序占用，不是本项目页面"
    $allReady = $false
} else {
    Write-Output "  [DOWN] 前端页面 (web)   端口 $webPort 未监听"
    $allReady = $false
}

# ---------------------------------------------------------------------------
# 失败处理
# ---------------------------------------------------------------------------
if ($stackExit -ne 0 -or -not $allReady) {
    Write-Output ''
    Write-Output '== 启动未完全成功 =='
    if ($stackExit -ne 0) {
        Write-Output "  · 启动脚本返回退出码 $stackExit"
    }
    if (-not $allReady) {
        Write-Output '  · 有组件没有就绪（见上面的 [DOWN] / [WARN] 行）'
    }
    Write-Output ''
    Write-Output '  先看日志，日志目录：logs\runtime\'
    Write-Output '    middleware.log            中间件（mysql / nacos / sentinel）'
    Write-Output '    gateway.err.log           网关 8080'
    Write-Output '    user-service.err.log      用户服务 8081（其余服务日志同名）'
    Write-Output '    capability-service.err.log / billing-service.err.log / ai-chat-service.err.log'
    Write-Output '    web.err.log               前端 dev server'
    Write-Output ''
    Write-Output '  常见原因：'
    Write-Output '    1) Docker Desktop 未就绪：手动打开 Docker Desktop，等状态变成 Running 再重跑 start.cmd'
    Write-Output '    2) 端口被占用：netstat -ano | findstr :8080 查看占用进程（前端端口见 web\.env 的 VITE_PORT）'
    Write-Output '    3) 依赖未安装：前端 cd web && pnpm install；Python 依赖见各服务 requirements.txt'
    Write-Output '    4) 本地配置缺失：执行 python scripts/init_dev.py 生成 .env（已存在则不会覆盖）'
    Write-Output ''
    Write-Output '  提示：本脚本可安全重复执行，已就绪的组件会自动跳过。'
    if ($stackExit -ne 0) { exit 20 }
    exit 30
}

# ---------------------------------------------------------------------------
# 4/4 成功汇总
# ---------------------------------------------------------------------------
Write-Output ''
Write-Output '== 4/4 全部就绪 =='
Write-Output ''
Write-Output "  访问地址    http://localhost:$webPort"
Write-Output '  演示账号    demo / demo123456'
Write-Output '  运行日志    logs\runtime\'
Write-Output ''
Write-Output '  停止服务：'
Write-Output "    · 停止本项目进程：Get-NetTCPConnection -State Listen -LocalPort 8080,8081,8082,8083,8090,$webPort | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }"
Write-Output '    · 停止中间件容器：docker stop aihub-pro-mysql aihub-pro-nacos aihub-pro-sentinel'
Write-Output '    · 直接退出 Docker Desktop 会一并停止全部中间件容器'
Write-Output ''

if ($NoOpen) {
    Write-Output "  已按 -NoOpen 跳过自动打开浏览器，请手动访问 http://localhost:$webPort"
} else {
    Write-Output '  正在打开默认浏览器…（不想自动打开可加 -NoOpen 参数）'
    Start-Process "http://localhost:$webPort"
}

exit 0

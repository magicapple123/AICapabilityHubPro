# AICapabilityHub Pro - start local stack (idempotent, English output only)
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-pro-stack.ps1
#        add -Check to print the resolved root, python and docker paths without starting anything
# Safe to re-run: components whose port is already listening are skipped.
# The checkout can live anywhere: root, python and docker are resolved at runtime.

param([switch]$Check)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path (Join-Path $root 'scripts\start_pro_local.py'))) {
  Write-Output "ERROR scripts\start_pro_local.py not found under $root"
  exit 1
}

function Resolve-Python {
  if ($env:PYTHON -and (Test-Path $env:PYTHON)) { return $env:PYTHON }
  $venv = Join-Path $root 'services\user-service\.venv\Scripts\python.exe'
  if (Test-Path $venv) { return $venv }
  foreach ($name in 'python', 'python3') {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
  }
  return $null
}

function Resolve-DockerCli {
  $cmd = Get-Command docker -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
  )
  foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
  return $null
}

function Resolve-DockerDesktop {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
  )
  foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
  return $null
}

$py = Resolve-Python
if (-not $py) { Write-Output 'ERROR python 3 not found; install it or set PYTHON to its full path'; exit 1 }
$dockerCli = Resolve-DockerCli
$dockerExe = Resolve-DockerDesktop

if ($Check) {
  Write-Output "root   $root"
  Write-Output "python $py"
  Write-Output "docker $dockerCli"
  Write-Output "desktop $dockerExe"
  exit 0
}

$logDir = Join-Path $root 'logs\runtime'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Web dev server port. The single source of truth is VITE_PORT in web/.env
# (that file is git-ignored, so it cannot drift from this script silently).
# The fallback is 5174 rather than 5173 on purpose: 5173 may already be taken by
# another local project, and pointing at it would only produce noise.
$webPort = 5174
$webEnvFile = Join-Path $root 'web\.env'
if (Test-Path $webEnvFile) {
  $webPortMatch = Select-String -Path $webEnvFile -Pattern '^\s*VITE_PORT\s*=\s*(\d+)' -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($webPortMatch) {
    $webPort = [int]$webPortMatch.Matches[0].Groups[1].Value
  } else {
    Write-Output "WARN  VITE_PORT not found in web/.env; falling back to $webPort"
  }
} else {
  Write-Output "WARN  web/.env not found; falling back to $webPort"
}
# Substring that must appear in the page returned by our own Vite dev server.
# Used to tell "port busy with our app" apart from "port busy with someone else".
$webMarker = 'AICapabilityHub'

function Test-Port([int]$port) {
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

# A listening port is not proof that our front end is up: another project can own
# the port. Only report the web port as ready when the page really is ours.
# ProgressPreference is scoped down so the request never prints progress bars,
# which would interleave with the plain "OK/DOWN" status lines of this script.
function Test-WebReady([int]$port) {
  if (-not (Test-Port $port)) { return $false }
  $previousProgress = $ProgressPreference
  $ProgressPreference = 'SilentlyContinue'
  try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$port" -UseBasicParsing -TimeoutSec 5
    return ($resp.StatusCode -eq 200 -and $resp.Content -match $webMarker)
  } catch { return $false } finally { $ProgressPreference = $previousProgress }
}

function Wait-Port([int]$port, [int]$timeoutSeconds) {
  for ($i = 0; $i -lt $timeoutSeconds; $i++) {
    if (Test-Port $port) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}

# A listening port can also be held by some unrelated process, so a healthy /health
# response is what proves the service itself is alive. Progress is scoped down for
# the same reason as in Test-WebReady: keep the console status-only.
function Test-ServiceHealth([int]$port) {
  $previousProgress = $ProgressPreference
  $ProgressPreference = 'SilentlyContinue'
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 5
    return ($resp.StatusCode -eq 200)
  } catch { return $false } finally { $ProgressPreference = $previousProgress }
}

function Start-Component([string]$name, [int]$port) {
  if ($port -gt 0 -and (Test-Port $port)) { Write-Output "SKIP  $name (port $port already listening)"; return }
  Start-Process -FilePath $py -ArgumentList 'scripts/start_pro_local.py', $name -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir "$name.out.log") -RedirectStandardError (Join-Path $logDir "$name.err.log")
  Write-Output "START $name"
}

Write-Output "== AICapabilityHub Pro local stack =="
Write-Output "root $root"

# 1) Docker engine
$engineUp = $false
if ($dockerCli) {
  $null = & $dockerCli info 2>&1
  $engineUp = ($LASTEXITCODE -eq 0)
}
if (-not $engineUp) {
  if (-not $dockerCli) { Write-Output 'ERROR docker CLI not found; install Docker Desktop and add it to PATH'; exit 1 }
  if ($dockerExe) { Start-Process -FilePath $dockerExe; Write-Output 'START docker desktop' }
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 3
    $null = & $dockerCli info 2>&1
    if ($LASTEXITCODE -eq 0) { $engineUp = $true; break }
  }
}
if (-not $engineUp) { Write-Output 'ERROR docker engine not ready after 180s'; exit 1 }
Write-Output 'OK    docker engine'

# 2) Middleware (mysql / nacos / sentinel)
& $py (Join-Path $root 'scripts\start_pro_local.py') middleware *> (Join-Path $logDir 'middleware.log')
$mysqlReady = $false
for ($i = 0; $i -lt 60; $i++) {
  $status = & $dockerCli inspect -f '{{.State.Health.Status}}' aihub-pro-mysql 2>$null
  if ($status -eq 'healthy') { $mysqlReady = $true; break }
  Start-Sleep -Seconds 2
}
if ($mysqlReady) { Write-Output 'OK    mysql healthy' } else { Write-Output 'WARN  mysql not healthy yet, services may retry' }

# 3) Business services
# Each service is checked before anything is started. Starting a process only to
# watch start_dev.py refuse the occupied port is worse than not starting at all:
# Start-Process truncates the redirect logs before the child even runs, which would
# wipe the logs of an already healthy service and leave a misleading
# "Port ... is occupied" first line. A listening port alone is not proof either,
# so /health is checked as well, and an unhealthy listener is surfaced as a warning
# instead of being silently skipped.
$servicePorts = @{
  'user-service'       = 8081
  'capability-service' = 8082
  'billing-service'    = 8083
  'ai-chat-service'    = 8090
}
foreach ($svc in 'user-service', 'capability-service', 'billing-service', 'ai-chat-service') {
  $svcPort = $servicePorts[$svc]
  if (Test-Port $svcPort) {
    if (Test-ServiceHealth $svcPort) { Write-Output "SKIP  $svc (port $svcPort healthy)" }
    else { Write-Output "WARN  $svc port $svcPort is listening but /health failed" }
  } else {
    Start-Component $svc 0
  }
  Start-Sleep -Milliseconds 300
}
$null = Wait-Port 8081 60; $null = Wait-Port 8082 60; $null = Wait-Port 8083 60; $null = Wait-Port 8090 60

# 4) Gateway and web
Start-Component 'gateway' 8080
# Web is guarded by the readiness check instead of the raw port check, so a port
# owned by a different project no longer produces a bogus SKIP. Three states:
#   our app serves it -> skip; another project holds it -> warn and do not start
#   (vite --strictPort would fail anyway); nothing listening -> start.
if (Test-WebReady $webPort) {
  Write-Output "SKIP  web (port $webPort already serving our front end)"
} elseif (Test-Port $webPort) {
  Write-Output "WARN  web port $webPort is held by another project; not starting (change VITE_PORT in web/.env)"
} else {
  Start-Component 'web' 0
}
$null = Wait-Port 8080 180
$null = Wait-Port $webPort 60

# 5) Status
Write-Output '-- status --'
foreach ($port in 8080, 8081, 8082, 8083, 8090) {
  if (Test-Port $port) { Write-Output "OK    port $port" } else { Write-Output "DOWN  port $port" }
}
if (Test-WebReady $webPort) {
  Write-Output "OK    port $webPort (AICapabilityHub)"
} elseif (Test-Port $webPort) {
  Write-Output "DOWN  port $webPort (port busy but not this project)"
  Write-Output "      hint: another application owns port $webPort; set VITE_PORT in web/.env to a free port"
} else {
  Write-Output "DOWN  port $webPort"
}
Write-Output "Open http://localhost:$webPort (demo / demo123456)"

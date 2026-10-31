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

function Test-Port([int]$port) {
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

function Wait-Port([int]$port, [int]$timeoutSeconds) {
  for ($i = 0; $i -lt $timeoutSeconds; $i++) {
    if (Test-Port $port) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
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
foreach ($svc in 'user-service', 'capability-service', 'billing-service', 'ai-chat-service') {
  Start-Component $svc 0
  Start-Sleep -Milliseconds 800
}
$null = Wait-Port 8081 60; $null = Wait-Port 8082 60; $null = Wait-Port 8083 60; $null = Wait-Port 8090 60

# 4) Gateway and web
Start-Component 'gateway' 8080
Start-Component 'web' 5173
$null = Wait-Port 8080 180
$null = Wait-Port 5173 60

# 5) Status
Write-Output '-- status --'
foreach ($port in 8080, 8081, 8082, 8083, 8090, 5173) {
  if (Test-Port $port) { Write-Output "OK    port $port" } else { Write-Output "DOWN  port $port" }
}
Write-Output 'Open http://localhost:5173 (demo / demo123456)'

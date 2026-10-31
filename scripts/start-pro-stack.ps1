# AICapabilityHub Pro - start local stack (idempotent, English output only)
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-pro-stack.ps1
# Safe to re-run: components whose port is already listening are skipped.

$ErrorActionPreference = 'Continue'
$root = 'D:\AICapabilityHubPro'
$py = 'D:\Python\Python312\python.exe'
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

# 1) Docker engine
$dockerExe = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'
$dockerCli = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
$engineUp = $false
if (Test-Path $dockerCli) {
  $null = & $dockerCli info 2>&1
  $engineUp = ($LASTEXITCODE -eq 0)
}
if (-not $engineUp) {
  if (Test-Path $dockerExe) { Start-Process -FilePath $dockerExe; Write-Output 'START docker desktop' }
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

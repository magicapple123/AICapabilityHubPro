# G2 clean-environment verification (one command; rolls back even on failure).
#
# Why a shell script: the flow is compose + port polling + a python smoke test.
# Python only owns the last step.
#
# Usage:
#   powershell -File scripts/clean_env_check.ps1              # up -> wait ready -> smoke (keep running)
#   powershell -File scripts/clean_env_check.ps1 -DownAfter   # tear down afterwards
#
# Precondition: ports 8081/8082/8083/8090 must be free (the script checks and refuses).

param(
    [string]$ComposeFile = "deploy/docker-compose.yml",
    [switch]$DownAfter,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$services = @(
    @{ Name = "user-service";       Port = 8081 },
    @{ Name = "billing-service";    Port = 8082 },
    @{ Name = "capability-service"; Port = 8083 },
    @{ Name = "ai-chat-service";    Port = 8090 }
)

# 1) Refuse to fight another process for a port.
$busy = @()
foreach ($svc in $services) {
    $conns = Get-NetTCPConnection -LocalPort $svc.Port -State Listen -ErrorAction SilentlyContinue
    if ($conns) { $busy += $svc.Port }
}
if ($busy.Count -gt 0) {
    Write-Host ("ERROR ports already in use: " + ($busy -join ", ")) -ForegroundColor Red
    Write-Host "Stop the local stack first, then retry." -ForegroundColor Yellow
    exit 2
}

function Test-Ready([int]$Port) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

$started = Get-Date
$exit = 0
try {
    Write-Host "[1/3] building and starting the stack..." -ForegroundColor Cyan
    docker compose -f $ComposeFile --profile app up -d --build
    if ($LASTEXITCODE -ne 0) { throw "compose up failed (exit $LASTEXITCODE)" }

    Write-Host "[2/3] waiting for /health/ready (max $TimeoutSeconds s)..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $ready = @{}
    while ((Get-Date) -lt $deadline) {
        foreach ($svc in $services) {
            if (-not $ready[$svc.Name] -and (Test-Ready $svc.Port)) {
                $ready[$svc.Name] = $true
                Write-Host ("  READY " + $svc.Name + " :" + $svc.Port) -ForegroundColor Green
            }
        }
        if ($ready.Count -eq $services.Count) { break }
        Start-Sleep -Seconds 3
    }
    $missing = $services | Where-Object { -not $ready[$_.Name] }
    if ($missing) { throw ("not ready: " + (($missing | ForEach-Object { $_.Name }) -join ", ")) }

    Write-Host "[3/3] gateway smoke..." -ForegroundColor Cyan
    python scripts/smoke_check.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_check failed (exit $LASTEXITCODE)" }

    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Host "PASS stack verified in $elapsed s" -ForegroundColor Green
}
catch {
    $exit = 1
    Write-Host ("FAIL " + $_) -ForegroundColor Red
    Write-Host "--- container status ---" -ForegroundColor Yellow
    docker compose -f $ComposeFile --profile app ps
}
finally {
    if ($DownAfter) {
        Write-Host "rollback: compose down" -ForegroundColor Yellow
        docker compose -f $ComposeFile --profile app down
        Write-Host "restore local stack: powershell -File scripts/start-pro-stack.ps1" -ForegroundColor Yellow
    }
}

exit $exit

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ReportPath,
    [switch]$SkipDocker,
    [switch]$SkipWebInstall
)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-GateStep([string]$Name, [string]$WorkingDirectory, [scriptblock]$Action) {
    $start = Get-Date
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Action
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
    } catch {
        Write-Error $_
        $exitCode = 1
    } finally {
        Pop-Location
    }
    $duration = ((Get-Date) - $start).TotalSeconds
    $passed = $exitCode -eq 0
    $results.Add([pscustomobject]@{
        name = $Name
        passed = $passed
        exit_code = $exitCode
        duration_seconds = [math]::Round($duration, 2)
    })
    $label = if ($passed) { "PASS" } else { "FAIL" }
    Write-Output ("[{0}] {1} ({2:n2}s)" -f $label, $Name, $duration)
}

Invoke-GateStep "contract lint" $ProjectRoot {
    python scripts/contract_lint.py
}

Invoke-GateStep "source baseline guard" $ProjectRoot {
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Assert-ProjectBaseline.ps1 -ProjectRoot $ProjectRoot
}

Invoke-GateStep "gateway tests" (Join-Path $ProjectRoot "gateway") {
    mvn -q test
}

# Local DB fixtures physically clean their isolated `qa*` rows. Never let the
# convenience gate inherit a developer's `.env`/MySQL URL; the deliberately
# unreachable port makes DB-dependent tests report skipped. Full DB coverage
# runs in the disposable MySQL service in GitHub Actions.
$originalDbUrl = $env:DB_URL
$env:DB_URL = "mysql+pymysql://root:offline-only@127.0.0.1:1/not_connected?charset=utf8mb4"

foreach ($service in @("user-service", "billing-service", "capability-service", "ai-chat-service")) {
    $serviceRoot = Join-Path $ProjectRoot ("services\{0}" -f $service)
    Invoke-GateStep ("{0} pytest" -f $service) $serviceRoot {
        python -m pytest -q
    }
    Invoke-GateStep ("{0} import" -f $service) $serviceRoot {
        python -c "import app.main; print('import ok')"
    }
}

# Do not leak the gate's isolated test URL into a caller's interactive shell.
$env:DB_URL = $originalDbUrl

$webRoot = Join-Path $ProjectRoot "web"
if (-not $SkipWebInstall) {
    Invoke-GateStep "web install" $webRoot {
        pnpm install --frozen-lockfile
    }
}
Invoke-GateStep "web lint" $webRoot { pnpm lint }
Invoke-GateStep "web build" $webRoot { pnpm build }

if (-not $SkipDocker) {
    Invoke-GateStep "docker compose config" (Join-Path $ProjectRoot "deploy") {
        docker compose config
    }
}

$failed = @($results | Where-Object { -not $_.passed })
$summary = [pscustomobject]@{
    generated_at = (Get-Date).ToString("o")
    project_root = $ProjectRoot
    passed = $failed.Count -eq 0
    total = $results.Count
    failed = $failed.Count
    steps = $results
}

if ($ReportPath) {
    $absoluteReport = if ([IO.Path]::IsPathRooted($ReportPath)) { $ReportPath } else { Join-Path $ProjectRoot $ReportPath }
    if (Test-Path -LiteralPath $absoluteReport) {
        throw "Refusing to overwrite an existing report: $absoluteReport"
    }
    $parent = Split-Path -Parent $absoluteReport
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $absoluteReport -Encoding UTF8
    Write-Output "Report: $absoluteReport"
}

if ($failed.Count -gt 0) {
    Write-Output ("Quality gate failed: {0}/{1} steps failed." -f $failed.Count, $results.Count)
    exit 1
}

Write-Output ("Quality gate passed: {0} steps." -f $results.Count)

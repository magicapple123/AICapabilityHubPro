[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$ReportPath,
    [switch]$SkipDocker,
    [switch]$SkipWebInstall
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$results = [System.Collections.Generic.List[object]]::new()
$runDirectory = Join-Path $ProjectRoot ("artifacts\quality\" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $runDirectory | Out-Null
if (-not $ReportPath) { $ReportPath = Join-Path $runDirectory "summary.json" }
$absoluteReport = if ([IO.Path]::IsPathRooted($ReportPath)) { $ReportPath } else { Join-Path $ProjectRoot $ReportPath }
if (Test-Path -LiteralPath $absoluteReport) { throw "Refusing to overwrite existing report: $absoluteReport" }

function Invoke-GateStep([string]$Name, [string]$WorkingDirectory, [scriptblock]$Action) {
    $start = Get-Date
    Push-Location -LiteralPath $WorkingDirectory
    try {
        $global:LASTEXITCODE = 0
        & $Action
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
    } catch {
        Write-Warning ("Step failed: {0}; {1}" -f $Name, $_.Exception.GetType().Name)
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

Invoke-GateStep "public tooling tests" $ProjectRoot {
    python -m pytest tests/tooling -q
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

try {
foreach ($service in @("user-service", "billing-service", "capability-service", "ai-chat-service")) {
    $serviceRoot = Join-Path $ProjectRoot ("services\{0}" -f $service)
    $venvPython = Join-Path $serviceRoot ".venv\Scripts\python.exe"
    $pythonCommand = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
    $junitPath = Join-Path $runDirectory ($service + ".xml")
    Invoke-GateStep ("{0} pytest" -f $service) $serviceRoot {
        & $pythonCommand -m pytest -q --junitxml=$junitPath
        if ($LASTEXITCODE -eq 0) { & $pythonCommand (Join-Path $ProjectRoot "scripts\check_test_report.py") $junitPath --allow-skips }
    }
    Invoke-GateStep ("{0} import" -f $service) $serviceRoot {
        & $pythonCommand -c "import app.main; print('import ok')"
    }
}
} finally {
# Do not leak the gate's isolated test URL into a caller's interactive shell.
$env:DB_URL = $originalDbUrl
}

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
        docker compose config --quiet
    }
}

$failed = @($results | Where-Object { -not $_.passed })
$summary = [pscustomobject]@{
    generated_at = (Get-Date).ToString("o")
    project_root = $ProjectRoot
    mode = "offline local checks"
    database_integration = "not executed; use isolated MySQL CI evidence"
    passed = $failed.Count -eq 0
    total = $results.Count
    failed = $failed.Count
    steps = $results
}

if ($ReportPath) {
    if (Test-Path -LiteralPath $absoluteReport) {
        throw "Refusing to overwrite an existing report: $absoluteReport"
    }
    $parent = Split-Path -Parent $absoluteReport
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $stream = [IO.File]::Open($absoluteReport, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $jsonBytes = [Text.Encoding]::UTF8.GetBytes(($summary | ConvertTo-Json -Depth 6))
        $stream.Write($jsonBytes, 0, $jsonBytes.Length)
    } finally { $stream.Dispose() }
    Write-Output "Report: $absoluteReport"
}

if ($failed.Count -gt 0) {
    Write-Output ("Quality gate failed: {0}/{1} steps failed." -f $failed.Count, $results.Count)
    exit 1
}

Write-Output ("Offline quality gate passed: {0} steps. DB integration is verified separately in CI." -f $results.Count)

[CmdletBinding()]
param(
    [string]$ProjectRoot
)

$ErrorActionPreference = "Continue"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [bool]$Passed, [string]$Detail, [switch]$Optional) {
    $checks.Add([pscustomobject]@{
        name = $Name
        passed = $Passed
        optional = [bool]$Optional
        detail = $Detail
    })
    $label = if ($Passed) { "PASS" } elseif ($Optional) { "WARN" } else { "FAIL" }
    Write-Output ("[{0}] {1}: {2}" -f $label, $Name, $Detail)
}

function Check-Command([string]$Name, [string[]]$Arguments) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        Add-Check "tool:$Name" $false "not found"
        return
    }
    $version = (& $Name @Arguments 2>&1 | Select-Object -First 1).ToString().Trim()
    Add-Check "tool:$Name" $true ("{0} ({1})" -f $version, $command.Source)
}

Write-Output ("Project root: {0}" -f $ProjectRoot)

foreach ($relativePath in @(
    ".git",
    "gateway\pom.xml",
    "deploy\docker-compose.yml",
    "web\package.json",
    "docs\implementation\README.md",
    "scripts\Invoke-QualityGate.ps1",
    ".github\workflows\quality-gate.yml"
)) {
    $path = Join-Path $ProjectRoot $relativePath
    Add-Check "file:$relativePath" (Test-Path -LiteralPath $path) $path
}

Check-Command "git" @("--version")
Check-Command "python" @("--version")
Check-Command "java" @("-version")
Check-Command "mvn" @("-version")
Check-Command "node" @("--version")
Check-Command "pnpm" @("--version")
Check-Command "docker" @("--version")

$origin = [string](git -C $ProjectRoot remote get-url origin 2>$null | Select-Object -First 1)
$origin = $origin.Trim()
$correctOrigin = $origin -match "^(https://github\.com/|git@github\.com:)magicapple123/AICapabilityHubPro(\.git)?$"
Add-Check "git:pro-origin" $correctOrigin $origin

if (@(git -C $ProjectRoot remote) -contains "source") {
    $sourcePush = [string](git -C $ProjectRoot remote get-url --push source 2>$null | Select-Object -First 1)
    Add-Check "git:source-push-protection" ($sourcePush.Trim() -eq "disabled://push-disabled") $sourcePush
}

$dockerInfo = docker info --format "{{.ServerVersion}}" 2>&1
if ($LASTEXITCODE -eq 0) {
    Add-Check "docker:daemon" $true ($dockerInfo | Select-Object -First 1)
} else {
    Add-Check "docker:daemon" $false "Docker Desktop daemon is not running" -Optional
}

$failed = @($checks | Where-Object { -not $_.passed -and -not $_.optional })
$warnings = @($checks | Where-Object { -not $_.passed -and $_.optional })
$summary = [pscustomobject]@{
    project_root = $ProjectRoot
    passed = $failed.Count -eq 0
    failed = $failed.Count
    warnings = $warnings.Count
    checks = $checks
}

Write-Output ("Environment result: failed={0}, warnings={1}" -f $failed.Count, $warnings.Count)
if ($failed.Count -gt 0) {
    exit 1
}

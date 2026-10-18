[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$SourceRoot = "D:\AICapabilityHub",
    [switch]$AllowSourceChanges
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$projectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

function Write-Check([string]$Name, [bool]$Passed, [string]$Detail) {
    $state = if ($Passed) { "PASS" } else { "FAIL" }
    [Console]::WriteLine(("[{0}] {1}: {2}" -f $state, $Name, $Detail))
    return $Passed
}

$allPassed = $true
$sourceGit = Join-Path $SourceRoot ".git"
$projectGit = Join-Path $projectRoot ".git"

$allPassed = (Write-Check "Pro Git repository" (Test-Path -LiteralPath $projectGit) $projectGit) -and $allPassed
$sourceExists = Test-Path -LiteralPath $sourceGit
if (-not $sourceExists) {
    [Console]::WriteLine(("[SKIP] Source isolation: baseline source not present at {0}" -f $SourceRoot))
}

if ($sourceExists -and (Test-Path -LiteralPath $projectGit)) {
    $sourceRemotes = @(git -C $projectRoot remote)
    if ($sourceRemotes -contains "source") {
        $sourceRemote = (git -C $projectRoot remote get-url source 2>$null | Select-Object -First 1).Trim()
        $remoteMatches = $sourceRemote -eq $SourceRoot
        $allPassed = (Write-Check "Source remote" $remoteMatches ("expected={0}; actual={1}" -f $SourceRoot, $sourceRemote)) -and $allPassed

        $pushUrl = (git -C $projectRoot remote get-url --push source 2>$null | Select-Object -First 1).Trim()
        $pushProtected = $pushUrl -eq "disabled://push-disabled"
        $allPassed = (Write-Check "Source push protection" ($pushProtected -or $AllowSourceChanges) ("push_url={0}" -f $pushUrl)) -and $allPassed

        if (Test-Path -LiteralPath (Join-Path $SourceRoot ".git")) {
            $sourceChanges = @(git -C $SourceRoot status --porcelain)
            $sourceClean = $sourceChanges.Count -eq 0
            $allPassed = (Write-Check "Source working tree clean" $sourceClean ("changed_files={0}" -f ($sourceChanges.Count))) -and $allPassed
        }
    }
}

$required = @(
    "docs\implementation\README.md",
    "scripts\Invoke-QualityGate.ps1",
    "scripts\contract_lint.py",
    ".github\workflows\quality-gate.yml"
)
foreach ($relativePath in $required) {
    $exists = Test-Path -LiteralPath (Join-Path $projectRoot $relativePath)
    $allPassed = (Write-Check "Required project file" $exists $relativePath) -and $allPassed
}

if (-not $allPassed) {
    exit 1
}

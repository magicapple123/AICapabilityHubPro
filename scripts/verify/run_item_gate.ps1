param([Parameter(Mandatory=$true)][string]$Item)
$ErrorActionPreference='Continue'
$root=Resolve-Path (Join-Path $PSScriptRoot '../..')
Push-Location $root
try {
  $config=Get-Content -Encoding UTF8 'deploy/.env' | Where-Object {$_ -match '^MYSQL_ROOT_PASSWORD='} | Select-Object -First 1
  $env:GATE_DB_PWD=($config -split '=',2)[1].Trim()
  $env:GATE_DB_PORT='23307'
  $env:NACOS_MODEL_CONFIG_ENABLED='false'
  $env:PYTHONIOENCODING='utf-8'
  $stamp=Get-Date -Format 'HHmmssfff'
  $log="artifacts/verify-2026-11-03/$Item-gate-$stamp.log"
  $failed=0
  "COMMAND: bash scripts/gate.sh all (GATE_DB_PORT=23307)" | Tee-Object -FilePath $log
  & 'C:/Program Files/Git/bin/bash.exe' scripts/gate.sh all 2>&1 | Tee-Object -FilePath $log -Append
  if($LASTEXITCODE -ne 0){$failed++}
  'COMMAND: python scripts/acceptance_check.py' | Tee-Object -FilePath $log -Append
  python scripts/acceptance_check.py 2>&1 | Tee-Object -FilePath $log -Append
  if($LASTEXITCODE -ne 0){$failed++}
  'COMMAND: pnpm --dir web lint' | Tee-Object -FilePath $log -Append
  pnpm --dir web lint 2>&1 | Tee-Object -FilePath $log -Append
  if($LASTEXITCODE -ne 0){$failed++}
  'COMMAND: pnpm --dir web build' | Tee-Object -FilePath $log -Append
  pnpm --dir web build 2>&1 | Tee-Object -FilePath $log -Append
  if($LASTEXITCODE -ne 0){$failed++}
  "ITEM_GATE=$Item FAILED_COMMANDS=$failed LOG=$log" | Tee-Object -FilePath $log -Append
  exit $failed
} finally { Pop-Location }

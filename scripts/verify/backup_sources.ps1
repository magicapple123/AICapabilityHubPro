param([Parameter(Mandatory=$true)][string]$Item,[Parameter(Mandatory=$true)][string[]]$Files)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$target=Join-Path $root ('artifacts/verify-2026-11-03/backups/'+$Item+'-'+[guid]::NewGuid().ToString('N'))
$scan=@($Files | ForEach-Object {Get-Item -LiteralPath (Join-Path $root $_)})
$scan | ForEach-Object {Write-Output ($_.FullName+' '+$_.Length+' bytes')}
foreach($file in $scan){
  $relative=$file.FullName.Substring($root.Length+1)
  $destination=Join-Path $target $relative
  New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
  Copy-Item -LiteralPath $file.FullName -Destination $destination -ErrorAction Stop
}
Write-Output ('BACKUP='+$target+' FILES='+$scan.Count)

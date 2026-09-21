param(
    [int]$Keep = 14
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupScript = Join-Path $scriptDir "backup.py"

python $backupScript
if ($LASTEXITCODE -ne 0) {
    throw "FabOS backup failed with exit code $LASTEXITCODE."
}

$dataDir = if ($env:FABOS_DATA_DIR) { [Environment]::ExpandEnvironmentVariables($env:FABOS_DATA_DIR) } else { Join-Path $HOME "WireVault FabOS Data" }
$backupDir = Join-Path $dataDir "Backups"
$backups = Get-ChildItem -Path $backupDir -Filter "fabos-backup-*.zip" -File | Sort-Object LastWriteTime -Descending
if ($Keep -lt 1) { $Keep = 1 }
$backups | Select-Object -Skip $Keep | Remove-Item -Force

Write-Host "FabOS backup complete. Retained $([Math]::Min($Keep, $backups.Count)) backup(s)."

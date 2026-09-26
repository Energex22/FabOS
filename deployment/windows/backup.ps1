param(
    [int]$Keep = 14,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupScript = Join-Path $scriptDir "backup.py"
$verifyScript = Join-Path $scriptDir "verify_backup.py"

if (-not $PythonExe) {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $PythonExe = $venvPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) {
            $PythonExe = $pythonCommand.Source
        } else {
            throw "Python was not found. Provide -PythonExe or install Python on PATH."
        }
    }
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Configured Python executable was not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $backupScript)) {
    throw "FabOS backup script was not found: $backupScript"
}
if (-not (Test-Path -LiteralPath $verifyScript)) {
    throw "FabOS backup verifier was not found: $verifyScript"
}

$archivePath = (& $PythonExe $backupScript | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0) {
    throw "FabOS backup failed with exit code $LASTEXITCODE."
}
$archivePath = [string]$archivePath
if (-not $archivePath -or -not (Test-Path -LiteralPath $archivePath)) {
    throw "FabOS backup did not produce a readable archive."
}

& $PythonExe $verifyScript $archivePath
if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
    throw "FabOS backup verification failed with exit code $LASTEXITCODE."
}

$dataDir = if ($env:FABOS_DATA_DIR) { [Environment]::ExpandEnvironmentVariables($env:FABOS_DATA_DIR) } else { Join-Path $HOME "WireVault FabOS Data" }
$backupDir = Join-Path $dataDir "Backups"
$backups = Get-ChildItem -Path $backupDir -Filter "fabos-backup-*.zip" -File | Sort-Object LastWriteTime -Descending
if ($Keep -lt 1) { $Keep = 1 }
$backups | Select-Object -Skip $Keep | Remove-Item -Force

Write-Host "FabOS backup complete and verified: $archivePath"
Write-Host "Retained $([Math]::Min($Keep, $backups.Count)) verified backup archive(s)."

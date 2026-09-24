param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Archive,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$verifyScript = Join-Path $scriptDir "verify_backup.py"
if (-not $PythonExe) {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) { $PythonExe = $venvPython }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) { $PythonExe = $pythonCommand.Source }
        else { throw "Python was not found. Provide -PythonExe or install Python on PATH." }
    }
}
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Configured Python executable was not found: $PythonExe" }
& $PythonExe $verifyScript $Archive
if ($LASTEXITCODE -ne 0) { throw "FabOS backup verification failed with exit code $LASTEXITCODE." }

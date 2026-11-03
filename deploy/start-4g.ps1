[CmdletBinding()]
param(
    [string]$AppRoot = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($AppRoot)) {
    $AppRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

$PythonBin = Join-Path $AppRoot '4G\.venv\Scripts\python.exe'
$EntryPoint = Join-Path $AppRoot '4G\4G.py'

if (-not (Test-Path -LiteralPath $PythonBin)) {
    throw "Python virtual environment is missing: $PythonBin"
}
if (-not (Test-Path -LiteralPath $EntryPoint)) {
    throw "4G.py is missing: $EntryPoint"
}

$env:PYTHONUNBUFFERED = '1'
Set-Location (Join-Path $AppRoot '4G')
& $PythonBin $EntryPoint
exit $LASTEXITCODE

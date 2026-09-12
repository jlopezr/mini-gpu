# Route verified archived netlists; retain every seed, log and detailed report.
param([int[]]$Seeds = @(1, 2, 3, 4, 5), [string]$ProjectDir = $PSScriptRoot,
      [string]$ReportDir = '')
$ErrorActionPreference = 'Stop'
if (-not $ReportDir) {
    $history = Join-Path $ProjectDir 'reports'
    $latest = Get-ChildItem $history -Directory | Sort-Object Name -Descending |
        Where-Object { Test-Path (Join-Path $_.FullName 'summary.json') } | Select-Object -First 1
    if (-not $latest) { throw 'Run build.ps1 first, or specify -ReportDir.' }
    $ReportDir = $latest.FullName
}
$arguments = @((Join-Path $PSScriptRoot 'sweep_report.py'), '--report-dir', $ReportDir, '--seeds') + @($Seeds | ForEach-Object { "$_" })
& (Join-Path $PSScriptRoot '../.venv/Scripts/python.exe') @arguments
if ($LASTEXITCODE -ne 0) { throw "Sweep failed (exit $LASTEXITCODE); reports retained." }

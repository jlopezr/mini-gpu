param([string]$Label='build', [switch]$ArchiveOnly, [switch]$Incremental)
$ErrorActionPreference='Stop'
$arguments=@((Join-Path $PSScriptRoot 'build_report.py'), '--label', $Label)
if($ArchiveOnly) { $arguments+='--archive-only' }
if($Incremental) { $arguments+='--incremental' }
& (Join-Path $PSScriptRoot '../.venv/Scripts/python.exe') @arguments
if($LASTEXITCODE -ne 0) { throw "Build/report failed (exit $LASTEXITCODE)" }

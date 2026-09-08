param([ValidateSet('Tests','Lint','Build','All')][string]$Action='Tests')
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$pythonExe=Join-Path $projectRoot '../.venv/Scripts/python.exe'
$apioExe=Join-Path $projectRoot '../.venv/Scripts/apio.exe'
if($Action -in @('Tests','All')) {
    & $pythonExe (Join-Path $projectRoot 'make_fixtures.py')
    if($LASTEXITCODE -ne 0) { throw 'Fixture generation failed' }
    & $pythonExe -m unittest discover -s $projectRoot -p 'test_*.py' -v
    if($LASTEXITCODE -ne 0) { throw 'Monitor client tests failed' }
    & $apioExe test -p $projectRoot
    if($LASTEXITCODE -ne 0) { throw 'RTL regression failed' }
}
if($Action -in @('Lint','All')) {
    & $apioExe lint -p $projectRoot
    if($LASTEXITCODE -ne 0) { throw 'Lint failed' }
}
if($Action -in @('Build','All')) {
    & $apioExe build -p $projectRoot
    if($LASTEXITCODE -ne 0) { throw 'Build failed' }
}

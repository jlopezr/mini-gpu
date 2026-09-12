param([ValidateSet('Tests','Lint','Build','All')][string]$Action='Tests')
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$pythonExe=Join-Path $projectRoot '../.venv/Scripts/python.exe'
$apioExe=Join-Path $projectRoot '../.venv/Scripts/apio.exe'
if($Action -in @('Tests','All')) {
    & $pythonExe (Join-Path $projectRoot 'make_fixtures.py')
    if($LASTEXITCODE -ne 0) { throw 'Fixture generation failed' }
    & $pythonExe -m unittest discover -s $projectRoot -p 'test_*.py' -v
    if($LASTEXITCODE -ne 0) { throw 'Python tests failed' }
    & $apioExe test -p $projectRoot
    if($LASTEXITCODE -ne 0) { throw 'RTL regression failed' }
}
if($Action -in @('Lint','All')) {
    & $apioExe lint -p $projectRoot
    if($LASTEXITCODE -ne 0) { throw 'Lint failed' }
}
if($Action -in @('Build','All')) {
    & (Join-Path $projectRoot 'build.ps1') -Label check
    if($LASTEXITCODE -ne 0) { throw 'Build failed' }
    # Apio passes --timing-allow-fail: explicitly enforce the clock target.
    $timingReport=Get-Content (Join-Path $projectRoot '_build/default/hardware.pnr') -Raw | ConvertFrom-Json
    $clockResults=@($timingReport.fmax.PSObject.Properties)
    if($clockResults.Count -eq 0) { throw 'No constrained clocks in timing report' }
    foreach($clockResult in $clockResults) {
        $result=$clockResult.Value
        if($result.constraint -lt 25 -or $result.achieved -lt $result.constraint) {
            throw "Timing failed: $($clockResult.Name) achieved $($result.achieved) MHz, target $($result.constraint) MHz"
        }
        Write-Host "Timing OK: $($result.achieved) MHz >= $($result.constraint) MHz"
    }
}

param([ValidateSet('Tests','Lint','Build','All')][string]$Action='Tests')
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
if($Action -in @('Tests','All')) {
    & (Join-Path $projectRoot '../tools/test.ps1') --prototype 17
    if($LASTEXITCODE -ne 0) { throw 'Tests failed' }
}
if($Action -in @('Lint','All')) {
    & (Join-Path $projectRoot '../tools/test.ps1') --prototype 17 --quick --lint
    if($LASTEXITCODE -ne 0) { throw 'Lint failed' }
}
if($Action -in @('Build','All')) {
    # build_report.py ya exige --timing-allow-fail: su código de salida es 1
    # si algún dominio no alcanza su constraint, así que basta con mirarlo.
    & (Join-Path $projectRoot '../tools/build.ps1') --prototype 17 --label check
    if($LASTEXITCODE -ne 0) { throw 'Build failed (o no alcanzó el timing objetivo)' }
}

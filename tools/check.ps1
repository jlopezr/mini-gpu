# Encadena test + lint + build para un prototipo, en ese orden, parando en
# el primer fallo. Equivalente a check.ps1 -Action All de 12/14/17.
#
# Solo reenvía -Prototype: test/lint/build tienen opciones propias
# incompatibles entre sí, así que check no intenta adivinar cuáles tienen
# sentido para los tres a la vez. Para eso, usa cada comando por separado.
param([Parameter(Mandatory = $true)][string] $Prototype)
$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'test.ps1') --prototype $Prototype
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot 'lint.ps1') --prototype $Prototype
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot 'build.ps1') --prototype $Prototype --label check
exit $LASTEXITCODE

<#
.SYNOPSIS
    Diagrama SVG de un modulo Verilog con yosys + netlistsvg: su interfaz (caja
    con pines) o, con -Inside, el top con sus submodulos. Experimental, fuera
    del sistema de lanzadores.

.DESCRIPTION
    Por defecto dibuja la INTERFAZ: yosys exporta el modulo a JSON solo con sus
    puertos (blackbox) y, como netlistsvg dibuja celdas y no el top, el JSON se
    envuelve en un top sintetico con una unica celda del tipo del modulo. Sale
    una caja con las entradas a la izquierda, las salidas a la derecha, los
    pines agrupados por prefijo (aux_, req_...) y el ancho de los buses.

    Con -Inside dibuja el top con sus submodulos como cajas (un nivel).

    Requiere yosys (oss-cad-suite de apio) y netlistsvg (Node.js):
        npm install -g netlistsvg

.PARAMETER VerilogPath
    Archivo .v con el modulo.

.PARAMETER TopModule
    Nombre del modulo; por defecto, el del archivo sin extension.

.PARAMETER ExtraFiles
    Ficheros .v adicionales. Normalmente no hace falta: el script busca solo, en
    la carpeta del archivo, los .v que definen los submodulos que el top
    instancia (y los suyos, transitivamente). Sirve para los que esten en otra
    carpeta.

.PARAMETER Inside
    En vez de la caja negra, dibuja el top con sus submodulos como cajas (un
    solo nivel) y los cables entre ellas. La logica propia del top (always,
    assign, mux...) no se dibuja. Salida: <modulo>_inside.svg.

.PARAMETER Help
    Muestra esta ayuda (tambien con -h, --help o sin argumentos).

.EXAMPLE
    .\tools\module-diagram.ps1 29.gpu-sm-pipeline\gpu_aux_adapter_128.v

.EXAMPLE
    .\tools\module-diagram.ps1 29.gpu-sm-pipeline\gpu_system_bl8.v -Inside
#>

param(
    [Parameter(Position = 0)]
    [string]$VerilogPath,

    [string]$TopModule,

    [string[]]$ExtraFiles = @(),

    [switch]$Inside,

    [Alias('h')]
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# --help / -h / sin argumentos: mostrar la ayuda de arriba.
if ($Help -or -not $VerilogPath -or $VerilogPath -in '--help', '-h', '-?', '/?') {
    Get-Help $PSCommandPath -Detailed
    return
}

if (-not (Test-Path $VerilogPath)) { throw "No se encuentra el archivo: $VerilogPath" }
if (-not $TopModule) { $TopModule = [System.IO.Path]::GetFileNameWithoutExtension($VerilogPath) }

function Find-Tool([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $pk = Join-Path $env:USERPROFILE ".apio\packages"
    if (Test-Path $pk) {
        $f = Get-ChildItem $pk -Recurse -Filter "$Name.exe" -ErrorAction SilentlyContinue |
             Where-Object { $_.DirectoryName -like "*\bin" } | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    return $null
}

$yosys = Find-Tool "yosys"
if (-not $yosys) { throw "No se encontro yosys (PATH o ~\.apio\packages\*\bin)." }
# El yosys de oss-cad-suite necesita sus DLL (bin y lib) en el PATH.
$binDir = Split-Path $yosys -Parent
$env:Path = "$binDir;$(Join-Path (Split-Path $binDir -Parent) 'lib');$env:Path"

$nsvg = (Get-Command netlistsvg -ErrorAction SilentlyContinue).Source
if (-not $nsvg) {
    throw "No se encontro netlistsvg. Instala Node.js y ejecuta: npm install -g netlistsvg"
}

$outDir = ".\diagrams"
New-Item -ItemType Directory -Force $outDir | Out-Null
$rawJson = Join-Path $outDir "$($TopModule)_raw.json"
$wrapJson = Join-Path $outDir "$($TopModule)_interface.json"
$svg = Join-Path $outDir "$($TopModule)_interface.svg"

# Dependencias: los .v de la misma carpeta que definen algun modulo que el top (o,
# transitivamente, esos ficheros) nombra. Se ignoran comentarios; los testbenches y
# modelos que nadie instancia no entran. Se suman a los -ExtraFiles explicitos.
function Get-Code([string]$path) {
    $t = Get-Content $path -Raw
    $t = [regex]::Replace($t, '/\*.*?\*/', ' ', 'Singleline')
    [regex]::Replace($t, '//[^\r\n]*', ' ')
}
$topFile = (Resolve-Path $VerilogPath).Path
$explicit = @($ExtraFiles | ForEach-Object { (Resolve-Path $_).Path })
$defs = @{}   # modulo -> fichero (el primero que lo define)
foreach ($f in Get-ChildItem (Split-Path $topFile -Parent) -Filter *.v) {
    if ($f.FullName -eq $topFile) { continue }
    foreach ($m in [regex]::Matches((Get-Code $f.FullName), '(?m)^\s*module\s+(\w+)')) {
        if (-not $defs.ContainsKey($m.Groups[1].Value)) { $defs[$m.Groups[1].Value] = $f.FullName }
    }
}
$auto = [System.Collections.Generic.List[string]]::new()
$queue = [System.Collections.Generic.Queue[string]]::new()
$queue.Enqueue($topFile)
while ($queue.Count -gt 0) {
    foreach ($w in [regex]::Matches((Get-Code $queue.Dequeue()), '\w+') | ForEach-Object Value | Select-Object -Unique) {
        $f = $defs[$w]
        if ($f -and $f -notin $auto -and $f -notin $explicit) { $auto.Add($f); $queue.Enqueue($f) }
    }
}
if ($auto.Count) {
    Write-Host "Dependencias encontradas en la carpeta: $(($auto | ForEach-Object { Split-Path $_ -Leaf }) -join ', ')"
}
$ExtraFiles = @($explicit) + @($auto)

# yosys trata '\' como escape en sus scripts: rutas absolutas y con '/'.
$files = (@($VerilogPath) + $ExtraFiles | ForEach-Object { (Resolve-Path $_).Path -replace '\\', '/' }) -join " "
$rawArg = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($rawJson) -replace '\\', '/'
$prep = if ($Inside) { "proc" } else { "proc; blackbox $TopModule" }
& $yosys -q -p "read_verilog $files; hierarchy -top $TopModule; $prep; write_json $rawArg"
if ($LASTEXITCODE -ne 0) { throw "yosys fallo (codigo $LASTEXITCODE)" }

if ($Inside) {
    # Un nivel: el top con solo las celdas que son instancias de modulos del diseno.
    $insideSvg = Join-Path $outDir "$($TopModule)_inside.svg"
    $insideJson = Join-Path $outDir "$($TopModule)_inside.json"
    $doc = Get-Content $rawJson -Raw | ConvertFrom-Json -Depth 100
    $mod = $doc.modules.$TopModule
    if (-not $mod) { throw "El JSON de yosys no contiene el modulo $TopModule" }
    $fixDir = { param($d) if ($d -eq 'inout') { 'output' } else { $d } }   # netlistsvg no admite inout
    foreach ($p in $mod.ports.PSObject.Properties) { $p.Value.direction = & $fixDir $p.Value.direction }
    $cells = [ordered]@{}
    foreach ($c in $mod.cells.PSObject.Properties) {
        if (-not $doc.modules.PSObject.Properties[$c.Value.type]) { continue }   # $and, $dff, ...
        foreach ($d in @($c.Value.port_directions.PSObject.Properties)) { $d.Value = & $fixDir $d.Value }
        # Los modulos con parametros se llaman $paramod\nombre\...: mostrar solo "nombre".
        if ($c.Value.type -match '^\$paramod(?:\$[0-9a-f]+)?\\([^\\]+)') { $c.Value.type = $Matches[1] }
        $cells[$c.Name] = $c.Value
    }
    if ($cells.Count -eq 0) { throw "$TopModule no instancia ningun submodulo (pasa sus .v con -ExtraFiles)." }
    $mod.cells = $cells
    $mod.attributes = [ordered]@{ top = 1 }
    $out = [ordered]@{ creator = "module-diagram.ps1"; modules = [ordered]@{ $TopModule = $mod } }
    $out | ConvertTo-Json -Depth 100 | Set-Content $insideJson -Encoding utf8
    & $nsvg $insideJson -o $insideSvg
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $insideSvg)) { throw "netlistsvg fallo" }
    Remove-Item $rawJson -ErrorAction SilentlyContinue
    Write-Host "SVG generado en: $insideSvg"
    Invoke-Item $insideSvg
    return
}

# Envolver: top sintetico con una celda del modulo, conectada a los mismos bits.
$doc = Get-Content $rawJson -Raw | ConvertFrom-Json -Depth 100
$mod = $doc.modules.$TopModule
if (-not $mod) { throw "El JSON de yosys no contiene el modulo $TopModule" }

$dirs = [ordered]@{}
$conns = [ordered]@{}
$ports = [ordered]@{}
$inouts = @()
foreach ($p in $mod.ports.PSObject.Properties) {
    # netlistsvg no entiende 'inout': se dibuja como salida (lado derecho) y se marca luego.
    $d = $p.Value.direction
    if ($d -eq 'inout') { $inouts += $p.Name; $d = 'output' }
    $dirs[$p.Name] = $d
    $conns[$p.Name] = @($p.Value.bits)
    $ports[$p.Name] = [ordered]@{ direction = $d; bits = @($p.Value.bits) }
}
$netnames = [ordered]@{}
foreach ($n in $ports.Keys) { $netnames[$n] = [ordered]@{ bits = $ports[$n].bits } }

$wrapper = [ordered]@{
    creator = "module-diagram.ps1"
    modules = [ordered]@{
        "${TopModule}_top" = [ordered]@{
            attributes = [ordered]@{ top = 1 }
            ports = $ports
            cells = [ordered]@{
                $TopModule = [ordered]@{
                    type = $TopModule
                    port_directions = $dirs
                    connections = $conns
                }
            }
            netnames = $netnames
        }
    }
}
$wrapper | ConvertTo-Json -Depth 100 | Set-Content $wrapJson -Encoding utf8

& $nsvg $wrapJson -o $svg
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $svg)) { throw "netlistsvg fallo" }

# Post-proceso: quitar los simbolos de puerto externos y los cables (la caja ya
# lleva las etiquetas de pin), anadir el ancho de los buses y recortar el lienzo.
$s = Get-Content $svg -Raw
$s = [regex]::Replace($s, '(?s)[ \t]*<g s:type="(?:input|output)Ext".*?</g>\r?\n', '')
$s = [regex]::Replace($s, '[ \t]*<line [^>]*/>\r?\n', '')
foreach ($n in $ports.Keys) {
    $w = @($ports[$n].bits).Count
    # Trocito de cable (10px) en cada pin; las etiquetas se apartan para no solaparse.
    $sw = if ($w -gt 1) { 2 } else { 1 }
    $pin = "(?<=id=`"port_$TopModule~$([regex]::Escape($n))`">\s*)<text x=`"(?:-3|5)`""
    if ($ports[$n].direction -eq 'input') {
        $s = $s -replace $pin, "<line x1=`"-10`" x2=`"0`" y1=`"0`" y2=`"0`" style=`"stroke-width:$sw`"/><text x=`"-13`""
    } else {
        $s = $s -replace $pin, "<line x1=`"0`" x2=`"10`" y1=`"0`" y2=`"0`" style=`"stroke-width:$sw`"/><text x=`"15`""
    }
    if ($w -gt 1) {
        $s = $s -replace "(?<=cell_$TopModule`">)$([regex]::Escape($n))(?=</text>)", "$n[$($w - 1):0]"
    }
    if ($n -in $inouts) {
        $s = $s -replace "(?<=cell_$TopModule`">)$([regex]::Escape($n))(\[\d+:0\])?(?=</text>)", '$0 (inout)'
    }
}
# Agrupar pines por prefijo (aux_, req_, ...) con un hueco entre grupos. Un prefijo
# que solo tiene un puerto (clk, reset, init_done) cuenta como "sin grupo".
$gap = 14
function Get-Prefix([string]$n) { if ($n -match '^([^_]+)_') { $Matches[1] } else { $n } }
$prefixCount = @{}
foreach ($n in $ports.Keys) { $prefixCount[(Get-Prefix $n)] = 1 + [int]$prefixCount[(Get-Prefix $n)] }
function Get-Group([string]$n) { $p = Get-Prefix $n; if ($prefixCount[$p] -gt 1) { $p } else { '' } }
# Grupos en orden de aparicion; cada grupo empieza a la misma altura en ambos lados.
$groups = @($ports.Keys | ForEach-Object { Get-Group $_ } | Select-Object -Unique)
$lastY = 0
$start = 10
foreach ($grp in $groups) {
    $rows = 0
    foreach ($dir in 'input', 'output') {
        $i = 0
        foreach ($n in $ports.Keys) {
            if ($ports[$n].direction -ne $dir -or (Get-Group $n) -ne $grp) { continue }
            $y = $start + 20 * $i
            $s = $s -replace "(<g transform=`"translate\(\d+,)\d+(\)`"[^>]*id=`"port_$TopModule~$([regex]::Escape($n))`">)", "`${1}$y`${2}"
            $lastY = [Math]::Max($lastY, $y)
            $i++
        }
        $rows = [Math]::Max($rows, $i)
    }
    $start += 20 * $rows + $gap
}
$s = [regex]::Replace($s, '(<rect width="[\d.]+" height=")[\d.]+(")', "`${1}$($lastY + 10)`${2}", 1)

# Nombre del modulo mas separado de la caja.
$s = $s -replace '(<text x="[\d.]+" y=")-4("[^>]*s:attribute="ref">)', '${1}-16${2}'

$g = [regex]::Match($s, 's:type="generic" transform="translate\(([\d.]+),([\d.]+)\)"')
$r = [regex]::Match($s, '<rect width="([\d.]+)" height="([\d.]+)"')
if ($g.Success -and $r.Success) {
    $x0 = [double]$g.Groups[1].Value; $y0 = [double]$g.Groups[2].Value
    $bw = [double]$r.Groups[1].Value; $bh = [double]$r.Groups[2].Value
    $left = 160; $right = 180; $pad = 20   # margen para etiquetas (fuente de 10px)
    $inv = [cultureinfo]::InvariantCulture
    $vb = [string]::Format($inv, "{0} {1} {2} {3}", ($x0 - $left), ($y0 - $pad - 10), ($left + $bw + $right), ($bh + 2 * $pad + 10))
    $s = [regex]::Replace($s, '<svg ([^>]*?)width="[\d.]+" height="[\d.]+"',
        "<svg `$1width=`"$($left + $bw + $right)`" height=`"$($bh + 2 * $pad + 10)`" viewBox=`"$vb`"")
}
Set-Content $svg $s -Encoding utf8

Remove-Item $rawJson -ErrorAction SilentlyContinue
Write-Host "SVG generado en: $svg"
Invoke-Item $svg

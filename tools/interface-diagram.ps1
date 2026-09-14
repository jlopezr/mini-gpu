<#
.SYNOPSIS
    Genera un diagrama SVG de la INTERFAZ (solo puertos, sin logica interna)
    de un modulo Verilog, usando yosys ('blackbox' + 'show').

.DESCRIPTION
    A diferencia de 'apio graph' (que muestra el netlist completo a nivel de
    puertas), este script convierte el modulo en una caja negra antes de
    dibujarlo, por lo que el SVG resultante solo muestra el bloque con sus
    entradas y salidas etiquetadas.

    Requiere:
      - yosys (viene con apio / oss-cad-suite)
      - graphviz (el ejecutable 'dot') en el PATH

.PARAMETER VerilogPath
    Ruta al archivo .v que contiene el modulo a diagramar.

.PARAMETER TopModule
    Nombre del modulo. Si no se indica, se usa el nombre del archivo (sin
    extension), asumiendo que archivo y modulo se llaman igual.

.PARAMETER ExtraFiles
    Archivos .v adicionales, solo si hacen falta para resolver includes o
    submodulos referenciados en la cabecera (no deberian ser necesarios si
    solo quieres la interfaz del propio modulo).

.EXAMPLE
    .\interface-diagram.ps1 -VerilogPath .\lsu.v

.EXAMPLE
    .\interface-diagram.ps1 -VerilogPath .\src\lsu.v -TopModule lsu
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$VerilogPath,

    [string]$TopModule,

    [string[]]$ExtraFiles = @()
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $VerilogPath)) {
    Write-Error "No se encuentra el archivo: $VerilogPath"
    exit 1
}

if (-not $TopModule) {
    $TopModule = [System.IO.Path]::GetFileNameWithoutExtension($VerilogPath)
}

# --- Helper: busca un ejecutable en PATH, o dentro de cualquier subcarpeta
#     de ~/.apio/packages/*/bin (asi cubrimos oss-cad-suite, graphviz, etc.
#     sin tener que conocer el nombre exacto de cada paquete). ---
function Find-Tool {
    param(
        [string]$Name  # nombre base, p.ej. "yosys" o "dot"
    )

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $apioPackagesDir = Join-Path $env:USERPROFILE ".apio\packages"
    if (Test-Path $apioPackagesDir) {
        $found = Get-ChildItem -Path $apioPackagesDir -Recurse -Filter "$Name*.exe" -ErrorAction SilentlyContinue |
                 Where-Object { $_.DirectoryName -like "*\bin" } |
                 Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }

    return $null
}

# --- Localizar yosys ---
$yosysExe = Find-Tool -Name "yosys"
if (-not $yosysExe) {
    Write-Error "No se encontro yosys ni en PATH ni en ~\.apio\packages\*\bin. Instala apio o anade yosys al PATH."
    exit 1
}

# --- Localizar dot (graphviz); yosys 'show' lo necesita para generar el SVG ---
$dotExe = Find-Tool -Name "dot"
if (-not $dotExe) {
    Write-Warning "No se encontro 'dot' (Graphviz) ni en PATH ni en ~\.apio\packages\*\bin."
    Write-Warning "'yosys show' probablemente fallara al generar el SVG."
    Write-Warning "En apio, 'dot' se instala como paquete separado: revisa 'apio raw -- dot -V'."
} else {
    # Nos aseguramos de que yosys encuentre 'dot' al ejecutarse: anadimos su
    # carpeta al PATH de este proceso (no toca el PATH del sistema).
    $dotDir = Split-Path $dotExe -Parent
    if ($env:Path -notlike "*$dotDir*") {
        $env:Path = "$dotDir;$env:Path"
    }
}

# --- Preparar carpeta y ruta de salida ---
$outDir = ".\diagrams"
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}
$outPrefix = Join-Path $outDir "$($TopModule)_interface"

$allFiles = @($VerilogPath) + $ExtraFiles
$filesArg = $allFiles -join " "

Write-Host "Usando yosys: $yosysExe"
if ($dotExe) { Write-Host "Usando dot:   $dotExe" }
Write-Host "Modulo top:   $TopModule"
Write-Host "Archivo(s):   $filesArg"
Write-Host ""

# --- Script de yosys: leer, aplanar procesos, convertir a blackbox, dibujar ---
$yosysScript = "read_verilog $filesArg; hierarchy -top $TopModule; proc; blackbox $TopModule; show -format svg -prefix `"$outPrefix`" $TopModule"

& $yosysExe -p $yosysScript

$svgPath = "$outPrefix.svg"
if (Test-Path $svgPath) {
    Write-Host ""
    Write-Host "SVG generado en: $svgPath"
    # Abrir automaticamente con la app asociada a .svg (navegador por defecto, normalmente)
    Invoke-Item $svgPath
} else {
    Write-Warning "yosys termino pero no se encontro el SVG esperado en $svgPath"
    Write-Warning "Revisa la salida anterior de yosys para ver el error (p.ej. 'blackbox' o 'show' fallidos)."
}

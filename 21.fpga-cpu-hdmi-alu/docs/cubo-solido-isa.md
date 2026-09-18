# Qué pide a la ISA un cubo sólido

Este documento usa [`cube_solid.asm`](../examples/cube_solid.asm) como carga de
trabajo concreta para evaluar extensiones de MiniISA. No intenta convertir la
ISA en una API gráfica: separa las operaciones generales que se repiten en el
programa de las optimizaciones que deben quedarse en software o en la
microarquitectura.

El programa hace cuatro trabajos distintos:

1. rota ocho vértices en Q16.16;
2. los proyecta mediante división por profundidad;
3. descarta las caras traseras mediante un área orientada;
4. rellena dos triángulos por cara visible con funciones de borde incrementales.

La primera versión funcional ocupa 515 palabras y, en el simulador CPU, ronda
0,6 millones de instrucciones por frame. Esta cifra no es todavía un benchmark
de una implementación optimizada: sirve para localizar patrones antes de
proponer instrucciones.

## Lo que no necesita una instrucción nueva

`putpixel` calcula actualmente la dirección de cada píxel como
`base + y*640 + x*2`, incluido un `MUL`. El rasterizador ya recorre cada fila de
izquierda a derecha, por lo que puede calcular la dirección una vez al principio
de la fila y sumarle dos por píxel. Esta mejora debe hacerse primero en software;
no justifica una instrucción gráfica.

Tampoco hace falta una instrucción `TRIANGLE` o `PROJECT`. Empotraría en la ISA
decisiones sobre formato de coordenadas, regla de cobertura, viewport y color.
Las primitivas generales de comparación, selección, multiplicación y acceso a
memoria cubren mejor otros programas además de este cubo.

## Resumen de candidatos

| Operación | Uso en el cubo | Situación |
|---|---|---|
| `SLT`, `SLTU` | Materializar cobertura como 0/1 | Ya forman parte de MiniISA bajo `compare`; falta llevar la capability a los backends que no la tengan |
| `SEL` | Elegir color sin abrir una rama por lane | Propuesta en v0.2/v0.3 |
| `MIN`, `MAX`, `MINU`, `MAXU` | Caja del triángulo y clipping al viewport | Propuestas en v0.2/v0.3 |
| `RCPFX` | Compartir `1/z` entre X e Y durante la perspectiva | Propuesta, con contrato numérico pendiente |
| `MACFX`, `MSUBFX` | Rotaciones y productos escalares Q16.16 | `MACFX` propuesto; `MSUBFX` no está cerrado |
| `MADD`, `MSUB` | Área orientada y evaluación inicial de funciones de borde | Multiply-add entero todavía pendiente de contrato |
| `STOREHP` | Escribir RGB565 y avanzar el puntero | Propuesto en v0.3 |

## Cobertura sin divergencia: `SLT` y `SEL`

El bucle interior actual decide si un píxel pertenece al triángulo comprobando
tres funciones de borde:

```asm
    BLT R12, R0, fuera
    BLT R13, R0, fuera
    BLT R14, R0, fuera
    JAL R30, putpixel
fuera:
```

En CPU esos saltos son razonables. En GPU, ocho píxeles de un warp pueden dar
resultados distintos y abrir caminos SIMT. `SLT` ya permite convertir cada
comparación en un booleano, y `SEL` permitiría escoger el dato sin modificar la
máscara activa:

```asm
    SLT  R7, R12, R0
    SLT  R8, R13, R0
    OR   R7, R7, R8
    SLT  R8, R14, R0
    OR   R7, R7, R8              ; 1 si alguna arista deja el píxel fuera
    SEL  Rcolor, Rfondo, Rcara, R7
    STOREH Rcolor, Rptr, 0
```

Esta forma resulta especialmente adecuada si cada lane es propietaria de un
píxel y escribe siempre fondo o cara. No hay carreras, y las lanes consecutivas
producen accesos consecutivos que la LSU puede coalescer.

La conclusión para la ISA no es añadir otra comparación: `SLT` y `SLTU` ya son
arquitectónicas. El trabajo es implementar y declarar `compare` allí donde el
rasterizador vaya a ejecutarse, y combinarla con `SEL`.

## Caja y clipping: `MIN` y `MAX`

Para obtener `minx`, `maxx`, `miny` y `maxy`, la rutina contiene doce parejas
de comparación y movimiento condicional. Con `MIN` y `MAX` queda expresado sin
saltos:

```asm
    MIN R15, R9,  R11
    MIN R15, R15, R13
    MAX R16, R9,  R11
    MAX R16, R16, R13

    MIN R17, R10, R12
    MIN R17, R17, R14
    MAX R18, R10, R12
    MAX R18, R18, R14
```

Las mismas instrucciones limitan la caja al framebuffer:

```asm
    MAX R15, R15, R0
    MIN R16, R16, R20             ; R20 = ancho-1
```

En CPU reducen código y branches. En GPU evitan que una preparación con
coordenadas distintas abra caminos divergentes. Son operaciones generales y
de contrato sencillo; constituyen una de las ampliaciones de menor riesgo.

## Perspectiva: `RCPFX`

La versión actual baja las coordenadas de Q16.16 a unidades de 1/256 y ejecuta
dos divisiones enteras por vértice:

```text
sx = 160 + (xi * 140) / zi
sy = 120 + (yi * 140) / zi
```

Un recíproco permite compartir la operación cara entre ambas coordenadas:

```asm
    RCPFX Rinvz, Rz
    MULFX Rfactor, Rinvz, Rescala
    MULFX Rx, Rx, Rfactor
    MULFX Ry, Ry, Rfactor
```

Además de ahorrar una división, mantiene la transformación en Q16.16. En un
rasterizador con textura, el mismo patrón se reutiliza para `u/w`, `v/w` y
`1/w`.

Antes de implementar `RCPFX` hay que cerrar su contrato: redondeo, error máximo,
cero, overflow y comportamiento signed. Para Q16.16, el resultado exacto se
describe conceptualmente mediante `2^32 / X`; ese numerador no cabe en un
registro ordinario de 32 bits.

## Determinantes y transformaciones: acumulación multiplicativa

El descarte de caras calcula el determinante 2D:

```text
area = ax*by - ay*bx
```

La evaluación inicial de cada función de borde repite el mismo patrón. Ahora
se expresa con dos `MUL` y un `SUB`:

```asm
    MUL R17, Rax, Rby
    MUL R18, Ray, Rbx
    SUB R17, R17, R18
```

Una pareja entera `MADD`/`MSUB` permitiría conservar un solo temporal:

```asm
    MUL  R17, Rax, Rby
    MSUB R17, Ray, Rbx
```

No se propone `CROSS2`: necesitaría cuatro fuentes explícitas y quedaría muy
ligada a geometría 2D. La acumulación multiplicativa es útil también en filtros,
audio y álgebra lineal. Deben definirse con cuidado el ancho del producto, el
overflow y si hay acumulación completa o solo sobre los 32 bits bajos.

Las rotaciones Q16.16 presentan el mismo caso con signo y escala fija. `MACFX`
ya está propuesto; para cubrir expresiones como `a*b - c*d` sin negar un
operando hace falta considerar también `MSUBFX`.

## Escritura secuencial: `STOREHP`

Una versión que recorra toda la caja, seleccione cara o fondo y escriba siempre
un píxel puede combinar store y avance:

```asm
    STOREHP Rcolor, Rptr, 2
```

en lugar de:

```asm
    STOREH Rcolor, Rptr, 0
    ADDI   Rptr, Rptr, 2
```

El beneficio aparece por píxel y no solo durante la preparación. También sirve
para borrados, sprites, texto y conversiones de imagen. En GPU, el incremento
debe ocurrir por lane y solo después de completar correctamente su acceso, como
ya recoge la propuesta v0.3.

## Orden de experimentación

Para atribuir cada mejora a su causa:

1. eliminar de `putpixel` el `MUL` por píxel manteniendo un puntero incremental;
2. portar el rasterizador a GPU y medir instrucciones, `LANE_OPS`, divergencia,
   tráfico LSU y tiempo con `SCANOUT` activo;
3. habilitar `SLT` y añadir `SEL`, y repetir las medidas;
4. probar `MIN/MAX` en preparación y clipping;
5. cerrar e implementar `RCPFX` para la transformación;
6. medir si `MADD/MSUB` y `MACFX/MSUBFX` justifican su coste de lectura y
   writeback;
7. evaluar `STOREHP` sobre una variante que escriba todos los píxeles de la caja.

`BLANK` y `PATTERN` pueden medir el techo bruto, pero el resultado gráfico que
importa debe medirse con `SCANOUT`: el framebuffer frontal ha de seguir visible
mientras la GPU construye el trasero.

## Criterio de aceptación

Una instrucción no se justifica solo porque acorte el ensamblador. Para entrar
en la ISA debería demostrar al menos uno de estos efectos sobre este caso y otro
workload independiente:

- reducción medible de ciclos o instrucciones retiradas;
- menor divergencia SIMT;
- menos temporales y presión de registros;
- mejor coalescencia o menos transacciones de memoria;
- contrato suficientemente general para código no gráfico.

El cubo sólido aporta el caso gráfico y un framebuffer verificable; no sustituye
los tests unitarios de extremos numéricos, máscaras de lanes y errores.

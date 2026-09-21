# Migración de la 21 a MMIO v2

Log de trabajo, escrito **durante** la migración. El orden de las secciones es
el orden real en que pasaron las cosas, no el orden del plan.

Contrato de referencia: [`../../1.isa/mmio.md`](../../1.isa/mmio.md).

**Alcance de cada decisión.** Cada apartado lleva una marca:

- `[TODAS]` vale para las diez carpetas.
- `[CPU]` vale para la familia CPU (6, 10, 16, 18, 19, 21).
- `[21]` es específico de esta carpeta.

---

## Fase 0 — Verificación del punto de partida

Antes de tocar nada se comprobó contra el árbol cada afirmación concreta del
encargo. La mayoría se sostiene; tres no, y una de ellas cambia el plan.

### Lo que se confirmó

| Afirmación | Estado |
|---|---|
| `cpu_dmem_adapter.v`: `MMIO_PREFIX = 20'h80000`, `mmio_address[11:0]` | correcto (líneas 63, 229, 292) |
| `monitor_mem_adapter_128.v`: mismo `MMIO_PREFIX` | correcto (líneas 29, 103, 144) |
| `mmio_decoder.v`: `device = address[11:8]` | correcto (línea 80) |
| `sysid.v`: 4 palabras en `0x80000F00` | correcto |
| `sim_devices.py`: `BASE = 0x8000_0000` y `0x8000_0200` | correcto (líneas 21, 166) |
| `apio.ini`: `--seed 13`, 87,09 MHz, +8,9 % | correcto |
| `x.tests/test_top_wiring.py` y `test_monitor_port.py` existen | correcto |
| `monitor.v` idéntico byte a byte | correcto, y son **exactamente** las 10 carpetas de prototipo (mismo MD5 `170E0AB3…`) |
| `tools/lint --prototype 21` da 38 diagnósticos | correcto: **38 `%Warning-PINMISSING`, 0 errores**. Éste es el número base a no empeorar |

### Lo que no cuadró

**1. El reparto de los 19 `.asm` es otro.** El total sí es 19, pero son **5 en
`x.tests/cases/` y 14 en `examples/`**, no 7 y 12.

- Casos: `video/registers`, `video/bounce`, `video/band`,
  `extensions/serial/uppercase`, `extensions/serial/empty-input`.
- Examples: los 14 que hacen `MOVHI Rn, 0x8000`.

El resto de `0x8000` que aparece en `grep` son constantes de ALU
(`0x80000000` como `INT_MIN`), no direcciones. Confundirlas y "migrarlas"
rompería `shift-amount`, `mulhi-signed`, `remainder-signs` y
`compare/signed-unsigned`, que es justo la clase de edición masiva que el
generador viene a evitar. `[TODAS]`

**2. `lint` no sale con «exit 1» por 38 diagnósticos sueltos.** Sale con exit 2
desde `apio lint` porque scons trata los `PINMISSING` como fatales, y el
lanzador lo reporta como fallo. El número a vigilar es **38**; el exit code no
distingue mejora de empeoramiento y no sirve de criterio. `[TODAS]`

**3. `monitor.py` no es una gemela, son trece copias divergentes.** A
diferencia de `monitor.v`, cada carpeta tiene la suya y no coinciden. La
migración de la 21 toca sólo la suya, pero conviene saber que aquí **no** hay
un fichero común que arreglar una vez. `[TODAS]`

### El hallazgo que cambia el plan

> **El ensamblador no tiene constantes simbólicas.**

`1.isa/mini_asm.py` soporta `.include` (ya se usa: `putpixel.inc`,
`drawline.inc`, `sin256.inc`), etiquetas, `.comm` y aritmética `+`/`-` en
`resolve_target`. Lo que **no** tiene es ninguna directiva tipo `.equ` / `.set`
que dé nombre a un valor.

Sin eso, el paso 2 del plan —«se genera el `.inc` del ensamblador y los
programas pasan a usar símbolos»— no tiene dónde apoyarse: un `.inc` generado
no puede expresar `VIDEO_BASE = 0x80200000`.

Hay una segunda trampa encima:

> **`MOVHI` no resuelve símbolos.** Usa `parse_int` (línea 937), mientras que
> `MOVI` (930) y `LI` (1063) sí pasan por `resolve_target`.

O sea que aunque existiera `.equ`, `MOVHI R2, VIDEO_BASE` seguiría sin
ensamblar. El vehículo natural es la pseudoinstrucción **`LI Rd, expr32`**, que
ya resuelve símbolos y expande a `MOVHI` + `ORI`.

**Consecuencia que hay que tener presente:** `LI` emite **dos palabras** donde
`MOVHI` emitía una. Los 19 programas cambian de tamaño y de cuenta de ciclos.
Cualquier caso de `x.tests` que compruebe un PC final, un tamaño de imagen o un
número de ciclos se romperá por esto y **no** por un error de dirección. `[TODAS]`

Trabajo añadido al plan, antes del generador:

1. `.equ NAME, expr` en `mini_asm.py`, alimentando el mismo diccionario
   `labels` (así hereda `resolve_target` y la aritmética `+`/`-` gratis).
2. Su test en `1.isa/test_mini_asm.py`, con control negativo.

Es cambio en el ensamblador **compartido por las diez carpetas y por el
simulador**, así que es la primera pieza del viaje y la que más se amortiza.
`[TODAS]`

### Orden revisado

El orden del encargo era correcto en su tesis —el generador primero, el RTL
después— pero le falta un escalón por delante:

```text
0.  verificación                        ← hecho
1.  .equ en el ensamblador              ← añadido en fase 0
2.  mmio_map.vh + generador + test
3.  migrar los 19 .asm a símbolos
4.  ensanchar el bus (con test_top_wiring extendido ANTES)
5.  RTL por dispositivo
6.  sim_devices.py + monitor.py
7.  docs y TODO.md
8.  síntesis y barrido                  ← sólo con permiso explícito
```

Los pasos 1–3 no tocan ni una dirección: al terminarlos los programas siguen
apuntando a `0x80000000`, pero por símbolo. Eso es deliberado — separa
«dar nombre a las direcciones» de «cambiar las direcciones», y deja un punto
intermedio donde todo pasa y se puede comparar. `[TODAS]`

---

## Fase 1 — `.equ` en el ensamblador `[TODAS]`

Escalón que el plan original no tenía, y que la fase 0 encontró. Sin constantes
simbólicas no hay `.inc` generado que valga.

### Qué cambió

| Fichero | Qué le pasa |
|---|---|
| `1.isa/mini_asm.py` | `.equ nombre, valor` (alias `.set`) en la pasada 1; dict `equates` aparte, fundido con `labels` al final |
| `1.isa/test_mini_asm.py` | clase `EquTest`: 6 casos positivos y 8 controles negativos |
| `1.isa/ensamblador.md` | apartado «Constantes: `.equ`», y la línea de «Qué no tiene» |

### Las tres decisiones de diseño, y por qué

**1. Un solo espacio de nombres con las etiquetas.** `equates` se guarda aparte
durante la pasada 1 —una constante no pertenece a ninguna sección y su valor no
se desplaza al colocar la imagen— pero se funde en `labels` al final. Así
`resolve_target` no tiene que saber de dónde viene cada nombre, y la aritmética
`+`/`-` que ya existía sirve igual para `BASE+0x04`.

El precio es que hay que rechazar las colisiones **en las dos direcciones**:
etiqueta que pisa constante y constante que pisa etiqueta. Están las dos
guardas y las dos tienen test.

**2. El valor se resuelve en el sitio, sin referencias hacia delante.** `.equ A,
B+1` con `B` definida después es **error**, y una `.equ` no puede referirse a
una etiqueta. Admitirlo pediría un solucionador de dependencias, y §20 del
contrato pide lo contrario: una fuente tonta. El error lo dice explícitamente
(«no resoluble … solo admite enteros y constantes .equ ya definidas») en vez de
soltar el «etiqueta no definida» genérico, que mandaría a buscar una errata.

**3. `MOVHI` se queda como está.** No resuelve símbolos (usa `parse_int`,
mientras `MOVI` y `LI` usan `resolve_target`). No se tocó: el vehículo es
`LI Rd, expr32`, que ya resuelve y expande a `MOVHI`+`ORI`. Darle símbolos a
`MOVHI` obligaría a inventar `hi()`/`lo()` para partir un valor de 32 bits en
dos mitades, y no hace falta para nada de esto.

### El control negativo

Un test que pasa no demuestra nada. Se rompió la referencia cinco veces y se
comprobó que falla **el test que toca**:

| Mutación | Qué falla | ¿El correcto? |
|---|---|---|
| M1 nombre desconocido resuelve a 0 | `nombre_no_definido_no_se_inventa`, `referencia_hacia_delante`, `no_puede_referirse_a_una_etiqueta` (+1 preexistente de etiquetas locales) | sí |
| M2 `labels.update(equates)` no se ejecuta | los 5 positivos | sí |
| M3 se quita la guardia de duplicada | `constante_duplicada`, y sólo ése | sí |
| M4 se quita la guardia etiqueta→constante | `choca_con_una_etiqueta`, y sólo ése | sí |
| M5 `.equ` ocupa 4 bytes | `no_ocupa_espacio` + los 5 positivos | sí |

M1 es la que importa: si un nombre mal escrito valiera cero, `LI R2,
VIDEO_BSAE` apuntaría a la dirección 0 —que es RAM válida— y el programa
escribiría en memoria en vez de en el registro, sin que nada se quejara.

**Aviso de método.** M3 y M5 no aplicaron al primer intento: el fichero tiene
finales de línea CRLF y el texto de la mutación iba con LF, así que
`.Replace()` no encontraba nada y el script imprimía «LA MUTACION NO APLICO».
Si esa comprobación no estuviera, las dos habrían salido como «ningún test
falla» —o sea, como un control negativo superado— cuando en realidad el código
no se había tocado. **Un control negativo necesita su propio control: verificar
que la mutación se aplicó.** `[TODAS]`

### Lo que se rompió

Nada. 61 tests del ensamblador en verde, y `run_tests.py --backend cpusim` da
52 casos y 0 fallos, igual que antes. Era esperable: la directiva es aditiva y
todavía no la usa ningún programa.

`python tools/check-links.py` — 610 enlaces, ninguno roto.

### Coste

Unas 40 líneas de ensamblador y 100 de test. **No se repite en las otras nueve
carpetas**: `mini_asm.py` es único y compartido. Es el trozo de la migración
que más se amortiza.

---

## Fase 2 — fuente única y generador `[TODAS]`

### Qué cambió

| Fichero | Qué le pasa |
|---|---|
| `1.isa/mmio_map.vh` | **nuevo**. La fuente maestra de §20: bases, offsets, bits de `DEVICES`, el magic. Sólo `define`, sin una expresión |
| `tools/generate_mmio.py` | **nuevo**. Parser de tres líneas + dos renderizadores + `--check` |
| `tools/generate-mmio`, `.ps1` | **nuevos**. Lanzadores, sin lógica, como manda `AGENTS.md` |
| `x.tests/inc/mmio.inc` | **generado**. El include del ensamblador, con `.once` |
| `tools/mmio_map.py` | **generado**. Las mismas constantes para monitor y simuladores |
| `x.tests/test_mmio_map.py` | **nuevo**. 25 tests en cuatro grupos |
| `tools/README.md` | apartado nuevo del lanzador |

### La decisión que quedaba pendiente: lo generado se versiona

Se commitean `mmio.inc` y `mmio_map.py`, y un test comprueba que están al día.
La alternativa —generarlos en tiempo de build— se descartó porque **no hay
tiempo de build**: `run_tests.py` y `tools/run_board.py` llaman al ensamblador
directamente sobre el `.asm`. Generar al vuelo obligaría a que todo camino que
ensambla ejecutara antes el generador, y el que se olvide falla de forma
oscura y en el sitio equivocado. Versionar y comprobar mueve el fallo a un
test que dice exactamente qué pasa y qué ejecutar. `[TODAS]`

### El fallo del propio generador

Merece su apartado porque es el modo de fallo que toda esta fase existe para
evitar, cometido por la pieza que lo evita.

`base_de()` deduce a qué bloque pertenece un `_OFF` por el prefijo más largo
de su nombre que tenga un `_BASE`. Con los nombres que tenía la primera
versión del `.vh`:

```text
MMIO_GPU_WARP_PC_OFF   → no existe MMIO_GPU_WARP_BASE (la base lleva S:
                         MMIO_GPU_WARPS_BASE) → cae a MMIO_GPU_BASE
```

Resultado: los cuatro descriptores de warp y los cinco registros de SIMT DEBUG
colgados de `MMIO_GPU_BASE`. `MMIO_GPU_WARP_PC_ADDR` salió en la **misma
dirección que `MMIO_GPU_ID_ADDR`**, y `WARP_RETIRED` encima de `GPU_CAPS`.

**Y no falló nada.** El `.inc` se generó, el ensamblador lo tragó sin una queja
y un programa habría escrito en el registro equivocado. Se vio leyendo la
salida, no por un test.

Arreglado por los dos lados, porque uno solo no basta:

1. **Nombres explícitos** en el `.vh` (`MMIO_GPU_WARPS_*`, `MMIO_GPU_SIMT_*`),
   con un comentario delante que dice por qué la S importa.
2. **Comprobación de colisiones** en el generador: dos registros en la misma
   dirección es `MmioMapError`, no un aviso. Es la red que caza el error la
   próxima vez sin depender de que alguien lea la salida.

Lección para las otras nueve: **una heurística sobre nombres necesita un
invariante que la verifique.** El nombre correcto evita el fallo; la
comprobación lo detecta. `[TODAS]`

### Por qué el test tiene tres grupos y no uno

`--check` sólo demuestra que `mmio.inc == generar(mmio_map.vh)`. Si alguien
edita mal el `.vh`, regenera tan contento y `--check` pasa. Por eso hay un
segundo grupo, `ConformidadTest`, con **los números copiados a mano de
`mmio.md`**. La duplicación ahí es el mecanismo, no un descuido: derivarlos del
mismo sitio que el generador lo convertiría en una tautología.

El tercero, `GeneradorEstrictoTest`, fija lo que el generador debe rechazar
—expresiones, `ifdef`, duplicados, colisiones—. El parser es estricto a
propósito: una línea que no entiende es un error, no un salto. Una constante
que desaparece del fichero generado porque el parser se la saltó no la echa de
menos nadie hasta la placa.

Y un cuarto, `EnsamblaDeVerdadTest`, que ensambla de verdad contra
`mini_asm` y compara las palabras. Un `.inc` sintácticamente válido pero
inútil pasaría los otros tres.

### El control negativo

| Mutación | Sincronía | Conformidad | ¿Correcto? |
|---|---|---|---|
| M1 editar el `.inc` generado a mano | **falla** | pasa | sí |
| M2 tocar el `.vh` y no regenerar | **falla** | **falla** | sí |
| M3 tocar el `.vh` **y regenerar** | pasa | **falla** | **sí, y es el que importa** |

M3 es la prueba de que la conformidad no es una tautología: la sincronía está
contenta —lo generado corresponde a la fuente— y aun así el test grita porque
la fuente ya no dice lo que dice el contrato. Sin ese grupo, mover una base por
error sería indetectable.

(Se intentó una cuarta, borrar el fichero generado, y el sandbox bloqueó el
`Remove-Item`. Se dio por cubierta: es un caso más débil que M1, y el código
trata el fichero ausente igual que uno distinto.)

### Lo que se rompió

Nada. 260 tests de `x.tests` (25 nuevos), 61 del ensamblador, 52 casos de
`cpusim` con 0 fallos, `check-links` con 610 enlaces y `generate-docs --check`
al día.

### Estado a día de hoy

**Todavía no se ha movido ninguna dirección.** `mmio_map.vh` ya dice
`MMIO_VIDEO_BASE = 0x80200000`, o sea el mapa v2, pero **nadie lo usa aún**:
ni el RTL, ni los `.asm`, ni los simuladores. Los 19 programas siguen con su
`MOVHI Rn, 0x8000` cableado y todo pasa. Es el punto intermedio buscado.

### Coste

`mmio_map.vh` (~180 líneas), generador (~200), test (~260). **Nada de esto se
repite en las otras nueve carpetas**: las tres piezas son del repo, no de la
21. Lo que sí se repetirá es consumirlas.

---

## Fase 3 — los 19 programas a símbolos, sin mover nada `[TODAS]` + `[21]`

### La pieza que faltaba: un mapa v1

Los programas no podían pasar a `mmio.inc` todavía —apunta a v2 y el RTL sigue
en v1—, así que se añadió `1.isa/mmio_map_v1.vh`: **el mapa de hoy, con los
mismos nombres que v2**. Los números salen del RTL de la 21, no de un
documento: `mmio_decoder.v` para los slots y los `localparam REG_*` de
`video_registers.v` y `serial_port.v` por cuatro.

Que los nombres coincidan es todo el truco: **migrar un programa en la fase 5
será cambiar su línea de `.include`**, nada más. Y como los dos ficheros
definen los mismos nombres, incluir los dos a la vez es error de constante
duplicada — o sea que un programa a medio migrar no ensambla, que es
justamente lo que se quiere.

`mmio_map_v1.vh` es andamio y lleva escrito cuándo se borra: cuando la última
de las diez carpetas esté migrada. `[TODAS]`

El generador pasó de un mapa a una tabla de mapas, unas 20 líneas.

### Lo que cambió

| Fichero | Qué le pasa |
|---|---|
| `1.isa/mmio_map_v1.vh` | **nuevo**, temporal. El mapa de hoy |
| `tools/generate_mmio.py` | tabla `MAPAS` en vez de una fuente; `parse_map`/`render_*` reciben el nombre de la fuente |
| 5 `.asm` de `x.tests/cases` | `.include "mmio_v1.inc"`, `LI Rn, MMIO_*_BASE`, offsets por símbolo |
| 14 `.asm` de `examples/` | lo mismo; 84 offsets en total |
| `x.tests/cases/video/registers/test.json` | `pc` de `0x44` a `0x48` |
| `x.tests/test_mmio_map.py` | clase del mapa v1, y la guarda de «ningún `.asm` cableado» |

### Qué se rompió

**Un caso, exactamente el predicho.** `video-registers` fija `pc` y falló con
`esperado 0x00000044, obtenido 0x00000048`: `LI` emite dos palabras donde
`MOVHI` emitía una. Se actualizó el esperado.

Lo interesante es **cuáles no fallaron**. Los dos casos de serie hacían
`MOVHI` + `ORI` —porque la base `0x80000200` no cabe en la mitad alta—, o sea
ya ocupaban dos palabras, así que `LI` no los alarga y su `pc` no se movió.

> Regla para las otras nueve: **se alargan los programas que cargaban la base
> con un solo `MOVHI`**, no los que ya hacían `MOVHI` + `ORI`. En v2 *ninguna*
> base es cargable con un solo `MOVHI` porque todas tienen la mitad baja a
> cero… salvo que, precisamente por eso, `LI` seguirá emitiendo dos. Cuenta
> los `MOVHI` sueltos de una carpeta y sabrás cuántos `pc` esperados hay que
> tocar. `[TODAS]`

### El fallo que cometió el propio test

La guarda «ningún `.asm` lleva una dirección cableada» se escribió primero
buscando `MOVHI Rn, 0x8000`. Saltó con cuatro casos:

```text
cases/alu/shift-amount/program.asm:4          MOVHI R1, 0x8000   ; INT_MIN
cases/extensions/alu-extended/mulhi-signed    MOVHI R13, 0x8000
cases/extensions/alu-extended/remainder-signs MOVHI R19, 0x8000
cases/extensions/compare/signed-unsigned      MOVHI R13, 0x8000
```

Ninguno es una dirección: `0x80000000` ahí es **INT_MIN**, un operando de la
ALU. La fase 0 ya avisó de esta confusión al recontar los 19 programas, y aun
así el test cayó en ella.

La solución no fue una lista de excepciones —el siguiente caso que usara
INT_MIN volvería a saltar— sino cambiar el criterio:

> **No es el valor lo que distingue una dirección, es el uso: es una dirección
> si el registro se desreferencia después.** INT_MIN se suma, se desplaza y se
> compara; una base se pone debajo de un `LOAD` o un `STORE`.

Con eso el test discrimina solo, y hay dos tests más que fijan las dos mitades
de la regla. `[TODAS]`

### El control negativo

| Mutación | Resultado | ¿Correcto? |
|---|---|---|
| volver a cablear la base en un example | **salta** | sí |
| caso nuevo con INT_MIN sin desreferenciar | **calla** | sí, y es la mitad que importa |
| ese mismo caso desreferenciando el registro | **salta** | sí |

Y uno gratis, no provocado: al añadir el mapa v1 saltó
`test_los_destinos_se_generan`, que existe para decir «has añadido una salida
y no has tocado el test». Funcionó sin que nadie lo probara a propósito.

### Estado

**Sigue sin moverse ninguna dirección.** Los 19 programas van por símbolo
contra el mapa de hoy, y las 52 pruebas de `cpusim` pasan, incluidas las siete
que comparan frame contra un binario de referencia. Eso es lo que demuestra
que la simbolización es correcta **por separado** del cambio de mapa: cuando
la fase 5 rompa algo, será el mapa.

RTL sin tocar, así que la semilla 13 sigue valiendo.

### Coste

Los 19 programas: unos 40 minutos, casi todo con un script de sustitución
guiado por el registro base de cada fichero (está en el scratchpad, no se
versionó: es de usar y tirar y depende de qué registro usa cada programa).

Lo caro no fue editar, fue **averiguar qué registro es la base en cada
fichero** —`R2` en unos, `R20` en otros— y que sólo se toquen los `LOAD`/
`STORE` que cuelgan de ése. Un `sed` sobre `, 4` habría destrozado
`STORE R13, R6, 0`, que escribe en el framebuffer.

Para la siguiente carpeta: **empieza listando (fichero, registro base,
dispositivo)**. Es el dato que hace el resto mecánico. `[TODAS]`

---

## Fase 4 — la red de seguridad del ancho de bus `[TODAS]`

El encargo lo pedía explícitamente: extender `test_top_wiring.py` **antes** de
tocar el ancho. Esta fase es sólo eso. No se ha modificado ni un bit de RTL.

### Por qué hace falta y por qué no la cubre nada

El fallo de la 18: doce bits de dirección en el decodificador, cinco en su
`top.v`. Verilog conectó los puertos truncando **sin un aviso**, y los
dieciséis dispositivos cayeron sobre el de vídeo — pedir `SYS_ID` devolvía
`FB_FRONT`.

No lo ve ningún banco porque **ninguno instancia `top`**, que es la misma
causa por la que existía ya la primera mitad de este fichero. Y no lo ve un
linter porque no es un error: es Verilog legal.

Importa ahora porque v2 separa los dispositivos por megabytes: ese bus se
ensancha en las diez carpetas.

### Qué comprueba

Para cada instanciación en cada `top.v`: el ancho declarado de la señal contra
el ancho declarado del puerto, leyendo el `.v` del módulo.

Una conexión con `[a:b]` explícito **no** es un fallo aunque no llene el
puerto: es una decisión escrita, y el `top.v` de la 21 tiene varias
legítimas (`.address(mmio_address[7:0])`). Lo que se persigue es el **nombre
desnudo** con otro ancho, que es truncamiento accidental.

Lo que no sabe medir, lo salta: un rango con una expresión que no es literal,
parámetro ni `PARAM-1` no se compara. Saltarse una comparación es aceptable;
inventarse un ancho, no.

### El estado del árbol

**1442 comparaciones en las diez carpetas, cero desajustes.** El árbol está
limpio hoy, como cabía esperar: el fallo de la 18 se arregló en su día.

### El fallo que tuvo el propio test, otra vez

La primera versión hacía **860** comparaciones, no 1442. Se saltaba el 40 %
por algo tonto:

```verilog
wire [31:0] mmio_write_data, mmio_read_data;
```

La expresión regular capturaba sólo el primer nombre, así que `mmio_read_data`
quedaba con ancho desconocido y se saltaba. Se descubrió porque una mutación
—declarar ese bus de 16 bits— **no hizo saltar nada**.

Es el tercer caso en esta migración del mismo patrón: la herramienta que
vigila un fallo silencioso lo comete. Por eso el test lleva ahora dos guardas
propias: un mínimo de comparaciones totales y que **ninguna carpeta quede a
cero**. Un test que compara menos sigue pasando, y ése es el peligro. `[TODAS]`

### El control negativo

| Mutación | Resultado |
|---|---|
| M1 el fallo de la 18 reproducido (12 bits → 5) | **salta**, nombrando `mmio_mux.address` y `mmio_decoder.address` |
| M2 al revés, bus más ancho que el puerto | **salta** |
| M3 dato de 32 bits declarado de 16 | **salta** (`cpu_dmem_adapter.mmio_read_data`) |
| M4 el analizador deja de entender los `top.v` | **salta** por el mínimo de comparaciones |

M1 es la prueba de que este test habría ahorrado una síntesis y una placa.

### Una trampa de método que costó veinte minutos

M4 cambiaba `\s{2,}` por `\s{9,}` en el propio test. Tras restaurarlo, el
control **seguía fallando** aunque el fichero en disco era el correcto.

La causa era el `__pycache__`: Python invalida el `.pyc` por **mtime y
tamaño**, y `{2,}` y `{9,}` ocupan lo mismo. Con la restauración dentro del
mismo segundo, Python siguió ejecutando el bytecode mutado.

> **Una mutación del mismo número de caracteres puede quedar enmascarada por
> el caché de bytecode, en los dos sentidos.** Lo peligroso no es que un
> control falle de más: es que un control que debía saltar salga «OK» porque
> se ejecutó el código viejo. Al hacer mutation testing sobre Python, borra
> `__pycache__` entre pasadas.

Se revisaron los controles anteriores de esta migración por si estaban
afectados: en cada tanda al menos una mutación sí disparó —lo que demuestra
que se ejecutó código fresco— y los controles cuyo resultado esperado era «OK»
mutaban ficheros de datos (`.asm`, `.inc`), que no tienen bytecode. Ninguno
queda invalidado. `[TODAS]`

### Lo que se rompió

Nada. 262 tests de `x.tests`, 61 del ensamblador, 52 casos de `cpusim`.
`lint --prototype 21` sigue en **38**, como debe, porque no se ha tocado RTL.

La semilla 13 sigue siendo válida.

### Coste

Unas 130 líneas de test. **No se repite**: cubre las diez carpetas desde el
primer día, porque itera la lista de prototipos. Es, con el generador, la otra
pieza que se amortiza entera en la primera carpeta.

---

## Corrección a la fase 5 preliminar: casi todo el RTL es copia compartida

Antes de la fase 5 se comprobó qué ficheros son idénticos entre carpetas y la
conclusión fue **errónea**: se dijo que sólo `monitor.v` lo era. El comando de
hashes agrupaba mal y daba un grupo por fichero.

La realidad, medida bien:

| Fichero | Copias | Distintas **antes** de tocar nada |
|---|---:|---:|
| `monitor.v` | 10 | 1 |
| `sysid.v` | 10 | **1** |
| `mmio_decoder.v` | 4 | **1** |
| `video_registers.v` | 4 | **1** |
| `cpu_perf_counters.v` | 4 | **1** |
| `mmio_mux.v` | 3 | **1** |
| `serial_port.v` | 2 | **1** |
| `monitor_mem_adapter_128.v` | 3 | **1** |
| `cpu_dmem_adapter.v` | 3 | 2 |

O sea: **migrar una carpeta bifurca ocho ficheros compartidos**, no uno. La
trampa 2 del encargo describe el problema para `monitor.v`, y aplica mucho más
ancho de lo que decía.

Y hay un test que lo vigilaba para `sysid.v`, no sólo para `monitor.v`:
`test_monitor_port.test_sysid_es_copia_identica`. Saltó en cuanto se tocó.

**Cómo se resolvió, y es la decisión de alcance más importante del log.** La
bifurcación es inherente a migrar carpeta a carpeta, así que no se evita: se
acota. El test pasa de «los diez idénticos» a **«los de la misma versión del
contrato, idénticos»**, agrupando por el magic que cada `sysid.v` lleva dentro.
Así conviven las dos generaciones durante la travesía y se sigue cazando que
alguien toque una copia y deje las demás atrás. Cuando migre la última
carpeta, el grupo de v1 se vacía y vuelve a ser la comprobación de siempre sin
tocar nada.

Relajarlo a «se parecen» habría sido lo fácil y habría dejado de comprobar
justo lo que importa. `[TODAS]`

---

## Fase 5a — el camino de dirección `[TODAS]`

La fase 5 se partió en dos al descubrir que `HALT_AT` cambia de contador
(ver «Lo que bloquea la 5b» al final). **5a mueve las bases de bloque; los
registros de cada dispositivo siguen donde estaban.**

El orden importa y no es cosmético: mover una base da **error de
decodificación**, que es ruidoso y se diagnostica en un minuto. Mover un
offset dentro del dispositivo hace que conteste **otro registro**, sin error
ninguno — escribir `CTRL` acaba escribiendo `FB_FRONT` y lo que se ve es una
imagen rara. Separarlos hace que el segundo paso empiece desde un estado
verificado. `[TODAS]`

### Qué cambió, y por qué

| Fichero | Qué le pasa |
|---|---|
| `cpu_dmem_adapter.v` | fuera `MMIO_PREFIX`; ahora `address[31]`. `mmio_address` de 12 a 32 bits |
| `monitor_mem_adapter_128.v` | lo mismo |
| `mmio_mux.v` | ancho por parámetro `ADDR_BITS = 32`, declarado **una vez** |
| `mmio_decoder.v` | bloques de 64 KiB; `block = address[26:16]`; SYSTEM/SERIAL/VIDEO/CPU_PERF |
| `sysid.v` | bloque SYSTEM de siete palabras en `0x80000000`, `MAGIC = 0x4D474155` |
| `top.v` | anchos, `DEVICES`/`MEM_*`/`MONITOR_VERSION`, y **cuatro** ventanas de monitor |
| 6 bancos | anchos, direcciones y programas ensamblados a mano |
| `tools/sim_devices.py` | bases v2, bloques de 64 KiB |
| `tools/sysid_device.py` | gemelo Python de SYSTEM, siete palabras |
| `21/monitor.py` | regiones desde el mapa generado |
| `x.tests/backends/fpga.py` | direcciones desde el mapa generado |
| 6 `.asm` más | `20.forth`, `cases-shared/video` y los 4 de `cases-shared/mmio` |

**La detección de MMIO pasa de veinte bits a uno.** `address[31:12] == 20'h80000`
era razonable cuando todo cabía en 4 KiB; ahora la pertenencia al espacio es
`address[31]` y quién vive en cada bloque lo decide el decodificador. Es más
barato **y** más seguro: un bit no se puede truncar al conectar un puerto.

**`monitor.v` no se ha tocado**, y conviene subrayarlo porque era la trampa 2.
Ya tenía cinco ranuras `WINDOWn_BASE/END` parametrizadas y v2 necesita cuatro.
Lo que cambia son los valores, en `top.v`.

### Lo que se rompió, en orden

Siete fallos, todos del tipo «una dirección v1 escrita en un sitio que no
miré». Se listan porque el **patrón** es lo que se repite:

1. `cpu_burst_system_tb` — `mon_write(32'h8000_0008)`.
2. `cpu_serial_tb` — programa ensamblado **a mano** en hexadecimal:
   `32'h5E80_8000` es `MOVHI R20, 0x8000`. No lo encuentra ninguna búsqueda de
   direcciones, porque la dirección está dentro de una instrucción.
3. `cpu_serial_tb` otra vez — y ésta es la más escurridiza: la dirección iba
   **partida en cuatro bytes** en el flujo del monitor,
   `send_byte(8'h80); send_byte(8'h00); …`.
4. `cpu_video_tb` — otro programa en hexadecimal.
5. `cpu_mmio_error_tb` — construido entero sobre la página de 4 KiB: un offset
   de 16 bits alcanzaba los dieciséis dispositivos. Con los bloques a
   megabytes hubo que **reescribirlo**, con la mitad alta como parámetro.
6. `20.forth/forth.asm` y `cases-shared/video/double-buffer` — programas fuera
   de las dos carpetas que la guarda escaneaba.
7. `cases-shared/mmio/*` — cuatro casos más, en la misma situación.

> **Una dirección MMIO aparece en cinco formas distintas**: literal
> (`32'h8000_0000`), dentro de una instrucción ensamblada a mano
> (`32'h5E80_8000`), partida en bytes de protocolo (`8'h80, 8'h00, …`), como
> offset de 16 bits sobre una base implícita, y en constantes de Python.
> Buscar sólo la primera encuentra menos de la mitad. `[TODAS]`

### El alcance de la guarda estaba mal

`test_ningun_asm_carga_una_base_mmio_a_mano` sólo miraba `x.tests/cases` y
`21/examples`. Los seis `.asm` de los puntos 6 y 7 aparecieron **corriendo el
simulador**, que es tarde: el sentido de esa guarda es que salte barato.

Ampliada a `cases-shared` y `20.forth`. La lección no es de patrón sino de
alcance: **los programas de este repo no viven todos bajo `x.tests/cases`**. Al
migrar la siguiente carpeta, lo primero es listar dónde hay `.asm`. `[TODAS]`

### Una gemela que mejoró por el camino

`test_monitor_protocol.test_la_ventana_del_host_llega_a_donde_llega_el_rtl`
comparaba `MONITOR_REGIONS` contra el `MMIO_PREFIX` del adaptador. Ese prefijo
ya no existe, así que había que reescribirlo — y al hacerlo se vio que estaba
comparando contra la cosa equivocada desde siempre.

La gemela **de verdad** de `MONITOR_REGIONS` son los `WINDOWn_BASE/END` del
`monitor #(...)`: el RTL filtra con unos y el host con los otros. El prefijo
del adaptador sólo coincidía por casualidad, mientras todo cabía en una
página. Ahora compara conjuntos completos, no pertenencia. `[TODAS]`

### Un detalle que obliga a escribir a mano

`MONITOR_REGIONS` **no** puede derivarse del mapa generado aunque el mapa esté
importado dos líneas más arriba: `tools/prototype_report.py` lee esa asignación
del **texto** del fichero, sin importar el módulo, y un `tuple(... for ...)` lo
deja ciego. Hay un test que lo exige.

Se deja literal y se añade un test que la contrasta contra el mapa generado.
Escribir a mano es obligatorio; dejarlo sin comprobar, no. `[TODAS]`

### Verificación

- **30 bancos RTL de la 21: SUCCESS.**
- 273 tests de `x.tests`, 61 del ensamblador.
- 52 casos de `cpusim`, 0 fallos, incluidos los siete que comparan frame.
- `lint --prototype 21`: **38**, exactamente la línea base.
- 612 enlaces, `generate-docs --check` y `generate-mmio --check` al día.

**La semilla 13 ya no vale**: esto es cambio de RTL. No se ha sintetizado.

### Lo que bloquea la 5b, y es una decisión tuya

`HALT_AT` cuenta hoy contra `SWAP_COUNT`. El contrato (§9.6, decisión
congelada 17) dice que debe contar contra `FRAME_COUNT`, «porque un programa
que se cuelga sin pedir swaps también tiene que poder capturarse».

El problema es que `run_until: {swap: N}` es un concepto de primera clase del
runner —`parse_run_until` sólo admite esa clave— y lo usan **nueve casos de
vídeo**, ocho de ellos con `reference.py` que recalcula el frame esperado.

Cambiar `HALT_AT` a frames obliga a convertir `run_until.swap` en
`run_until.frame` y a revisar los nueve. Frames y swaps no son lo mismo: un
programa que dibuja despacio produce varios frames por swap, así que el
instante de captura cambia y algunas referencias habrá que reevaluarlas.

Es mecánico pero no trivial, y el contrato no deja alternativa conforme. Lo
dejo señalado antes de gastarlo.

---

## Fase 5b — el simulador y los dos rojos

**Estado: verde.** Lo que sigue se escribió en dos tandas: primero con el árbol
rojo, describiendo dónde estaba la línea, y después al cerrarlo. Se deja el
orden real —incluido lo que creí que era el problema y no lo era— porque eso es
justo lo que la siguiente carpeta necesita leer.

### Hecho y verificado

| Fichero | Qué le pasa |
|---|---|
| `video_registers.v` | offsets de v2 (CTRL a +0x00), `FRAME_COUNT` propio de 32 bits, `HALT_TARGET`, `VIDEO_TX`, error de dato |
| `cpu_perf_counters.v` | array en +0, `PERF_CTRL` en +0x100, `PERF_OVF0/1`, banderas de desbordamiento |
| `mmio_decoder.v` | `VIDEO_REGISTERS = 0x3ff`, reglas de error de §12.6, `perf_select`, mezcla del error del dispositivo |
| `top.v`, 8 bancos | cableado, offsets y programas |
| los 25 `.asm` | pasan de `mmio_v1.inc` a `mmio.inc`; el mapa de transición se borra |

El mapa de transición cumplió su función y desapareció, como decía su propia
cabecera. Ese fue el punto: **los programas cambiaron una línea**, y todo lo
demás ya estaba en símbolos.

### Rojo número 1: «60 009 violaciones JEDEC» que no eran JEDEC

El síntoma era el peor posible: un contador de violaciones de temporización
que **escalaba con el tiempo de simulación**, o sea tráfico malo continuo. Y
escribí aquí, con el árbol rojo, que *no* era la dirección del framebuffer
«porque el programa escribía la misma en 5a, que pasaba». Era exactamente la
dirección del framebuffer. La frase estaba mal porque comparaba contra una
fase que había parado antes de que el contador subiera.

Lo que pasaba: `sdram_model.v` llama a la misma tarea `fail()` para una
violación de tRCD y para «fila fuera del rango que modela este banco», así que
60 009 accesos a una fila inexistente se cuentan como 60 009 violaciones
JEDEC. El banco modela 4 bancos × **128** filas, la fila sale de los bits
[23:11] de la dirección de palabra, y 0x01000000 pide la fila 4096.

> Cuando un contador de errores agrega varias causas bajo el mismo nombre, el
> nombre miente. Mirar los mensajes, no el total. `[TODAS]`

Y la causa de fondo era mía, con un agravante documental:

- Regeneré `fullframe.hex` desde `examples/fullframe.asm`, **que es el
  programa de la placa** y pone el framebuffer en 0x01000000.
- La cabecera del banco y el README decían que el `.hex` salía justamente de
  ahí. **Llevaban tiempo mintiendo**: el `.hex` versionado usaba bases bajas,
  0x00010000 y 0x00035800, que es lo único que cabe en el modelo. Nadie lo
  notó porque nadie lo regeneró.
- Y lo regeneré además **en el formato equivocado**: el banco lo leía con
  `$readmemh` en un array de medias palabras y `--hex` emite palabras de 32
  bits.

Arreglo, en tres piezas que valen para cualquier carpeta:

1. `fullframe_tb.asm` existe de verdad, al lado del banco, y es el programa
   del banco. Las dos bases son `.equ` al principio, y es **lo único** que lo
   diferencia de `examples/fullframe.asm`.
2. El banco lee **palabras de 32 bits** y las parte en dos celdas de SDRAM. Un
   formato, una orden, y la orden está escrita en la cabecera del banco.
3. `x.tests/test_fullframe_fixture.py` comprueba las tres cosas: que el `.hex`
   sale de ese fuente, que los dos programas sólo difieren en las `.equ`, y
   que las bases del banco caben en las filas que el modelo tiene —esta última
   leyendo `ROWS` del propio banco, no copiándolo—.

Control negativo: con el `.hex` regenerado desde el programa de la placa —la
mutación que de verdad ocurrió— el test falla y dice la orden exacta para
arreglarlo.

> Una fixture generada y versionada se queda vieja en silencio. Si no hay un
> test que la regenere y compare, la cabecera que dice de dónde sale es
> folclore. `[TODAS]`

### Rojo número 2: el simulador, que era lo mecánico que parecía

`tools/sim_devices.py` tenía la tabla de registros en v2 y los métodos en v1.
Migrados `read`, `write` y `tick`: `FRAME_COUNT` propio, `STATUS` sin los
frames arriba, `HALT_TARGET`, `VIDEO_TX`, el alineamiento de 16 bytes como
**error** y el modo 3 reservado como error.

Lo que **no** era mecánico:

- **`run_until: {swap: N}` ya no puede ir por `HALT_AT`.** El arnés armaba la
  alarma del dispositivo para parar tras N intercambios. En v2 la alarma
  cuenta frames, así que pararía en otro sitio —y con `HALT_TARGET` a cero, en
  ninguno—. Pero la respuesta correcta no era convertir los nueve casos a
  frames: `run_until` es una **condición de observación del banco de pruebas**
  («captura el frame tras el intercambio N»), no un registro que el programa
  vea. Se implementa ahora con un atributo del dispositivo,
  `stop_after_swaps`, que no es MMIO y no se puede leer desde un programa. Los
  nueve casos y sus ocho modelos de referencia no se tocan.

  > Antes de migrar un uso de un registro, pregunta si ese uso era del
  > contrato o del arnés. Los del arnés salen del contrato, no se traducen.
  > `[TODAS]`

- **Dos casos probaban el truncamiento silencioso.** `video-registers` y
  `shared-double-buffer` escribían FB_BACK con los dos bits bajos a uno para
  comprobar que el hardware los ignoraba. En v2 eso es un error de acceso, y
  un programa **no puede comprobar su propio fallo**. Al quitarlo de los dos,
  el alineamiento se quedaba sin probar en ningún sitio, así que hay caso
  nuevo, `shared-video-fb-desalineada`, que corre en las dos arquitecturas.

- **El caso nuevo pasaba por el motivo equivocado**, y sólo lo dijo el control
  negativo. El arnés sólo construye el dispositivo de vídeo si el caso declara
  `expect.video`, `expect.frame` o `run_until`; sin ninguno, el `STORE` no
  daba error por desalineado sino porque **no había dispositivo detrás**. Con
  `FB_ALIGN` relajado a 4 el caso seguía en verde.

  > Un caso que espera un error puede estar viéndolo venir de otro sitio.
  > Rompe la causa concreta y comprueba que el caso se entera; si no, no está
  > probando lo que crees. `[TODAS]`

- **Los dos simuladores de GPU validaban la dirección pero no el dato.** Las
  escrituras se difieren al final de la instrucción y sólo la dirección pasaba
  por `validate()`; el `RuntimeError` del registro salía del simulador en vez
  de convertirse en el fallo del kernel. Arreglado en `minigpu_sim.py` y en
  `cycle_sim.py`. `[GPU]`

### Dos hallazgos del ancho de bus, en bancos

`video_fullframe_tb.v` y `subword_ls_tb.v` declaraban la dirección MMIO de
**cinco bits** (`wire [4:0] mmio_address`). Es literalmente el fallo de la 18
—doce contra cinco— viviendo dentro de dos bancos. Y `escribir_mmio` tomaba
`input [4:0] offset`, así que `HALT_TARGET` en +0x20 se truncaba a +0x00, que
es CTRL.

`test_top_wiring.py` no los caza: **sólo mira `top.v`**. Extenderlo a los
bancos es trabajo pendiente y probablemente barato. `[TODAS]`

### `HALT_AT` cuenta frames, y eso se nota más de lo que parece

Dos consecuencias que no se ven leyendo el contrato:

- **`HALT_TARGET` tras reset es cero, o sea no para a nadie.** Cualquier banco
  o arnés que armara `HALT_AT` y esperara una parada ahora se queda esperando.
  El síntoma es un timeout, que no se parece a la causa. Es el cambio de v2
  más fácil de pasar por alto al migrar una carpeta.
- **Frames y swaps no son intercambiables.** Mientras la CPU dibuja un frame
  entero pasan varios frames de scanout sin ningún intercambio, así que una
  alarma de N frames llega mucho antes que una de N swaps. En
  `video_fullframe_tb` hubo que subir el umbral de 2 a 6.

### Cuatro ficheros más que estaban en v1 y nadie miraba

Aparecieron al ir a por los dos rojos, y los cuatro son del mismo tipo: sitios
donde una dirección o un offset de v1 vivía fuera de los `.asm` y del RTL.

| Dónde | Qué llevaba | Cómo se vio |
| --- | --- | --- |
| `video_registers_tb.v` | los diez offsets en v1, entero | «FB_FRONT tras reset: 00000001» — leía CTRL, que arranca en PATTERN |
| `x.tests/test_sim_peripherals.py` | `STORE R0, R1, 8` como SWAP, y +0x1C como offset «reservado» | límite de instrucciones: nunca pedía el intercambio |
| `2.cpu-sim-func/test_serial_device.py` | ventana de 256 bytes en 0x80000200, y ejecutaba el ejemplo de la 19 | fallo de acceso |
| `11.gpu-sim-func/test_minigpu_sim.py` | MMIO en 0x80000000 y FB_BACK en +4 | el 0x80000000 «sin dispositivo» ahora es SYSTEM, y la lectura tenía éxito |

El del banco es el que más cuesta: migrarlo a mano son diez offsets repartidos
por 350 líneas. Ahora están como `localparam` al principio, que es lo que
habría que hacer **antes** de tocar nada en la siguiente carpeta.

> Los offsets sueltos en un banco son la misma deuda que las direcciones
> cableadas en un `.asm`, y no hay generador que los cubra. Nombrarlos primero
> convierte la migración en una edición de cinco líneas. `[TODAS]`

### `run_until: {swap: N}`: resuelto sin tocar los nueve casos

Ver arriba. Era una parada del arnés disfrazada de registro.

### La deuda que decidí no pagar aquí

§4.1 y §16.2 dicen que MMIO no admite escrituras sub-palabra. Lo implementé,
y lo revertí: `monitor.py`, `capture-frames` y varios bancos escriben MMIO
byte a byte, y todos tienen que pasar a `WRITE_WORD` **a la vez**. Es un
cambio del protocolo del host, no del mapa, y mezclarlo con la migración de
direcciones hace indistinguibles dos clases de fallo.

Queda anotado en `mmio_decoder.v` con el hazard concreto: escribir `HALT_AT`
en cuatro trozos la rearma cuatro veces. `write_mask` ya entra al módulo para
que el día que se aplique sea una condición y no un cambio de interfaz.

Y ahora está **fijada en un test**, que es la diferencia entre una deuda y un
descuido: `video_registers_tb.v` escribe FB_BACK en cuatro bytes y comprueba
que queda `0x44332211`, o sea desalineado y sin protestar. Cuando alguien
pague la deuda, ese test falla y le dice exactamente qué contrato cambia.

### Verificación al cerrar la fase

| Qué | Resultado |
| --- | --- |
| `apio test` de la 21 | 19 bancos, todos PASS |
| `run_tests --backend cpusim` | 53 casos, 0 fallos |
| `run_tests --backend gpusim` | 40 casos, 0 fallos |
| `run_tests --backend gpusim-cycle` | 40 casos, 0 fallos (15 min) |
| `unittest` de `x.tests` | 269 tests OK |
| `unittest` de `1.isa`, `2.cpu-sim-func`, `11.gpu-sim-func` | 61 / 44 / 62 OK |
| `tools/lint --prototype 21` | 36 diagnósticos (base: 38) |
| `check-links` + `generate-docs --check` | 610 enlaces OK, docs al día |
| `apio test` de la 19 | SUCCESS — la carpeta sin migrar sigue verde |

Sobre lint: la base eran **38 PINMISSING y cero avisos de anchura**. A mitad
de fase había 36 PINMISSING **y dos WIDTHTRUNC**, o sea el mismo total con dos
avisos nuevos de la clase exacta que costó una placa en la 18. Eran míos, en
`cpu_perf_counters.v`: las ranuras de contador son de seis bits porque §12.6
admite 64, pero `PERF_OVF0` sólo tiene 32, así que indexarlo con seis bits es
truncar y además aliasar la ranura 32 sobre la 0.

> Mirar el total de lint no basta: hay que mirar el reparto por tipo. Dos
> avisos nuevos escondidos tras dos que desaparecen dan el mismo número.
> `[TODAS]`

---

## Qué cuesta la siguiente carpeta

Contado en piezas, no en horas, porque lo que se tarda depende de cuántas de
estas ya estén hechas.

**Gratis, hecho una vez y para todas:** `.equ`, el generador y su `--check`,
el test de anchuras de `top.v`, los periféricos funcionales y los tres
backends de simulador. Esto era la mitad del trabajo de la 21 y no se repite.

**Una línea por fichero:** los `.asm`. Cambiar `mmio_v1.inc` por `mmio.inc`.
Las direcciones ya son símbolos.

**Media hora, mecánico y con red:** el camino de dirección. Quitar el prefijo
de 4 KiB, ensanchar a 32 bits, y correr `test_top_wiring.py` **antes** de
tocar nada. Es la parte que en la 18 costó una placa y aquí no costó nada.

**Media tarde, y es donde se va el tiempo:** los bancos de pruebas. No hay
generador que los cubra, los offsets viven sueltos por todo el fichero y las
direcciones aparecen además en formas que ninguna búsqueda encuentra:
constantes literales, instrucciones ensambladas a mano (`32'h5E80_8000`), y
direcciones partidas en bytes de protocolo (`send_byte(8'h80); send_byte(...)`).
Consejo concreto: **nombrar los offsets como `localparam` al principio del
banco antes de migrar ninguno**, y sólo entonces cambiarlos.

**Variable, y hay que mirarlo carpeta por carpeta:** lo que la 21 no tiene.

| Carpeta | Lo que aquí no se tocó |
| --- | --- |
| 10, 16 | adaptador de SDRAM de 16 bits: una palabra son dos ráfagas |
| 6 | sin SDRAM y sin ventana de periféricos: casi todo esto no aplica |
| 12, 14, 17, 22 | dos páginas, LSU vectorial, warps; el bloque GPU de v2 entero |
| 18 | `HALT_AT` con el mismo bug de `==` que se arregló aquí |

**El coste que no se ve:** cada carpeta tiene sus propias fixtures generadas
(`.hex`, `.bin`) y su propia cabecera diciendo de dónde salen. La de aquí
mentía. Antes de regenerar ninguna, comprobar de qué fuente sale de verdad, y
dejar un test que lo fije.

---

## Fase 6 — pendiente: síntesis y barrido

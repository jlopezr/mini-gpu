# Migración de la 19 a MMIO v2

Log de trabajo, escrito **durante** la migración. El orden de las secciones es
el orden real en que pasaron las cosas, no el orden del plan.

Contrato de referencia: [`../../1.isa/mmio.md`](../../1.isa/mmio.md).

**Este fichero no se lee solo.** La bitácora de la 21 —
[`../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md`](../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md)
— es la migración completa, con las piezas compartidas y las lecciones
generales. Aquí sólo se escribe **la diferencia**: lo que en la 19 no salió
como allí, y por qué.

**Alcance de cada decisión.** Cada apartado lleva una marca:

- `[TODAS]` vale para las diez carpetas.
- `[CPU]` vale para la familia CPU (6, 10, 16, 18, 19, 21).
- `[19]` es específico de esta carpeta.

---

## Fase 0 — Verificación del punto de partida

El encargo se declara a sí mismo una hipótesis y pide verificarlo dato a dato
antes de actuar. Se hizo. **La parte estructural se sostiene entera**; lo que
no cuadra son dos estimaciones de coste y un exit code.

### El punto de partida está verde

| Comando | Resultado |
|---|---|
| `tools/test --prototype 19` | **SUCCESS**, 44 s |
| `run_tests.py --backend cpusim` | **53 casos, 0 fallos**, 34 omitidos por arquitectura, 17,3 s |
| `tools/lint --prototype 19` | **36 `%Warning-PINMISSING`, 0 de anchura** |
| `check-links.py` | 614 enlaces en 175 `.md`, ninguno roto |
| `generate-docs --check` | al día |
| `generate_mmio.py --check` | al día |
| `unittest discover -s x.tests` | **269 tests OK** |

Nada estaba rojo antes de tocar nada. Éstos son los números base.

### Lo que se confirmó

| Afirmación del encargo | Estado |
|---|---|
| 12 `.asm` en `examples/` | correcto |
| 10 tocan MMIO; `fpga_smoke_test.asm` y `perf_loop.asm` no | **correcto, exactamente esos dos** |
| 24 bancos `*_tb.v` (la 21 tiene 29) | correcto: 24 y 29, cinco de diferencia |
| 3 `.hex` versionados en la raíz | correcto: `frame_full.hex`, `fullframe.hex`, `perf_loop.hex` |
| 36 PINMISSING y cero avisos de anchura | **correcto, y el reparto es de un solo tipo** |
| La lista de ficheros idénticos a la 21 | correcto |
| La lista de ficheros que difieren | **correcto, clavada** |
| `cpu.v` y `cpu_tb.v` difieren por la ALU, no por MMIO | correcto |
| `19.fpga-cpu-hdmi-ls/examples` **no** está en la guarda de `.asm` cableados | correcto: `CARPETAS` tiene `cases`, `cases-shared`, `20.forth` y `21/examples` |

El diff byte a byte de los 53 `.v`/`.sv` de la carpeta contra la 21 da
**37 idénticos y 20 distintos**, y los 20 son exactamente los 18 de la lista
del encargo más `cpu.v` y `cpu_tb.v`. Ni un fichero sólo en la 19.

### Lo que no cuadró

**1. `lint --prototype 19` sale con 1, no con 2.** La 21 registró exit 2 desde
`apio lint`; el lanzador de aquí devuelve 1. Es irrelevante para el criterio
—el propio encargo dice que el objetivo es el reparto, no el exit code— pero se
anota para que nadie lo lea como una regresión. El número a no empeorar es
**36 PINMISSING / 0 de anchura**. `[TODAS]`

**2. «Los `.asm` primero, y es una línea por fichero» no es cierto aquí, y es
la diferencia grande con la 21.**

El encargo hereda esa frase de la sección «qué cuesta la siguiente carpeta» de
la 21, donde era exacta: allí los 19 programas ya estaban simbolizados contra
`mmio_v1.inc` en la fase 3, así que migrar fue cambiar la línea del `.include`.

Pero **`1.isa/mmio_map_v1.vh` ya no existe**. Era andamio y llevaba escrito
cuándo se borraba; se borró al cerrar la fase 5b de la 21. Y los diez `.asm` de
la 19 están en v1 crudo:

```asm
MOVHI R20, 0x8000          ; registros de video en 0x80000000
...
STORE R30, R20, 0          ; FB_FRONT
STORE R30, R20, 4          ; FB_BACK
```

O sea que para la 19 —y para las ocho carpetas que quedan— el paso de los
`.asm` **no es un `.include` sustituido, son las dos fases de la 21 a la vez**:
dar nombre a las direcciones y cambiarlas, en la misma edición. Se pierde el
punto intermedio que la 21 construyó a propósito, donde todo pasaba y se podía
comparar antes de mover un solo número.

Y no es sólo la base: los offsets también se mueven. `CTRL` pasa a +0x00 en v2,
así que `FB_FRONT`, `FB_BACK`, `SWAP` y `STATUS` cambian los cuatro. Un
programa migrado a medias no falla al ensamblar, escribe en el registro de al
lado.

> **La estimación «una línea por fichero» caducó cuando se borró el mapa de
> transición.** Vale para una carpeta migrada *durante* la travesía de la 21;
> no vale para ninguna de las que quedan. `[TODAS]`

**3. Los diez programas van a alargarse, los diez.** La regla de la fase 3 de
la 21 —se alargan los que cargaban la base con un `MOVHI` suelto— aquí aplica
al 100 %: los diez usan `MOVHI Rn, 0x8000` sin `ORI`. Al pasar a
`LI Rn, MMIO_*_BASE` cada uno gana una palabra, así que cualquier `pc` esperado
o tamaño de imagen fijado contra estos programas se mueve. `[19]`

### La fixture miente igual que en la 21, y aún no está arreglada

De los tres `.hex` de la raíz:

| Fichero | Papel | ¿Igual que el de la 21? |
|---|---|---|
| `perf_loop.hex` | **entrada** de `perf_probe_tb.v` | idéntico |
| `frame_full.hex` | **salida** que vuelca `video_fullframe_tb.v` | idéntico |
| `fullframe.hex` | **entrada** de `video_fullframe_tb.v` | **distinto** |

`fullframe.hex` es el caso exacto de la trampa 3. En la 19:

- **no existe `fullframe_tb.asm`.** La 21 lo creó al arreglar el rojo número 1;
  aquí el banco sigue leyendo un `.hex` sin fuente declarada al lado.
- `README.md:208` dice «El programa es `examples/fullframe.asm`». Es la misma
  frase falsa que tenía la 21: ese programa pone el framebuffer en
  `0x01000000`, y el modelo de SDRAM del banco no llega.
- La cabecera del banco, en cambio, **sí** documenta bien las bases bajas
  (`0x00010000` y `0x00035800`) y explica el porqué de las filas. O sea que la
  carpeta tiene la explicación correcta y el fichero equivocado: el README y el
  banco se contradicen entre ellos, y nadie lo notó porque nadie regeneró nada.

Así que la 19 necesita el equivalente de `test_fullframe_fixture.py`, y
regenerar `fullframe.hex` «como pone en el README» reproduciría las 60 009
falsas violaciones JEDEC punto por punto.

### Un hallazgo que la 21 dejó anotado como pendiente, y aquí ya está visible

`tools/test --prototype 19` imprime, y pasa igualmente:

```text
write_combine_tb.v:59: warning: Port 17 (mmio_address) of module
cpu_dmem_adapter expects 12 bit(s), given 4.
```

Es el fallo de la 18 —dirección MMIO declarada más estrecha que el puerto—
viviendo dentro de un banco de la 19, y con **cuatro** bits. La 21 encontró dos
casos iguales (`video_fullframe_tb`, `subword_ls_tb`) y dejó escrito que
`test_top_wiring.py` no los caza porque sólo mira `top.v`.

Lo que añade la 19: **aquí sí hay quien avise, y es `iverilog`**, que lo dice en
cada ejecución de la suite. El aviso está en el log desde hace tiempo y pasa
desapercibido entre los `sorry:` de `dvi_generator.sv`. Cuando el bus se
ensanche a 32 bits, este puerto pasará de «4 contra 12» a «4 contra 32» y
seguirá sin fallar nada. `[TODAS]`

### Una verificación de la fase 0 que no verificaba nada

`python tools/generate_mmio.py --check` salió con 0 y se anotó como «al día».
**No comprobó nada:** `generate_mmio.py` no tiene bloque `if __name__ ==
"__main__"`. El punto de entrada es `tools/generate-mmio`, y el `.py` es sólo
la biblioteca. Ejecutarlo directamente no llama a `main()`, no imprime nada y
sale con 0.

Se descubrió al generar el mapa v1: el comando decía «EXIT=0» y no había
escrito ningún fichero.

> Un script sin `__main__` ejecutado a mano **sale con 0 siempre**. Como `0` es
> lo que se espera de un `--check`, el falso verde es indistinguible del bueno.
> Usa los lanzadores de `tools/`, que es lo que `AGENTS.md` lleva diciendo
> desde el principio. `[TODAS]`

El `--check` real, por el lanzador, sí estaba al día.

### Estado

Verificación hecha, **nada modificado todavía**. Ni RTL, ni `.asm`, ni tests.
La semilla 4 de `apio.ini` sigue siendo válida porque no se ha tocado un bit.

---

## Fase 1 — resucitar el mapa de transición `[TODAS]`

Consecuencia directa del punto 2 de la fase 0. Se decidió recuperar el punto
intermedio de la 21 en vez de saltar directo a v2.

### Por qué, y qué se compra con ello

Migrar una carpeta son dos cambios distintos:

1. dar nombre a las direcciones (los `.asm` dejan de llevar `0x8000` a mano);
2. cambiar las direcciones (v1 → v2).

Juntos, un fallo posterior no dice cuál de los dos lo causó. Separados, hay un
punto donde **todo pasa y nada se ha movido**, y a partir de ahí lo que se
rompa es el mapa. La 21 lo construyó a propósito y le valió la pena; el
fichero se borró al terminar y aquí hizo falta otra vez.

### Qué cambió

| Fichero | Qué le pasa |
|---|---|
| `1.isa/mmio_map_v1.vh` | **nuevo** (rehecho). El mapa de hoy, con los nombres de v2 |
| `tools/generate_mmio.py` | segunda entrada en `MAPAS`; el soporte de varios mapas ya estaba |
| `x.tests/inc/mmio_v1.inc` | **generado** |
| `tools/mmio_map_v1.py` | **generado** |
| `x.tests/test_mmio_map.py` | clase `MapaV1Test`, 5 tests; y el destino nuevo en la guarda de salidas |

Los números salen del **RTL de la 19**, no del fichero borrado de la 21 ni de
un documento: `mmio_decoder.v` para las ranuras (`device = address[11:8]` sobre
`MMIO_PREFIX = 20'h80000`: VIDEO=0, SERIAL=2, PERF=3, SYSID=15) y los
`localparam REG_*` de cada dispositivo.

### El criterio de borrado estaba mal, y por eso hubo que rehacerlo

La cabecera del fichero de la 21 decía: «si un mapa de transición sigue aquí y
ningún `.asm` lo incluye, sobra». Al cerrar la 21 eso era literalmente cierto
—ningún `.asm` lo incluía— y se borró. Pero **ocho carpetas seguían en v1**.

> El andamio no sobra cuando lo suelta la primera carpeta, sino cuando lo
> suelta la **última**. La condición de borrado de una pieza de transición no
> es «nadie la usa hoy», es «nadie va a necesitarla». `[TODAS]`

Queda corregido en la cabecera del `.vh` y en el comentario de `MAPAS`.

### La decisión de alcance: SYSTEM no se simboliza

El mapa v1 define **23 constantes**, todas con nombre de v2. VIDEO, SERIAL y
los dos contadores de rendimiento traducen limpio. **SYSTEM no**, y sólo se
declara su base.

En v1 el bloque son cuatro palabras (`SYS_ID`, `CONTRACT`, `DEV_BITMAP`,
`ISA_PROFILE`); en v2 son siete con otro reparto, y `SYS_ID` junta en una
palabra lo que v2 separa en `MAGIC` y `SYSTEM_ID`. No son los mismos registros
con otro offset: son otros registros.

Darles nombres de v2 habría sido lo cómodo y habría hecho que cambiar el
`.include` *pareciera* suficiente cuando no lo es. Ningún `.asm` de la 19 lee
ese bloque —lo lee el host por el camino del monitor— así que no cuesta nada
dejarlo fuera.

> Un mapa de transición sólo debe dar nombre común a lo que de verdad es el
> mismo registro. Donde la correspondencia no existe, **dejar el hueco** es
> más seguro que inventar un alias. `[TODAS]`

### El invariante, que ahora está comprobado en vez de supuesto

Las 23 constantes de v1 son **subconjunto** de las 95 de v2. Eso es lo que hace
que migrar un `.asm` sea una línea: ningún símbolo puede quedar sin definir al
cambiar el `.include`. La 21 lo daba por hecho; aquí hay un test
(`test_los_nombres_de_v1_existen_todos_en_v2`).

Y la otra mitad: incluir los dos `.inc` a la vez es **error de constante
duplicada**, así que un programa a medio migrar no ensambla. El mensaje del
ensamblador nombra los dos ficheros y las dos líneas.

### Lo específico de la 19, y es lo que la hace peligrosa `[19]`

Los nueve programas de vídeo usan **FB_FRONT, FB_BACK, SWAP y CTRL**, y los
cuatro cambian de offset en v2, porque `CTRL` pasa de +0x18 al +0x00 y empuja
al resto. No es la base lo que se mueve —eso daría error de decodificación, que
es ruidoso—: son los cuatro registros. Hay un test que lo fija
(`test_video_se_mueve_entero_al_pasar_a_v2`).

El inventario (fichero, registro base, dispositivo), que es el dato que la 21
recomienda sacar primero:

| Programa | Base | Dispositivo | Offsets v1 |
|---|---|---|---|
| `bresenham_circles`, `bresenham_lines` | `R2` | VIDEO | 0, 4, 8, 0x18 |
| `fullframe`, `subword_demo`, `swap_demo`, `swap_demo_fast`, `swap_smoke` | `R20` | VIDEO | 0, 4, 8, 0x18 |
| `tear_demo`, `tear_demo_fast` | `R20` | VIDEO | 0, 4, 0x18 |
| `serial_upper` | `R20` | SERIAL | 0, 4 |
| `fpga_smoke_test`, `perf_loop` | — | — | no tocan MMIO |

Dos bases distintas (`R2` y `R20`) y ningún programa que toque PERF ni SYSID.
Es más homogéneo que la 21, donde había que mirar fichero a fichero.

### El control negativo, y el falso OK que produjo

| Mutación | Qué falla | ¿El correcto? |
|---|---|---|
| M1 un valor de v1 deja de ser el del RTL, **y se regenera** | `los_valores_son_los_del_rtl`, `ensambla_de_verdad` | sí, y es el que importa |
| M2 constante en v1 que no existe en v2 | `los_nombres_de_v1_existen_todos_en_v2` | sí |
| M3 el `.inc` generado, editado a mano | `lo_generado_esta_al_dia` | sí |
| M4 `CTRL` y `FB_FRONT` intercambiados | `video_se_mueve_entero` + los dos de valor | sí |

M1 es el que demuestra que la conformidad no es una tautología: la sincronía
está contenta —lo generado corresponde a la fuente— y el test grita igual
porque la fuente ya no dice lo que dice el RTL.

**M4 salió «OK» la primera vez, y era falso.** La versión inicial movía sólo
`CTRL` a +0x00, que es donde lo tiene v2. Pero los offsets de v1 son densos
(0, 4, 8, 0xC, 0x10, 0x14, 0x18), así que eso lo pone **encima de `FB_FRONT`**
y el generador lo rechaza por colisión con exit 2. Lo generado se quedó como
estaba, los tests leyeron `mmio_map_v1.py` sin mutar, y no falló ninguno — que
es exactamente la firma de un control negativo superado.

El script ya verificaba que la mutación se aplicara **al fichero fuente**, que
es la guarda que la 21 dejó escrita. No bastaba:

> Cuando la mutación pasa por un generador, verificar que el **fuente** cambió
> no basta: hay que verificar que la **regeneración tuvo éxito**. Un generador
> que rechaza la mutación deja los ficheros generados intactos, y los tests
> leen datos rancios y pasan. `[TODAS]`

Hay dos cosas buenas escondidas ahí. Una, que la comprobación de colisiones del
generador —la que la 21 añadió tras colgar los warps de la base equivocada—
funcionó sin que nadie la provocara, por segunda vez. Y dos, que
`video_se_mueve_entero` resultó **inalcanzable con una mutación de un solo
valor**: hace falta intercambiar dos offsets. Que haga falta una mutación doble
no es un defecto del test, significa que el fallo simple ya lo caza una capa
antes; pero había que averiguarlo, porque si no el control sale verde por el
motivo equivocado.

### Y una guarda que saltó sola, por segunda vez

`test_los_destinos_se_generan` —«has añadido una salida y no has tocado el
test»— falló en cuanto se añadió la entrada a `MAPAS`. La 21 ya registró que
saltó sin que nadie lo provocara al **crear** el mapa v1; ha vuelto a hacerlo
al **resucitarlo**. Es el único test de ese fichero que ha saltado por su
cuenta, las dos veces.

### Lo que se rompió

Nada más. Y no se ha movido ninguna dirección: el RTL, los `.asm` y los
simuladores siguen intactos.

| Qué | Antes | Ahora |
|---|---|---|
| `unittest` de `x.tests` | 269 OK | **274 OK** |
| `unittest` de `1.isa` | 61 OK | 61 OK |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | 53 casos, 0 fallos |
| `check-links` | 614 | 618 (los de este log) |
| `generate-docs --check` | al día | al día |
| `generate-mmio --check` | al día | al día, los **cuatro** destinos |

La semilla 4 sigue válida: no se ha tocado RTL.

### Coste

Unas 120 líneas de `.vh` (casi todo comentario), 12 de generador y 100 de test,
más el control negativo. **No se repite en las ocho carpetas que quedan**: el
mapa v1 es del repo, y lo que tuvo de específico de la 19 fue comprobar que sus
números son los del RTL de aquí.

Más barato de lo estimado: el generador ya soportaba una tabla de mapas desde
la 21, así que añadir una fuente fueron doce líneas. Más caro de lo estimado:
el control negativo, por M4.

---

## Fase 2 — los diez programas a símbolos, sin mover nada `[19]`

Punto intermedio alcanzado: los diez `.asm` van por símbolo contra el mapa de
hoy y apuntan exactamente donde apuntaban.

### La guarda primero, y saltó como debía

Antes de tocar un `.asm` se añadió `19.fpga-cpu-hdmi-ls/examples` a `CARPETAS`
en `test_mmio_map.py`. Falló al instante nombrando **los diez ficheros**, ni
uno más ni uno menos, lo que confirma de paso el inventario de la fase 0.

Hacerlo en este orden es gratis y convierte la guarda en una lista de trabajo:
cuando deja de fallar, la fase está hecha.

### Por qué nadie se había enterado

`19/examples` no estaba en la lista, sí. Pero la causa de fondo es más
incómoda:

> **Ningún `test.json` de `x.tests` apunta a los `examples` de la 19.** Los
> casos de vídeo y de serie usan los de la **21**. Los de la 19 sólo los
> consumen la placa y las personas.

O sea que estos diez programas no tenían **ningún** consumidor automático. No
es que la guarda se olvidara de mirarlos: es que nada los miraba. Por eso
podían quedarse en v1 indefinidamente sin poner nada rojo.

> Al migrar la siguiente carpeta, mira si sus `examples` los ejecuta algún
> caso. Si no, la única red que vas a tener es la guarda de direcciones
> cableadas, y todo lo demás hay que verificarlo a mano. `[TODAS]`

### Qué cambió

Los diez llevan `.include "mmio_v1.inc"`, la base por `LI Rn, MMIO_*_BASE` y
los offsets por nombre. Dos bases distintas, `R2` y `R20`, y la tabla de la
fase 1 hizo el resto mecánico.

La sustitución fue con un script guiado por el registro base de cada fichero
(en el scratchpad, sin versionar: es de usar y tirar). Sólo toca los
`LOAD`/`STORE` cuyo registro base es **exactamente** el de ese fichero, que es
el aviso de la 21: un `sed` sobre `, 4` habría destrozado los `STORE` que
escriben en el framebuffer.

### La validación: el binario no puede cambiar

Simbolizar no debe mover ni una palabra. Así que cada programa se ensambló
antes y después, y se comparó contra un «esperado» construido del original
sustituyendo sólo la carga de la base por su `LI` equivalente **con el número
cableado**. Eso aísla la simbolización del crecimiento de `LI`.

**Los diez, idénticos palabra a palabra.**

| Programa | Palabras | Crecimiento |
|---|---:|---:|
| `bresenham_lines` | 104 | +1 |
| `bresenham_circles` | 92 | +1 |
| `swap_demo_fast` | 75 | +1 |
| `tear_demo_fast` | 62 | +1 |
| `fullframe` | 56 | +1 |
| `subword_demo`, `swap_demo` | 42 | +1 |
| `tear_demo` | 37 | +1 |
| `swap_smoke` | 19 | +1 |
| `serial_upper` | 15 | **+0** |

La regla de la 21 se confirma clavada: crecen los nueve que cargaban la base
con un `MOVHI` suelto, y `serial_upper` no, porque ya hacía `MOVHI` + `ORI` y
`LI` emite esas mismas dos palabras.

### El control negativo, y por qué comparar tamaños no basta

| Mutación | Resultado |
|---|---|
| `SWAP` simbolizado como `FB_BACK` | **DIFIERE en 2 palabras** |
| base de VIDEO cambiada por la de SERIAL | **DIFIERE en 1 palabra** |

Lo que hay que mirar de esta tabla no es que salte, es la otra columna: en los
dos casos el programa sigue midiendo **42 palabras**. Una comprobación de
tamaño, o de `pc` final, habría pasado las dos.

> Simbolizar mal no cambia el tamaño del programa, cambia el contenido de una
> instrucción. Validar una simbolización comparando longitudes o el `pc` final
> no comprueba nada; hay que comparar **palabra a palabra**. `[TODAS]`

Es la misma clase de fallo silencioso de siempre, y aquí es especialmente
peligroso porque —como dice el apartado anterior— estos programas no los
ejecuta ningún caso.

### Lo que se rompió

Nada, y esta vez era la predicción. Ningún caso de `x.tests` fija un `pc`
contra estos programas porque ninguno los usa, así que el `+1` de `LI` no
rompió nada. En la 21 sí hubo que tocar un `pc` esperado.

| Qué | Resultado |
|---|---|
| `unittest` de `x.tests` | **274 OK** (la guarda ya no salta) |
| `run_tests --backend cpusim` | 53 casos, 0 fallos |
| `tools/test --prototype 19` | **SUCCESS**, 44 s |

### Estado

**Sigue sin moverse ninguna dirección.** Los diez programas van por símbolo
contra el mapa de hoy. RTL sin tocar, semilla 4 válida.

Éste es el punto intermedio que la fase 1 existía para construir: a partir de
aquí, lo que se rompa es el mapa.

### Coste

Media hora, casi toda en escribir las dos herramientas de usar y tirar (el
sustituidor y el verificador). La edición en sí fue un comando. Sale **más
barato que en la 21**, y por una razón que no se repite: la 19 es más
homogénea —dos registros base, cuatro offsets, un solo dispositivo por
programa— mientras que allí había que mirar fichero a fichero.

---

## Fase 3 — la red de seguridad, extendida a los bancos `[TODAS]`

El encargo pide correr `test_top_wiring.py` **antes** de tocar la anchura. Se
hizo, y estaba verde. Pero verde no significaba lo que parecía.

### El test sólo miraba `top.v`, y el fallo vive igual en un banco

La 21 lo dejó anotado como trabajo pendiente y «probablemente barato». Lo era:
`desajustes_de_ancho` ya era genérica salvo que tenía `top.v` escrito dentro.
Separarla en `desajustes_de_fichero(fichero, carpeta)` fueron cinco líneas.

Hacía falta antes de ensanchar, no después, porque la 19 tenía esto:

```verilog
wire [3:0] mmio_mask, mmio_addr;   // write_combine_tb.v:46
```

La máscara **sí** es de cuatro bits; la dirección heredó la anchura por
compartir declaración, y va a un puerto de doce. Es el fallo de la 18 con otro
número, y `iverilog` lo viene avisando en cada ejecución de la suite sin que
nadie lo lea:

```text
write_combine_tb.v:59: warning: Port 17 (mmio_address) of module
cpu_dmem_adapter expects 12 bit(s), given 4.
```

> Un banco con la dirección truncada no da error: da un banco que **pasa
> probando otra cosa**. `video_registers` selecciona con `address[7:2]`, así
> que con cinco bits todo lo que esté por encima de +0x1C aliasa sobre los
> registros de abajo. `[TODAS]`

### Lo que apareció al encenderlo: 25 desajustes, y no todos son míos

**4681 comparaciones en los bancos de las diez carpetas, 25 desajustes**,
repartidos en tres carpetas. Siete de cada diez carpetas están limpias.

| Carpeta | Desajustes | De qué |
|---|---:|---|
| 19 | 13 | 10 de dirección MMIO (los míos) + 3 de `perf_probe_tb` |
| 21 | 7 | **4 de dirección MMIO** + 3 de `perf_probe_tb` |
| 18 | 5 | 2 de dirección MMIO + 3 de `perf_probe_tb` |

Dos cosas que no esperaba:

**1. La 21, ya migrada, conserva cuatro direcciones MMIO sin ensanchar.** En
`subword_ls_tb` (dos), `video_fullframe_tb` y `write_combine_tb`: señales de 4
y 5 bits contra puertos de **32**. Su bitácora cuenta que encontró y arregló
dos casos de esta clase, y que extender el test a los bancos quedaba
pendiente; al extenderlo se ve que quedaron cuatro. En v2 duelen más que en
v1, porque con los bloques separados por megabytes una dirección de cinco bits
no puede ni expresar una base.

**2. `perf_probe_tb.v` tiene un desajuste ajeno a MMIO**, y en las tres
carpetas: `wire [7:0] halted, finished, error;` conectado a puertos de un bit.
Ese banco es **copia idéntica** en 18, 19 y 21, así que arreglarlo es un cambio
compartido y no se mezcla con una migración de direcciones —es la trampa de
`monitor.v` con otro fichero—. Queda anotado, no tocado.

### Cómo se acota: lista explícita, no criterio relajado

`AnchosEnBancosTest` está **activo para las diez carpetas**, con un conjunto
`DEUDA_EN_BANCOS` que lista los desajustes ajenos uno a uno, con nombre,
línea y motivo.

> Una lista explícita es una deuda; un criterio relajado es un agujero.
> `[TODAS]`

Y para que la lista no se pudra hay un segundo test,
`test_la_deuda_no_crece_ni_se_queda_rancia`: si alguien arregla uno de esos
desajustes y no borra su línea, **salta y obliga a borrarla**. Sin eso, una
lista de excepciones se convierte con el tiempo en el agujero que venía a
evitar.

La regla para quien migre una de esas carpetas está escrita en el propio
comentario: **si tu carpeta aparece en la lista, vacíala antes de darla por
migrada**.

### Estado al abrir la fase

El test queda **rojo a propósito**, y sólo por los diez desajustes de la 19,
que son exactamente la lista de trabajo del ensanchado. Cuando se ponga verde,
el camino de dirección está hecho.

### Un fallo del propio test, y van cuatro en esta migración

`test_toda_entrada_del_monitor_sale_de_algun_sitio` empezó a decir «9 de 10».
La causa: tras cerrar la lista de parámetros del `monitor #(...)`, el parser
buscaba el nombre de instancia con `\s*\w+\s*\(`. Y en v2 hay un **comentario**
en medio, porque las ventanas se anotan una a una:

```verilog
.WINDOW3_BASE(33'h0_8101_0000),.WINDOW3_END(33'h0_8102_0000))  // CPU PERF
  monitor_i (
```

Con eso `puertos_del_monitor` devolvía `{}` y **la carpeta se saltaba entera**,
sin decir nada. La 21 llevaba saltándose desde su propia migración.

> Es el cuarto caso en estas dos bitácoras del mismo patrón: la herramienta
> que vigila un fallo silencioso lo comete. Y el detalle que lo hace repetirse:
> el modo de fallo por defecto de un analizador es **no ver**, que es
> indistinguible de **no hay nada**. Por eso todas las guardas de este fichero
> llevan un mínimo de cosas comparadas. `[TODAS]`

Arreglado para que salte comentarios de línea y de bloque. Las diez vuelven a
mirarse, y el contraste de que no sobre-captura: la 19 y la 21 dan 35 puertos
frente a 29 de las demás, y los seis de más son exactamente los del puerto
serie, que ellas conectan y la 18 no.

---

## Fase 4 — el RTL, que salió casi gratis `[19]`

### El atajo, y por qué es el camino correcto y no una trampa

Los siete ficheros MMIO de la 19 difieren de los de la 21 **sólo por la
migración**. Se comprobó fichero a fichero antes de tocar nada; el diff de
`cpu_dmem_adapter.v`, por ejemplo, son 32 líneas y todas son `MMIO_PREFIX`,
la anchura y los comentarios.

Así que se copiaron de la 21:

| Fichero | Líneas 19 → 21 |
|---|---|
| `mmio_mux.v` | 120 → 126 |
| `mmio_decoder.v` | 112 → 206 |
| `sysid.v` | 76 → 101 |
| `video_registers.v` | 298 → 409 |
| `cpu_perf_counters.v` | 93 → 185 |
| `monitor_mem_adapter_128.v` | 208 → 207 |
| `cpu_dmem_adapter.v` | 373 → 383 |

Copiar no es hacer trampa aquí, es **lo que el repo quiere**: estos ficheros
están pensados para ser idénticos entre carpetas, y hay un test que lo exige
agrupando por versión del contrato. Tras la copia, los siete son byte a byte
los de la 21, que es exactamente el estado en el que el test los quiere.

Lo único que se migró a mano fue **`top.v`**, porque lleva valores propios de
la carpeta: `FOLDER(8'd19)`, `MONITOR_VERSION(32'h0000_0413)` y las cuatro
ventanas del monitor.

> Antes de migrar el RTL de una carpeta, **haz el diff contra una ya migrada**.
> Si las diferencias son sólo la migración, es una copia y no media tarde. `[TODAS]`

### El fallo que encontró la copia, y es de placa

Al adaptar `top.v` apareció esto, en la 21 **ya migrada y dada por buena**:

```verilog
mmio_decoder #(.FOLDER(8'd21), .HAS_SERIAL(1), .VIDEO_REGISTERS(64'h7f), ...
```

`0x7f` son los **siete** registros de v1. En v2 hay diez, y el valor por
defecto que la migración puso en `mmio_decoder.v` es `0x3ff` — pero `top.v` lo
pisaba. O sea que en el bitstream de la 21, **`HALT_AT`, `HALT_TARGET` y
`VIDEO_TX` contestaban error de acceso** aunque `video_registers.v` los
implementa.

Por qué no lo vio nadie, y son tres razones que se suman:

1. `cpu_mmio_error_tb` instancia el decodificador **con su propio** `0x3ff`, o
   sea prueba el decodificador y no el diseño.
2. Ningún banco instancia `top`, que es la razón por la que existe
   `test_top_wiring.py`.
3. **`0x7f` es un bitmap perfectamente válido.** No hay nada de qué quejarse:
   no es un error de sintaxis, ni un ancho raro, ni un valor imposible. Es el
   valor correcto del contrato anterior.

> El resto de un mapa viejo no se delata solo cuando **sigue siendo legal**.
> Un `MMIO_PREFIX` desaparece al migrar porque el código no compila sin él; un
> parámetro que sólo cambia de número sobrevive callado. Busca los parámetros
> que `top.v` pisa, uno a uno. `[TODAS]`

Arreglado en las dos carpetas, y con test:
`test_el_top_no_estrecha_el_bitmap_de_video`.

La primera versión de ese test comparaba contra el valor por defecto de
`mmio_decoder.v` y **acusó a la 16 injustamente**, que pasa `0x4f`. La 16 tiene
razón: implementa cinco registros, en los índices 0, 1, 2, 3 y 6. La gemela de
verdad no es el contrato sino **lo que implementa el `video_registers.v` de esa
carpeta**, así que el test deriva el bitmap de sus `localparam REG_*`. Con eso
las cuatro carpetas con vídeo salen consistentes y la 16 sigue pudiendo
implementar menos.

Control negativo: reintroducido el `0x7f` en la 21, el test nombra los índices
`[7, 8, 9]` que faltan.

---

## Fase 5 — los bancos y los programas

### Los bancos: seis copiados, uno a mano, tres que no eran lo que parecían

De los diez, siete se copiaron de la 21 (dos con un parche de una línea para la
versión de monitor) porque el diff era sólo migración. `cpu_mmio_error_tb` es
el que la 21 tuvo que **reescribir entero** —estaba construido sobre la página
de 4 KiB— y esa reescritura vale igual aquí.

**`monitor_tb.v` no se podía copiar, y por el motivo contrario al esperado.**
El de la 19 tiene **567** líneas y el de la 21, **483**. La 19 tiene pruebas de
atomicidad de `WRITE_WORD` —cuenta los pulsos para distinguir «el dato acabó
bien» de «el dato llegó en UNA transacción»— que el de la 21 no tiene.
Copiarlo habría **borrado cobertura real**. Se migró a mano: las cuatro
ventanas y un comentario, doce líneas.

> Un fichero más corto en la carpeta ya migrada no significa que la migración
> lo simplificara. Compara en las dos direcciones antes de copiar. `[TODAS]`

Y queda anotado que **la 21 no tiene esa cobertura**: o la perdió, o la 19 la
ganó después. No se ha tocado.

### Los programas: la línea que todo el andamio existía para permitir

Con el RTL en v2, los diez `.asm` pasaron de `mmio_v1.inc` a `mmio.inc`. **Una
línea por fichero**, que es exactamente lo que la fase 1 compró.

Y salió un contraste que no estaba planeado: al comparar los programas
migrados con los de la 21 —migrados meses antes, por otro camino, contra el
mismo contrato— **la única diferencia es una línea en blanco**. Dos
migraciones independientes convergieron al mismo texto.

### La fixture, que mentía igual que en la 21

Se aplicaron las tres piezas de la 21:

1. **`fullframe_tb.asm` existe**, al lado del banco. Es `examples/fullframe.asm`
   con las dos bases del framebuffer como `.equ`, bajas para que quepan en las
   128 filas del modelo de SDRAM.
2. **`fullframe.hex` regenerado desde ahí**, en palabras de 32 bits, con la
   orden escrita en la cabecera del banco.
3. **El README corregido.** Decía que el programa era `examples/fullframe.asm`
   y era falso, la misma frase que tenía la 21.

Confirmación fuerte: el `fullframe.hex` regenerado sale **byte a byte igual al
de la 21**.

`x.tests/test_fullframe_fixture.py` pasa de mirar una carpeta cableada a
**descubrir sola** las que tienen el trío completo. No es cosmético:

> Con la carpeta escrita a mano arriba, cubrir la 19 dependía de que alguien se
> acordara de añadirla — que es exactamente cómo la cabecera del banco de la 21
> llegó a mentir durante meses. Un test que se descubre solo cubre la 18 el día
> que cree su `fullframe_tb.asm`, sin que nadie lo recuerde. `[TODAS]`

Control negativo: regenerado el `.hex` desde el programa de la placa —la
mutación que de verdad ocurrió en la 21— el test falla, nombra la carpeta y da
la orden exacta.

### Lo que se rompió

Menos de lo esperado, y nada por sorpresa. Los fallos que hubo fueron todos
«un sitio que no miré», y el test de anchuras los fue nombrando uno a uno hasta
ponerse verde.

Lo único que no vio ningún test automático fue el **lado host**: los dos fallos
finales de `x.tests` fueron `MONITOR_REGIONS` de `monitor.py`, que seguía con
la ventana única. Eso sí lo cazaron sus dos gemelas.

---

## Verificación al cerrar

| Qué | Base | Ahora |
|---|---|---|
| `tools/test --prototype 19` | SUCCESS, 44 s | **SUCCESS, 125 s**, 24 bancos |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | 53 casos, 0 fallos |
| `tools/lint --prototype 19` | 36 PINMISSING, 0 anchura | **34 PINMISSING, 0 anchura** |
| `unittest` de `x.tests` | 269 OK | **278 OK** |
| `unittest` de `1.isa` / `2.cpu-sim-func` / `11.gpu-sim-func` | 61 / 44 / 62 | 61 / 44 / 62 OK |
| `check-links` | 614 | 625, ninguno roto |
| `generate-docs --check` / `generate-mmio --check` | al día | al día |
| `tools/test --prototype 21` | — | SUCCESS, 121 s |

Lint **mejora** por tipo: 34 frente a 36, y sigue sin un solo aviso de anchura.
A mitad de fase llegó a 60, todos PINMISSING de bancos que aún no conectaban
los puertos nuevos de los módulos copiados; era ruido de transición y bajó solo.

**No se ha sintetizado.** La semilla 4 de `apio.ini` está invalidada y el
barrido, pendiente. La 21 también: sus tres bancos arreglados no la afectan
—no se sintetizan— pero el `VIDEO_REGISTERS` de su `top.v` sí.

---

## Lo que esta migración le hizo a la 21

No estaba en el encargo, pero salió al mirar, y conviene que esté escrito en un
sitio. Migrar una segunda carpeta **audita la primera**, porque obliga a releer
cada decisión con un caso distinto delante.

| Qué | Cómo apareció |
|---|---|
| `VIDEO_REGISTERS(64'h7f)` en su `top.v`: tres registros de vídeo daban error en placa | al adaptar el `top.v` de la 19 |
| Cuatro direcciones MMIO sin ensanchar en tres de sus bancos (4 y 5 bits contra puertos de 32) | al extender `test_top_wiring` a los bancos |
| `puertos_del_monitor` se la saltaba entera desde su propia migración | al ver «9 de 10» |
| Su README sigue documentando `FB_FRONT` en `0x80000000` | al corregir el de la 19 |
| Su `monitor_tb.v` no tiene la cobertura de atomicidad de `WRITE_WORD` que sí tiene la 19 | al comparar antes de copiar |

Los tres primeros están arreglados. Los dos últimos, anotados y sin tocar: el
README es suyo y la cobertura de `monitor_tb` es una decisión que no me
corresponde deshacer.

> La primera carpeta migrada no está terminada cuando se declara conforme, sino
> cuando la segunda ha pasado por encima. Reserva tiempo para eso al planificar
> la siguiente, porque no sale a cero. `[TODAS]`

---

## Qué cuesta la siguiente carpeta, corregido

La estimación de la 21 sigue siendo buena en su estructura. Lo que cambia:

**Lo que era «una línea por fichero» y no lo era.** La 21 escribió que migrar
los `.asm` es cambiar el `.include`. Cierto **sólo si el mapa de transición
existe**. Se había borrado, y reconstruirlo fue la fase 1 entera. Ya está
hecho y no se repite: `1.isa/mmio_map_v1.vh` vuelve a estar, con el criterio de
borrado corregido.

**Lo que salió más barato de lo estimado:**

- **El RTL, con diferencia.** La 21 lo estimó en «media hora mecánica» para el
  camino de dirección más el resto por dispositivo. Aquí fueron **siete copias
  y un `top.v`**, porque los ficheros eran los mismos menos la migración.
- **Los bancos.** La 21 dijo «media tarde, y es donde se va el tiempo». Aquí
  siete de diez se copiaron.
- **Los `.asm`.** Más homogéneos que en la 21: dos registros base, cuatro
  offsets, un dispositivo por programa.

**Lo que salió más caro:**

- **Los controles negativos**, por M4 de la fase 1: una mutación que el
  generador rechaza produce un falso OK.
- **Auditar la 21**, que no estaba presupuestado (ver arriba).
- **El lado host y los documentos.** Ningún test los cubre del todo, y el
  README tenía una tabla de registros entera en v1 más una receta de placa que
  ya no funcionaba.

### Para la 18, medido

Es **casi una gemela de la 19**: 39 ficheros idénticos byte a byte, 14
distintos, ninguno exclusivo. Y de los ocho ficheros MMIO:

| Fichero | Estado en la 18 |
|---|---|
| `mmio_decoder.v`, `mmio_mux.v`, `sysid.v` | **idénticos a los de la 19** |
| `video_registers.v`, `cpu_perf_counters.v`, `monitor_mem_adapter_128.v` | **idénticos** |
| `cpu_dmem_adapter.v`, `top.v` | difieren |

**Seis de los ocho se copian ya migrados.** Su `mmio_decoder.v` tiene el mismo
reparto (VIDEO=0, SERIAL=2, PERF=3, SYSID=15 sobre `MMIO_PREFIX = 20'h80000`),
así que `mmio_map_v1.vh` le vale sin tocar nada.

Le quedan: 8 `examples` (6 con MMIO), `cpu_dmem_adapter.v`, `top.v`, once
bancos, su `monitor.py`, sus documentos, y dos deudas ya localizadas —los dos
desajustes de anchura de `video_fullframe_tb` anotados en `DEUDA_EN_BANCOS`, y
el bug de `HALT_AT` con `==` que la 21 le atribuye—.

### Para la 17, y es otra forma

No es «una carpeta más pequeña», es **otro mapa**:

```verilog
wire mmio     = address[31:13] == 19'h40000;   // DOS paginas de 4 KiB
wire gpu_page = address[12];                   // no una
```

Con la regla de conformidad —el periférico que tengas, en v2; `sysid`
obligatorio siempre— la 17 tiene exactamente esto:

| Hoy (v1) | En v2 |
|---|---|
| `sysid`, 4 palabras en `0x80000F00` | SYSTEM, 7 palabras. **Fichero compartido: se copia ya migrado** |
| `0x100` contexto, `0x104` slots de LSU, `0x10C` primer error, `0x110` PC del error, `0x114` warps retirados | `MMIO_GPU_SIMT_*`, que define **exactamente esos cinco** |
| `0x108` `retired_count` | `MMIO_GPU_PERF_BASE` + `MMIO_PERF_RETIRED_OFF` |
| 8 descriptores de warp de 16 B en `0x80001000` | `MMIO_GPU_WARPS_BASE`, stride 16: **encaje directo** |

No tiene vídeo, ni serie, ni contadores de CPU, ni el bloque GPU CORE, así que
no tiene que inventárselos.

Lo que sí cuesta:

1. **No hereda nada del trabajo de la 19**: su decodificación es *inline* en
   `gpu_system.v`, no un `mmio_decoder.v`. Hay que reescribirla como bloques de
   64 KiB. Es diseño, no renombrado — aunque `gpu_system.v` es único de cada
   carpeta, así que no bifurca nada compartido.
2. **`retired_count` está intercalado** entre los registros SIMT (en `0x108`,
   entre `slots` y `primer error`). En v2 se va a otro bloque, así que los
   offsets de SIMT posteriores **se desplazan**. Es la clase de movimiento que
   no da error y contesta otro registro.
3. **`mmio_map_v1.vh` no le sirve**: no tiene un solo nombre de GPU. Hay que
   extenderlo, que es aditivo.
4. Sólo **un** `.asm` real (`fixtures/10.asm`). Los otros dos que aparecen
   están bajo `_build/`: al añadir la 17 a la guarda de direcciones cableadas,
   **hay que excluir `_build`**.

Y una trampa que ya se vio: los `0x80000000` de `gpu_control_tb.v`
(`32'hf8000000`, `32'hc8000000`) son **codificaciones de instrucción**, no
direcciones. Es el error de `INT_MIN` de la 21 con otro disfraz, y una búsqueda
por valor los traería todos.

### Orden recomendado

**19 → 18 → 17.** La 18 porque la 19 la deja casi hecha; la 17 después, porque
es la primera de la familia GPU y lo que se aprenda ahí sirve para 12, 14 y 22.

---

## Fase 6 — pendiente: síntesis, barrido y placa

Nada de esto se ha pagado todavía, y hace falta permiso explícito:

- **Barrido de semillas** de la 19 (`build-sweep --prototype 19 --seeds 1..8`).
  La 4 está invalidada.
- **Barrido de la 21**, por el cambio de `VIDEO_REGISTERS`.
- **Placa**, que es lo único que puede confirmar dos cosas que ninguna
  simulación ve: que `HALT_TARGET` y `VIDEO_TX` responden de verdad —o sea que
  el bug del bitmap estaba arreglado— y que las cuatro ventanas del monitor
  dejan pasar lo que deben.

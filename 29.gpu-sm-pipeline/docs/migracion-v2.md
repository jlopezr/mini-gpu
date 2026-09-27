# Migración de la 22 a MMIO v2

La última carpeta del repo, y con ella se cierra la travesía. El diseño está en
[la bitácora de la 17](../../17.fpga-gpu-ram-v2/docs/migracion-v2.md); lo que
el atajo de copiar da y no da, en [la de la 14](../../14.fpga-gpu-ram/docs/migracion-v2.md)
y [la de la 12](../../12.fpga-gpu/docs/migracion-v2.md). Aquí va lo que sólo
pasa en ésta, que es casi todo lo caro de la familia.

## El encargo subestimó esta carpeta, y por tres sitios a la vez

El encargo la pone la última «porque es la grande». Lo es, pero el coste no
estaba donde decía.

**1. No son cuatro sitios de decodificación. Son seis.** El encargo cuenta los
cuatro `gpu_system.v`. En esta carpeta hay además:

- `gpu_system_bl8.v`, 409 líneas frente a las 187 del otro, **y es el que se
  sintetiza**: lo monta `top_bl8`, o sea el entorno `default`. El
  `gpu_system.v` de la 22 sólo lo usa el entorno `base-bl1` y cinco bancos.
- `gpu_lsu2.v`, que decide por su cuenta si una dirección es MMIO para mandarla
  por el camino escalar en vez de por el de memoria:

  ```verilog
  mmio_lanes[i]=sel_pending[i] && (sel_addr[i*32+12 +: 20]==20'h80000);
  ```

  **Ese sexto sitio no lo encuentra ninguna de las búsquedas que el encargo
  propone.** La dirección no es un literal: es un rango de bits comparado
  contra un prefijo. Es una **séptima forma** de escribir una dirección,
  además de las seis que el encargo lista. Apareció porque `gpu_lsu2_tb.v`
  falló con nueve casos de golpe, no porque nadie la buscara.

**2. VIDEO no cambia de base: se reordena entero.** Es el bloque que más se
mueve (§9), y el encargo no lo menciona porque su tabla sólo miraba capacidades.
En v1 `CTRL` era la palabra 6, la última, porque se añadió después; en v2 es la
0 y empuja a todas. Los cuatro registros que usan los kernels —FB_FRONT,
FB_BACK, SWAP y CTRL— **cambian los cuatro**.

Y aparece `FRAME_COUNT` como registro propio (§9.5). En v1 el contador de
frames viajaba empotrado en los bits 31:16 de `STATUS`. Un programa que leyera
STATUS y se quedara con la mitad alta ahora lee ceros: no falla, devuelve otra
cosa.

**3. `VIDEO_TX` cambia de bloque, y el mapa lo dice con todas las letras.**
§9.7: «pertenece a VIDEO, no al bloque de contadores de la GPU, por la regla de
§12.1 […]. En su día vivió en los contadores de la GPU, y eso era un accidente
de que solo la GPU tenía contadores».

O sea que el bloque PERF de esta carpeta no conformaba con §14.4: tenía
`VIDEO_TX` en la ranura 5, donde el contrato pone `STALL_MEM`. Mudarlo bajó
`STALL_MEM` de la 6 a la 5 y `LANE_OPS` de la 7 a la 6, y obligó a llevarse con
él su regla de `gating` —el scanout sigue leyendo SDRAM con la GPU parada, así
que el contador sólo avanza con `running`—. Si esa regla se hubiera quedado
atrás, el número habría vuelto a medir el reloj de pared.

`LANE_OPS` no lo nombra el mapa; se queda en la primera ranura libre detrás de
las seis de §14.4, que §12.6 permite.

> Cuando un contador cambia de bloque, lo que hay que mudar no es el registro:
> es el registro **y la razón por la que se contaba así**. La razón vivía en un
> comentario del fichero de origen. `[TODAS]`

## Lo que la guarda de `.asm` cobró, y era todo aquí

Once ficheros, los once en `examples/`, tal y como salió al añadir las ocho
rutas. Migrados a `.include "mmio.inc"` + `LI Rn, MMIO_VIDEO_BASE` y offsets
por símbolo, que es el idioma de la 19.

`mmio_selftest.asm` fue el caro, y por una razón estructural: en v1 leía
`VIDEO_CTRL` y los contadores **con el mismo registro base**, porque los dos
estaban dentro de la misma página de 4 KiB (`LOAD R3, R20, 768`). En v2 son dos
bloques separados por megabytes, así que hace falta **un segundo registro
base**. No es un cambio de constante, es un registro más.

Y los `.hex` versionados hubo que reensamblarlos. Dos detalles que costaron
tiempo:

- `gpu_mmio_tb.v` carga `examples/mmio_selftest.hex`, no el `.asm`. Migrar el
  fuente y no regenerar el binario da `error_code=02` en un `pc` que no dice
  nada. **Ningún camino automático regenera esos `.hex`.**
- El ensamblador emite el hexadecimal en **mayúsculas** y los versionados están
  en minúsculas, así que una regeneración limpia ensucia el diff de todos los
  ficheros aunque el contenido sea idéntico. Se comprobó que `bench.hex` y
  `plasma_nommio.hex` sólo cambiaban de caja y se revirtieron.

## Lo que hice mal y cazó el repo

Le di a `top.v` —el entorno `base-bl1`, que monta `gpu_system` y no tiene vídeo
ni contadores— unas ventanas **precisas**: sólo los bloques que ese sistema
implementa. Parecía obviamente mejor que copiar las de `top_bl8.v`.

Saltó `test_monitor_port.test_todas_las_instancias_de_un_prototipo_coinciden`,
cuyo docstring contesta exactamente eso:

> «La 22 tiene dos tops y un banco de pruebas; los tres han de decir lo mismo,
> o se depura un mapa que no es el que está sintetizado.»

Las ventanas son del **prototipo**, no del entorno: el CLI es un solo programa
hablando con el bitstream que haya puesto, y dos listas distintas en la misma
carpeta significan depurar contra un mapa que no es el que corre. La
consecuencia aceptada —igual que en v1— es que en `base-bl1` el monitor deja
pasar VIDEO y los contadores, y el NACK lo da el decodificador en vez del
monitor.

> Una invariante del repo que parece un descuido puede ser una decisión. Antes
> de «arreglarla», lee el test que la vigila: el docstring suele tener la razón
> que a ti no se te ocurrió. `[TODAS]`

**Y la lista de ventanas tiene CUATRO copias en esta carpeta**, no dos:
`top.v`, `top_bl8.v`, `MONITOR_REGIONS` de `monitor.py` y los parámetros de
`gpu_monitor_regions_tb.v` — que es, precisamente, el banco que existe para
vigilar que las copias no diverjan.

## El guion que se reemplazó a sí mismo

Migrar los 26 bancos con una tabla de sustituciones ordenada produjo dos líneas
mal en `gpu_monitor_regions_tb.v`. La causa: `0x8000_0f00` → `0x8000_0000` por
la regla de SYSID, y acto seguido la regla de VIDEO vio ese `0x8000_0000`
recién escrito y lo convirtió en `0x8020_0004`. **Una regla posterior se comió
la salida de una anterior.**

No falló ningún test: las dos líneas quedaron apuntando a direcciones válidas,
sólo que a las equivocadas —una lectura etiquetada «bloque de identificación
entero» leyendo el framebuffer—. Se vio leyendo el fichero, no ejecutándolo.

> Una tabla de reemplazos sobre un texto es una función que se aplica en
> cascada, no en paralelo. Si algún valor de salida puede casar con un patrón
> de entrada posterior, hay que hacer dos pasadas con marcadores intermedios, o
> revisar el resultado a mano. `[TODAS]`

## Controles negativos que caducaron con el mapa

Tres, y los tres habrían pasado sin probar nada:

| Dónde | Decía | Por qué caducó |
|---|---|---|
| `gpu_lsu2_tb.v` | `0xF000_0000` está fuera de rango | En v2 tiene el bit 31: cae en el espacio de dispositivos y la LSU la manda a MMIO. Ahora es `0x7000_0000` |
| `gpu_monitor_regions_tb.v` | rechaza «el hueco donde estaba el vídeo antes» | Ese hueco es un accidente de la disposición vieja. Ahora apunta a GPU CORE, que es un bloque del mapa sin nada detrás |
| `test_monitor.py` de la 12 | `0x80000000` no es ninguna ventana | En v2 **sí** lo es: es SYSTEM |

El del `0xF000_0000` es el más instructivo: no caducó porque se arreglara el
caso, sino porque **el mapa se hizo más grande**. Lo que era «tan lejos que no
existe» pasó a ser «un sitio con dueño».

## Temporización: cuatro de cuatro

| Reloj | v1 | v2 | Δ |
|---|---:|---:|---:|
| `sdram_clk` | 38,39 | **40,43** | +5,3 % |
| `clk_pix` | 74,17 | **71,10** | −4,1 % |
| `clk_pix_5x` | 227,79 | **227,58** | −0,1 % |

Los tres pasan. Y el camino crítico:

```text
22 v1:  gpu.lsu.grp_line[9] -> gpu.lsu.n_lanes[3]
22 v2:  gpu.lsu.grp_line[4] -> gpu.lsu.n_lanes[4]
```

**El mismo sitio**, en la LSU vectorial. Con esto la familia entera queda así:

| | v1 | v2 | Δ | Crítico v1 → v2 |
|---|---:|---:|---:|---|
| 12 | 33,93 | 35,06 | +3,3 % | `gpu.sm` → `gpu.sm` |
| 14 | 31,15 | 34,25 | +10,0 % | LSU → LSU |
| 17 | 46,73 | 44,83 | −4,1 % | LSU → LSU |
| 22 | 38,39 | 40,43 | +5,3 % | LSU → LSU |

Cuatro carpetas, ocho informes de camino crítico, y **MMIO no aparece en
ninguno**. Tres deltas positivos y uno negativo. El lazo estructural de la 16
no existe en esta familia, por la razón que explica la bitácora de la 17: la
máquina de estados de `gpu_system` nunca mira la respuesta del dispositivo para
decidir a dónde va. La regla del encargo —«con mux o sin mux»— predecía mal.

## Verificación

- `./tools/test --prototype 22`: **26 bancos RTL** y 8 tests Python, todos OK.
- `x.tests`: 285 tests, **todos en verde**. La guarda de `.asm` ya pasa con las
  ocho rutas y los 152 programas versionados.
- `sysid.v` de la 22 ya es byte a byte el de las otras nueve: **los diez son
  idénticos y el grupo de v1 está vacío**.
- Semilla: no se fija. Esta carpeta no tenía párrafo y ahora lo tiene, con el
  mismo criterio que las otras tres.
- `gpusim` 40 casos, `gpusim-cycle` 40, `cpusim` 53 — **0 fallos** en los tres.
- `1.isa` 61, `2.cpu-sim-func` 44, `11.gpu-sim-func` 62, todos OK.
- `check-links` 706 enlaces en 193 `.md`; `generate-mmio --check` al día;
  `generate-docs` regenerado; `synthesis-report.md` sin un solo FAIL.
- Lint por tipo: 31 `PINMISSING`, **el mismo número que antes de tocar nada**.

## La placa, que encontró dos cosas que la simulación no

Los 26 bancos y los 280 tests estaban en verde **antes** de la primera ronda de
placa, y la placa dio **18 fallos de 33**. Los dos motivos:

**1. `x.tests/backends/gpu_fpga.py` seguía entero en v1.** El encargo decía que
«el backend de placa es único y compartido, `x.tests/backends/fpga.py`, y está
en v2». Cierto — pero `gpu_fpga.py` **es otro fichero** y no lo estaba: llevaba
los cinco registros de vídeo en la página de v1 y cuatro direcciones de
depuración cableadas (`0x80000108`, `0x10c`, `0x110`, `0x114`).

Nadie lo había notado porque, como avisa el propio encargo, **ningún camino
automático ejecuta el backend de placa**. Migrado, y las tres bases —warps,
SIMT y PERF— se leen ahora del `monitor.py` del prototipo, como ya se hacía con
la de warps.

> «El backend de placa está en v2» era cierto del fichero que nombraba y falso
> del que hacía falta. Cuando una nota diga que un fichero compartido ya está
> hecho, comprueba que es **ese** el que tu familia usa. `[TODAS]`

**2. El contador de retiros cambió de dominio de reset sin que nadie lo
pidiera, y fue culpa mía.** En v1 el global lo servía el bloque de depuración
desde el wire del SM, que cuelga de `core_reset`; al moverlo a GPU
PERFORMANCE pasó a servirlo `gpu_perf_counters`, que colgaba de `reset` y por
tanto **acumula entre casos**. El síntoma: `instructions_executed` daba
20.864.707 donde el caso esperaba 22.

No es que el contador estuviera mal, es que **era otro contador**. Arreglado
colgando `perf` de `core_reset`: mientras `PERF_CTRL` no exista, el reset es el
único modo de ponerlos a cero, así que tienen que compartir dominio con el
núcleo que miden.

> Mover un registro de bloque puede moverlo también de dominio de reloj o de
> reset, y eso no lo dice el mapa. Al reubicar un contador, comprueba **quién
> lo pone a cero** además de dónde se lee. `[TODAS]`

**Y el tercero, que sí era una deuda declarada:**
`shared-video-fb-desalineada` falló como estaba previsto —§9.2 exige error en
base desalineada y la GPU truncaba—. Con la placa delante salía barato, así que
se cerró: `gpu_video_regs.v` rechaza la palabra entera y no guarda nada.

**Resultado final en silicio: 33 casos, 0 fallos.** Y de paso, la 12 (30/0) y la
14 (31/0).

## Y con esto se borra el andamio

`1.isa/mmio_map_v1.vh` cumplía por fin su criterio de borrado —«sobra cuando lo
suelta la ÚLTIMA carpeta»— y se ha ido, con `x.tests/inc/mmio_v1.inc`,
`tools/mmio_map_v1.py`, su entrada en `MAPAS` y la clase `MapaV1Test`.

Antes de borrarlo se comprobó que **ningún `.asm` del repo incluye
`mmio_v1.inc`**. Quedaban dos referencias y las dos eran comentarios rancios en
ficheros que ya incluían `mmio.inc`: `20.forth/forth.asm`, que decía «SERIAL
(MMIO v2, ver mmio_v1.inc)» —contradiciéndose a sí mismo en la misma línea— y
`x.tests/cases/extensions/serial/uppercase/program.asm`. Corregidos.

La suite de `x.tests` pasa de 285 a **280** tests: los cinco que faltan son los
de `MapaV1Test`, borrados a propósito con el andamio que vigilaban.

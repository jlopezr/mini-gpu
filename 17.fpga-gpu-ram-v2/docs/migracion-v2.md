# Migración de la 17 a MMIO v2

Primera carpeta de la familia GPU. Lo que no se repite aquí está en las seis
bitácoras anteriores, sobre todo en
[la de la 21](../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md) (el camino
completo) y [la de la 16](../../16.fpga-cpu-hdmi/docs/migracion-v2.md) (la
temporización). Esto es sólo la diferencia.

## El encargo estaba mayormente bien, y donde fallaba fallaba por omisión

[El encargo](../../docs/encargo-migracion-v2-gpu.md) se midió en `8c2b261` y se
ejecutó en `5423e65`, dos commits después. El único cambio entre medio que toca
estas carpetas es un `.md` nuevo, así que sus medidas de RTL seguían vivas.

Su **corrección grande es correcta**: `gpu_system.v` es de hecho un fichero
compartido. 14↔17 difieren en una línea (`FOLDER`), 17↔22 en esa más un puerto,
y 12↔14 en 16/17 líneas que son todas la interfaz de memoria, ninguna de MMIO.
Los seis ficheros byte a byte idénticos son exactamente esos seis. Comprobarlo
costó un `git hash-object` por fichero, como decía.

Lo que no cuadró:

| Afirmación | Realidad |
|---|---|
| «la 22 es la misma forma más un puerto» | La 22 tiene **dos** sistemas: `gpu_system.v` (187 líneas) y `gpu_system_bl8.v` (**409**, +257), y el que sintetiza `top_bl8` —el entorno `default`— es el segundo. Son **cinco** sitios de decodificación, no cuatro, y el quinto es el caro |
| `MONITOR_REGIONS`: 12 «ninguna», 14/17 una, 22 dos | 12 tiene **tres**, 14/17 **tres**, 22 **cinco**. Se le cayeron `WARP_CONFIG_BASE` y `SYSID_BASE` en todas y `VIDEO_BASE` en la 22 |
| «añade las cuatro `examples/`» | Los `.asm` están sobre todo en `fixtures/`: **128 de 152**. Añadir sólo `examples/` deja el 84 % sin vigilar |
| «64 `.asm` en `_build` bajo esas cuatro carpetas» | Los 64 están **todos en la 17**, bajo `_build/bench/{before,after}/fixtures`. Y no son trampa si añades `examples/` y `fixtures/` como rutas: sólo lo son si añades la raíz |
| «sus `apio.ini` sólo llevan `--detailed-timing-report`» | La 12 y la 14 **no lo llevan**. Hubo que añadírselo antes de poder mirarles el camino crítico |
| «no hay línea base de barrido» | La 12, la 14 y la 17 tienen un barrido de ocho semillas registrado en su `apio.ini`, con un párrafo explicando que **no fijar semilla es deliberado**. Sólo la 22 no tiene nada |

Esa última contradice la «Definición de terminado», que pide semilla fijada en
las cuatro «porque ninguna la tiene hoy». Ninguna la fija, sí, pero tres lo
argumentan. Se decidió **no fijar en ninguna** y extender el criterio a la 22.

> Antes de cumplir una definición de terminado al pie de la letra, mira si lo
> que pide ya está decidido al revés **con su razón escrita**. «Ninguna lo
> tiene» y «todas decidieron no tenerlo» se ven igual en un `grep`. `[TODAS]`

## El lazo estructural de la 16 NO aparece aquí, y el motivo no es el mux

Es el hallazgo que más cambia la estimación de las tres que quedan.

El encargo predice el lazo de la 16 —`mmio_address[28]` → decodificador →
dispositivo → **lógica de próximo estado del propio adaptador**— porque estas
cuatro carpetas decodifican inline, sin `mmio_mux` que lo parta. La forma es la
misma, así que la conclusión parece seguir.

**No sigue, y se ve en el RTL antes de sintetizar.** El lazo de la 16 existe
porque su adaptador *decide a dónde ir* mirando la respuesta del dispositivo.
La máquina de estados de `gpu_system.v` no hace eso:

```verilog
1: begin
    if(mmio) begin
        host_read_data<=...; host_error<=mmio_bad; host_ready<=1; host_state<=0;
    end else if(aux_ready) host_state<=2;
end
```

La transición depende de `mmio` y de `aux_ready`. **No depende de `mmio_data`
ni de `mmio_bad`**: esos dos sólo entran en registros de datos. O sea que el
camino dirección → decodificador → dispositivo termina en la entrada de un
registro, que es un camino registro-a-registro normal, no un lazo.

> La regla que el encargo escribe es «con mux o sin mux». La regla que de
> verdad predice el lazo es **¿la máquina de estados mira la respuesta del
> dispositivo?**. La 16 la mira; la 18, la 19 y la 21 no la miran porque el mux
> se interpone; esta familia no la mira porque nunca se diseñó así. El mux es
> *una* forma de no mirarla, no la única. `[TODAS]`

Y el camino crítico **medido** de v1, extraído del `build.log` (la temporización
buena, que es la última):

```text
17: gpu.lsu_mask[6]          -> ... -> occupied  (46,73 MHz)
14: gpu.lsu.pending[3][2] -> gpu.lsu.pick[2]     (31,15 MHz)
22: gpu.lsu.grp_line[9] -> gpu.lsu.n_lanes[3]    (38,39 MHz)
```

En las tres está **dentro de la LSU**, en el arbitraje de lanes.

Y el de v2, ya sintetizado (`reports/20260920-165936-823837-mmio-v2`):

```text
17 v2:  gpu.lsu.req_mask[7] -> gpu.lsu_mask[7]   (44,83 MHz)
```

**El mismo sitio.** MMIO no aparece ni antes ni después de migrar.

| | Fmax | Margen sobre 25 MHz |
|---|---:|---:|
| 17 v1 | 46,73 | +86,9 % |
| **17 v2** | **44,83** | **+79,3 %** |

Y el área, que es lo que el encargo insinuaba como sospecha razonable:

| | LUT | FF |
|---|---:|---:|
| 17 v1 | 31 311 | 10 310 |
| 17 v2 | 31 392 | 10 310 |

**+81 LUT (+0,26 %) y ni un biestable.** v2 no cuesta área aquí: cambia un
comparador de prefijo de 19 bits por uno de 16 y reparte el `case` en cuatro
más pequeños.

Son 1,90 MHz menos, un −4,1 %, y **no es el coste estructural de la 16**: el
camino no ha cambiado de sitio y 19,23 de sus 22,3 ns son rutado. Es ruido de
emplazamiento de una carpeta que ni siquiera fija semilla. La 16 perdía el
diseño entero (cero de dieciséis semillas); aquí no se mueve nada.

### La trampa de la doble temporización, con número

El `build.log` trae la temporización dos veces y la buena es la última. En la
14 la diferencia decide el veredicto, no el margen:

```text
estimacion pre-rutado:  22,92 MHz  (FAIL at 25.00 MHz)
la buena:               31,15 MHz  (PASS at 25.00 MHz)
```

Leer la primera te dice que la carpeta **no cierra ni en v1**. En la 16 la
diferencia era de 18 MHz pero las dos pasaban; aquí cambia PASS por FAIL.

## Lo que la guarda de `.asm` encontró, y dónde no

Añadidas las **ocho** rutas (`examples/` y `fixtures/` de las cuatro), la
guarda nombra **once** ficheros, y los once están en `22/examples`. Los 128
`fixtures` y los `examples` de la 12, la 14 y la 17 no cablean ni una
dirección.

O sea que el coste de los `.asm` en esta familia es **cero para tres carpetas y
todo para la cuarta**, y la cuarta ya era la última del orden. Los once usan
sólo VIDEO y PERF, que `mmio_map_v1.vh` ya nombraba antes de esta migración.

## El mapa de transición: qué hizo falta de verdad

`mmio_map_v1.vh` no tenía ningún nombre de GPU, confirmado. Se le añadieron
`MMIO_GPU_SIMT_BASE`, `MMIO_GPU_PERF_BASE`, `MMIO_GPU_WARPS_BASE` y los nueve
`_OFF`, sacados del RTL de hoy y no de un documento.

Dos decisiones que conviene no repetir mal:

- **GPU WARPS no se mueve por dentro.** `gpu_sm.v` reparte `cfg_word[4:2]` como
  índice y `cfg_word[1:0]` como palabra, o sea PC/ACTIVE/GROUP/SIMT en 16 B —
  exactamente §14.2, bits de `SIMT_STATE` incluidos. Sólo cambia la base.
- **GPU PERFORMANCE no se le dio nombre a la 12, la 14 ni la 17.** Su único
  contador global vive en v1 dentro de SIMT DEBUG, en +0x08. Para que
  `MMIO_GPU_PERF_BASE + MMIO_PERF_RETIRED_OFF` cuadrase habría que poner la
  base en `0x80000104`, que es inventarse un bloque donde no hay ninguno — el
  mismo error que la nota de SYSTEM del propio fichero describe.

El control negativo del detector de colisiones se hizo y falla por el motivo
correcto: mover `FIRST_ERROR_OFF` a `0x04` da
`dos registros en 0x80000104: MMIO_GPU_SIMT_LSU_SLOTS y MMIO_GPU_SIMT_FIRST_ERROR`.

## Lo que costó más de lo estimado: las cinco formas, y una sexta

El encargo lista cinco formas de escribir una dirección y avisa de una sexta en
esta familia (codificaciones de instrucción). Las dos que costaron tiempo:

**La sexta es real y abundante.** `gpu_control_tb.v` y `gpu_regions_tb.v` están
llenos de `32'hc4000003`, `32'hf8000000`, `32'hc8000000`. Un `grep 8000` sobre
los bancos de la 17 da 28 aciertos y **sólo 11 son direcciones**. Nombrar los
offsets como `localparam` antes de tocar nada, como dice la 21, es lo que hace
que el resto del banco sea legible: lo que queda suelto son instrucciones.

**La tercera —bytes de protocolo— es la que se escapa.** `gpu_uart_tb.v` no
aparecía en ninguna búsqueda de `32'h8000` porque sus direcciones van así:

```verilog
request[1]=8'h80; request[2]=0; request[3]=8'h10; request[4]=8'h30;
```

Eso es `0x80001030`, el descriptor del warp 3. Se descubrió porque el banco
falló, no porque nadie lo buscara. **Un noveno banco que la lista de trabajo no
contenía.**

> Cuando migres una familia, el inventario de direcciones que sale de un `grep`
> es un piso, no un techo. Lo que lo cierra es correr los bancos. `[TODAS]`

## Lo que falló pareciendo que funcionaba

**Un `.Replace()` de PowerShell que no reemplazó nada, y el `if` que lo tapó.**
El encargo avisa de esto (CRLF en disco, LF en el índice). Pasó igual, y con un
agravante propio: el guion hacía varias sustituciones y comprobaba
`if($t -eq $o)` al final. Como las otras sí se aplicaron, la comprobación dio
verde con la cabecera sin insertar.

> Un control de «¿se aplicó la mutación?» que mira el agregado no vale cuando
> hay varias mutaciones. Cuenta las coincidencias **de cada una** antes de
> escribir. `[TODAS]`

**`mmio_monitor_tb.v` parecía trabajo y no lo era.** Es uno de los seis
ficheros byte a byte idénticos en las cuatro, y lleva `32'h80000f00`. Migrarlo
habría bifurcado un fichero compartido. Instancia `monitor` contra una memoria
falsa, no `gpu_system`: esa dirección nunca llega al decodificador y es
arbitraria. Costó un `Select-String` comprobarlo.

**`OK: monitor 1.16` en la suite compartida.** Parecía el analizador roto de la
trampa 5 por cuarta vez —la 16 instancia monitor **3.16**, no 1.16—. No lo es:
sale de `check_identity`, que lee la versión por serie, y en la suite el valor
es un mock. Se persiguió y no había nada.

## Lo que se dejó fuera a propósito

**GPU CORE (§14.1) no se implementa.** Arranque, parada y estado de la GPU van
por el protocolo del monitor, no por MMIO. Implementar `WARP_START/LIVE/DONE`
es hardware nuevo, no migrar un mapa, y hay precedente: la cabecera de
`sysid.v` dice que **CPU CORE (§13.1) tampoco existe** en la familia CPU. El
bloque contesta error, que es lo que §4.3 pide de un bloque ausente.

**La ranura 0 de GPU PERFORMANCE (CYCLES) tampoco.** Este prototipo no tiene
contador de ciclos. Contesta error y no cero: un cero en CYCLES no se distingue
de un contador parado.

## Las gemelas que hubo que tocar a la vez

`MONITOR_REGIONS` de `monitor.py` tiene **dos** gemelas, no una:

1. los parámetros `WINDOWn_BASE/END` del `monitor` que instancia `top.v`;
2. `DEBUG_BASE` de `WarpMixin`, en `tools/monitor_protocol.py`, que es
   **compartido por las diez carpetas** y sigue en v1 porque tres de esta
   familia no están migradas. Sin declararlo en el `monitor.py` de la carpeta,
   `select_context` escribe en una dirección que este bitstream rechaza — y el
   síntoma no es un error, es «los registros del warp equivocado».

Las ventanas se abren al **contenido real** del bloque, no a sus 64 KiB: abrir
el bloque entero dejaría que el monitor pidiera direcciones que el
decodificador rechaza, y el NACK vendría del bus en vez del monitor.

## Verificación

- `./tools/test --prototype 17`: nueve bancos RTL y 8 tests Python, todos OK.
- `./tools/lint --prototype 17`: **17 `PINMISSING`**, el mismo reparto por tipo
  que la 12 y la 14 sin tocar. No ha empeorado. (La 22 parte de 31.)
- `x.tests`: 285 tests; sólo falla la guarda de `.asm`, que es la lista de
  trabajo de la 22 y está pendiente a propósito.
- `sysid.v` de la 17 ya es byte a byte el de las seis de CPU
  (`70696acd…`). Quedan tres en el grupo de v1.
- `generate-mmio --check`: al día, los cuatro ficheros.

## Qué salió más barato y qué más caro

**Más barato:** la decodificación en sí. Cambiar dos páginas de 4 KiB por
`address[31:16]` es más simple que lo que había, no más complejo, y el `case`
pasó de `address[11:2]` con un bloque de alias de identificación intercalado a
un `case` por bloque. Y el `sysid.v` de v2 ya existía: fue una copia, no un
diseño.

**Más caro:** el inventario. El grep dio 11 direcciones en 5 bancos; el trabajo
real fueron 13 en 6, y el sexto sólo apareció al ejecutar. Y las gemelas del
lado host eran dos, una de ellas en un fichero compartido por diez carpetas.

**Para la 14**, que es la siguiente: debería ser esta misma migración con
`FOLDER(8'd14)`, y el `gpu_uart_tb.v` y las ventanas de `top.v` también. Si no
sale casi gratis, eso es el hallazgo.

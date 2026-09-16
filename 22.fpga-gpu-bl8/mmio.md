# La ventana MMIO de la MiniGPU

## Por qué se abrió a la GPU

Hasta ahora el MMIO era territorio exclusivo del host, por **dos barreras
independientes**:

- `gpu_lsu2` marcaba fault toda dirección ≥ `0x02000000`, así que un `STORE` a
  `0x80000200` no llegaba a ningún sitio;
- y la escritura del MMIO exigía `halted`, o sea la GPU parada.

Eso dejaba a la GPU **ciega y muda respecto al vídeo**: no podía encender el
scanout, ni saber en qué frame va, ni pedir un intercambio de buffers. El doble
buffer, que es lo que hace falta para que la imagen deje de temblar, no se
puede implementar como en 21 —allí lo dispara la CPU escribiendo `SWAP`— porque
aquí nadie podía escribir nada.

Y de paso dejaba toda la instrumentación en simulación, que es lenta: los
cuatro frames de `plasma.asm` tardan unos ocho minutos (`gpu_plasma_tb`, 463 s
medidos), casi la mitad del tiempo de la suite entera del prototipo.

## Mapa

```text
0x80000000-0x8000007F  configuracion de warps    host
0x80000100-0x80000114  depuracion y contadores   host
0x80000200-0x8000023F  VIDEO_CTRL / FB_BASE      host y GPU, lectura y escritura
0x80000300-0x8000033F  contadores de rendimiento host y GPU, solo lectura
```

**La GPU no llega a la configuración de warps.** Que un warp reconfigure los
warps es justo el tipo de cosa que no se quiere poder hacer por accidente, y no
hay ningún caso de uso que lo pida. Escribir un contador tampoco: son de
lectura, y un intento de escritura es fault.

### Contadores (`gpu_perf_counters.v`)

```text
0x80000300  CYCLES       ciclos CON LA GPU CORRIENDO (da la vuelta)
0x80000304  RETIRED      instrucciones retiradas
0x80000308  IMEM_HITS    aciertos del bufer de instrucciones
0x8000030c  IMEM_MISSES  fallos del bufer de instrucciones
0x80000310  LSU_TX       transacciones emitidas por la LSU vectorial
0x80000314  VIDEO_TX     transacciones emitidas por el scanout
0x80000318  STALL_MEM    ciclos con la LSU sin poder aceptar peticion
```

Con `CYCLES`, `STALL_MEM` e `IMEM_MISSES` se separa cómputo de memoria de fetch
sin instrumentar nada más. Y lo importante: **un programa se mide a sí mismo en
la placa**, leyendo `CYCLES` antes y después, sin simular y sin cronómetro.

Todos avanzan **solo con la GPU corriendo**, y eso no es un detalle. Un contador
libre vale para que un programa se mida a sí mismo (las dos lecturas las hace la
GPU, y entre ellas solo pasa lo que ella hace), pero **no** para que lo mida el
host: ahí, entre las dos lecturas caben las órdenes por serie y el bucle que
sondea si ha parado. Con `CYCLES` libre, `profile.py` daba un CPI de 43 en vez
de 15,6 — medía el reloj de pared. Ver `profiling.md`.

`VIDEO_TX` se cuenta igual, porque el scanout sigue leyendo SDRAM con la GPU
parada y ese tráfico no es del programa.

## Cómo está hecho

### En la LSU: un camino escalar aparte

Un acceso a MMIO **no se coalesce**. Se sirve de una lane cada vez, la de menor
índice pendiente:

- `mmio_lanes[i]` marca las lanes cuya dirección cae en `0x80000xxx`;
- esas dejan de ser fault;
- si la lane líder es de MMIO, el grupo es **ella sola** (`leader_onehot`) y la
  transacción sale por un puerto de 32 bits en vez de por el fabric.

Un registro de 32 bits no es una línea de 16 bytes, y ocho lanes escribiendo
registros distintos a la vez no tiene semántica útil. Como los accesos a MMIO
son contados —unos pocos por frame—, que sean lentos da exactamente igual.

Un detalle que salió limpio: en `WAIT`, la respuesta de MMIO se replica en las
cuatro palabras de `rsp_line` (`{4{mmio_rsp_rdata}}`). Así `RETIRE` reparte el
dato sin enterarse de que era MMIO — elija el `sel` que elija, saca el valor
bueno.

### En el sistema: un mux, no un árbitro

El host solo accede con la GPU parada y la GPU solo cuando corre, así que **no
compiten de verdad**. Basta con multiplexar la dirección, y la GPU gana el mux
en su ciclo de aceptación. No hace falta arbitraje ni prioridad.

## Dos trampas de la ISA que costaron un intento

Escribiendo `examples/mmio_selftest.asm` me di de bruces con las dos:

1. **Un salto divergente necesita `SSY etiqueta` delante**, marcando dónde
   reconvergen los caminos. Sin él, el SM para con `ERROR_SIMT` (0x06). Mi
   `BNE R1, R0, ...` para que solo el hilo 0 tocara el MMIO fallaba justo ahí.
2. **El inmediato de `LOAD`/`STORE` es un desplazamiento en BYTES**, no en
   palabras: `mem32[Ra + imm]`. Yo puse 128 para llegar a `0x200` razonando en
   palabras. `JALR` sí escala por 4, que es de donde me vino la confusión.

## Qué desbloquea

Lo inmediato es el **doble buffer**: con la GPU capaz de escribir un registro
`SWAP`, el patrón de 21 ya se puede trasladar. Eso es lo que hace falta para
que la imagen deje de temblar, porque hoy el scanout lee a 60 Hz la misma
memoria que la GPU reescribe a 8 fps.

Y después, sincronizar con vsync: la GPU puede leer el contador de frames y
esperar, en vez de dibujar a ciegas.

## Dónde está el contrato

Este documento cuenta **por qué** la 22 abrió el MMIO y **cómo** está construido.
No es la referencia de direcciones: el mapa completo del repositorio, el contrato
de registros de cada dispositivo, las discrepancias entre prototipos y el reparto
al que se quiere converger están en
[`docs/mapa-de-memoria.md`](../docs/mapa-de-memoria.md).

Dos direcciones de las de arriba **van a moverse** al aplicar ese contrato: la
configuración de warps sale de `0x80000000` a la página GPU `0x80001000`, y el
vídeo vuelve de `0x80000200` a `0x80000000`, que es donde lo tienen los cores de
CPU. Depuración y contadores ya están en su sitio definitivo.

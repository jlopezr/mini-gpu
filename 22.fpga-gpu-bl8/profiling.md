# Perfil de un frame: dónde se va el tiempo

Medida de **un frame** de `examples/plasma.asm` con el scanout encendido, leída
de los contadores de `0x80000300` (ver `mmio.md`). En placa se saca con
`profile.py`; esta concreta salió de `gpu_profile_tb.v`.

```text
CYCLES      3 334 230
RETIRED       170 486
IMEM_HITS     170 469
IMEM_MISSES        17
LSU_TX          9 600
VIDEO_TX       83 960
STALL_MEM           0
SWAP_COUNT          1
```

## Lo que dicen

### 1. El fetch está resuelto

17 fallos en 170 486 búsquedas: **0,01%**. El bucle de 160 bytes cabe en las 16
líneas del bufer y a partir de la primera vuelta no vuelve a la SDRAM. El
problema que se llevó el 29% del tiempo con 4 líneas ya no existe.

### 2. La memoria NO es el cuello de botella

`STALL_MEM = 0`. Ni un solo ciclo en el que el SM quisiera entregar una
petición a la LSU y no pudiera. Los ocho slots vectoriales absorben todo lo que
el SM es capaz de pedir.

Esto es una afirmación fuerte y conviene entenderla bien: **no es que la
memoria vaya sobrada, es que el SM no pide lo bastante rápido como para
saturarla.**

### 3. El scanout mueve 8,7× más tráfico que los datos

| Cliente | Transacciones de 16 B | |
| --- | --- | --- |
| Scanout (vídeo) | 83 960 | 89,7% |
| Datos (LSU) | 9 600 | 10,3% |
| Fetch | 17 | 0,0% |
| **Total** | **93 577** | = 1 463 KiB |

11,2 MB/s de los 23,5 que da el canal.

Las 9 600 de la LSU cuadran exactamente con la teoría: 38 400 palabras de 32
bits ÷ 4 por transacción. La coalescencia funciona al 100%.

Y reformula el `+29%` que medimos antes: el vídeo no es un coste lateral, es
**el cliente dominante del canal**. Que aun así solo cueste un 29% es porque la
GPU tiene tanto margen de memoria que absorbe el golpe.

### 4. Qué cuenta exactamente `RETIRED`

**Instrucciones de WARP, no de hilo.** En `gpu_sm.v`, `RETIRE` hace
`retired_count<=retired_count+1'b1` una sola vez, sin mirar cuántas lanes
estaban activas. Así que los ciclos por instrucción de más abajo son por
instrucción de warp, y cada una hace trabajo para hasta 8 hilos.

Puesto en operaciones de hilo, que es la unidad de trabajo real:

| | |
| --- | --- |
| Instrucciones de warp | 166 046 |
| Lanes activas por instrucción | 8 |
| Operaciones de hilo | 1 328 368 |
| Ciclos | 2 917 419 |
| **Ciclos por operación de hilo** | **2,20** |

(En `plasma.asm` las 8 lanes están siempre activas. El `BLT` del final de fila
parece divergente pero no lo es: las 8 lanes de un warp llevan valores de `x2`
consecutivos empezando en un múltiplo de 8, y el umbral 160 también es múltiplo
de 8, así que o cruzan las ocho o ninguna. Por eso el programa no necesita
`SSY` ahí.)

Y de ahí sale el número que de verdad duele: la máquina entrega **0,455
operaciones de lane por ciclo** teniendo **ocho ALU de lane**. Las lanes están
paradas el **94% del tiempo**.

### 4b. Cuánta divergencia hay: `LANE_OPS`

`RETIRED` no puede decirlo, porque cuenta instrucciones de warp sin mirar la
máscara. Por eso se añadió `LANE_OPS` (`0x8000031c`), que acumula
`popcount(active)` en cada retiro. Medido en el mismo frame:

```text
LANE_OPS  1 229 247      RETIRED  166 046
```

| | |
| --- | --- |
| Lanes activas por instrucción | **7,40 de 8** (92,5%) |
| Utilización de las ALU | **5,27%** |
| La misma utilización si no divergiera nada | 5,69% |

Hay divergencia, pero poca, y viene de los tramos de un solo hilo: el bucle
que espera el intercambio de buffers, donde 1 de 64 hilos está activo. El
bucle de dibujado no diverge nada — y no por suerte, sino porque las 8 lanes
de un warp llevan valores consecutivos y el umbral del `BLT` es múltiplo de 8.

**Esto zanja una pregunta de diseño.** Empaquetar warps distintos en las lanes
que deja libres la divergencia —lo que en la literatura de GPU es *dynamic
warp formation*— es tentador porque aquí sería más fácil de lo normal: cada
lane tiene su propio banco de registros, así que no hay que banquear nada. Pero
la medida dice que **del 94,7% de ocio, solo ~7,5% es divergencia**; el otro
~87% es el camino de control.

Hecho a la perfección, el empaquetado llevaría la utilización del 5,27% al
5,69%. Segmentar el cauce apunta al 30-50%. **Es optimizar lo que no limita**,
al menos con programas de este estilo.

Eso reencuadra toda la sección siguiente. No estamos ante una máquina bien
alimentada a la que le sobra un 20%: estamos ante ocho unidades de cálculo casi
siempre ociosas porque el camino de control tarda 17,6 ciclos en darles una
instrucción.

### 5. El cuello es el SM, y es estructural

```text
3 334 230 ciclos / 170 486 instrucciones = 19,6 ciclos por instruccion
```

Con el fetch acertando el 100% y cero stalls de memoria, esos 19,6 ciclos son
la máquina misma. `gpu_sm.v` recorre **once estados por instrucción**:

```text
PICK → CONTEXT → RECON → FETCH → FETCH_WAIT → RF_WAIT → DECODE
     → START → EXEC → FINISH → RETIRE → PICK
```

y ejecuta **una instrucción a la vez en toda la máquina**: hay un solo registro
`current` con el warp activo, y no se vuelve a `PICK` hasta que la instrucción
en curso retira.

### Qué ocultan los warps y qué no

Conviene ser preciso, porque las dos cosas se confunden con facilidad.

**Los 8 warps SÍ ocultan la latencia de memoria.** En `PICK`, un warp con
`wait_mem` o `wait_bar` se salta y se elige otro:

```verilog
if (!pick_found && live[candidate]!=0 && !wait_mem[candidate] && !wait_bar[candidate])
```

Así que cuando un warp lanza un `LOAD`, el SM no se queda esperando: marca ese
warp y sigue con otro. **Eso es exactamente por lo que `STALL_MEM = 0` y por lo
que la memoria no aparece como cuello de botella.** El mecanismo funciona.

**Lo que NO se oculta es el propio cauce de instrucción.** El SM completa los
once estados de una instrucción antes de empezar la siguiente, sea del warp
que sea. Mientras un warp está en `FETCH_WAIT`, ningún otro está decodificando:
no hay segmentación entre etapas, solo entrelazado a granularidad de
instrucción completa.

De ahí los 19,6 ciclos: no son latencia de memoria escondida a medias, son el
cauce entero pagado once veces por instrucción.

Los 64 hilos (8 warps × 8 lanes) corren todos, desde el reset: `gpu_sm.v`
inicializa `live[w]=8'hff` y `active[w]=8'hff` para los ocho, con `pc[w]=0`. No
hay que arrancar nada.

## Dónde optimizar, por orden de evidencia

1. **Segmentar el cauce del SM.** Es el cambio grande y el que la medida
   señala. No es "hacer que los warps corran a la vez" —ya se entrelazan— sino
   que las ETAPAS se solapen: mientras el warp A está en `FETCH_WAIT`, el warp
   B podría estar en `DECODE`. Con once estados por instrucción y ocho warps
   disponibles para llenarlos, hay mucho que ganar. Es también el cambio más
   invasivo: hay que replicar por warp el estado que hoy es único
   (`instruction`, y todo lo que cuelga de `current`).

2. **Acortar el handshake de fetch. HECHO.** Ver abajo.

3. **Las operaciones multiciclo.** `MUL` son 4 estados y los desplazamientos un
   bit por ciclo. En este programa aportan ~0,5 ciclos por instrucción de
   media: ya no es donde está el dinero, aunque sí conviene seguir escribiendo
   los programas evitando `SHL` grandes (ver `plasma.asm`).

## Aplicada la optimización 2: el fetch en 2 ciclos en vez de 4

`gpu_imem_buffer` traducía entre los dos contratos con una máquina de tres
estados. Costaba **dos ciclos de más en cada búsqueda, incluso acertando**:
uno para latchear una dirección que ya era un registro estable del SM, y otro
para registrar un dato que el bufer ya entregaba registrado.

Las dos etapas sobraban, y por razones que se pueden comprobar en el RTL:

- `imem_address` es `context_pc`, y el SM se queda en `FETCH_WAIT` hasta la
  respuesta: la dirección no cambia durante toda la búsqueda, ni siquiera en un
  fallo de decenas de ciclos.
- `instruction_buffer` ya latchea en su `ST_IDLE` todo lo que necesita
  (`fill_index`, `fill_tag`, `want_word`), así que le basta un pulso de un
  ciclo en `cpu_imem_valid`.

El módulo queda sin máquina de estados: **pegamento puramente combinacional**.
`instruction_buffer.v` no se toca, así que sigue compartido con 21 sin
bifurcar.

| | Antes | Después | |
| --- | --- | --- | --- |
| Ciclos/frame | 3 322 444 | 2 905 633 | **−12,5%** |
| Ciclos por instrucción | 19,55 | 17,57 | **−10,1%** |

La predicción era "2 ciclos de 19,6, o sea 10,2%". Salió 10,1%. El −12,5% del
frame es algo mayor porque, al acabar antes el dibujado, el bucle de espera del
intercambio da menos vueltas (`RETIRED` baja de 170 486 a 166 046).

**Esto depende de un invariante que conviene no perder de vista:** el SM no
puede tener dos búsquedas en vuelo, y por eso `imem_ready` puede ser constante.
El día que se segmente el cauce del SM —la optimización 1— hay que revisar
exactamente esto.

## Lo que este perfil deja claro para el futuro

Las tres optimizaciones grandes de esta sesión —camino de 128 bits,
coalescencia, bufer de instrucciones— han movido el cuello de botella hasta
sacarlo por completo del subsistema de memoria. La LSU v2 sirve el 10% del
tráfico sin despeinarse y el canal va al 48% de su pico.

A partir de aquí, **cualquier trabajo en memoria da rendimientos casi nulos**
hasta que el SM sepa solapar warps. Esto incluye la segmentación de la LSU
(v2.1) descrita en `lsu-v2.md`: con `STALL_MEM = 0`, esconder la latencia de
una transacción detrás de otra no ganaría nada medible hoy.

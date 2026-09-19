# Log: la unificación del MMIO de la página de 4 KiB

> **Esto es un log cerrado, no una referencia.** Cuenta qué se hizo entre el
> 15 y el 18 de septiembre de 2026 para que los diez prototipos con bitstream
> compartieran un mismo mapa MMIO, cómo se hizo y por qué. **No describe el
> estado actual ni el contrato objetivo, y no debe usarse para decidir nada
> nuevo.**
>
> - Lo que implementa cada prototipo hoy:
>   [`resumen-prototipos.md`](resumen-prototipos.md).
> - El contrato al que se converge: [`../1.isa/mmio.md`](../1.isa/mmio.md).
> - El trabajo pendiente: [`../TODO.md`](../TODO.md).
>
> Se conserva porque el **porqué** de varias decisiones que siguen vivas en el
> RTL solo está escrito aquí, y porque documenta dos errores que costaron una
> ronda de placa cada uno.

El plan que ejecutó esta ronda partía del «contrato objetivo» de un documento
que ya no existe, `docs/mapa-de-memoria.md`, cuyo contenido se repartió entre
los tres de arriba. Aquel contrato conservaba la página única de 4 KiB y los
slots de 256 B; MMIO v2 los abandona. **Lo que esta ronda construyó es, por
tanto, un estado intermedio**, no el destino.

---

## Qué se hizo

### Las fases, en orden

| Fase | Qué hizo |
|---|---|
| 0–2 | Inventario, colisiones entre familias, decisión de reparto por slots |
| 3 | Uniformar los registros de vídeo entre CPU y GPU |
| 3.4 | Acceso de 32 bits al MMIO: `READ_WORD` |
| 3.5 | Contadores de CPU a MMIO, `VIDEO_CTRL` en `+0x18`, bases de framebuffer a cero |
| 4a | `SYS_ID` e `ISA_PROFILE`, escritos a mano y fijados con un test |
| 5 | `monitor.v` único parametrizado, y renumerado de versiones a 3/4 |

El **por qué** de cada una vive hoy en los comentarios de los ficheros que
tocaron y en las docstrings de los tests que las fijan:
`x.tests/test_monitor_port.py`, `test_sysid_device.py`, `test_monitor_protocol.py`,
`test_top_wiring.py`, `test_run_tests_parallel.py`. El historial completo está en
git.

### Los dos movimientos que resolvieron la colisión

Había dos choques: `0x80000000` era vídeo o configuración de warps según la
familia, y `0x80000200` era serie o vídeo. Se arreglaron con dos movimientos y
ninguno más:

- la configuración de warps salió de `0x80000000` a una segunda página,
  `0x80001000`, en 12, 14, 17 y 22;
- el vídeo de la 22 volvió de `0x80000200` a `0x80000000`.

Depuración SIMT y contadores no se movieron nunca: ya estaban en su sitio.
**Ningún core de CPU cambió de dirección**, que era el criterio — se tomó como
base el troceado en slots de 256 B de la 19 y la 21 precisamente porque ya
cumplía sin tocar nada.

Mandar los warps a una segunda página en vez de a un slot libre de la primera fue
deliberado: dejaba lo exclusivo de la GPU separado de lo compartido, en vez de
intercalado. Costó un bit más en el comparador de prefijo del decodificador de
GPU.

### El `monitor.v` único (fase 5)

Se dejó **un solo `monitor.v`, copia idéntica en las diez carpetas**. Todo lo
que distingue a un prototipo entra por parámetro desde su `top.v`:
`VERSION_MAJOR`/`MINOR`, `HAS_SERIAL`, `RAM_END` y cinco ventanas MMIO.

Tres decisiones que cambiaron comportamiento, y conviene conocerlas:

- **La base es el monitor de la 19, no el de la GPU.** El plan suponía lo
  contrario —el de la GPU ya era el parametrizado— pero el de la familia CPU
  tiene dos cosas que el otro no: decodificación de comando **segmentada**
  (`command_decoded` one-hot registrado) y validación de bloque **segmentada**
  (`STATE_CALCULATE_BLOCK_END` / `STATE_VALIDATE_BLOCK`). Las dos existen para
  cumplir a 120 MHz, y partir del de la GPU habría metido el sumador ancho en el
  camino del byte de UART justo donde ya se sabía que no cumple.

  Coste: las cuatro GPU ganan dos etapas de pipeline por comando. Sobre un enlace
  de 1 Mbaud —10 µs por byte— dos ciclos a 25 MHz no se miden.

- **La familia CPU ganó lista blanca de bloques, y es permisiva.** Antes
  rechazaba todo lo que no fuera RAM, así que un `READ_BLOCK` sobre MMIO daba
  NACK. Resultó **acotado**, porque la comprobación solo gobierna bloques: los
  accesos byte a byte y `READ_WORD` no pasan por ella en ninguna de las dos
  familias y se filtran aguas abajo.

- **`RUN` y `STEP` exigen parado Y sin error, en las dos familias.** La GPU ya lo
  hacía; la CPU no. Arrancar sobre un error latcheado contestaba `b0` y volvía a
  parar en el acto: el host veía un arranque que no arrancó. Con `ff` sabe que
  tiene que resetear primero.

De paso se cerró un cabo suelto: 6 y 10 tenían `MONITOR_REGIONS = ()` en su
`monitor.py` aunque ya llevaban `sysid`. No daba la cara porque `read_word` no
valida, pero `read_memory` y `read_block` sí, así que leer la identificación por
bloque se habría rechazado en el host antes de llegar al cable.

### `WRITE_WORD`, y por qué se reabrió algo descartado

`WRITE_WORD` estuvo descartado «con motivo» y el motivo era falso en sus dos
mitades. Queda escrito porque es el ejemplo de por qué una lista de descartes se
lee como un razonamiento de su día, no como una verdad:

1. «Obliga a llevar máscara de bytes hasta el puerto aux y hasta la RAM.» **No
   hizo falta.** El puerto aux de la GPU ya era de 32 bits con strobe de 4, y el
   `memory_map` de la 6 ya tenía habilitación por byte: dos líneas. El coste real
   estaba donde el descarte no miró, en los adaptadores de SDRAM de **16 bits**
   (10 y 16), donde una palabra son DOS ráfagas y hubo que añadir dos estados
   simétricos a los que la lectura ya tenía.

2. «Solo evita el desgarro de escritura, que ya se evita con el núcleo parado.»
   **El contraargumento estaba dos líneas más abajo**: `READ_WORD` entró porque
   `frame_count` avanza con el núcleo parado. Pues `FB_FRONT` lo lee ese mismo
   scanout, que cuelga de `reset` y no de `core_reset`. Y `HALT_AT` es peor: en
   `video_registers.v` CUALQUIER escritura reinicia `swap_count` y rearma la
   alarma con el valor ya mezclado, así que byte a byte eso ocurre cuatro veces
   y con valores intermedios.

Lo que el descarte no decía y sí importa, medido en placa: una ida y vuelta por
el UART cuesta **16 ms fijos** por el latency timer del FTDI —un `PING` de dos
bytes tarda lo mismo que un bloque de 256—, así que escribir un registro de 32
bits pasa de cuatro viajes a uno. Lo que **no** mejora es `WRITE_BLOCK`, que ya
mandaba sus 256 bytes en un viaje.

### Cómo se cerró el timing de la 6 y la 10

`WRITE_WORD` costó entre 15 y 19 MHz en la familia CPU. Las de 80 MHz tenían
margen; 6, 10 y 16 no cerraron a la primera. La 16 era cosa de la semilla —siete
de ocho cumplían, se fijó la 1—. La 6 y la 10 no: barrido de ocho semillas en
cada una, ninguna cumplía los 120 MHz, con medianas un 10 % y un 17 % por debajo.
Cuando la mediana cae así, el problema no es cómo se coloca el diseño: es el
diseño.

Se hicieron **dos** cosas:

**Arreglar el camino crítico**, que era el mismo en las dos y **no** era el mux
de `req_wdata`/`req_wmask` que la 16 señalaba en su `apio.ini`. Era la BRAM
`block_read_buffer` entrando en el mux de `response_byte_0`: ese registro lo
escriben una veintena de ramas del FSM, así que su entrada D son cuatro niveles
de LUT, y colgar ahí la BRAM les sumaba sus 5,8 ns de clk-to-q.

El arreglo fue dar al byte de bloque su propio registro —`block_read_byte`, que
yosys absorbe en el registro de salida de la BRAM— y elegirlo en el mux de
`tx_data`, que es registro a registro. **No cambia ni un ciclo del protocolo** y
sale con menos LUTs y menos FFs. Vale para las diez carpetas.

**Y aun así bajar el reloj a 100 MHz**, porque a 120 seguía sin cumplir ninguna
semilla y en la 6 incluso empeoró:

| | antes del arreglo | después, a 120 | después, a 100 |
|---|---|---|---|
| 6 | 108,51 (mediana de 8) | 88,93 | **104,41, cumple 1 de 8** |
| 10 | 99,41 | 106,49 | **107,36, cumplen 7 de 8** |

Quitado el cuello de la BRAM, en la 6 el que manda pasa a ser
`mem_address → sysid_ready → memory_map_i.release_wait`, con 1,2 ns de lógica y
más de 4 de rutado. La 6 ocupa el 7 % del chip y el emplazador la dispersa, así
que ahí no se gana desde el RTL. **Cumple una semilla de ocho, la 4, con
+4,4 %** — en esa carpeta la semilla ya no elige margen, elige si el diseño
funciona. Su `apio.ini` lo dice con todas las letras.

Bajar el reloj **arrastró el baudio**: 120/40 daban 3 Mbaud exactos y a 100 MHz
no hay divisor que los dé (33,33). `uart.v` además exige múltiplo de 4
—sobremuestrea a ×4—, lo que descarta 50, y 2,5 Mbaud no lo sabe hacer el FTDI.
Las dos quedaron en **1 Mbaud con divisor 100**, el mismo que 16, 18, 19 y 21. En
la 10 hubo que bajar también `CLK_FREQ_HZ` en su `top.v`, de donde salen los
tiempos del controlador de SDRAM.

La salida que **no** se tomó fue dejar `WRITE_WORD` fuera de esas dos, ni darles
un `monitor.v` aparte: habrían salido más baratas ese día y más caras siempre.

### La política de dirección inexistente

Decidida el 17/09/2026 e implementada: dispositivo ausente u offset reservado da
error en lectura y escritura, salvo comportamiento definido expresamente. Sin
excepción general para el slot de identificación.

El decodificador de CPU devuelve error y lo propaga a los adaptadores del núcleo
y del monitor; los select de periférico se anulan antes de cualquier efecto
lateral. Los simuladores validan el offset antes de ejecutar el acceso, y el
cliente del host distingue magic, cero histórico, rechazo explícito y fallo de
transporte.

El monitor acumula primero un `READ_BLOCK` y solo emite `a1` tras leer todos sus
bytes, para que un `ff` de datos no se confunda con un NACK. Si un bloque falla,
consume el payload pendiente antes de volver a interpretar comandos, para
conservar la sincronía del UART.

Esta política **sobrevive intacta a MMIO v2**, que la recoge y la amplía en su
§4.3.

---

## Los dos fallos que solo dio la placa

Salieron en la ronda del 17/09/2026 y los dos se arreglaron:

- **La 18 truncaba la dirección MMIO a cinco bits en su `top.v`.** Los
  adaptadores, el mux y el decodificador declaran doce; Verilog trunca en
  silencio al conectar el puerto, así que los siete bits altos se perdían y los
  dieciséis dispositivos de la página caían todos sobre el de vídeo: pedir
  `SYS_ID` o `PERF_CYCLES` devolvía `FB_FRONT`, y escribir en cualquier sitio
  escribía `FB_FRONT`. **No lo ve ningún banco porque ninguno instancia `top`** —
  el mismo agujero que dejó `mem_read_word` sin conectar en 10 y 16. Hay ya un
  `test_top_wiring.py` que fija ese tipo de fallo.

- **`x.tests/backends/gpu_fpga.py` no miraba `requires`.** Mientras `cases-gpu`
  fue el único origen de casos para placa no se notó; con `cases-shared` sí,
  porque `shared-double-buffer` pide `video` y la 12 no lo tiene: se ejecutaba
  hasta que la placa contestaba `ff`, o sea un ERROR donde tocaba un SKIP.

---

## La lección que no debe quedarse aquí

Se cobró tres veces en esta ronda, y **no pertenece a un log archivado** sino a
las instrucciones de trabajo del repositorio ([`../AGENTS.md`](../AGENTS.md),
[`../tools/README.md`](../tools/README.md)):

> **La semilla de `nextpnr` es propiedad de un *netlist*, no de un diseño.**
> Cualquier cambio de RTL, por tonto que parezca —subir una constante de ocho
> bits basta—, invalida un barrido anterior.

Y su corolario práctico: `yosys` y `nextpnr` son monohilo, así que se sintetiza
en paralelo con `Start-Job`, una carpeta por trabajo.

---

## Qué quedó sin terminar

Se movió a [`../TODO.md`](../TODO.md) y no se sigue aquí:

- Resintetizar las carpetas cuyo bitstream es anterior al `monitor.v` final, y su
  ronda de placa.
- `DEV_BITMAP`, que nunca tuvo consumidor. Su contradicción con la fase 4a
  —`SYS_ID` e `ISA_PROFILE` se escribieron a mano con el argumento de que un
  fichero generado se desincroniza en silencio— quedó resuelta en MMIO v2 §5.4,
  que lo deriva del RTL por el camino de `capabilities.json`.
- Un apunte suelto sin dueño: **`urgent_r` se dispersa mucho en la 19**. Su
  barrido da 3 de 8 semillas, peor que cualquier barrido anterior de esa
  carpeta, y el camino crítico es 84 % rutado (2,18 ns de lógica contra 11,70 de
  rutado). No bloquea nada, pero es la clase de cosa que un día deja de pasar
  del todo.

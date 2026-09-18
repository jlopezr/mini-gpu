# Plan de unificación del mapa de memoria y MMIO — lo que queda

Lista de trabajo para aplicar el **contrato objetivo** de
[`mapa-de-memoria.md`](mapa-de-memoria.md) §6 al RTL, a los monitores y a los
tests. Ese documento define *qué* debe quedar; este, *qué falta* y *en qué
orden*.

Objetivo declarado: **que el mismo programa valga en varios prototipos**. El
criterio para ordenar es ese, no la dificultad.

> **Este documento sólo contiene lo abierto.** Las fases 0, 1, 2, 3, 3.4, 3.5,
> 4a y el renumerado de la 5 están cerradas y se han quitado de aquí: lo que
> hacían vive ahora en el RTL, y **por qué** lo hacían vive en los comentarios
> de cada fichero y en las docstrings de los tests que las fijan
> (`x.tests/test_monitor_port.py`, `test_sysid_device.py`,
> `test_monitor_protocol.py`, `test_top_wiring.py`, `test_run_tests_parallel.py`).
> El historial completo está en git. Repetirlo aquí convertía el plan en un
> diario, y un diario de doscientas líneas de trabajo terminado esconde las
> quince que aún importan.

---

## Estado al 18/09/2026

El timing de la 6 y la 10 está **resuelto**: las dos bajan a 100 MHz y cierran.
Queda **una** cosa con dueño y **una** fase entera que hoy no tiene quien la
pida.

| Qué | Dónde | Bloquea a |
|---|---|---|
| Ronda de placa: la 6, la 10, y **repetir las ocho ya hechas** | abajo | cerrar 3.5 y 5 |
| `DEV_BITMAP` | fase 4b | nada: no tiene consumidor |

Lo de «repetir las ocho» no es un retroceso: `monitor.v` volvió a cambiar
después de verificarlas, y el fichero es el mismo en las diez carpetas, así que
sus bitstreams ya no son los que se probaron. Es una pasada automatizada de
unos diez minutos de placa, y sale más barato que la alternativa —un
`monitor.v` aparte para la 6 y la 10— que reintroduciría exactamente las copias
divergentes que esta fase acaba de quitar.

---

## Lo primero: la ronda de placa

Es lo que desbloquea cerrar dos fases, y **acumula cinco cambios sin verificar
en hardware**. Va primero porque cuanto más se acumula, menos dice un fallo
sobre cuál de ellos lo causó.

**La 19 ya está hecha** (17/09/2026): programada con su bitstream nuevo,
contesta `4.19`, y sobre ella se comprobaron `SYS_ID` (`0x4d470013`), los
contadores en MMIO con `read-word 0x80000300` mientras la CPU corría,
`WRITE_WORD` sobre SDRAM y sobre `FB_BACK`, el rechazo de dirección no alineada
en el RTL y el mensaje de «hay que parar la CPU».

**Las otras siete con bitstream se pasaron el 17/09/2026** (12, 14, 16, 17, 18,
21, 22), cada una con esas comprobaciones **y** la suite de casos contra placa
(`test-board`). Todas en verde al terminar. La 17 no tiene `version.json` y por
tanto no es un target de `test-board`: eso es deliberado, no un hueco.

Los dos fallos que salieron eran de los que **sólo** da la placa:

- **La 18 truncaba la dirección MMIO a cinco bits en su `top.v`.** Los
  adaptadores, el mux y el decodificador declaran doce; Verilog trunca en
  silencio al conectar el puerto, así que los siete bits altos se perdían y los
  dieciséis dispositivos de la página caían todos sobre el de vídeo: pedir
  `SYS_ID` o `PERF_CYCLES` devolvía `FB_FRONT`, y escribir en cualquier sitio
  escribía `FB_FRONT`. No lo ve ningún banco porque ninguno instancia `top` —
  es exactamente el mismo agujero que dejó `mem_read_word` sin conectar en 10 y
  16. Arreglado y reverificado.
- **`x.tests/backends/gpu_fpga.py` no miraba `requires`.** Mientras `cases-gpu`
  fue el único origen de casos para placa no se notó; con `cases-shared` sí,
  porque `shared-double-buffer` pide `video` y la 12 no lo tiene: se ejecutaba
  hasta que la placa contestaba `ff`, o sea un ERROR donde tocaba un SKIP.
  Añadida la comprobación que `fpga.py` ya tenía.

**Esas ocho hay que repetirlas**, porque `monitor.v` volvió a cambiar después
(ver `WRITE_WORD` más abajo) y el fichero es común a las diez. Pendientes,
pues: la 6, la 10 y repetir las ocho.

Lo que hay que validar, y por qué cada cosa puede fallar sólo en placa:

- **Fase 3.5 entera.** Contadores en MMIO, `VIDEO_CTRL`, bases de framebuffer a
  cero. Cerrada en RTL, simuladores y pruebas. Verificada en la 19; falta en las
  demás. Se dejó agrupada al final a propósito, para no pagar un `nextpnr` por
  cada punto.
- **El renumerado de versiones, ahora a 3/4.** Un `top.v` que se olvide del
  parámetro contesta `x.0`, y eso sólo se ve preguntándoselo a la placa. Toda
  placa sin reprogramar dará MISMATCH en `board-info`, que es el aviso correcto
  y no un fallo.
- **`SYS_ID` en 6 y 10.** Llegan por el camino del monitor, no por una ventana
  MMIO; en simulación no hay nada que lo distinga de estar bien.
- **`READ_WORD` en la 10 y la 16.** `mem_read_word` estaba **sin conectar** en
  sus `top.v`: en placa devolvía X. No se vio antes porque `monitor_tb` maneja
  esa señal él mismo y ningún banco instancia `top`. Hay ya un
  `test_top_wiring.py` que lo fija, pero quien tiene la última palabra es la
  placa. **Visto ya en la 16**, que pasó entera; la 10 sigue pendiente.
- **La convergencia de los `monitor.v` y `WRITE_WORD`**, que cambian el netlist
  de las diez carpetas. De `WRITE_WORD` el camino de 128 bits está visto en 19 y
  18, y el de la GPU en 12, 14, 17 y 22. **El de 16 bits —10 y 16, que hacen la
  escritura en DOS ráfagas— está visto en la 16 y falta la 10**, y es el que más
  código nuevo lleva.

Recordatorio que ya costó una vez y que aquí se volvió a cumplir dos veces más:
la semilla de `nextpnr` es propiedad de un *netlist*, no de un diseño, así que
cualquier cambio de RTL invalida un barrido anterior.

- La 19 mantiene su `--seed 4` y sigue cumpliendo.
- La 16 **perdió** su semilla: la 4, que estaba fijada, cayó a 96,58 MHz con
  100 exigidos. Rebarrido: cumplen siete de ocho; se fijó la 1 (+5,0 %) y ya
  cierra a 105,03 MHz.
- **La 6 y la 10 no se arreglaban con semilla a 120 MHz**: bajaron a 100 y ahí
  cierran. Ver el apartado de `WRITE_WORD`.
- **Todas las demás hay que resintetizarlas otra vez**, porque `monitor.v`
  cambió después de que se archivaran sus builds. Sus semillas fijadas vuelven
  a ser de un netlist que ya no existe.

`yosys` y `nextpnr` son monohilo: se sintetiza en paralelo con `Start-Job`, una
carpeta por trabajo.

---

## Convergencia de los `monitor.v` (fase 5)

**Estado: simulación cerrada, síntesis a medias, placa pendiente.** `x.tests`
pasa (235 tests) y **los bancos RTL de las diez carpetas pasan**, incluida la 22.
En 19 y 21 hubo que actualizar los modelos de los tests serie, que aún buscaban
constantes retiradas de `monitor.py`. La 6 cubre además el rechazo de `RUN` y
`STEP` con error latcheado, sin emitir peticiones al núcleo.

De la síntesis de las diez, **ocho cierran timing y dos no** (la 6 y la 10); ver
el apartado de `WRITE_WORD` más abajo, que es lo que las movió.

Lo que se hizo: un `monitor.v` único, **copia idéntica en las diez carpetas** con
juego de comandos (6, 10, 12, 14, 16, 17, 18, 19, 21, 22). Todo lo que distingue
a un prototipo entra por parámetro desde su `top.v`: `VERSION_MAJOR`/`MINOR`,
`HAS_SERIAL`, `RAM_END` y cinco ventanas MMIO.

Tres decisiones que conviene revisar antes de darlo por bueno, porque las tres
cambian comportamiento:

- **La base es el de la 19, no el de la GPU.** El plan suponía lo contrario —el
  de la GPU ya era el parametrizado— pero el de la familia CPU tiene dos cosas
  que el otro no: la decodificación de comando **segmentada** (`command_decoded`
  one-hot registrado) y la validación de bloque **segmentada**
  (`STATE_CALCULATE_BLOCK_END` / `STATE_VALIDATE_BLOCK`). Las dos existen para
  cumplir a 120 MHz. Partir del de la GPU habría metido el sumador ancho en el
  camino del byte de UART justo donde ya se sabe que no cumple.

  Coste: las cuatro GPU ganan dos etapas de pipeline por comando. Sobre un
  enlace de 1 Mbaud —10 µs por byte— dos ciclos a 25 MHz no se miden.

- **La familia CPU gana lista blanca de bloques, y es permisiva.** Antes
  rechazaba todo lo que no fuera RAM (`mem_address[31:25] != 0`), así que un
  `READ_BLOCK` sobre MMIO daba NACK. Ahora pasa por las ventanas declaradas. Es
  el cambio que el plan temía; resultó **acotado**, porque la comprobación sólo
  gobierna bloques: los accesos byte a byte y `READ_WORD` no pasan por ella en
  ninguna de las dos familias, y siguen filtrándose aguas abajo. Eso es también
  lo que deja pendiente aplicar la política de la sección siguiente.

- **`RUN` y `STEP` ahora exigen parado Y sin error, en las dos familias.** La
  GPU ya lo hacía; la CPU no. Arrancar sobre un error latcheado contestaba `b0`
  y volvía a parar en el acto: el host veía un arranque que no arrancó. Con `ff`
  sabe que tiene que resetear primero. **Es visible en el protocolo** sin que
  cambie el juego de comandos, así que merece mirarse con cuidado en los bancos
  de la familia CPU.

De paso se cerró un cabo suelto: 6 y 10 tenían `MONITOR_REGIONS = ()` en su
`monitor.py` aunque ya llevaban `sysid`. No daba la cara porque `read_word` no
valida, pero `read_memory` y `read_block` sí, así que leer la identificación por
bloque se habría rechazado en el host antes de llegar al cable.

### `WRITE_WORD` (17/09/2026)

Este comando estaba **descartado con motivo** en «Fuera de esta ronda». Se
reabrió, se implementó y se propagó a las diez. Lo que sigue es por qué el
argumento de descarte no valía, que es justo lo que aquel apartado pide de
quien lo reabra.

El descarte decía dos cosas y las dos eran falsas:

1. «Obliga a llevar máscara de bytes hasta el puerto aux y hasta la RAM, en las
   dos familias.» **No hizo falta.** El puerto aux de la GPU ya era de 32 bits
   con strobe de 4 (`aux_write_data` / `aux_strobe` en `gpu_system.v`), y el
   `memory_map` de la 6 ya tenía habilitación por byte. Ahí el cambio es poner
   el strobe a `4'b1111` y el dato entero: dos líneas. El coste real estaba
   donde el descarte no miró, en los adaptadores de SDRAM de **16 bits** (10 y
   16), donde una palabra son DOS ráfagas y hubo que añadir dos estados
   (`STATE_MON_WRITE2` / `STATE_MON_WWAIT2`), simétricos a los que la lectura ya
   tenía desde `READ_WORD`.

2. «Sólo evita el desgarro de escritura, que ya se evita escribiendo con el
   núcleo parado.» **El contraargumento estaba dos líneas más abajo, en el mismo
   párrafo**: `READ_WORD` entró porque `frame_count` avanza con el núcleo
   parado. Pues `FB_FRONT` lo lee ese mismo scanout, que cuelga de `reset` y no
   de `core_reset`. Y `HALT_AT` es peor: en `video_registers.v` CUALQUIER
   escritura reinicia `swap_count` y rearma la alarma con el valor ya mezclado,
   así que byte a byte eso ocurre cuatro veces y con valores intermedios; un
   intercambio que caiga entre dos bytes para la CPU en una cuenta que nadie
   pidió. El argumento que justificó `READ_WORD` vale igual dado la vuelta.

Lo que el descarte **no** decía y sí importa, medido en placa: una ida y vuelta
por el UART cuesta **16 ms fijos** por el latency timer del FTDI —un `PING` de
dos bytes tarda lo mismo que un bloque de 256—, así que escribir un registro de
32 bits pasa de cuatro viajes (64 ms) a uno (16 ms). Lo que NO mejora es
`WRITE_BLOCK`, que ya mandaba sus 256 bytes en un solo viaje: quien quiera que
eso vuele tiene que bajar el latency timer del FTDI y subir `MAX_BLOCK_SIZE`, y
no es trabajo de RTL.

**El coste que sí apareció es de timing.** `WRITE_WORD` cuesta entre 15 y 19 MHz
en la familia CPU. Las de 80 MHz (18, 19, 21) tienen margen de sobra; 6, 10 y 16
no cerraron a la primera (110,45 contra 120; 103,15 contra 120; 96,58 contra
100, viniendo de 127,26, 122,58 y 112,03).

La 16 era cosa de la semilla y ya está resuelta (siete de ocho cumplen, fijada
la 1, cierra a 105,03). **La 6 y la 10 no.** Barrido de ocho semillas en cada
una, ninguna cumple:

| | rango del barrido | mediana | exigidos |
|---|---|---|---|
| 6 | 104,00 – 110,58 MHz | 108,51 | 120 |
| 10 | 95,07 – 103,56 MHz | 99,41 | 120 |

La mediana cae un 10 % y un 17 % por debajo de la restricción, así que aquí el
problema no es cómo se coloca el diseño: es el diseño. Son las dos carpetas que
corren a 120 MHz, las dos únicas sin margen, y las dos que menos falta les hace
`WRITE_WORD` —no tienen registros de vídeo ni `HALT_AT`, que es lo que el
comando existe para arreglar; en ellas sólo ahorra tres viajes de UART.

### Cómo se resolvió (18/09/2026)

Se hicieron **dos** cosas, no una: arreglar el camino crítico de `monitor.v`, y
aun así bajar el reloj de las dos a 100 MHz.

**El camino crítico era el mismo en las dos, y no era el mux de
`req_wdata`/`req_wmask`** que la 16 señalaba en su `apio.ini`. Era la BRAM
`block_read_buffer` entrando en el mux de `response_byte_0`: ese registro lo
escriben una veintena de ramas del FSM, así que su entrada D son cuatro niveles
de LUT, y colgar ahí la BRAM les sumaba sus 5,8 ns de clk-to-q. Salían 9,05 ns
en la 6 y 9,69 en la 10.

El arreglo es dar al byte de bloque su propio registro (`block_read_byte`, que
yosys absorbe en el registro de salida de la BRAM) y elegirlo en el mux de
`tx_data`, que es registro a registro. **No cambia ni un ciclo del protocolo** y
sale con menos LUTs y menos FFs que antes. Vale para las diez carpetas.

No bastó. A 120 MHz seguía sin cumplir ninguna semilla, y en la 6 **empeoró**:

| | antes del arreglo | después, a 120 | después, a 100 |
|---|---|---|---|
| 6 | 108,51 (mediana de 8) | 88,93 | **104,41, cumple 1 de 8** |
| 10 | 99,41 | 106,49 | **107,36, cumplen 7 de 8** |

La 10 gana un 7 % y a 100 MHz va holgada. La 6 no: quitado el cuello de la
BRAM, el que manda pasa a ser
`mem_address → sysid_ready → memory_map_i.release_wait`, con 1,2 ns de lógica y
más de 4 de rutado. La 6 ocupa el 7 % del chip y el emplazador la dispersa, así
que ahí no se gana desde el RTL. **Cumple una semilla de ocho, la 4, con
+4,4 %**, que es lo más justo del repositorio: en esa carpeta la semilla ya no
elige margen, elige si el diseño funciona. Su `apio.ini` lo dice con todas las
letras.

Bajar el reloj **arrastra el baudio**, como su `README.md` llevaba tiempo
avisando: 120/40 daban 3 Mbaud exactos y a 100 MHz no hay divisor que los dé
(33,33). `uart.v` además exige múltiplo de 4 —sobremuestrea a ×4—, lo que
descarta 50, y 2,5 Mbaud no lo sabe hacer el FTDI. Las dos quedan en **1 Mbaud
con divisor 100**, el mismo que 16, 18, 19 y 21.

En la 10 hay que bajar también `CLK_FREQ_HZ` en su `top.v`: de ahí salen los
tiempos del controlador de SDRAM, y quedarse en 120 sería pedirle refrescos a
destiempo.

La salida que **no** se tomó fue `HAS_WRITE_WORD` —dejar el comando fuera de la
6 y la 10—, y tampoco un `monitor.v` aparte para esas dos. Las dos habrían
salido más baratas hoy y más caras siempre: vuelven a partir en dos algo que
esta fase acaba de unificar, y el precio de mantenerlo unido resultó ser una
pasada de placa, no una deuda permanente.

### Lo que falta de este punto

- [x] Correr los bancos de las diez carpetas y `x.tests` (235 tests).
- [x] **Cerrar timing en la 6 y la 10**: `block_read_byte` en `monitor.v` y las
      dos a 100 MHz, con 1 Mbaud. Semillas fijadas: la 4 en la 6, la 2 en la 10.
- [x] Ronda de placa de las siete con bitstream (12, 14, 16, 17, 18, 21, 22),
      con `test-board` además de las comprobaciones de contrato. Dos fallos,
      los dos arreglados: la dirección MMIO truncada de la 18 y `requires` sin
      mirar en `gpu_fpga.py`.
- [ ] **Resintetizar las ocho** con el `monitor.v` nuevo, rebarriendo semilla.
- [ ] **Ronda de placa de la 6, la 10 y otra vez las ocho.**

---

## Aplicar la política decidida: dirección inexistente

**Decidido el 17/09/2026:** dispositivo ausente u offset reservado da error en
lectura y escritura, salvo comportamiento definido expresamente para el
registro. No hay excepción general para el slot de identificación. El contrato
y su justificación están en [`mapa-de-memoria.md`](mapa-de-memoria.md) §6.

La implementación está hecha. El decodificador CPU ahora devuelve error y lo
propaga a los adaptadores del núcleo y del monitor; los select de periférico se
anulan antes de cualquier efecto lateral. Solo las cuatro palabras de `SYS_ID`
son legibles y `DEV_BITMAP = 0` sigue siendo un valor válido. Los simuladores
validan el offset antes de ejecutar el acceso, y el cliente del host distingue
magic, cero histórico, rechazo explícito y fallo de transporte.

El monitor acumula primero un `READ_BLOCK` y solo emite `a1` tras leer todos sus
bytes; así un `ff` de datos no se confunde con NACK. Si un bloque falla, consume
el payload pendiente antes de volver a interpretar comandos, para conservar la
sincronía de UART.

- [x] Propagar el error MMIO a CPU, monitor y simuladores, sin efectos en el
      periférico rechazado.
- [x] Eliminar alias de identificación y rechazar escrituras a sus cuatro
      palabras; conservar `DEV_BITMAP = 0` con `CONTRACT = 1`.
- [x] Probar accesos inválidos de programa, host y bloques, además de valores
      válidos cero, en simuladores y bancos RTL.
- [x] Verificar estas rutas **en la 19** (17/09/2026, bitstream 4.19). Los
      offsets que existen contestan (`FB_FRONT`, `PERF_CYCLES`, `SYS_ID` con su
      magic `0x4d470013`); los dispositivos 4 y 5, `SYS_ID +0x10` y `video +0xf0`
      se rechazan; y escribir `SYS_ID` se rechaza. O sea que el decodificador se
      comporta en placa como dice el contrato.
- [x] Verificar estas mismas rutas en **12, 14, 16, 17, 18, 21 y 22**
      (17/09/2026). Las siete rechazan `SYS_ID+0x10`, los dispositivos 4 y 5 y
      la escritura a `SYS_ID`; las que tienen vídeo rechazan además `video+0xf0`.
      Aquí salió el truncamiento de dirección de la 18, que hacía que *todo*
      ese rechazo no ocurriera: sin los siete bits altos no hay dispositivo
      inexistente que valga, porque ninguna dirección sale del de vídeo.
- [ ] Verificar la **6 y la 10**, y repetir las siete con el `monitor.v` nuevo.

---

## Fase 4b — `DEV_BITMAP`

**No tiene hoy ningún consumidor que la pida.** Se deja escrita porque el hueco
existe en el contrato (`+0x08`, lee cero, que con `CONTRACT = 1` significa «sin
declarar» y no «ningún dispositivo»), no porque haga falta ya.

- [ ] **Generarlo desde `capabilities.json`**, no a mano: escrito a mano en cada
      sitio sería una tercera gemela que mantener junto a las ventanas y
      `MONITOR_REGIONS`, justo lo que §6.5 quiere quitar.

      **Ojo, esto contradice lo que se decidió en 4a**, y la contradicción es
      deliberada, así que hay que resolverla antes de empezar: `sysid.v` e
      `ISA_PROFILE` se escribieron **a mano y contrastados con un test**, con el
      argumento de que un fichero generado se desincroniza en silencio si
      alguien toca el RTL y no regenera, mientras que un test que compara falla
      a gritos. Si ese argumento valía para `ISA_PROFILE`, hay que explicar por
      qué no vale para `DEV_BITMAP` — o generar los dos, o ninguno.
- [ ] Hace falta maquinaria que **no existe**: hay `.vh` generados, pero sólo de
      fixtures de simulación, y `generate-docs` sólo toca Markdown. No hay
      precedente de Verilog **sintetizable** generado, ni de un test que
      compruebe que lo generado está al día.
- [ ] `capabilities.json` no tiene números de bit. Hay que añadirlos y
      comprometerse a no reutilizarlos nunca.
- [ ] ~~Hacerlo a la vez que lo que quede de la fase 5~~. **Esa ventana se
      cerró**: de la fase 5 sólo quedan timing en la 6 y la 10 y la ronda de
      placa, y ninguna de las dos cosas construye un generador. Si `DEV_BITMAP`
      se hace algún día, se paga el generador entero él solo.

---

## Fuera de esta ronda, y por qué

Esto no está pendiente: está **descartado con motivo**. Se deja escrito para no
volver a proponerlo sin argumento nuevo.

> Esta lista se equivocó una vez. `WRITE_WORD` estuvo aquí con dos argumentos, y
> los dos eran falsos: ver su apartado en la fase 5. La regla de «no reabrir sin
> argumento nuevo» sigue valiendo, pero conviene leer estas entradas como lo que
> son —un razonamiento de su día, no una verdad— y comprobar sus premisas antes
> de darlas por buenas.

- **Control de lanzamiento GPU por registros** (`0x80001080–0x80001FFF`). Hoy
  run/halt/step/reset llegan por señales del monitor. Convertirlos en registros
  choca de frente con que la interfaz host es byte a byte y sólo funciona con la
  GPU parada. Es rediseño, no reubicación.
- **Convivencia CPU+GPU en el mismo bitstream.** El contrato se diseña para no
  cerrarle la puerta —por eso lo exclusivo de la GPU va a una segunda página en
  vez de a un slot libre de la primera— pero los siete puntos de «lo que falta
  por resolver» de §6 (arbitraje, dominios de reloj, orden de escrituras, quién
  pide los swaps) son otro proyecto.
- **Aceptar MMIO sin modelar el dispositivo.** No se debe añadir una ventana
  que simplemente acepte accesos para que un programa deje de fallar. Esto no
  descarta simular periféricos: 2, 11 y 25 comparten `VideoDevice` (con captura)
  y `SerialDevice`, accesibles por MMIO cuando se instancian. El pipeline de la
  25 enruta MMIO y difiere los efectos de UART hasta el commit. La paridad se
  comprueba ejecutando programas en `x.tests/test_sim_peripherals.py`, no solo
  construyendo objetos de dispositivo.
  Los modelos deben respetar offsets y efectos de los registros implementados;
  el vídeo funcional no reproduce contienda, underflow ni desgarro, y la serie
  no reproduce el tiempo de llegada de los bytes. `plasma_nommio.asm` sirve
  para ejecutar sin dispositivo de vídeo, no como argumento contra modelarlo.

---

## Apunte suelto

- **Por qué `urgent_r` se dispersa tanto en la 19.** Su barrido da 3 de 8
  semillas, peor que cualquier barrido anterior de esa carpeta, y el camino
  crítico es 84 % rutado (2,18 ns de lógica contra 11,70 de rutado). No bloquea
  nada, pero es la clase de cosa que un día deja de pasar del todo.

# CPU pipelined sobre la base del prototipo 35

Prototipo derivado de `35.fpga-cpu-fifo-sdram2`. Mantiene el mismo fabric FIFO,
SDRAM de cuatro bancos, consola de video, puerto serie, INPUT y mapa MMIO; su
objetivo es aislar la pregunta de microarquitectura: si la MiniCPU puede
convertirse en un nucleo segmentado que acepte una instruccion nueva por ciclo
en el caso comun.

La identificacion de placa es monitor `5.38`. La CPU va a 25 MHz (el oscilador
de la placa, sin PLL) y cierra a unos 52-57 MHz; la SDRAM a 100 MHz.

## Estado actual (12 de noviembre)

```text
          ┌─ instruction_buffer (I-cache 8 KB, EBR) ─┐
cpu.v ────┤                                          ├── arbitro ── SDRAM
 IF/ID/EX/WB └─ dcache (8 KB, EBR) ── cpu_dmem_adapter ─┘
```

- **Pipeline IF/ID/EX/WB** con punto de retiro arquitectonico. La ALU y la
  decision de salto van en ID; EX solo hace el acceso a memoria. Las
  dependencias paran ID (sin adelantamiento) y un salto tomado vacia la cola de
  busqueda. Cada etapa es un `always` con un unico dueño por registro
  (`timing-etapas.md`).
- **Busqueda de una instruccion por ciclo.** `imem` separa peticion
  (`valid/ready`) y respuesta (`rvalid`); una cola de tres entradas en IF y un
  contador descartan las respuestas del camino viejo tras un salto.
- **Cache de instrucciones** (`instruction_buffer.v`): 8 KB, mapeo directo,
  lineas de 16 bytes (una rafaga BL8), en EBR. Acierto en un ciclo y una
  busqueda por ciclo; si una busqueda falla, la que ya se acepto detras se
  repite tras el relleno, asi que `ready` sigue saliendo de un registro.
- **Cache de datos** (`dcache.v`): 8 KB, mapeo directo, escritura inmediata a
  memoria y sin reservar linea al escribir, en EBR. Los STORE a SDRAM no
  esperan (posted) y siguen pasando por el bufer de combinacion de
  `cpu_dmem_adapter`; un LOAD que acierta espera a que el adaptador no deba
  respuestas, para no adelantar a la de un STORE.
- **Volcados sin esperar respuesta** (`cpu_dmem_adapter.v`): el bufer de
  combinacion es de una linea, pero al cambiar de linea la vieja se manda al
  puerto y el STORE se contesta al ciclo siguiente, sin esperar a la SDRAM;
  caben hasta 4 escrituras en vuelo (la cola del puerto). El orden lo garantiza
  el camino (cola del puente, cabeza por puerto en el fabric y emision en orden
  de llegada en el controlador), asi que un LOAD detras de un volcado ve el
  dato. Solo esperan a que se confirmen todas las escrituras el MMIO (que puede
  fallar y debe dar error preciso), la parada de la CPU (el monitor lee por
  otro puerto) y un LOAD a la linea guardada.
- **MUL, MULHI, MULFX, DIV, DIVU, REM y REMU** en EX (`cpu.v`, seccion 04b),
  que se queda la instruccion varios ciclos como un acceso a memoria. ID manda
  los operandos por `ex_result` y `ex_store_data`; al acabar, EX escribe el
  resultado en `ex_result` y la instruccion sigue como una de ALU, asi que WB
  y las dependencias no cambian. MUL/MULHI/MULFX salen del mismo producto con
  signo (cuatro parciales 16x16 en DSP, inferidos): 3 ciclos mas que una
  instruccion de ALU. La division es iterativa con signo al final: unos 34
  ciclos mas, y un REM/REMU justo detras de su DIV/DIVU con los mismos
  registros reutiliza el resto (2 ciclos mas, `ALU_FAST_PATH`, como en la 35).
  La division por cero es un error preciso. Sus esperas tienen contador propio
  (ranura 14, `STALL_MULDIV`, un motivo mas del reparto) y la ranura 15
  (`MULDIV_RETIRED`) cuenta cuantas se retiran.
- **Invalidacion por epoca** en las dos caches: cada etiqueta guarda la epoca
  en que se escribio e invalidar todo es sumar uno (en el flanco de `reset` o de
  la CPU parandose). Sin bits de valido, cada cache cuesta unas 330-390 LUT en
  vez de unas 2.000-2.300.
- **Contadores de rendimiento** (CPU PERFORMANCE, `1.isa/mmio.md` §13.2): las
  ranuras 8-11 y 14 reparten cada ciclo sin emitir en un motivo (`CPI = 1 +
  EX con memoria + MUL/DIV + dependencia + salto + ID vacio + otros`), las
  12-13 cuentan aciertos y fallos de la cache de datos y la 15 las MUL/DIV
  retiradas. `run_tests.py --measure` los saca en tablas.
- **SDRAM**: los registros de los pines van en las celdas de IO tambien con
  Yosys (`syn_useioff` en `sdram_controller_128.v`); la ventana de fase buena
  paso de 8 a unas 20-22 posiciones. La fase sale en el bitstream
  (`SDRAM_PHASE` en `top.v`, una por herramienta) y se mide con
  `tools/phase-sweep`.

Bancos: `tools/test -p 38` (entre ellos `cpu_perf_tb`, que mide CPI sin placa,
`dcache_tb`, `instruction_buffer_reset_tb`, `cpu_dmem_adapter_tb` y
`cpu_muldiv_tb`, con mutantes comprobados). `cpu_data_path_tb` junta CPU, D-cache y adaptador reales,
y `cpu_memory_system_tb` añade puente, fabric, controlador, modelo de SDRAM y
dos generadores de trafico en los otros puertos. En placa, los 49 casos de C
pasan.

**Cuidado con el orden de las `<=` en Yosys (0.63+173).** Dentro de un bloque
anidado, una asignacion condicional seguida de otra sin condicion a la misma
señal sale mal: `if (c) begin if (a) v <= 0; v <= b; end` da `a ? 0 : b` en vez
de `b` (y con un `if/else` completo delante, Yosys ignora la ultima). En el
nivel de arriba del `always`, o con el valor por defecto primero y el
condicional despues (lo habitual), sale bien. La primera version de los
volcados sin esperar pasaba todos los bancos y fallaba 12 casos en placa por
eso: `if (wb_valid) send_flush; wb_valid <= 1`, con `wb_valid <= 0` dentro de
la tarea, dejaba la linea nueva invalida. Se encontro simulando la netlist de
Yosys (`synth -flatten; write_verilog` mas `simlib.v`) con el mismo banco.
Regla: nunca una asignacion sin condicion despues de otra condicional a la
misma señal; las tareas lo esconden facil.

## Rendimiento medido en placa

CPI de algunos casos de `run_tests.py --measure`; cada columna añade un cambio.

| Caso | Busqueda 1/ciclo | STORE sin esperar | I-cache 256 B | + D-cache 8 KB | I-cache 8 KB EBR | Volcados sin esperar |
|---|---:|---:|---:|---:|---:|---:|
| video-bounce | 4,43 | 3,85 | 3,85 | 3,85 | 3,85 | 2,61 |
| video-band | — | — | — | — | 3,82 | 2,90 |
| video-swap-demo | — | — | — | — | 3,86 | 2,65 |
| program-bresenham-lines-core | 7,93 | 7,81 | 2,64 | 2,64 | 2,48 | — |
| program-bresenham-circles-core | 7,79 | 7,49 | 2,65 | 2,65 | 2,57 | — |
| shared-calls-call-return | — | 10,86 | 8,32 | 8,14 | 8,41 | — |
| program-memory-copy | 6,68 | 6,05 | 6,07 | 5,00 | 5,02 | 4,64 |
| program-array-sum | 6,03 | 5,88 | 5,79 | 4,85 | 4,79 | — |
| subword-loads | 16,54 | 15,54 | 15,77 | 6,85 | 7,08 | — |

La I-cache en EBR descubre un fallo un ciclo mas tarde que la de biestables
(acepta, lee la EBR y compara al ciclo siguiente), asi que en los casos cortos,
que son casi todo fallos de primer acceso, sube 0,2-0,5 de CPI. Lo que gana es
espacio (8 KB en vez de 256 B por ~740 LUT menos); estos casos no tienen codigo
que lo aproveche.

Lo que dicen los contadores:

- **Video** no hace ni un LOAD a SDRAM: su "EX con memoria" (1,40) eran STORE
  al framebuffer y accesos MMIO, que ninguna cache acelera. Con los volcados
  sin esperar baja a 0,35-0,58 (lo que queda es sobre todo MMIO y el STORE que
  encuentra las 4 escrituras en vuelo).
- **Bresenham** (2,64) pierde sobre todo en saltos (1,03 por instruccion: unos
  3 ciclos por salto tomado) y dependencias (0,34).
- **MUL/DIV** (build `muldiv-contadores`, 72 casos en placa): pesan poco
  salvo en mandelbrot, donde el 21 % de las instrucciones son MUL y su espera
  es 0,68 de un CPI de 2,76. En starfield las DIV esperan 24 ciclos de media,
  pero son el 0,6 % de las instrucciones (0,14 de CPI). Lo que mas rinde es
  acortar la MUL (hoy 3 ciclos), no un scoreboard para la DIV.
- **Los fallos de cache que quedan son de primer acceso.** Los casos son muy
  cortos (10-5.000 instrucciones) y caben enteros en 8 KB: agrandar las caches
  no mejoraria ninguno. La cache de datos acierta un 57-60 % en memory-copy y
  array-sum porque cada linea nueva falla la primera vez.

## Donde se pierde el CPI (build `icache-ebr`)

Reparto de `--measure` ponderado por instrucciones, para que los programas
largos pesen lo que deben. Entre parentesis, la parte de lo perdido (CPI - 1):

| Grupo | CPI | EX con memoria | Dependencia | Salto | ID vacio |
|---|---:|---:|---:|---:|---:|
| Video (6 casos, 25,6 M instr.) | 3,96 | 1,48 (50 %) | 0,50 (17 %) | 0,98 (33 %) | 0 |
| Programas largos sin video (5 casos, 1,9 M) | 3,92 | 1,17 (40 %) | 1,04 (35 %) | 0,71 (24 %) | 0 |
| Casos cortos (< 1000 instr.) | 4,96 | 1,66 | 0,58 | 0,85 | 0,85 |

"ID vacio" ya es 0 en todo lo que dura: la busqueda esta resuelta. Lo que queda
se ve entero en el bucle que domina el video, el fondo de `video/bounce`:

```text
bg_word: STORE R23, R6, 0     ; dos pixeles al framebuffer
         ADDI  R6, R6, 4
         ADDI  R3, R3, 1
         BLT   R3, R25, bg_word
```

Cuatro instrucciones que deberian costar 4 ciclos y cuestan ~15,8:

- **Salto, ~3,8 ciclos por vuelta**: el BLT tomado deja 3 burbujas.
- **Dependencia, ~2**: el BLT usa el R3 del ADDI de justo antes y, sin
  adelantamiento, espera a que llegue a WB.
- **EX con memoria, ~5,6**: tres de cada cuatro STORE se funden en el bufer de
  combinacion; el cuarto cambia de linea y arranca un volcado, y con UNA sola
  linea de bufer el adaptador no acepta nada mas (`dmem_ready` bajo) hasta que
  la SDRAM contesta, unos 18 ciclos. El STORE siguiente los espera. (Resuelto
  despues con los volcados sin esperar respuesta: video-bounce 3,85 -> 2,61.)

## Pasos siguientes

En orden de lo que mas promete segun las medidas:

1. **Saltos mas baratos** (hoy 3 burbujas por salto tomado):
   - B) Respuesta directa a ID cuando la cola esta vacia, sin pasar por ella
     (2 burbujas). Barato y fuera del camino critico; se mide con
     `cpu_perf_tb`.
   - A) Pedir el destino en el mismo ciclo en que ID decide (1 burbuja con B).
     Alarga el camino critico (decodificar → banco → comparar → salto) hasta la
     I-cache: hacerlo con el informe de tiempos delante.
   - Despues, prediccion (saltos hacia atras tomados, o una BTB).
2. **Adelantamiento EX/WB → ID**, para las dependencias (0,34 en bresenham,
   1,04 en los programas largos). Toca el mismo camino critico que 1A.
   Un resultado de ALU existe al salir de ID y se puede adelantar desde EX;
   el de un LOAD o una MUL/DIV solo al acabar EX (`ex_class` vuelve a NORMAL),
   asi que desde EX solo se adelanta si la clase ya es NORMAL o es de ALU.

   Con los volcados sin esperar (ya hechos), 1 y 2, el bucle de arriba pasaria
   de ~16 ciclos a ~6-7, y el video de CPI 3,96 (hoy 2,6) a cerca de 1,7; con
   el reloj a 50 MHz (paso 8), 4-5 veces mas rapido en tiempo real que con
   `icache-ebr`.
3. **Un acierto de la D-cache cuesta 3 ciclos de EX** (medido en
   `cpu_data_path_tb`, con CPU, D-cache y adaptador reales: 3,00 por LOAD, y
   3,31 justo detras de un STORE). Ciclo a ciclo:

   ```text
   E0  el LOAD entra en EX; la D-cache lo acepta y lee la EBR
   E1  compara la etiqueta y registra la respuesta (local_rvalid)
   E2  llega rvalid: el LOAD pasa a WB y EX queda vacio
   E3  entra en EX la instruccion siguiente
   ```

   Un ciclo es la lectura de la EBR, otro la respuesta registrada y el
   tercero que la instruccion siguiente no entra en EX en el mismo ciclo en
   que el acceso acaba (`ctl_advance` mira `ex_is_memory`, no si termina).
   subword-loads son 13 instrucciones: un fallo frio y 9 aciertos de 3
   ciclos, de ahi sus ~3,5. Tras un STORE solo se anaden 0,31: `pending`
   cuenta las respuestas del adaptador, que contesta un STORE al ciclo
   siguiente.

   Que hacer: dejar entrar la siguiente en el ciclo en que el acceso acaba
   (-1 ciclo en todo acceso a memoria o MMIO) y, para tiempos, registrar la
   comparacion de la D-cache (+1). Un LOAD por ciclo necesita una etapa MEM
   aparte (partir ID/EX, paso de los 80 MHz).
4. **Menos fallos de primer acceso**: traer la linea siguiente por adelantado
   (prefetch) en las dos caches, o lineas de 32 bytes.
5. **Un programa grande para medir tamaños**: una demo en C con biblioteca o un
   juego que pase de 8 KB de codigo o datos. Con `IMEM_MISSES` y `DMEM_MISSES`
   se ve directamente si 16 KB o dos vias servirian; con los casos actuales no.
6. **Reloj de la SDRAM por la celda de IO** (`ODDRX1F` con `D0=1, D1=0`, como
   el DVI). Hoy `assign sdram_clk = clk` va por rutado general y la ventana de
   fase aun se mueve entre builds (2-21 en uno, 8-29 en otro). Tambien `dq_oe`,
   replicado por pin, para que quepa en las celdas de IO.
7. **MMIO, solo si aparece un caso que lo necesite.** El "EX con memoria"
   alto de input-keys-and-mouse (2,33) NO es tiempo perdido: es una espera
   activa (`LOAD STATUS / ANDI / BEQ`) hasta que el PC manda una tecla, y
   preguntar mas deprisa solo da mas vueltas. Lo mismo el `wait_swap` del
   video. Un acceso MMIO cuesta unos 5-6 ciclos. Una escritura MMIO NO puede
   simplemente no esperar como las de SDRAM: puede dar error (hueco del mapa,
   registro de solo lectura, el dispositivo la rechaza) y la ISA pide errores
   precisos, con el PC en la instruccion culpable. Solo se podria si el error
   se decidiera por la direccion al aceptar, o con un error pegajoso impreciso
   (cambio de ISA). Ningun caso medido hace MMIO util en cantidad.
   Lo que si se puede recortar es la latencia, hoy ~7 ciclos por acceso:
   la etapa 1 de `mmio_decoder` (decodificacion registrada) se puso en la 30
   para cerrar 80 MHz y a 25-50 MHz sobra. Con un parametro (y `EXTRA_CYCLES`
   del `mmio_mux` a juego) seria un ciclo menos. La etapa 2 no se puede quitar:
   el error de SWAP y el byte del puerto serie solo valen despues de escribir.
8. **Subir el reloj de la CPU a 40-50 MHz, aplazado.** A 25 MHz sobra margen
   (cierra a 52-57) para los saltos y el adelantamiento, que alargan el camino
   critico; se sube al final. PLL y divisor UART 100 -> 200.
   A 50 hay que barrer semillas y, si no cumplen, quedarse en 40. Medir antes y despues contra la 35 (`bench-all -p 35 -p 38`;
   la 35 va a 80 MHz y necesita antes `syn_useioff` para volver a cumplir).
9. **Mas alla de ~50 MHz hay que partir ID**, que es todo el camino critico
   (decodificar -> banco -> comparar -> salto -> enable de IF e ID): pipeline
   clasico IF/ID/EX/MEM/WB con adelantamiento a EX, predecodificar en la cola
   de IF para que las dependencias se detecten desde registros, y la
   redireccion del salto registrada (con prediccion para no pagarlo). Techo
   realista 70-80 MHz, por rutado. Ver `timing-etapas.md`.
10. **Scoreboard: todavia no.** Con el pipeline en orden y cada instruccion en
    una posicion fija, comparar las fuentes de ID con `ex_rd`/`wb_rd` ya es un
    scoreboard de dos entradas, y el adelantamiento usa esas mismas
    comparaciones. Hara falta cuando algo termine fuera de su posicion: una DIV
    que corra de fondo mientras siguen entrando instrucciones independientes
    (hoy para EX ~35 ciclos; medir antes si pesa), o LOADs que no bloqueen EX mientras falla la
    D-cache (y entonces tambien reglas para que los errores sigan siendo
    precisos).
11. **Instruction buffer y fabric de la 35-37**: la 38 tiene ya su propia
    version de `instruction_buffer.v` (protocolo partido y EBR). Si se quiere
    llevar a los otros prototipos, hay que cambiar tambien su CPU.

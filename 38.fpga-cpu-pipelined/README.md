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
- **Invalidacion por epoca** en las dos caches: cada etiqueta guarda la epoca
  en que se escribio e invalidar todo es sumar uno (en el flanco de `reset` o de
  la CPU parandose). Sin bits de valido, cada cache cuesta unas 330-390 LUT en
  vez de unas 2.000-2.300.
- **Contadores de rendimiento** (CPU PERFORMANCE, `1.isa/mmio.md` §13.2): las
  ranuras 8-11 reparten cada ciclo sin emitir en un motivo (`CPI = 1 + EX con
  memoria + dependencia + salto + ID vacio + otros`) y las 12-13 cuentan
  aciertos y fallos de la cache de datos. `run_tests.py --measure` los saca en
  tablas.
- **SDRAM**: los registros de los pines van en las celdas de IO tambien con
  Yosys (`syn_useioff` en `sdram_controller_128.v`); la ventana de fase buena
  paso de 8 a unas 20-22 posiciones. La fase sale en el bitstream
  (`SDRAM_PHASE` en `top.v`, una por herramienta) y se mide con
  `tools/phase-sweep`.

Bancos: `tools/test -p 38` (entre ellos `cpu_perf_tb`, que mide CPI sin placa,
`dcache_tb` e `instruction_buffer_reset_tb`, con mutantes comprobados). En placa,
los 49 casos de C pasan.

## Rendimiento medido en placa

CPI de algunos casos de `run_tests.py --measure`; cada columna añade un cambio.

| Caso | Busqueda 1/ciclo | STORE sin esperar | I-cache 256 B | + D-cache 8 KB | I-cache 8 KB EBR |
|---|---:|---:|---:|---:|---:|
| video-bounce | 4,43 | 3,85 | 3,85 | 3,85 | 3,85 |
| program-bresenham-lines-core | 7,93 | 7,81 | 2,64 | 2,64 | 2,48 |
| program-bresenham-circles-core | 7,79 | 7,49 | 2,65 | 2,65 | 2,57 |
| shared-calls-call-return | — | 10,86 | 8,32 | 8,14 | 8,41 |
| program-memory-copy | 6,68 | 6,05 | 6,07 | 5,00 | 5,02 |
| program-array-sum | 6,03 | 5,88 | 5,79 | 4,85 | 4,79 |
| subword-loads | 16,54 | 15,54 | 15,77 | 6,85 | 7,08 |

La I-cache en EBR descubre un fallo un ciclo mas tarde que la de biestables
(acepta, lee la EBR y compara al ciclo siguiente), asi que en los casos cortos,
que son casi todo fallos de primer acceso, sube 0,2-0,5 de CPI. Lo que gana es
espacio (8 KB en vez de 256 B por ~740 LUT menos); estos casos no tienen codigo
que lo aproveche.

Lo que dicen los contadores:

- **Video** no hace ni un LOAD a SDRAM: su "EX con memoria" (1,40) son STORE al
  framebuffer y accesos MMIO, que ninguna cache acelera.
- **Bresenham** (2,64) pierde sobre todo en saltos (1,03 por instruccion: unos
  3 ciclos por salto tomado) y dependencias (0,34).
- **Los fallos de cache que quedan son de primer acceso.** Los casos son muy
  cortos (10-5.000 instrucciones) y caben enteros en 8 KB: agrandar las caches
  no mejoraria ninguno. La cache de datos acierta un 57-60 % en memory-copy y
  array-sum porque cada linea nueva falla la primera vez.

## Pasos siguientes

En orden de lo que mas promete segun las medidas:

1. **Subir el reloj de la CPU a 40-50 MHz** (PLL; divisor UART 100 -> 200).
   Cierra a 52-57 MHz, asi que 50 deja poco margen: barrer semillas y, si no
   cumplen, 40. Medir antes y despues contra la 35 (`bench-all -p 35 -p 38`;
   la 35 va a 80 MHz y necesita antes `syn_useioff` para volver a cumplir).
2. **Saltos mas baratos** (hoy 3 burbujas por salto tomado):
   - B) Respuesta directa a ID cuando la cola esta vacia, sin pasar por ella
     (2 burbujas). Barato y fuera del camino critico; se mide con
     `cpu_perf_tb`.
   - A) Pedir el destino en el mismo ciclo en que ID decide (1 burbuja con B).
     Alarga el camino critico (decodificar → banco → comparar → salto) hasta la
     I-cache: hacerlo con el informe de tiempos delante.
   - Despues, prediccion (saltos hacia atras tomados, o una BTB).
3. **Adelantamiento EX/WB → ID**, para las dependencias (0,34 en bresenham).
   Toca el mismo camino critico que 2A.
4. **Por que un acierto de la D-cache cuesta 2-3 ciclos**: subword-loads
   acierta 9 de 10 LOAD y aun le quedan 3,46 ciclos de "EX con memoria" por
   instruccion. Mirarlo en `cpu_perf_tb`.
5. **Menos fallos de primer acceso**: traer la linea siguiente por adelantado
   (prefetch) en las dos caches, o lineas de 32 bytes.
6. **Un programa grande para medir tamaños**: una demo en C con biblioteca o un
   juego que pase de 8 KB de codigo o datos. Con `IMEM_MISSES` y `DMEM_MISSES`
   se ve directamente si 16 KB o dos vias servirian; con los casos actuales no.
7. **Reloj de la SDRAM por la celda de IO** (`ODDRX1F` con `D0=1, D1=0`, como
   el DVI). Hoy `assign sdram_clk = clk` va por rutado general y la ventana de
   fase aun se mueve entre builds (2-21 en uno, 8-29 en otro). Tambien `dq_oe`,
   replicado por pin, para que quepa en las celdas de IO.
8. **Video y MMIO**: lo que frena las demos de video son los STORE al
   framebuffer que vacian el bufer de combinacion y la espera de MMIO.
9. **Mas alla de ~50 MHz hay que partir ID**, que es todo el camino critico
   (decodificar -> banco -> comparar -> salto -> enable de IF e ID): pipeline
   clasico IF/ID/EX/MEM/WB con adelantamiento a EX, predecodificar en la cola
   de IF para que las dependencias se detecten desde registros, y la
   redireccion del salto registrada (con prediccion para no pagarlo). Techo
   realista 70-80 MHz, por rutado. Ver `timing-etapas.md`.
10. **MUL y DIV no estan implementadas**: hoy dan `ERROR_INVALID_OPCODE` en ID
    (por eso el caso `multiply` sale `n/a`). MUL con los bloques DSP en dos
    etapas, DIV iterativa y bloqueante; nunca en el camino de un ciclo.
11. **Instruction buffer y fabric de la 35-37**: la 38 tiene ya su propia
    version de `instruction_buffer.v` (protocolo partido y EBR). Si se quiere
    llevar a los otros prototipos, hay que cambiar tambien su CPU.

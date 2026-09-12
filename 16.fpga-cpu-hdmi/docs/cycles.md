# Ciclos por instrucción

Igual que en `6.fpga-cpu`, pero aquí la memoria ya no es una EBR interna: es la SDRAM
externa de 16 bits a través de `sdram_controller.v` + `sdram_system_adapter.v`. Y sí,
va bastante peor.

La parte común: **27 ciclos**.

| Estado        | Ciclos | Qué hace                                                 |
|---------------|--------|----------------------------------------------------------|
| FETCH_REQUEST | 1      | Pone imem_address <= pc, levanta imem_valid              |
| FETCH_WAIT    | 23     | Espera imem_ready                                        |
| DECODE        | 1      | Registra operand_a/operand_b desde el banco de registros |
| EXECUTE       | 1      | Despacha según opcode                                    |
| (específico)  | 0..n   | Estados específicos de cada instrucción                  |
| RETIRE        | 1      | Marca instruction_retired, vuelve a fetch                |

*Base = 27 ciclos.* Los 23 de FETCH_WAIT son la jerarquía de memoria completa: la palabra
de 32 bits se parte en **dos accesos SDRAM de 16 bits** (`sdram_system_adapter.v:133-141`
y `:208-215`), y cada lectura cuesta 9 ciclos en el controlador a 120 MHz
(IDLE→ACTIVE 1, tRCD 3, READ 1, CL 2+1, CAPTURE 1, más 1 de muestreo de `done`). Los
otros 5 son la secuencia IDLE / WAIT_FIRST / START_NEXT / WAIT_SECOND / RELEASE del
adaptador.

## Tabla por instrucción

| Instrucción               | Opcode         | Estados extra                   | Total     |
|---------------------------|----------------|---------------------------------|-----------|
| NOP, HALT                 | 00, 3f         | —                               | 27        |
| MOVI MOVHI GETTID         | 10, 17, 30     | —                               | 27        |
| ADD SUB AND OR XOR        | 01,02,04,05,06 | ALU_WRITE                       | 28        |
| ADDI ANDI ORI XORI        | 11,12,13,14    | ALU_WRITE                       | 28        |
| BRA                       | 2f             | BRANCH_COMMIT                   | 28        |
| SHL SHR SAR               | 07,08,09       | SHIFT_STEP ×n + SHIFT_WRITE     | 28 + n    |
| BEQ BNE BLT BGE BLTU BGEU | 20–25          | BRANCH_COMPARE + BRANCH_COMMIT  | 29        |
| STORE                     | 16             | MEMORY_WAIT (21)                | 48        |
| LOAD                      | 15             | MEMORY_WAIT (23)                | 50        |
| MUL, MULFX, DIV           | 0a, 03, 0c     | **no implementados** → HALTED   | 26 y para |
| TRAP, opcode inválido     | 3e             | va directo a HALTED, sin RETIRE | 26 y para |

Medido en simulación (cpu + sdram_system_adapter + un modelo de SDRAM con la latencia
exacta del controlador). n en los shifts es `operand_b[4:0]`, de 0 a 31 → SHL va de 28 a
59 ciclos.

STORE cuesta 2 ciclos menos que LOAD porque la escritura SDRAM termina en tWR (2) en vez
de esperar CL (2) + el ciclo de captura: 8 ciclos por acceso en vez de 9.

### MUL / DIV: aquí no existen

Tenías razón. `cpu.v:58,65,66` definen `OPCODE_MULFX`, `OPCODE_MUL` y `OPCODE_DIV`, y el
validador de encoding de `cpu.v:151-153` los acepta como R-type bien formados — pero el
`case` de STATE_EXECUTE no tiene rama para ellos, así que caen en el `default` de
`cpu.v:501` y paran la CPU con `ERROR_INVALID_OPCODE` (0x01). Verificado: 26 ciclos y
halt con code=01. No hay multiplicador ni divisor iterativo que complique nada.

### Refresco

Falta un detalle que no existía en la versión con EBR: cada `REFRESH_PERIOD_CYCLES` =
120 MHz / 128 kHz ≈ **937 ciclos**, el controlador se va a ST_REFRESH y consume 9 ciclos
(1 + 1 + tRFC 7). Además `req_ready` se baja durante los últimos `MAX_ACCESS_CYCLES` = 15
ciclos del periodo (`sdram_controller.v:75-76`), así que una petición que llegue en esa
ventana espera hasta 15 ciclos extra. En total, entre un 1% y un 2,5% de sobrecoste medio
sobre los números de la tabla.

## Comparación con 6.fpga-cpu

|                           | 6.fpga-cpu (EBR) | 10.fpga-cpu-ram (SDRAM) |
|---------------------------|------------------|-------------------------|
| Base                      | 9                | 27                      |
| ADD                       | 9                | 28                      |
| LOAD                      | 14               | 50                      |
| MIPS (instrucción simple) | ~11 @ 100 MHz    | ~4,4 @ 120 MHz          |

**3 veces más lento por instrucción**, y eso subiendo el reloj de 100 a 120 MHz. LOAD es
lo peor: 3,5×. A 120 MHz una ADD tarda 233 ns.

De dónde viene el destrozo, midiendo con un modelo de memoria de latencia cero para
aislarlo:

| Fuente                         | Ciclos base |
|--------------------------------|-------------|
| 6.fpga-cpu, EBR                | 9           |
| 10, memoria ideal (latencia 0) | 13          |
| 10, SDRAM real                 | 27          |

Es decir: **+4 ciclos** por el troceo 32→16 bits y el handshake del adaptador, y **+14**
por la latencia física de la SDRAM (2 × 7 ciclos). El coste no está en la CPU — está en
que cada fetch son dos transacciones cerradas de página con tRCD y CAS completos.

## Qué haría falta para arreglarlo

Por orden de impacto, y todo ataca al mismo sitio (los 23 ciclos de FETCH_WAIT):

1. **Ancho de ráfaga 2 en vez de BL1.** Las dos mitades de la instrucción son palabras
   consecutivas de la misma fila: con BL2 se paga ACTIVE + tRCD + CAS una sola vez.
   Ahorraría del orden de 8 ciclos por fetch de golpe. Es el cambio más rentable con
   diferencia.
2. **No cerrar la página.** El controlador usa auto-precharge en todos los accesos
   (`sdram_controller.v:103`). Con política de página abierta, los fetches secuenciales
   (que son casi todos) se saltarían ACTIVE + tRCD: otros 4 ciclos.
3. **Una caché de instrucciones**, aunque sea de una línea. El código secuencial haría
   que el 2 y el 3 se amorticen entre varias instrucciones.
4. Solapar fetch con retire — pero eso ya es pipelining de verdad, como decía la nota
   de 6.fpga-cpu.

Optimizar instrucciones concretas aquí no tiene ningún sentido: el 85% del tiempo de una
ADD es esperar a la SDRAM.

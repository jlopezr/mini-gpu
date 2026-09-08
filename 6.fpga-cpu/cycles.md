# Ciclos por instrucción

La parte común: 9 ciclos. Toda instrucción recorre la misma secuencia:

| Estado        | Ciclos | Qué hace                                                 |
|---------------|--------|----------------------------------------------------------|
| FETCH_REQUEST | 1      | Pone imem_address <= pc, levanta imem_valid              |
| FETCH_WAIT    | 5      | Espera imem_ready                                        |
| DECODE        | 1      | Registra operand_a/operand_b desde el banco de registros |
| EXECUTE       | 1      | Despacha según opcode                                    |
| (específico)  | 0..n   | Estados específicos de cada instrucción                  |
| RETIRE        | 1      | Marca instruction_retired, vuelve a fetch                |

*Base = 9 ciclos.* Los 5 de FETCH_WAIT son la latencia real de tu jerarquía de memoria: 1 ciclo para que memory_map acepte la petición, 1 para que la EBR registre la lectura, 1 para el registro de respuesta cross-bank (memory_map.v:137-145), 1 para imem_ready_r, 1 para que la CPU lo vea.

## Tabla por instrucción

| Instrucción                   | Opcode            | Estados extra                    | Total    |
|-------------------------------|-------------------|----------------------------------|----------|
| NOP, HALT                     | 00, 3f            | —                                | 9        |
| ADD SUB AND OR XOR            | 01,02,04,05,06    | —                                | 9        |
| MOVI ADDI ANDI ORI XORI MOVHI | 10,11,12,13,14,17 | —                                | 9        |
| GETTID                        | 30                | —                                | 9        |
| BRA                           | 2f                | BRANCH_COMMIT                    | 10       |
| SHL SHR SAR                   | 07,08,09          | SHIFT_STEP ×n + SHIFT_WRITE      | 10 + n   |
| BEQ BNE BLT BGE BLTU BGEU     | 20–25             | BRANCH_COMPARE + BRANCH_COMMIT   | 11       |
| MUL                           | 0a                | MUL_PRODUCTS/CROSS/COMBINE/WRITE | 13       |
| MULFX                         | 03                | igual que MUL                    | 13 !     |
| LOAD STORE                    | 15,16             | MEMORY_WAIT (5)                  | 14       |
| DIV                           | 0c                | DIV_STEP ×32 + MUL_WRITE         | 42 !     |
| TRAP, opcode inválido         | 3e                | va directo a HALTED, sin RETIRE  | 8 y para |

n en los shifts es operand_b[4:0], de 0 a 31 — así que SHL va de 10 a 41 ciclos. Es el desplazador iterativo de 1 bit de cpu.v:634-643, elegido para evitar un barrel shifter en el datapath de 120 MHz.

Las marcadas con `!` son las dos que he derivado de la FSM, no medidas, porque el testbench no las ejecuta. Y ahí hay un detalle que te interesa: la tabla de valores esperados de cpu_memory_map_tb.v:66-77 manda MULFX (0x03) y DIV (0x0c) a la rama else, que espera 9 ciclos. Si algún día añades un programa de test que use DIV a través de memory_map, ese $fatal saltará con "expected 9, got 42" y no será un bug de la CPU, sino de la tabla del testbench.

## Lo que esto significa para el rendimiento
De los 9 ciclos base, 5 son esperar a la memoria de instrucciones. Es decir, el 56% del tiempo de una ADD es fetch. A 100 MHz una instrucción simple tarda 90 ns → unos 11 MIPS.

Si en algún momento quieres subir el rendimiento, el orden de impacto es claro: acortar la latencia de fetch (quitar el registro de respuesta cross-bank ahorraría 1 ciclo de los 9, un 11%) rinde mucho más que optimizar cualquier instrucción concreta. Y solapar fetch con retire sería lo grande, pero eso ya es pipelining de verdad.
# Ciclos por instrucción

La versión 18 corre a **80 MHz** y usa un búfer de instrucciones de cuatro
líneas de 16 bytes, un bus SDRAM BL8 de 128 bits y combinación de escrituras.
El coste de una instrucción depende de si su búsqueda acierta en el búfer y de
las esperas de datos. Un ciclo son **12,5 ns**.

Esta tabla sustituye a la heredada del camino BL1 de la versión 10: los valores
27/28/48/50 ciclos y la afirmación de que MUL y DIV no estaban implementados
ya no describen esta versión.

## Tabla por instrucción

Se cuenta desde `STATE_FETCH_REQUEST` hasta `STATE_RETIRE`, ambos incluidos.
Los valores siguientes son el caso de **acierto en el búfer de instrucciones**,
sin una transacción anterior pendiente. Se deducen de
[`cpu.v`](../cpu.v) y [`instruction_buffer.v`](../instruction_buffer.v).
Coinciden con los valores que comprueba [`cpu_tb.v`](../cpu_tb.v) usando su
modelo de memoria de instrucciones de un ciclo; ese banco no mide los fallos
BL8 ni fija la latencia de LOAD/STORE.

| Instrucción                             | Ciclos con acierto de instrucciones | Estados específicos                       |
|-----------------------------------------|------------------------------------:|-------------------------------------------|
| NOP, HALT                               |                                   6 | Ninguno                                   |
| MOVI, MOVHI, GETTID                     |                                   6 | Ninguno                                   |
| ADD, SUB, AND, OR, XOR                  |                                   7 | ALU_WRITE                                 |
| ADDI, ANDI, ORI, XORI                   |                                   7 | ALU_WRITE                                 |
| BRA                                     |                                   7 | BRANCH_COMMIT                             |
| JAL, JALR, JR                           |                                   7 | BRANCH_COMMIT                             |
| BEQ, BNE, BLT, BGE, BLTU, BGEU          |                                   8 | BRANCH_COMPARE + BRANCH_COMMIT            |
| SHL, SHR, SAR                           |                               7 + n | SHIFT_STEP × n + SHIFT_WRITE              |
| MUL, MULFX                              |                                  11 | PRODUCTS + CROSS + COMBINE + SIGN + WRITE |
| DIV                                     |                                  40 | DIV_STEP × 32 + SIGN + WRITE              |
| STORE, aceptado en el búfer sin vaciado |                                   8 | MEMORY_WAIT × 2                           |
| STORE que requiere vaciado              |                               6 + W | MEMORY_WAIT × W                           |
| LOAD                                    |                               6 + W | MEMORY_WAIT × W                           |

`n = operand_b[4:0]`, entre 0 y 31: los desplazamientos cuestan entre 7 y
38 ciclos. DIV supone divisor distinto de cero. TRAP y las instrucciones
inválidas paran sin retirarse; no son una instrucción completada para el CPI.

La base de seis ciclos es FETCH_REQUEST (1), FETCH_WAIT (2), DECODE (1),
EXECUTE (1) y RETIRE (1). Los dos ciclos de FETCH_WAIT incluyen la respuesta
registrada del búfer y su consumo por la CPU.

`W` es el número de ciclos que la CPU permanece en MEMORY_WAIT hasta consumir
la respuesta. En una escritura aceptada sin vaciado vale 2, aunque el adaptador
la acepte en un solo ciclo. Las escrituras MMIO tienen su propio handshake y
pueden requerir primero un vaciado; no usan la fila de STORE de ocho ciclos.

## Qué añade la memoria

Un **fallo de instrucciones** añade a cualquier fila el tiempo extra respecto
al acierto: solicitud al árbitro, lectura de una ráfaga de 16 bytes y entrega
desde el búfer. La latencia depende de la competencia con vídeo y otros
clientes, del refresco y del estado del controlador. No hay un único CPI fijo
por opcode para el sistema completo.

En datos, [`cpu_dmem_adapter.v`](../cpu_dmem_adapter.v) permite:

- Aceptar STORE en una línea nueva o combinarlo en la misma línea sin esperar
  a SDRAM. La respuesta confirma su aceptación en el búfer, no su escritura
  física en SDRAM.
- Volcar la línea anterior antes de aceptar un STORE en otra línea.
- Leer mediante una ráfaga. Si LOAD apunta a la línea pendiente, primero la
  vuelca; las lecturas a otras líneas no fuerzan ese vaciado.
- Vaciar antes de cualquier MMIO y al parar la CPU. El monitor espera a que
  termine el vaciado antes de acceder a SDRAM.

## Mejora frente a la 16

Comparación documentada en **simulación** para el bucle de dibujo de cuatro
instrucciones por palabra (`STORE`, dos `ADDI` y `BLT`):

| Camino de memoria                            | Ciclos por palabra | CPI aproximado (ciclos/palabra ÷ 4) |
|----------------------------------------------|-------------------:|------------------------------------:|
| Versión 16                                   |              145,9 |                                36,5 |
| Versión 18, BL8 antes de combinar escrituras |               49,7 |                                12,4 |
| Versión 18, BL8 y combinación de escrituras  |           **35,2** |                             **8,8** |

Son **4,15× menos ciclos** y **3,32× de mejora en tiempo**, contando la bajada
de 100 a 80 MHz. No es una aceleración universal: depende del programa.
El detalle está en [combinación de escrituras](combinacion-escrituras.md) y
el banco de integración es [`cpu_burst_system_tb.v`](../cpu_burst_system_tb.v).
Estas cifras no deben mezclarse con las medidas antiguas en placa de las demos,
que corresponden a otras condiciones de ejecución.

## Contadores de rendimiento

La 18 añade dos contadores en [`top.v`](../top.v), accesibles desde el monitor,
para medir el CPI de programas completos con las esperas de memoria incluidas.
Las medidas en placa de abajo son las registradas en el proyecto; esta
actualización documental no supone una nueva ejecución en hardware.

`instruction_retired` salía de la CPU desde la 6 y no iba a ninguna parte. Ahora
alimenta `cpu_instructions`; junto a `cpu_cycles` da el CPI real, esperas de
memoria incluidas, que es justo lo que este documento estimaba a mano.

| Registro           | Qué cuenta                      |
|--------------------|---------------------------------|
| `cpu_cycles`       | Ciclos con la CPU no parada     |
| `cpu_instructions` | Pulsos de `instruction_retired` |

Dos decisiones que importan al leer los números:

- **Se ponen a cero al arrancar la CPU**, no al resetearla. Así `run` / `halt` /
  `run` da tres medidas independientes en vez de una suma que crece sin sentido.
- **Saturan en vez de dar la vuelta.** Un contador que ha dado la vuelta miente
  en silencio, y a 80 MHz son 53 segundos de programa.

Son dos comandos del monitor y no uno (`0x36` ciclos, `0x37` instrucciones)
porque el búfer de respuesta tiene 7 bytes y los dos contadores juntos necesitan
9. Se leen con la CPU ya parada, así que ninguno se mueve entre una lectura y la
otra.

```bash
python monitor.py perf --port COM3   # cycles=... instructions=... CPI=...
```

### Medido en placa

Nueve programas de `x.tests`, con el vídeo corriendo:

| Programa                 | Instr. | CPI   |
|--------------------------|-------:|------:|
| `program-fibonacci`      |     77 |  8,82 |
| `program-shift-multiply` |     28 |  9,64 |
| `multiply`               |      4 | 12,50 |
| `program-array-sum`      |     34 | 12,56 |
| `program-memory-copy`    |     44 | 13,27 |
| `logic-immediates`       |     10 | 13,40 |
| `unsigned-branches`      |     11 | 14,55 |
| `smoke`                  |     12 | 15,25 |
| `shift-amount`           |     15 | 19,80 |

El rango es lo interesante, y no la media. Los 8,8 de `fibonacci` son un bucle
que cabe en el búfer de instrucciones: se paga el fallo una vez y se amortiza
en 77 instrucciones. Los 15 a 20 de los programas cortos son casi todo fallos
de búfer, porque no hay bucle donde amortizarlos: con doce instrucciones
seguidas, cada línea nueva se paga entera.

El búfer reduce la espera de búsqueda cuando hay acierto. Los bucles pequeños
amortizan los fallos iniciales y aprovechan mejor esa reducción; por eso conviene
comparar los mismos programas entre versiones, además del coste por opcode.

### Los casos de las extensiones, medidos igual

Los siete de [`cases/extensions`](../../x.tests/cases/extensions), en la
misma placa y con el vídeo corriendo:

| Programa                      | Instr. | CPI   |
|-------------------------------|-------:|------:|
| `calls-jump-table`            |     12 | 12,00 |
| `calls-link-and-return`       |     13 | 16,15 |
| `calls-unaligned-target`      |      4 | 21,00 |
| `subword-stores`              |     11 | 12,73 |
| `subword-misaligned-halfword` |      2 | 19,50 |
| `subword-loads`               |     13 | 43,31 |

(`calls-reserved-fields` para en la primera instrucción sin retirarla, así que
no tiene CPI.)

Dos cosas que merece la pena leer aquí:

- **Las llamadas no son caras.** `calls-jump-table` sale a 12,00 con tres
  `JALR` y tres `JR` entre doce instrucciones, o sea por debajo de la media de
  los programas cortos. Es lo esperable: siete ciclos, los mismos que `BRA`.
  Lo que encarece `calls-unaligned-target` hasta 21,00 no son los saltos sino
  que son cuatro instrucciones en total, y el fallo de búfer inicial no se
  amortiza en nada.
- **`subword-loads` a 43,31 es el precio de la memoria, no del opcode.** Son
  diez cargas seguidas sin bucle: cada una espera su respuesta de la SDRAM
  compitiendo con el barrido de vídeo, y no hay nada donde amortizar. Es el
  mismo `6 + W` de un `LOAD` de palabra; la extensión del byte leído no cuesta
  ciclos, se hace dentro de la CPU. `subword-stores`, que no espera respuesta
  porque el búfer de escritura las acepta, se queda en 12,73.

El contador de instrucciones se contrasta con el del simulador en la tabla de
`--measure`: coinciden exactamente en los nueve. Ese contraste ya encontró un
fallo —ver el README—, así que no es decorativo.

Para comparar versiones enteras, [`x.tests`](../../x.tests/README.md)
tiene `--measure`, que ejecuta cada caso en cada versión aplicable y saca la
tabla en Markdown.

# Validación del modelo 25

Resultados obtenidos el 16-09-2026, Python de `.venv`, sin RTL segmentado.
Parámetros por defecto: 8 warps × 8 lanes, MUL=4, DIV=32, shift iterativo,
LSU FIFO con 8 slots, 17 ciclos por transacción, buffer directo de 16 líneas
de 16 bytes y penalización de fallo de 17 ciclos. Memoria de 2 MiB en las
comparaciones de programas; el tamaño no altera sus latencias.

## Pruebas ejecutadas

- Suite propia: 28 tests; 27 pasan al activar Plasma completo. La prueba de los
  dos Mandelbrot a tamaño completo queda omitida explícitamente. La pasada
  normal omite también Plasma completo y tarda aproximadamente 1,5 segundos.
- 32 casos cortos originales de `x.tests/cases-gpu` se ejecutan dentro del test
  de conformidad, conservando sus expectativas de registros, memoria, errores,
  PC, máscaras y número de instrucciones.
- Datapath: 1.280 combinaciones deterministas de opcode/operandos frente a
  MiniCPU, más límites de signed, wrap, resto, división por cero y encoding.
- Pruebas temporales de ausencia de commit anticipado, una instrucción por warp,
  backpressure, latencias multiciclo, LSU llena/FIFO, fetch con conflictos,
  liberación de barrera durante división y retención de respuesta tras colisión.
- Infraestructura existente: 9 tests de integración del runner GPU y 26 de
  capabilities pasan; el runner CLI también pasa los tres casos de memoria con
  `--backend gpusim --version cycle`.
- CLI ejecutada con salida JSON y traza JSONL limitada sobre `simt_demo.asm`.

## Programas completos y reducidos

Cada fila compara **todo** el estado arquitectónico final con el funcional GPU:
memoria, registros de cada lane, PC, máscaras, pilas, generaciones de barrera,
estado y contadores por warp. El test exige igualdad y ausencia de error.

| Programa | Instrucciones de warp | Ciclos | CPI | X ocupada | Conflictos RF (ciclos) |
|---|---:|---:|---:|---:|---:|
| Plasma, frame completo original | 151.880 | 218.132 | 1,4362 | 97,35% | 0 |
| Mandelbrot 16×8, máximo 16 iteraciones | 816 | 3.173 | 3,8885 | 83,96% | 0 |
| Load/store, 32 iteraciones por hilo | 1.336 | 17.545 | 13,1325 | 4,74% | 0 |
| Mixto: 4 warps de loads, 4 de ALU | 3.508 | 5.508 | 1,5701 | 61,07% | 498 |

Plasma produce 9.600 transacciones LSU, como la referencia de 23/24. Su binario
ensamblado tiene SHA-256
`bfd00be6df0b57273e6b05c88001ebd21779be2a0e222bcadb671d6f3a3d68aa`.
Los informes reproducibles guardan también hashes de memoria y configuración.

Los 498 ciclos de conflicto de la carga mixta corresponden a **125 respuestas
nuevas** que llegan con el puerto ocupado, de 128 loads. Varias esperan más de
un ciclo. `response_arrival_collisions` distingue estos 125 sucesos de los
498 ciclos de solapamiento sostenido de `writeback_collisions`.
El conflicto consume un 9,04% de los ciclos de esta carga. No implica que al
añadir otro puerto se gane ese porcentaje: hace falta simular esa alternativa.

Plasma solo escribe memoria: **cero conflictos allí no demuestra que los loads
no vayan a colisionar**. La carga mixta y la regresión dirigida de un load con
una ALU ejercitan exactamente ese camino. Esta última modifica la memoria
después de llegar la respuesta retenida y comprueba que RF recibe el dato
capturado originalmente, no una segunda lectura posterior.

## Por qué no coincide el CPI de las propuestas anteriores

23/24 modelaban el protocolo de las lanes antiguas. Aquí X simple dura un ciclo,
sin HALTED/DECODE/RETIRE dentro de cada lane; branches tampoco pagan dos estados
adicionales. El tiempo de X en Plasma es 212.352 ciclos: 65.312 de MUL,
23.056 de shifts multiciclo y el resto de operaciones simples. Constituye una
cota inferior real del tiempo total de este recurso no segmentado.

Los 218.132 ciclos observados dejan 5.780 ciclos con X vacía, frente al coste de
702.472 ciclos X de la tabla histórica de lanes completas. No se han ajustado
latencias para obtener ningún CPI publicado. Además, este modelo no introduce
scanout ni competencia fetch/LSU por el fabric, y completa vectores LSU en FIFO:
no es comparable directamente con el tiempo de una placa mostrando vídeo.

El buffer ve 15 misses para este binario concreto; otros perfiles documentan
17 sobre variantes con MMIO y diferente código. Cada miss se cuenta al iniciar
un fetch real, no se fija a la cifra de un perfil anterior.

## Reproducir

```powershell
$env:MINIGPU_FULL_PLASMA='1'
$env:MINIGPU_REPORT_DIR='25.gpu-sim-cycle-uarch/reports'
.\tools\test.ps1 --prototype 25 --quick
```

`reports/` queda fuera de Git según la política existente del repositorio.
Para los Mandelbrot originales completos, establecer también
`MINIGPU_FULL_CONFORMANCE=1`; esos dos casos no se han ejecutado durante esta
validación. Tampoco se han ejecutado síntesis FPGA ni tests de un RTL futuro.

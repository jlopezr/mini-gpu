# Inventario de recursos de la 37: dónde vive cada estructura

Medido el 9 de octubre de 2026 sobre `37.fpga-cpu-gpu-mk2` (RTL del commit
`ffcbb2a`), con `yosys` (`synth_ecp5 -nowidelut`, sin aplanar) módulo a módulo.
El objetivo es saber dónde está cada estructura de estado (flip-flops, RAM
distribuida o EBR), cuánto ocupa y qué conviene mover para bajar la congestión
de rutado.

## Cómo leer la tabla

- **Lógico**: lo que el RTL declara. **Bits**: ese tamaño en número.
- **FF, LUT4, DPR16X4, EBR, MULT**: celdas que saca `yosys`. Un `DPR16X4` es una
  RAM distribuida de 16 × 4 = 64 bits, hecha con las LUT de un slice en modo RAM
  (lectura asíncrona, escritura síncrona). Una EBR (`DP16KD`) son 18 Kib,
  lectura síncrona, bloque dedicado. `yosys` no cuenta los `DPR16X4` dentro de
  los `LUT4`, pero ocupan slices.
- **Conex. (est.)**: arcos que tendría que rutar `nextpnr` para esa parte.
  Fórmula: 3 × (LUT4 + FF) + 6 × CCU2C + 12 × DPR16X4 + 60 × EBR + 40 × MULT.
  El 3 se ajustó con el diseño completo (249.297 arcos para 54.434 LUT y 25.027
  FF). Cuenta entradas por celda; no mide distancia ni abanico. Orden de
  magnitud, ±30 %.
- Las filas marcadas *(parte del SM)* están dentro de la fila "SM completo" y no
  suman aparte.

## Tabla

| Elemento                                           | Dónde           | Lógico                                                                                                                                                                                                       | Bits                               | FF     | LUT4                  | DPR16X4     | EBR              | MULT | Conex. (est.) | Mejora                                                                                                                  |
|----------------------------------------------------|-----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------|--------|-----------------------|-------------|------------------|------|---------------|-------------------------------------------------------------------------------------------------------------------------|
| **CPU: banco de registros**                        | FF + LUT        | 32×32 (31 útiles)                                                                                                                                                                                            | 1.024                              | 1.061  | **2.589**             | –           | –                | –    | ~11.000       | **Alta**: RAM distribuida (sin reset-all, R0 aparte)                                                                    |
| CPU: contadores de rendimiento                     | FF + LUT        | 8×32 + desbordes                                                                                                                                                                                             | 256                                | 330    | 508 (+133 CCU2C)      | –           | –                | –    | ~3.300        | Baja                                                                                                                    |
| CPU: núcleo                                        | FF + LUT        | –                                                                                                                                                                                                            | –                                  | 980    | 1.758                 | –           | –                | 4    | ~8.400        | Ninguna                                                                                                                 |
| **GPU: registros por carril** (×8)                 | EBR             | 8 warps × 32 × 32 por carril                                                                                                                                                                                 | 65.536                             | 600    | 696                   | –           | 16 (22 % de uso) | –    | ~4.900        | Baja (dos puertos de lectura duplican la EBR)                                                                           |
| **GPU: pila SIMT** (una por warp) *(parte del SM)* | RAM distribuida | 8 warps × 8 niveles                                                                                                                                                                                          | 7.424                              | –      | –                     | 116 (100 %) | –                | –    | ~1.400        | Baja (<1 % del chip); en EBR añade un ciclo de lectura                                                                  |
| GPU: cabecera de pila `*_top` *(parte del SM)*     | FF              | 8 × 116                                                                                                                                                                                                      | 928                                | 928    | –                     | –           | –                | –    | ~2.800        | Ninguna (esconde la latencia de la pila)                                                                                |
| **GPU: estado por warp** *(parte del SM)*          | FF + mux 8:1    | `pc`, `groups`, `logical_id`, `warp_arg`, `warp_retired_count`, `active`, `live`, `load_rd`, `sp`, `pp`                                                                                                      | ~2.080                             | ~2.080 | (en los mux del SM)   | –           | –                | –    | ~6.200        | **Media**: `logical_id` y `warp_arg` (512 bits) a RAM distribuida                                                       |
| **GPU: descriptores** (hito 2) *(parte del SM)*    | FF + mux        | `desc_pc` 256, `desc_groups` 256, `desc_active` 64                                                                                                                                                           | 576                                | 576    | (en los mux del SM)   | –           | –                | –    | ~1.700        | Media: RAM y lanzamiento secuencial en 8 ciclos (cambia el contrato de `launch_all`)                                    |
| **GPU: SM completo**                               | FF + LUT + DPR  | lo anterior + pipeline                                                                                                                                                                                       | –                                  | 4.720  | 11.679 (+248 CCU2C)   | 116         | –                | –    | ~50.700       | ver filas anteriores                                                                                                    |
| **GPU: carriles completos** (×8)                   | FF + LUT        | estado de trabajo + lógica                                                                                                                                                                                   | ~6.960 (cota)                      | 6.968  | 11.664 (+2.456 CCU2C) | –           | –                | 32   | ~72.000       | **Alta (por revisar)**: registros de multiplicador y divisor                                                            |
| GPU: LSU (`gpu_lsu2`)                              | DPR + FF + LUT  | `addresses` y `values` (8 × 256), respuesta por carril `words` (8 carriles × 8 × 32), `pending`, `errors`, `stores`, `sizes`, `signeds` y el registro de grupo (`grp_wdata`, `rsp_line` de 128, `grp_addr`…) | ~6.700 (6.160 en DPR + ~540 en FF) | 774    | 4.277                 | 193 (50 %)  | –                | –    | ~17.500       | Media: los DPR están al 50 % (arrays de 8 posiciones en RAM de 16). Mayor punto de convergencia (1.220 bits de puertos) |
| CPU: buffer de instrucciones                       | DPR + FF + LUT  | `line_data` 4 líneas × 128, `line_tag` 4 × 26, `line_valid` 4 y la FSM de relleno                                                                                                                            | ~650 (512 en DPR + ~140 en FF)     | 533    | 699 (+32 CCU2C)       | 32 (25 %)   | –                | –    | ~4.300        | Subir a 16 líneas llena los mismos DPR; aumenta etiquetas y comparadores                                                |
| GPU: buffer de instrucciones                       | DPR + FF + LUT  | `line_data` 16 líneas × 128, `line_tag` 16 × 24, `line_valid` 16 y la FSM de relleno                                                                                                                          | 2.048 en DPR + 400 de tags/valid   | no aislado | no aislado           | 32 (100 %)  | –                | –    | no aislado    | Ninguna por capacidad: la RAM de datos ya está llena                                                                    |
| GPU: contadores de rendimiento                     | FF + LUT        | 5+ de 32 bits                                                                                                                                                                                                | ≥160                               | 192    | 234 (+96 CCU2C)       | –           | –                | –    | ~1.850        | Baja                                                                                                                    |

Total de la GPU en la 37: 29.596 LUT4 (27.906 en la 36, +1.690). Total del
diseño: 54.434 LUT4 (65 %) y 25.027 FF (29 %).

## Qué es un descriptor

Cada warp tiene tres campos de arranque, separados del estado con el que corre:
`desc_pc` (32 bits, primera instrucción), `desc_groups` (32 bits, grupos de
carriles iniciales) y `desc_active` (8 bits, carriles que participan). En el
lanzamiento (`RUN` o `WARP_START`) el SM copia el descriptor al estado de
ejecución (`pc`, `groups`, `active`, `live`) y pone a cero contadores, `sp`, `pp`,
barreras y `generation` (`gpu_sm.v`, bloque `if (launch && !error)`). Escribir un
descriptor no hace vivo al warp, y escribir uno de un warp vivo da error. Con
`launch_all`, el SM lanza todos los warps cuyo `desc_active` no es cero, y por
eso necesita leer los 8 descriptores a la vez: de ahí que sean registros.

## Por qué la pila SIMT no es compartida

Hay una por warp (ocho): el índice es `warp * profundidad + sp[warp]`
(`gpu_sm.v:228`). Los warps se intercalan por round-robin y cada uno puede estar
a mitad de una divergencia, con entradas vivas entre una instrucción suya y la
siguiente. Compartirla obligaría a salvar y restaurar al cambiar de warp, o a un
reparto dinámico con riesgo de quedarse sin entradas.

## Hallazgos

1. **El banco de registros de la CPU es el mayor derroche de conexiones.** Está
   en flip-flops porque `register_file.v:58` pone a cero los 32 registros en el
   reset, lo que impide inferir RAM. Con tres lecturas asíncronas por
   flip-flops, los multiplexores (2.589 LUT4) cuestan más que los datos. El
   fichero declara ser idéntico byte a byte en todas las carpetas, y los tests
   esperan registros a cero tras el reset: cambiarlo es una decisión de diseño.
2. **Más de la mitad de los FF de cada carril es del multiplicador y el
   divisor** (~326 y ~134 bits por declaración; es una cota alta, `yosys` puede
   haber fusionado alguno). No corren a la vez, así que podrían compartir
   registros.
3. **Los descriptores añaden 576 FF** y su reparto a los 8 warps. Son el 100 %
   del aumento de FF del SM respecto a la 36.
4. **Las EBR de los registros de los carriles están al 22 %**, pero repartirlas
   entre carriles choca en los puertos.
5. **Los DPR del LSU están al 50 %.** Sus arrays (`addresses`, `values`, la
   respuesta por carril) tienen 8 posiciones y un `DPR16X4` tiene 16, así que
   la mitad de cada celda queda sin usar: 6.160 bits lógicos en 193 celdas
   (12.352 bits físicos). Fusionar arrays para llenar las 16 posiciones
   ahorraría hasta ~96 celdas, pero `addresses` y `values` se leen a la vez y
   una celda tiene un solo puerto de lectura: no lo he comprobado.
6. **El buffer de instrucciones de la CPU usa el 25 % de sus DPR; el de la GPU
   ya usa el 100 %.** La CPU instancia 4 líneas de 128 bits en 32 celdas de 16
   posiciones. Con 16 líneas (`LINES=16`) serían las mismas 32 celdas con 4
   veces más caché, a costa de más etiquetas, bits válidos y comparadores. La
   GPU ya está configurada con 16 líneas: sus 2.048 bits de datos llenan las 32
   `DPR16X4`. Es una posible mejora de rendimiento para la CPU, no un ahorro de
   área ni una mejora pendiente de aprovechamiento RAM en la GPU.

   Se probó esa ampliación en la 35 con semilla 10. Comparar 16 etiquetas en
   paralelo creó una ruta de 14,7 ns en `instruction_buffer_i.hit_now` y bajó
   la CPU de 82,74 a 67,94 MHz. Leer solo la etiqueta indexada permitió inferir
   6 `DPR16X4` adicionales para las etiquetas y redujo unas 500 LUT, pero el
   primer routing seguía en 72,94 MHz. Registrar la búsqueda corta el camino a
   costa de un ciclo por *fetch*; una prueba anterior midió alrededor de un 8 %
   menos de rendimiento. Por ello se conservan 4 líneas en CPU: llenar una RAM
   ya asignada no compensa si empeora Fmax o CPI.

## Banco de registros de la CPU: resultado en la 35 y proyección para la 37

Esta sección se refiere **solo al banco escalar de la CPU** instanciado en
`cpu.v`, no a los registros de la GPU. En la 37, `gpu_lane.v` ya no contiene un
banco privado: recibe `register_a` y `register_b` desde el SM. Este instancia
ocho `gpu_register_file`, uno por carril, y cada uno reúne en EBR los registros
de los ocho warps de ese carril (8 warps × 32 registros × 32 bits). Esos bancos
GPU son precisamente los 16 `DP16KD` de la fila «GPU: registros por carril» y
no se ven afectados por el cambio descrito aquí.

La mejora marcada como prioritaria en la primera fila de la tabla ya se aplicó
en `35.fpga-cpu-fifo-sdram2`. No usa EBR: el banco se infiere como **RAM
distribuida** de los PFU, mediante tres copias de 16 `DPR16X4` (48 celdas en
total), necesarias para conservar las dos lecturas combinacionales de la CPU y
la lectura de depuración. Las 10 EBR (`DP16KD`) del diseño de la 35 no cambiaron.

El reset simultáneo de las 32 palabras impedía inferir esa RAM. La versión nueva
lo sustituye por un barrido que escribe cero en una dirección por ciclo y expone
`busy`; la CPU permanece en reset lógico hasta que termina. No cambia el camino
normal del banco: las dos lecturas siguen siendo combinacionales y la escritura
sigue siendo síncrona. Por tanto, las instrucciones conservan los mismos estados
y ciclos por instrucción. El único coste temporal es **32 ciclos adicionales
después de cada reset** (0,4 us a 80 MHz); una orden `RUN` o `STEP` durante ese
intervalo se ignora.

### Resultado medido en la 35

Comparación directa con semilla 17 y las mismas opciones de `nextpnr`:

| Métrica                       | Banco original | RAM distribuida |         Diferencia |
|-------------------------------|---------------:|----------------:|-------------------:|
| LUT4 antes de *packing*       |         18.456 |          16.367 |   -2.089 (-11,3 %) |
| `TRELLIS_FF`                  |         11.607 |          10.589 |    -1.018 (-8,8 %) |
| Arcos a rutar                 |         97.746 |          88.278 |    -9.468 (-9,7 %) |
| Longitud final de cable       |        105.276 |          95.968 |    -9.308 (-8,8 %) |
| Fmax CPU (objetivo 80 MHz)    |      83,21 MHz |       81,67 MHz | -1,54 MHz (-1,9 %) |
| Fmax SDRAM (objetivo 100 MHz) |     107,35 MHz |      114,08 MHz | +6,73 MHz (+6,3 %) |

Dentro del banco, el cambio fue de 1.061 FF y 2.589 LUT4 a 43 FF, 141 LUT4 y
48 `DPR16X4`. La reducción de área y conexiones es inequívoca, pero no produjo
una mejora de Fmax de CPU en esa implantación: la ruta limitante quedó en otra
lógica y el resultado varió ligeramente con la nueva colocación. Tampoco bajó
de forma apreciable el pico local de ocupación (p99 de arcos por tile, 76 a 75),
algo esperable en una 35 que solo ocupaba alrededor del 19 % de las LUT.

### Qué cabe esperar en la 37

La tabla de inventario anterior refleja el RTL base medido (`ffcbb2a`), donde la
CPU de la 37 todavía conservaba el `register_file.v` escalar antiguo. La
transformación se ha portado ahora una sola vez, junto con el bloqueo por
`busy`, y la regresión RTL conserva los ciclos normales de la CPU. No se
multiplica por los ocho carriles ni modifica las 16 EBR de los bancos GPU. A
falta de sintetizar el nuevo RTL, si yosys reproduce la inferencia observada en
la 35, la estimación respecto al inventario base es:

| Recurso del diseño completo |   37 actual | Estimación tras el cambio |                    Ahorro estimado |
|-----------------------------|------------:|--------------------------:|-----------------------------------:|
| LUT4                        |      54.434 |                   ~52.345 |                     ~2.089 (3,8 %) |
| FF                          |      25.027 |                   ~24.009 |                     ~1.018 (4,1 %) |
| `DPR16X4`                   | actual + 48 |               actual + 48 | ocupa 48 celdas de RAM distribuida |
| Arcos de routing            |     249.297 |                  ~239.800 |                     ~9.500 (3,8 %) |

El ahorro absoluto debería ser muy parecido al de la 35 porque el módulo de CPU
de partida es el mismo; no debe multiplicarse por ocho. El porcentaje total es
menor por el tamaño de la 37, pero puede resultar más útil: la 37 está al 65 %
de LUT y su colocación y routing son mucho más exigentes. Quitar unos dos mil
LUT y mil FF del banco escalar elimina además los multiplexores 32:1 de sus tres
lecturas, una fuente de conexiones de alto abanico. Es razonable esperar menos
trabajo de routing y más libertad para el colocador, pero **no se puede prometer
una subida de Fmax**: la experiencia de la 35 muestra que la ruta crítica puede
desplazarse a MMIO, búsqueda de instrucciones u otra parte de la CPU/GPU.

El port de `register_file.v`, la señal `busy`, el bloqueo de la CPU y la espera
del banco de pruebas ya está hecho. Para validar las estimaciones falta comparar
el RTL anterior y el nuevo con las mismas opciones y un barrido de las mismas
semillas. La decisión debería apoyarse en la tasa de semillas que cierran timing
y en congestión/arcos, no solo en el mejor Fmax de una semilla.

## Lo que no está resuelto

- Los multiplexores de lectura de los arrays del SM están dentro de sus 11.679
  LUT4 y no se separan por fila.
- Los carriles incluyen toda su lógica, no solo el estado de trabajo.
- Los bits del LSU y de los buffers de instrucciones salen de sumar las
  declaraciones del RTL (`gpu_lsu2.v`, `instruction_buffer.v`). Las cifras de
  FF y LUT del buffer corresponden a la síntesis aislada con el valor por
  defecto de 4 líneas (la instancia de CPU); la instancia GPU de 16 líneas no
  se midió por separado. Los DPR sí coinciden con lo declarado: 193 en el LSU y
  32 en cada buffer de instrucciones.
- No se midió cuánto ocupa un `DPR16X4` en slices ni el total de EBR del diseño
  completo (el vídeo usa más que las 16 de la GPU).
- Un mapa de calor de arcos por tile de la semilla 3 no resultó interpretable
  (netlist aplanado, sin forma de atribuir calor a módulos).

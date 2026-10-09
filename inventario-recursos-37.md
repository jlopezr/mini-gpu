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

| Elemento | Dónde | Lógico | Bits | FF | LUT4 | DPR16X4 | EBR | MULT | Conex. (est.) | Mejora |
|---|---|---|---|---|---|---|---|---|---|---|
| **CPU: banco de registros** | FF + LUT | 32×32 (31 útiles) | 1.024 | 1.061 | **2.589** | – | – | – | ~11.000 | **Alta**: RAM distribuida (sin reset-all, R0 aparte) |
| CPU: contadores de rendimiento | FF + LUT | 8×32 + desbordes | 256 | 330 | 508 (+133 CCU2C) | – | – | – | ~3.300 | Baja |
| CPU: núcleo | FF + LUT | – | – | 980 | 1.758 | – | – | 4 | ~8.400 | Ninguna |
| **GPU: registros por carril** (×8) | EBR | 8 warps × 32 × 32 por carril | 65.536 | 600 | 696 | – | 16 (22 % de uso) | – | ~4.900 | Baja (dos puertos de lectura duplican la EBR) |
| **GPU: pila SIMT** (una por warp) *(parte del SM)* | RAM distribuida | 8 warps × 8 niveles | 7.424 | – | – | 116 (100 %) | – | – | ~1.400 | Baja (<1 % del chip); en EBR añade un ciclo de lectura |
| GPU: cabecera de pila `*_top` *(parte del SM)* | FF | 8 × 116 | 928 | 928 | – | – | – | – | ~2.800 | Ninguna (esconde la latencia de la pila) |
| **GPU: estado por warp** *(parte del SM)* | FF + mux 8:1 | `pc`, `groups`, `logical_id`, `warp_arg`, `warp_retired_count`, `active`, `live`, `load_rd`, `sp`, `pp` | ~2.080 | ~2.080 | (en los mux del SM) | – | – | – | ~6.200 | **Media**: `logical_id` y `warp_arg` (512 bits) a RAM distribuida |
| **GPU: descriptores** (hito 2) *(parte del SM)* | FF + mux | `desc_pc` 256, `desc_groups` 256, `desc_active` 64 | 576 | 576 | (en los mux del SM) | – | – | – | ~1.700 | Media: RAM y lanzamiento secuencial en 8 ciclos (cambia el contrato de `launch_all`) |
| **GPU: SM completo** | FF + LUT + DPR | lo anterior + pipeline | – | 4.720 | 11.679 (+248 CCU2C) | 116 | – | – | ~50.700 | ver filas anteriores |
| **GPU: carriles completos** (×8) | FF + LUT | estado de trabajo + lógica | ~6.960 (cota) | 6.968 | 11.664 (+2.456 CCU2C) | – | – | 32 | ~72.000 | **Alta (por revisar)**: registros de multiplicador y divisor |
| GPU: LSU (`gpu_lsu2`) | DPR + FF + LUT | `addresses` y `values` (8 × 256), respuesta por carril `words` (8 carriles × 8 × 32), `pending`, `errors`, `stores`, `sizes`, `signeds` y el registro de grupo (`grp_wdata`, `rsp_line` de 128, `grp_addr`…) | ~6.700 (6.160 en DPR + ~540 en FF) | 774 | 4.277 | 193 (50 %) | – | – | ~17.500 | Media: los DPR están al 50 % (arrays de 8 posiciones en RAM de 16). Mayor punto de convergencia (1.220 bits de puertos) |
| GPU: buffer de instrucciones | DPR + FF + LUT | `line_data` 4 líneas × 128, `line_tag` 4 × 26, `line_valid` 4 y la FSM de relleno | ~650 (512 en DPR + ~140 en FF) | 533 | 699 (+32 CCU2C) | 32 (25 %) | – | – | ~4.300 | Baja en área; con 16 líneas ocuparía los mismos DPR (más caché gratis, tags en FF) |
| GPU: contadores de rendimiento | FF + LUT | 5+ de 32 bits | ≥160 | 192 | 234 (+96 CCU2C) | – | – | – | ~1.850 | Baja |

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
6. **El buffer de instrucciones usa el 25 % de sus DPR.** 4 líneas de 128 bits
   caben en 32 celdas de 16 posiciones. Con 16 líneas (`LINES=16`) serían las
   mismas 32 celdas con 4 veces más caché, a costa de más etiquetas en FF
   (26 bits por línea) y de que el índice crezca. Es una mejora de
   rendimiento más que de área.

## Lo que no está resuelto

- Los multiplexores de lectura de los arrays del SM están dentro de sus 11.679
  LUT4 y no se separan por fila.
- Los carriles incluyen toda su lógica, no solo el estado de trabajo.
- Los bits del LSU y del buffer de instrucciones salen de sumar las
  declaraciones del RTL (`gpu_lsu2.v`, `instruction_buffer.v`), y los de
  los registros escalares (la FSM, contadores internos) son aproximados. Los
  DPR sí coinciden con lo declarado (193 y 32 celdas).
- No se midió cuánto ocupa un `DPR16X4` en slices ni el total de EBR del diseño
  completo (el vídeo usa más que las 16 de la GPU).
- Un mapa de calor de arcos por tile de la semilla 3 no resultó interpretable
  (netlist aplanado, sin forma de atribuir calor a módulos).

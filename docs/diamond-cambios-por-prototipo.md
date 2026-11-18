# Qué hubo que cambiar en cada prototipo para compilar con Diamond

Vista por **conceptos**, no por líneas. Cada columna es una clase de cambio; cada fila, un prototipo.
Estado a 10 de noviembre de 2026. Las lecciones y la explicación de cada concepto están en
`reset-y-diamond-lecciones.md` (reset, `rx_overrun`, respuesta fantasma) y en las notas de Synplify.

Leyenda: **✔** aplicado · **·** no aplica o no hizo falta.

## Tabla

| Proto | PLL (tiene y está arreglada) | Reset registrado | RAM de 2 escrituras | CDC bloqueados (`diamond-constraints.txt`) | `rx_overrun` con reset en la expresión | Respuesta huérfana    | Reset blando a las lanes | Etapa SDRAM y fase | Tabla de PAR | Placa con Diamond    |
|-------|------------------------------|------------------|---------------------|--------------------------------------------|----------------------------------------|-----------------------|--------------------------|--------------------|--------------|----------------------|
| 3     | sin PLL                      | ·                | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | sin prueba           |
| 4     | ✔                            | ·                | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | sin prueba           |
| 5     | ✔                            | ·                | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | sin prueba           |
| 6     | ✔                            | ·                | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | 13/13                |
| 7     | sin PLL                      | ·                | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | sin prueba           |
| 8     | sin PLL                      | ·                | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | sin prueba           |
| 9     | ✔                            | ya lo era        | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | sin prueba (sin CPU) |
| 10    | ✔                            | ya lo era        | ·                   | ·                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | 19/19                |
| 12    | sin PLL                      | ✔                | ✔                   | ·                                          | ·                                      | ·                     | ✔ (vía `core_reset`)     | ·                  | defecto      | 63/63                |
| 13    | ✔                            | ·                | ·                   | ✔                                          | ·                                      | ·                     | ·                        | ·                  | 8            | sin prueba (sin CPU) |
| 14    | sin PLL                      | ✔                | ·                   | ·                                          | ·                                      | ·                     | ✔ (vía `core_reset`)     | ·                  | defecto      | 66/66                |
| 16    | ✔                            | ya lo era        | ·                   | ✔                                          | ·                                      | ·                     | ·                        | ·                  | defecto      | 30/30                |
| 17    | sin PLL                      | ✔                | ·                   | ·                                          | ·                                      | ·                     | ✔ (vía `core_reset`)     | ·                  | defecto      | 66/66                |
| 18    | ✔                            | heredado de 16   | ·                   | ✔                                          | ·                                      | defensiva             | ·                        | ·                  | 3            | 30/30                |
| 19    | ✔                            | heredado de 16   | ·                   | ✔                                          | ✔                                      | defensiva             | ·                        | ·                  | 3            | 45/45                |
| 21    | ✔                            | heredado de 16   | ·                   | ✔                                          | ✔                                      | defensiva             | ·                        | ·                  | 3            | 71/71                |
| 22    | ✔ (solo vídeo)               | ✔                | ·                   | ✔                                          | ·                                      | ·                     | ✔ (vía `core_reset`)     | ·                  | defecto      | 70/70                |
| 30    | ✔                            | ya lo era        | ·                   | ✔                                          | ✔                                      | defensiva             | ·                        | ·                  | defecto      | 72/72                |
| 34    | ✔                            | ya lo era        | ·                   | ✔                                          | ✔                                      | sin arreglo           | ·                        | no portado         | 3            | falla en placa (0/72)|
| 35    | ✔                            | por dominio      | ·                   | ✔                                          | ✔                                      | descarte en el bridge | ·                        | ✔                  | 3            | 72/72                |
| 36    | ✔                            | por dominio      | ·                   | ✔                                          | ✔                                      | descarte en el bridge | ✔ (vía `core_reset`)     | ✔                  | defecto      | 79/79                |
| 37    | ✔                            | por dominio      | ·                   | ✔                                          | ✔                                      | descarte en el bridge | ✔ (`soft_reset`)         | ✔                  | defecto      | 97/97                |
| 38    | ✔                            | por dominio      | ·                   | ✔                                          | ✔                                      | descarte en el bridge | ·                        | ✔                  | 5            | 49/49                |

Los prototipos de simulación (0, 1, 2, 11, 15, 20, 23–25, 28, 31, 32, 39, 40) no se sintetizan y no están.

En "Reset blando a las lanes", **·** significa que el prototipo no tiene GPU.

## Los conceptos

1. **PLL.** Se ha comprobado en el código que todas las instancias de `EHXPLLL` (4, 5, 6, 9, 10, 13, 16, 18,
   19, 21, 22, 29, 30, 33–38) llevan ya `CPHASE = DIV-1` y los atributos de frecuencia, así que no queda ninguna
   sin arreglar. Los prototipos sin PLL (3, 7, 8, 12, 14, 17, 26, 27) van a 25 MHz nativos y no lo necesitan.
   Las PLL generadas con `ecppll` ponen `CLKOP_CPHASE = DIV/2` y Diamond aborta en Map. Se usa `DIV-1`, que vale
   también para apio. Además se le dan a Diamond las frecuencias de la PLL con
   `(* FREQUENCY_PIN_CLKI/CLKOP/CLKOS *)`, y los `localparam` van antes de los atributos o se desprenden.
2. **Reset registrado.** Un reset combinacional (`!(&power_on)`) dejaba la placa mala con Diamond aunque la
   simulación y el netlist fueran bien. Ahora es un registro de desplazamiento (`reset_shift`) o, en 35–38,
   un `reset_sync` por dominio de reloj.
3. **RAM de dos escrituras.** Synplify no la infiere como bloque, la deja en registros y no termina. Solo
   afectaba a `12.fpga-gpu/gpu_bram.v`, que usa `ifdef DIAMOND` y 8 DP16KD de 4 bits por banco.
4. **CDC bloqueados.** Diamond trata como síncronos los relojes de PLL distintas y suma el desfase como
   skew, así que da errores en cruces que no existen en el chip. Se bloquean con `BLOCK PATH` solo tras
   comprobar en el RTL que el cruce es seguro (toggle con 2 FF, o dato acompañando a un toggle). `clk → clk`
   nunca se bloquea, porque es lo que limita a la CPU.
5. **`rx_overrun`.** Con `if (reset) … else` Synplify mandaba el reset al LSR y el flop arrancaba a 1. El reset
   va dentro de la expresión del dato: `x <= !reset && (x || set) && !clear`.
6. **Respuesta huérfana.** Con Diamond, una respuesta llega a quien no la espera y la fábrica se queda en `RESP`.
   En 18, 19, 21 y 30 el adaptador acepta cualquier respuesta fuera de `ST_ISSUE`
   (`rsp_ready = state != ST_ISSUE`), una solución defensiva: la causa raíz sigue sin aclarar. En 35–38 el bridge
   cuenta peticiones y respuestas y tira la que llega con la cuenta a cero. La 22 tiene el mismo patrón en
   `gpu_lsu2` y no se ha tocado porque pasa 70/70. La 34 falla por otra causa. Detalle en
   `reset-y-diamond-lecciones.md`, secciones 4.1, 4.5 y 4.6.
7. **Reset blando a las lanes.** Es un fallo **lógico**, no de Diamond: `GPU_CONTROL.RESET` tiene que llegar a las
   lanes. Si no llega, un error de lane (división por cero) sobrevive al reset y el kernel siguiente falla con
   error 4 aunque no tenga nada malo. Todos los prototipos con GPU lo tienen (12, 14, 17, 22, 36 y 37): en casi
   todos `gpu_system` calcula `core_reset = reset || gpu_reset` y se lo pasa como reset a `gpu_sm`. La 37 es la
   excepción: `gpu_sm` recibe una entrada `soft_reset` propia, porque allí `RESET` conserva los descriptores, y
   ahí fue donde se detectó el fallo. Los prototipos sin GPU no lo necesitan. La caché de instrucciones también
   se invalida en reset en 35–38.
8. **Etapa SDRAM y fase.** Un registro extra antes de los pines de la SDRAM (en `sdram_controller_128.v`) y
   `pll_phase_ctl.v`, con la fase que hay que aplicar tras programar. Está en 35–38. La 34 no lo tiene: su
   controlador tiene 728 líneas frente a las 871 de 35 y 38. La fase buena **depende de la herramienta** (10 con
   Diamond, 2 con Yosys en la 38), así que 35 y 38 la eligen en síntesis con `ifdef DIAMOND` (`SDRAM_PHASE` en
   `top.v`) y el bitstream sale ya con ella.
9. **Tabla de PAR.** La misma síntesis cierra o no según la tabla de coste de PAR
   (`--strategy par_place_iterator_start_pt=K`). Un cambio mínimo de RTL puede mover el resultado por 0,1 MHz.

## Cambios que valen para todos (en `tools/`, no en el prototipo)

- El runner define la macro `DIAMOND` y pasa las macros separadas por espacio (con `;` ignora la segunda).
- `diamond-constraints.txt` se anexa al `.lpf` si existe. Cuenta como fuente a efectos de STALE.
- Los errores de ancho mínimo de pulso se muestran como aviso, no como fallo (caso 13).
- El monitor es un solo fichero para todos los prototipos, con el contador de bloques registrado.

## Pendiente y dudas

- **34:** con `diamond-constraints.txt` y la tabla 3 cierra timing (`clk_mem` 100,38 MHz), pero en la placa
  falla los 72 casos: la lectura de memoria que sigue a una escritura deja sin respuesta al monitor. No hay
  constancia de que haya pasado nunca la suite en la placa. El arreglo defensivo del adaptador (el de 18, 19, 21
  y 30) no lo resuelve, y se deshizo. La 34 usa la arquitectura antigua de SDRAM (`sdram_clk = clk`, captura en
  el flanco de bajada, sin etapa previa ni control de fase) y nunca recibió el port de 35–38. Arreglarla
  significa portar esa arquitectura (unos 15 ficheros), que es lo que ya es la 35 sin GPU.
- **Causa raíz de la respuesta huérfana** en 18/19/21/30: sigue abierta.
- **`apio build` falla** desde el 8 de noviembre dentro de yosys, también en el 6 (pequeño). Los últimos
  builds correctos de apio de cada prototipo son anteriores y se ven en `build-list --prototypes`.

# Propuesta: abaratar el lanzamiento de kernels en la GPU de la 36

Origen: medidas sobre la placa con el renderizador 2D de MiniGL (prototipo 36, 80 MHz) y lectura del RTL.

## 1. Qué se ha medido

| Medida | Ciclos de CPU |
|---|---:|
| Lectura MMIO de la GPU | 38 |
| Escritura MMIO de la GPU | 29 |
| Lectura MMIO de contadores de la CPU | 14 |
| Lectura de SDRAM | 60 |
| Escritura de SDRAM | 38 |
| Lanzamiento vacío, `gpu_launch` estándar | 3 087 |
| Lanzamiento vacío, `gpu_run_fast` (software) | 1 760 |

Relleno de n palabras alineadas a 16 B (40 repeticiones, `gpu_run_fast`):

| Palabras | CPU | GPU 1 warp | GPU 2 warps | Mejor GPU vs CPU |
|---:|---:|---:|---:|---:|
| 32 | 1 242 | 3 743 | 3 896 | 0,33x |
| 64 | 2 437 | 4 851 | 4 723 | 0,52x |
| 128 | 4 826 | 7 156 | 6 307 | 0,77x |
| 256 | 9 605 | 11 657 | 9 469 | 1,01x |
| 512 | 19 162 | 20 779 | 15 793 | 1,21x |
| 1 024 | 38 277 | 39 017 | 28 312 | 1,35x |
| 2 048 | 76 506 | 75 502 | 53 607 | 1,43x |

Lectura de los datos:

* El punto de equilibrio está en ~256 palabras (~512 píxeles).
* Con 64 palabras, 4 851 ciclos frente a 1 760 del lanzamiento vacío: el kernel mismo cuesta ~3 000 ciclos de CPU. La sección 5 lo explica: es ejecución a 25 MHz, no arranque en frío.
* El rendimiento asintótico es de ~26 ciclos de CPU por palabra en la GPU frente a ~37 en la CPU: 1,4x–1,8x como mucho.

## 2. Palancas de hardware, de más a menos valor

### 2.1 Escritura de la GPU a memoria (techo del speed-up)

Un grupo de 8 lanes escribe 2 líneas de 16 B y cuesta ~200 ciclos, mucho más de lo que necesitaría una ráfaga de SDRAM. La LSU espera la respuesta de cada grupo.

* Escrituras sin esperar la respuesta (posted), o
* fusionar líneas consecutivas de instrucciones distintas en una sola ráfaga.

Es lo único que sube el techo de 1,4x–1,8x. Ninguna mejora del lanzamiento lo toca. No está verificado en el RTL de `gpu_lsu2.v`.

### 2.2 Coste de cada acceso MMIO (~29 ciclos por escritura)

`gpu_mmio_bridge.v` cruza de reloj con peticiones por cambio de nivel y dos biestables en cada sentido. Solo admite un acceso en vuelo y la CPU espera la confirmación `done` de cada uno. Esos 29 ciclos son sobre todo cruce de reloj y espera, no trabajo.

Opciones:

* **Escrituras posted en el puente:** la CPU continúa tras entregar la escritura y solo se bloquea si el siguiente acceso MMIO llega con el anterior en vuelo. Entre dos `STORE` consecutivos la CPU gasta ~7 ciclos por instrucción, así que casi toda la latencia se esconde. Coste: los errores de una escritura (`h_error`) dejarían de llegar al `STORE` que los causó y habría que llevarlos a un registro de estado pegajoso.
* **Cola pequeña (FIFO de 4–8 entradas) de escrituras** en el dominio de la CPU.
* **Escritura de difusión a todos los warps:** una escritura con máscara en vez de 5 por warp.
* **Descriptor en memoria con timbre:** la CPU escribe un bloque en SDRAM y un único registro con su dirección. La GPU lo lee con una transacción de línea (2 escrituras MMIO en vez de ~26).
* **Lectura bloqueante de fin:** un registro que no contesta hasta que la GPU termina. Quita los ~38 ciclos por sondeo.

### 2.3 Arranque en frío del kernel

Medido en la sección 5: no es arranque en frío sino ejecución a 25 MHz, y el buffer de instrucciones se vacía en cada lanzamiento (`gpu_imem_buffer.v`: "se vacía mientras `halted` está alto"), así que cada kernel empieza con todos sus fallos.

## 3. Registros de descriptor persistentes (lectura de `gpu_sm.v` y `gpu_system.v`)

Qué conserva la GPU entre lanzamientos (sin `GPU_RESET`, que lo borra todo):

| Registro | ¿Persiste tras acabar el warp? | Por qué |
|---|---|---|
| `LOGICAL_ID[w]` | Sí | Solo se pone a 0 en el reset (`gpu_sm.v:475`) |
| `WARP_ARG[w]` | Sí | Idem |
| `GROUP[w]` | Sí | Solo reset y escritura (`gpu_sm.v:474`, `:498`) |
| `PC[w]` | No | `EXIT` hace `pc <= d_sequential_pc` (`:595`) |
| `ACTIVE[w]` / `live[w]` | No | `EXIT` pone `active <= 0` y limpia `live` (`:593-594`) |

Consecuencias:

* Con una configuración estable (mismos `GROUP`, `LOGICAL_ID` y bloque de argumentos), cada lanzamiento solo necesita reescribir **`PC` y `ACTIVE` por warp** y dar `RUN`: 2 escrituras por warp en vez de 5.
* Escribir `ACTIVE` ya reinicia contadores y pilas SIMT del warp (`:503-504`), así que no hace falta nada más.
* `WARP_ARG` apunta al bloque de argumentos, que vive en RAM: si su dirección no cambia, los argumentos nuevos se escriben en RAM (barato), no por MMIO.
* Con 1 warp: de ~8 escrituras MMIO a 3 (PC, ACTIVE, RUN). Con 2 warps: de ~13 a 5. A ~29 ciclos cada una, esto baja ~150–230 ciclos del lanzamiento. Es útil, pero no cambia la conclusión: el grueso está en el kernel (~3 000) y no en las escrituras de descriptor.
* Si el RTL guardara una copia del descriptor (el "hito 2" que menciona `gpu_system.v`) y `WARP_START` lo recargara, bastaría un registro con la máscara de warps: 1 escritura por lanzamiento. Hoy `WARP_START` da error.

Es una mejora solo de software: no hay que tocar el RTL ni resintetizar.

## 4. Orden propuesto

1. ~~Medir con `IMEM_MISSES`/`LSU_TX` dónde se van los ciclos del kernel~~ (hecho, sección 5).
2. Variante de `gpu_run_fast` que reutiliza `GROUP`, `LOGICAL_ID` y `WARP_ARG` y solo escribe `PC`+`ACTIVE`+`RUN`, y medir la ganancia.
3. Mirar si la GPU cierra temporización a más de 25 MHz (`clock2_gen.v`, informes de nextpnr). Es la palanca más grande (sección 5).
4. Leer `gpu_lsu2.v` para ver si las escrituras ya se pueden emitir sin esperar.
5. Si compensa, RTL: escrituras posted en `gpu_mmio_bridge.v` y/o LSU con escrituras sin respuesta.

## 5. Medida de dónde se van los ciclos (`glaunch5.c`, placa 36, `gpu_run_fast`)

Contadores de GPU PERFORMANCE alrededor de lanzamientos. "CPU" son ciclos de CPU (80 MHz) por lanzamiento completo; "CYCLES" son ciclos de la GPU mientras corre, en `gclk` (25 MHz). Las columnas de abajo van por lanzamiento.

| Escenario | CPU | CYCLES GPU | Instr. retiradas | Aciertos ibuf | Fallos ibuf | Transacciones LSU |
|---|---:|---:|---:|---:|---:|---:|
| fill 64, 1 warp, 1.º lanzamiento | 5 095 | 1 149 | 51 | 45 | 6 | 22 |
| fill 64, 1 warp, 2.º lanzamiento | 5 084 | 1 149 | 51 | 45 | 6 | 22 |
| fill 64, 1 warp, media de 20 | 4 956 | 1 149 | 51 | 45 | 6 | 22 |
| kernel vacío, 1.º | 2 043 | 180 | 6 | 3 | 3 | 4 |
| kernel vacío, 2.º | 2 048 | 180 | 6 | 3 | 3 | 4 |
| kernel vacío, media de 20 | 1 906 | 180 | 6 | 3 | 3 | 4 |
| fill 8, 1 warp, media | 3 000 | 526 | 23 | 17 | 6 | 8 |
| fill 64, 2 warps, media | 4 941 | 1 044 | 70 | 64 | 6 | 28 |
| fill 256, 1 warp, media | 11 875 | 3 287 | 147 | 141 | 6 | 70 |

(Una ejecución, sin errores; las diferencias entre filas de 1 y 20 repeticiones son del bucle de medida de la CPU.)

### Lo que sale

1. **La GPU va a 25 MHz y la CPU a 80** (`gpu_system_tb.v`, `gpu_mmio_bridge_tb.v`). Un ciclo de GPU son 3,2 de CPU. Se comprueba con los datos: de fill 8 a fill 64 la CPU suma 1 956 ciclos y la GPU 623 (razón 3,1); de 64 a 256, 6 919 frente a 2 138 (3,2).
2. **Casi todo el tiempo de un fill es ejecución en la GPU, no lanzamiento.** Fill 64: 1 149 ciclos de GPU = ~3 680 de CPU, el 74 % de los 4 956. Lo demás (~1 300) es lanzamiento y sondeo. Kernel vacío: 180 de GPU = ~580 de CPU, y el resto (~1 330) es el lanzamiento puro.
3. **Corrección de lo dicho antes:** los "~3 000 ciclos de arranque en frío" eran en realidad ejecución del kernel a 25 MHz, y los "26 ciclos por palabra" de la GPU eran de CPU (unos 8 de GPU). No había arranque en frío aparte.
4. **Cada lanzamiento arranca con el buffer de instrucciones vacío.** Los fallos son siempre los mismos en el 1.º, 2.º y media (3 en el vacío, 6 en fill): el buffer se vacía mientras la GPU está parada. Meterlo en la lógica de "no vaciar si el código no ha cambiado" sería una mejora pequeña (6 fallos por lanzamiento).
5. **Un kernel vacío ya hace 4 transacciones de LSU:** las lecturas de los parámetros del bloque de argumentos.
6. **El coste de escribir lo domina la LSU.** De fill 64 a 256, +48 transacciones de LSU y +2 138 ciclos de GPU: ~44 ciclos de GPU (~140 de CPU) por transacción de línea de 16 B. Cada iteración del bucle emite 2 líneas (8 lanes × 4 B) y la LSU espera cada una.

### Consecuencias

(La estimación de "GPU a 80 MHz" de abajo es solo una cota teórica: no se espera que la GPU cierre temporización a esa frecuencia.)

* **El techo de la GPU lo marcan el reloj de 25 MHz y la LSU sin pipeline, no el lanzamiento.** Con la GPU a 80 MHz, el fill de 64 pasaría de ~4 956 a ~2 400 ciclos de CPU, justo igual que la CPU (2 437): el punto de equilibrio bajaría de ~256 a ~64 palabras. Falta ver si la GPU cierra temporización a esa frecuencia.
* **Los registros de descriptor persistentes ahorran ~150–230 ciclos de un lanzamiento de ~1 300 puros** (el resto del lanzamiento es el cruce de reloj y el sondeo). Útil, pero secundario.
* **Escrituras posted en el puente** ayudarían al lanzamiento (~1 300 ciclos) pero no al kernel (el 74 %).

## 6. Descriptores persistentes: `gpu_run_fast2` (`glaunch6.c`, placa 36)

`gpu_run_fast2` (solo en el scratchpad, no en el repo) relanza reescribiendo únicamente `PC` y `ACTIVE` de cada warp y dando `RUN`. Requiere una llamada previa a `gpu_run_fast` con el mismo `nwarps` y el mismo bloque de argumentos, que deja `GROUP`, `LOGICAL_ID` y `WARP_ARG`. Ciclos de CPU por lanzamiento, media de 100:

| Escenario | `gpu_run_fast` | `gpu_run_fast2` | Ahorro |
|---|---:|---:|---:|
| Kernel vacío, 1 warp | 1 692 | 1 377 | 315 (19 %) |
| Fill 64, 1 warp | 4 853 | 4 540 | 313 (6 %) |
| Kernel vacío, 2 warps | 2 169 | 1 726 | 443 (20 %) |
| Fill 64, 2 warps | 4 723 | 4 279 | 444 (9 %) |
| Fill 256, 1 warp | 11 664 | 11 349 | 315 (3 %) |

Sin errores y 0 palabras mal en los rellenos de comprobación. Confirma la lectura del RTL: los descriptores persisten, y el ahorro es de ~315 ciclos por warp-par de escrituras (1 warp) y ~445 (2 warps), algo más de lo estimado (150–230). Aun así no cambia el panorama: el lanzamiento vacío sigue en ~1 400 ciclos (cruce de reloj, `RUN` y sondeo) y el kernel manda.

## 7. Las dos opciones de hardware que quedan (pendientes de evaluar)

Con el lanzamiento casi agotado por software (secciones 5 y 6), solo quedan dos cambios de RTL con ganancia apreciable. Ninguno está medido ni implementado; los números salen de las secciones anteriores.

### 7.1 LSU: escrituras sin esperar la respuesta (`gpu_lsu2.v`)

* **Qué:** que la LSU emita las escrituras sin esperar la respuesta de la memoria (posted), o que fusione líneas consecutivas de instrucciones distintas en una sola ráfaga.
* **Por qué:** de fill 64 a fill 256 hay +48 transacciones y +2 138 ciclos de GPU, unos 44 ciclos de GPU (~140 de CPU) por línea de 16 B. Cada iteración del bucle emite 2 líneas y la LSU espera cada una. Una ráfaga de SDRAM necesitaría una fracción de eso.
* **Qué ganaría:** es lo único que sube el techo de 1,4x–1,8x del relleno y mueve el punto de equilibrio (~256 palabras). Afecta al ~74 % del tiempo de un fill, que es ejecución del kernel.
* **Riesgos a mirar:** el orden de escrituras y lecturas a la misma dirección, que los fallos de una escritura (`rsp_error`) lleguen al warp correcto, y que el fin del kernel (`EXIT`) espere a que las escrituras pendientes hayan salido antes de dar el trabajo por acabado.
* **Coste:** RTL y resíntesis (~10 min), más repetir el barrido de semillas.
* **Primer paso:** leer `gpu_lsu2.v` y ver cuántas escrituras puede tener ya en vuelo.

### 7.2 Puente MMIO: escrituras posted (`gpu_mmio_bridge.v`)

* **Qué:** que la CPU no espere el `done` de una escritura MMIO a la GPU; el puente acepta la escritura, la CPU sigue, y solo se bloquea si el acceso siguiente llega con otro en vuelo (o, mejor, una cola de 4–8 escrituras).
* **Por qué:** cada acceso MMIO cuesta ~29 ciclos (escritura) o ~38 (lectura), y es sobre todo cruce de reloj de 80 a 25 MHz con dos biestables en cada sentido. Entre dos `STORE` consecutivos la CPU ya gasta ~7 ciclos por instrucción, así que la mayor parte de esa espera se escondería.
* **Qué ganaría:** acorta el lanzamiento (~1 400 ciclos, de los que `gpu_run_fast2` ya quitó ~315). No toca el kernel, que es el ~74 % de un fill de 64.
* **Riesgos a mirar:** los errores de una escritura (`h_error`) ya no llegarían al `STORE` que los causó; habría que llevarlos a un registro de estado pegajoso. Las lecturas (STATUS, sondeo) deben quedar ordenadas detrás de las escrituras pendientes. El `RUN` no puede adelantarse a los `STORE` de PC/ACTIVE.
* **Coste:** RTL y resíntesis. Es más pequeño que 7.1, pero el beneficio también.

### Orden recomendado

1. Leer `gpu_lsu2.v` (7.1): si ya admite varias escrituras en vuelo, el cambio puede ser pequeño.
2. Decidir 7.2 solo después, si el lanzamiento sigue pesando.

## 8. Lectura de `gpu_lsu2.v` (opción 7.1)

**Cómo es hoy.** La LSU es una máquina de estados que sirve **un grupo cada vez**: `IDLE -> GROUP -> ISSUE -> WAIT -> RETIRE -> IDLE`. `WAIT` espera `mem_rsp_valid` también en las **escrituras** (`gpu_lsu2.v:305`), aunque su respuesta no lleva datos. El propio fichero dice "sin segmentación todavía" (v2.1). Por eso:

* Una escritura de 16 B ocupa la LSU durante todo el viaje: cola asíncrona de petición (25 a 100 MHz), fabric, SDRAM secuencial, cola asíncrona de respuesta (100 a 25 MHz) y los estados propios.
* Dos warps no se solapan en la LSU. Coincide con la medida: fill 64 con 1 warp = 1 149 ciclos de GPU y con 2 warps = 1 044, casi igual.

**Lo que el resto del sistema ya permite** (`propuesta-fabric6-pipeline.md`): el fabric tiene una cola global de 8 comandos y una de 8 respuestas, y acepta peticiones sin esperar a las anteriores. El controlador SDRAM es secuencial, pero conserva el orden, y una escritura de 16 B debería ocupar al controlador mucho menos que los ~44 ciclos de GPU (~176 ciclos de memoria) que la LSU espera ahora. Por tanto la LSU es hoy el cuello de botella de las escrituras, no la SDRAM. Es una estimación: no he medido la ocupación del controlador.

**Cambio mínimo propuesto (escrituras posted):**

1. En `ISSUE`, si `grp_write` y no es MMIO, al aceptar la petición pasar directamente a un estado de retiro (como `RETIRE`) sin pasar por `WAIT`, y sumar 1 a un contador `st_out` de escrituras sin confirmar.
2. Un lazo aparte consume las respuestas de escritura (`mem_rsp_ready` activo cuando `st_out > 0` y no se espera una carga) y resta 1 a `st_out`.
3. Antes de emitir una carga o un acceso MMIO, esperar a `st_out == 0`. Más simple que contar respuestas descartadas, y los bucles de solo escritura (el caso del relleno) no lo notan.
4. Errores de memoria en una escritura (`mem_rsp_error`): llegarían tarde, cuando la instrucción ya retiró. Lo más simple es una bandera pegajosa que haga fallar a la GPU (los fallos por dirección ya se detectan en `GROUP`, antes de salir, así que esto solo cubriría fallos de la memoria misma).
5. **Fin de kernel:** la GPU no puede declararse terminada mientras `st_out > 0`, o la CPU leería memoria antes de que las escrituras hayan llegado. Hay que sacar un `lsu_idle` de la LSU y combinarlo en `gpu_system.v` con `live_warps`/STATUS, que es lo que sondea `gpu_run_poll`.

**Qué se puede esperar (estimación, sin medir).** La LSU dejaría de gastar ~35–40 ciclos de GPU por línea escrita y pasaría a ~4–5 (estados propios). Entonces el límite pasa a ser la emisión de instrucciones del SM (~4 instrucciones por iteración del bucle de relleno) y el ritmo del controlador SDRAM. Con 2 warps empezarían a solaparse. Es plausible un factor 2x o más en el relleno grande, pero solo la medida lo dirá.

**Riesgos:** el orden entre escrituras y lecturas a la misma dirección (se mantiene mientras el puerto de la LSU sea en orden y las cargas esperen a `st_out == 0`), la bandera de error tardía, y el cambio en la condición de "terminado", que también afecta a `HALT`, `STEP` y al depurador.

**Pasos:** (a) implementar en `gpu_lsu2.v` y `gpu_system.v`; (b) probar en `gpu_system_tb.v` con `ram_port #(.LAT(5))` y escrituras seguidas de carga a la misma dirección; (c) resintetizar con barrido de semillas (el camino crítico de la LSU ya fue una preocupación, ver los comentarios del fichero); (d) medir con `glaunch4.c` y `glaunch5.c`.

## 9. Qué hay en la 37 y la 38, y si lo propuesto se traslada

Revisado el 5 de noviembre de 2026 comparando ficheros y leyendo los README. Nada de esto está probado en placa.

### 37 (`37.fpga-cpu-gpu-mk2`)

| Tema | Estado en la 37 |
|---|---|
| Descriptores persistentes (sección 3) | **Hecho en RTL** (hito 2): el SM guarda `desc_pc`, `desc_active` y `desc_groups` aparte del estado de ejecución, y `RUN`/`WARP_START` los copian a ejecución. `RESET` conserva descriptores, `LOGICAL_WARP_ID` y `WARP_ARG`. Con `WARP_START` un lanzamiento es 1 escritura con la máscara de warps. Mejor que lo que mide `gpu_run_fast2` en la 36, y sin trabajo de software por warp. |
| Escrituras posted en la LSU (7.1) | **No hecho.** `gpu_lsu2.v` sigue con `ISSUE -> WAIT -> RETIRE`, y `mem_rsp_ready = state==WAIT` (línea 234). Lo que sí hay es **fusión de escrituras por bytes**: varias lanes en la misma línea de 16 B van en una sola transacción (2 a 1 con píxeles RGB565, −44 % a −50 % de transacciones de framebuffer en el renderer 2D, según el simulador funcional). Reduce el **número** de esperas, no las elimina. Es complementario a lo posted. |
| Escrituras posted en el puente MMIO (7.2) | **No hecho.** `gpu_mmio_bridge.v` es idéntico al de la 36. El README de la 37 anota como pendiente un tiempo máximo en `mmio_mux`. El adaptador de la CPU ya vacía su buffer de escrituras antes de cualquier acceso MMIO, y eso hay que respetarlo si el puente pasa a posted. |
| Reloj de la GPU | `clk_25mhz` alcanza 35,6 MHz en el último build documentado (8 de octubre), sin la fusión por bytes. No hay camino a 80 MHz, pero hay margen teórico hasta ~30 MHz con un PLL (la GPU hoy usa el oscilador directo). El 2 de noviembre el rutado de la fusión no terminó con la semilla 7: falta semilla. |
| Estado | No probado en placa. La fusión por bytes sin semilla que cierre. |

### 38 (`38.fpga-cpu-pipelined`)

* **No tiene GPU.** Hay `top.v` y `gpu_aux_adapter_128.v`, pero ni `gpu_lsu2.v`, ni `gpu_sm.v`, ni `gpu_system.v`, ni el puente. Es un experimento de CPU segmentada sobre la base de la 35. No hay nada de lo propuesto aquí.
* Su `memory_fabric_fifo_6.v` es distinto del de la 36 y la 37 (que son idénticos entre sí): el árbitro está reescrito con una pasada de prioridad urgente y otra de round-robin, ~190 líneas distintas. El puerto de cada master es el mismo (petición/respuesta con `valid`/`ready`), así que una LSU con escrituras posted debería enchufarse igual, pero habría que comprobar que el fabric de la 38 sigue devolviendo las respuestas en orden por puerto (lo que sí garantiza el de la 36).

### ¿Se traslada la propuesta?

* **LSU posted (7.1):** el cambio vive en `ISSUE`/`WAIT`/`RETIRE` y en la bandera de "terminado". Estos estados son iguales en la 36 y la 37; lo que cambia en la 37 es la formación del grupo (fusión por bytes), que no se toca. Debería aplicarse casi igual en las dos. La condición de fin hay que adaptarla: en la 37 `gpu_system.v` combina la ocupación de la LSU (`lsu_core_occupied`) y otras señales, donde cabe añadir `st_out != 0`.
* **Puente posted (7.2):** el puente es idéntico, así que sirve para ambas. Ojo con el adaptador de la CPU de la 37 y su orden de escrituras.
* **Descriptores (sección 3):** en la 37 ya no hace falta `gpu_run_fast2`; el runtime debería usar `WARP_START`. En la 36 solo queda el truco de software.
* **38:** no aplica hasta que lleve GPU. Si se integra, copiar `gpu_*` de la 37 con los cambios, y vigilar el fabric.
* **Dónde hacerlo:** lo natural es la 37, que ya lleva el hito 2 y la fusión por bytes y todavía no cierra timing con ningún cambio; añadir lo posted ahí obliga a re-barrer semillas una sola vez. Hacerlo en la 36 la dejaría sin servir de referencia que cierra timing.

## 10. Implementación en la 37 (rama `lsu-posted-writes`)

Hecho en `37.fpga-cpu-gpu-mk2` (`gpu_lsu2.v`, `gpu_system.v`, `gpu_lsu2_tb.v`, README): escrituras posted con `MAX_POSTED` (8; 0 = comportamiento anterior), `wr_pending` en `lsu_occupied`, `live_hold` en `gpu_system.v` para que `WARP_DONE`/STATUS esperen a las escrituras y `wr_error` pegajoso. Detalles en el README de la 37.

Verificado en simulación (iverilog): `gpu_lsu2_tb` con casos nuevos (17–21), `gpu_system_tb` (también con latencia 90), `gpu_core_tb`, `gpu_barrier_tb`, `gpu_alu_tb`, `gpu_jump_tb`. Se comprobó que los tests detectan fallos: con `MAX_POSTED=0` falla el caso de liberación del warp (55 ciclos frente a 13), y quitar la espera de las cargas, el tope de la cuenta o `live_hold` hace fallar un banco.

**Pendiente:** síntesis (se prevé pasar a Diamond: ver el timing de `clk_25mhz` y de la LSU, que ya fue un camino crítico) y medida en placa con `glaunch4.c`/`glaunch5.c` para ver cuánto baja el coste por línea. La estimación de 2x o más sigue sin confirmar.

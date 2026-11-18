# Reset en FPGA y flujo Diamond: lecciones del 8 y el 10 de noviembre de 2026

Resumen de lo que se midió y se aprendió al llevar los prototipos 35, 36, 37 y 38 (el 8) y 18, 19, 21, 30 y 34
(el 10) a Lattice Diamond y probarlos en la placa ULX3S. Separa lo **medido en la placa** de lo que es **explicación probable**:
donde no se demostró, lo dice.

## 1. Qué pasó (en una página)

| Síntoma en la placa | Causa | Arreglo |
|---|---|---|
| La CPU ejecutaba corrida 16 B (`pc` final +0x10) con los registros bien | El bridge entregaba una **respuesta fantasma** retenida al arrancar; `instruction_buffer` la tomaba como contestación a su primera petición | `fabric_fifo_bridge` cuenta peticiones y respuestas (`outstanding`) y tira la respuesta que llega con la cuenta a 0 |
| En 18, 19, 21 y 30 el monitor respondía a `status` pero se colgaba en el primer acceso a memoria, y la suite fallaba entera | La fábrica `memory_fabric_4` se quedaba en `RESP` para el puerto 0 sin que el adaptador hubiera pedido nada. **Causa sin aclarar** | El adaptador acepta cualquier respuesta fuera de `ST_ISSUE` (sección 4.5): tolera el síntoma, no lo explica |
| Un kernel de GPU fallaba con error 4 y el siguiente también | El error de una lane (división por cero) **sobrevivía** a `GPU_CONTROL.RESET` | `gpu_sm` pasa `reset \|\| soft_reset` a las lanes; `instruction_buffer` invalida sus líneas en reset |
| `serial_port` arrancaba con `STATUS = 0x14000` (`rx_overrun` = 1) y `serial-empty-input` fallaba | El flop de `rx_overrun` **no se limpiaba con el reset** | El reset va dentro de la lógica de datos del flop (sección 3) |
| 10 casos de C fallaban en la 36 con `GPU_ERR_STATE` | La imagen usaba `WARP_START`, que la 36 (hito 1) no tiene; no era un fallo de hardware | Los casos declaran `requires: gpu_warp_start` |
| `workgroup-barrier-isolation` fallaba solo dentro de la suite | Carrera del propio programa: un `LOAD` de warp son 8 lecturas en olas distintas | Bucle de espera dentro de una región `SSY` |

Los tres primeros son **la misma clase de fallo**: estado interno que no está a su valor de reposo
cuando la lógica empieza a trabajar. Conviene tratarlo como una clase, no como tres incidencias.

Resultado en placa con builds de Diamond (todas con timing cerrado): 35 → 72/72, 36 → 79/79
(10 omitidos por `WARP_START`), 37 → 97/97, 38 → 49/49, 18 → 30/30, 19 → 45/45, 21 → 71/71, 30 → 72/72.
La 34 cierra timing pero falla 72/72 en la placa y no hay constancia de que haya pasado nunca (sección 4.6).

## 2. Cómo debe funcionar el reset en este proyecto

### 2.1 Reloj por reloj, aserción asíncrona y liberación síncrona

Cada dominio de reloj (`clk`, `clk_mem`, `clk_gpu`...) tiene su propio reset, generado por
`reset_sync.v`: se **activa** de inmediato con `arst` y se **libera** tras `STAGES` ciclos limpios de
*ese* reloj (aquí 16).

```verilog
wire arst_cpu = !pll_locked || !btn_pwr_n;     // reset de entrada del dominio
reset_sync #(.STAGES(16)) rs_cpu (.clk(clk), .arst(arst_cpu), .rst(reset_cpu));
```

Reglas que se siguen:

- Un `reset_sync` por dominio. Nunca se cruza un reset de un reloj a otro.
- `arst` incluye `!pll_locked` del reloj correspondiente: mientras la PLL no engancha, el dominio está en reset.
- Varias instancias del mismo `reset_sync` (`rs_cpu`, `rs_bus`, `rs_vid`...) reparten el fanout para ayudar al timing.
- Un reset **blando** (`soft_reset`, `GPU_CONTROL.RESET`) debe llegar a **todo** el estado que el
  reset duro limpia. El caso de las lanes de la GPU es el ejemplo de lo que pasa si no (sección 4).

### 2.2 Cómo escribir un flop con reset y condiciones

Para banderas que se ponen, se borran y se mantienen, usar la forma de **función de siguiente estado**,
con el reset como término de la expresión:

```verilog
// Antes. En Diamond el flop arrancaba a 1 y el reset no lo limpiaba.
always @(posedge clk) begin
  if (reset) begin
    rx_overrun <= 1'b0;
  end else begin
    if (host_push && rx_count == DEPTH) rx_overrun <= 1'b1;
    if (bus_write && selected == REG_STATUS && write_mask[2] && write_data[16])
      rx_overrun <= 1'b0;                       // borrar gana a poner
  end
end

// Después. El reset forma parte del dato.
wire overrun_clear = bus_write && selected == REG_STATUS && write_mask[2] && write_data[16];
wire overrun_set   = host_push && rx_count == DEPTH;
always @(posedge clk)
  rx_overrun <= !reset && (rx_overrun || overrun_set) && !overrun_clear;
```

La semántica es la misma (reset gana a todo; borrar gana a poner; si nada actúa, mantiene). Está en
las carpetas 30 y 34 a 38 (`serial_port.v`) y `serial_port_tb.v` pasa contra todas.

**Cuándo aplicarlo.** Hay muchísimos `if (reset) ... else ...` en el repositorio y casi todos funcionan.
No hay que reescribirlos en masa. Sí conviene la forma de siguiente estado en:

- banderas pegajosas (`*_overrun`, `*_error`, `*_seen`, `*_valid` retenidos) con condiciones de poner y borrar;
- estado que decide si una transacción es válida (retención de respuestas, contadores de peticiones);
- cualquier flop cuyo valor erróneo al arrancar no se nota hasta mucho después.

### 2.3 Comprobar el reset en la placa, no solo en simulación

La simulación no lo habría visto: en simulación el reset funciona. Lo que se hizo y funciona como método:

1. **Leer el estado justo tras programar**, antes de ejecutar nada (`STATUS` del serial, `GPU_STATUS`,
   `phase-status` de los bridges). Un valor distinto del de reposo es un reset que no actúa.
2. **Añadir contadores de diagnóstico temporales** que distingan hipótesis: cuántos ciclos vale 1 con
   `reset` activo, en qué ciclo se ve por primera vez, qué valían `reset`, `host_push` y `bus_write` en ese
   instante. (Las builds instrumentadas se descartan y no se commitean.)
3. **Probar la hipótesis con un cambio mínimo** y medir otra vez, como se hizo con el reset dentro de la
   lógica de datos (`STATUS` pasó de `0x14000` a `0x4000`).
4. Si hace falta, exportar el netlist de después de PAR (`ldbanno -n Verilog -o net.v -w hardware_impl1.ncd`)
   y mirar a qué señales están conectados `LSR` y `CE` del flop.

## 3. Lo que se midió y lo que es explicación probable

**Medido con la 36 en Diamond:**

- El flop `rx_overrun` valía 1 durante 255 ciclos o más con `reset` activo (el contador de diagnóstico
  llegó a su tope) y seguía a 1 al bajar `reset`.
- No hubo pushes (`push_total = 0`, `rx_max = 0`), así que nada lo ponía a 1 después.
- Escribir `0x10000` en `STATUS` lo borraba: el flop se podía borrar por el camino de datos.
- Con el reset dentro de la lógica de datos, `STATUS = 0x4000` tras programar.
- El código es idéntico en la 35, 37, 34 y 30; en la 37 y la 38 funcionaba con la forma antigua. La
  diferencia entre "funciona" y "no funciona" dependía del mapeo concreto de cada build.

**Explicación probable (no demostrada dentro de Synplify):** con `if (reset) ... else ...`, Synplify lleva
`reset` al `LSR` (reset síncrono local) del flop y la condición de actualización al `CE`. En el netlist
posterior a PAR el flop tenía `LSR = reset_bus` y un `CE` que incluye el reset, con el dato de entrada a 1 en
reset cuando no se borra. Si `LSR` no se aplica como el RTL cree, el flop se carga con ese 1. Además el
netlist muestra `GSR("DISABLED")`, así que tampoco hay garantía de un valor inicial por configuración.
La forma de siguiente estado entrega el 0 por el camino normal de datos en cada ciclo de reset y no depende
de ese mapeo.

Una alternativa que **no se ha probado** es dar un valor inicial en la declaración (`reg x = 1'b0;`).

## 4. Detalles de cada hallazgo

### 4.1 Respuesta fantasma en el bridge
`phase-status` mostraba `hold_valid = 1` en los puertos 0 y 1 justo tras programar, con
`aceptadas = 0`. `instruction_buffer` tomaba esa respuesta como contestación a su primera petición y las
líneas llegaban desplazadas una posición: la CPU ejecutaba una línea de ceros (4 NOP). Con el descarte,
`phantom_seen` queda pegajoso para detectar si vuelve a ocurrir. El origen exacto del fantasma sigue sin
conocerse. Es intermitente.

### 4.2 Error de lane que sobrevive al reset blando
`gpu_sm` instanciaba las lanes con `.reset(reset)`. Un error de lane (división por cero) sobrevivía a
`GPU_CONTROL.RESET` y el kernel siguiente fallaba con error 4 en PC 0. Ahora `.reset(reset || soft_reset)`.

Es un fallo **lógico**, no de Diamond, y las demás GPU lo tienen resuelto de otra forma: en 12, 14, 17, 22, 29 y
36 `gpu_system` calcula `core_reset = reset || gpu_reset` y se lo pasa como reset a `gpu_sm` y a las lanes. Solo
la 37 tiene una entrada `soft_reset` propia, porque allí `RESET` conserva los descriptores.

### 4.3 Dos modos de lanzar la GPU

- **Hito 2 (37):** `WARP_START` lanza warps sueltos; `RESET` conserva los descriptores.
- **Hito 1 (36):** no hay `WARP_START`; se lanza con `RUN` y la imagen debe compilarse con `--board`.

Los casos de C compilan sin `--board`, así que usan `WARP_START`. En la 36 el lanzamiento fallaba y
`GPU_RUN` devolvía `GPU_ERR_STATE` (4). **Ojo:** ese 4 es un código del runtime
(`GPU_ERR_STATE`), no `ERROR_DIVISION_BY_ZERO` de la GPU; son numeraciones distintas. Una instrucción
inexistente da `ERROR_INVALID_OPCODE` (1) o `ERROR_INVALID_ENCODING` (5), no un fallo de resultado.
Siguiente paso posible: que el runner use `<caso>_board.bin` cuando el prototipo no tiene `WARP_START`,
para que la 36 también pruebe esos casos.

### 4.4 Carrera de `workgroup-barrier-isolation`
Los ocho carriles de un warp leen la misma dirección (un solo banco) y el LSU sirve un carril por banco y
por ola. Si el `STORE` del otro grupo cae en medio, unos ven 0 y otros 7; el `BEQ` diverge sin región
`SSY` y se produce `ERROR_SIMT`. El simulador no lo ve porque su `LOAD` es atómico. Con `SSY` la
divergencia es legal y el warp reconverge antes de la `BAR`.

### 4.5 Respuesta huérfana en 18, 19, 21 y 30 (fábrica de 4 puertos)

**Síntoma.** Con Diamond, tras programar, el monitor contesta a `status` y a `reset`, pero el primer acceso a
memoria da timeout y ya no responde más. La CPU se queda en `pc = 0` y la suite entera falla. La build de apio
de la 21 del 5 de noviembre sí pasaba, y el mismo RTL con apio compilado a mano (yosys, nextpnr y ecppack) pasó
30/30 en el 18.

**Diagnóstico** (builds con LEDs que capturan señales con el reset dentro de la expresión): `memory_fabric_4` en
`RESP` para el cliente 0 (`cpu_dmem_adapter`), con 0 concesiones desde el reset y el adaptador en `IDLE`. Según el
RTL es imposible, porque la fábrica solo entra en `RESP` tras conceder una petición. Quien debía consumir esa
respuesta (`rsp_ready = state == ST_WAIT`) nunca estaba en `ST_WAIT`: la fábrica se quedaba en `RESP` para
siempre y bloqueaba a los demás clientes, incluido el monitor.

**Hipótesis descartadas** (cada una dejó el mismo estado): inicialización de las FIFO, forma síncrona o asíncrona
del reset de `state`, captura de `active_master`, recodificación one-hot de `state`, `reset_sync` y un desajuste
de reset entre adaptador y fábrica. **Sospechoso sin demostrar:** el aviso de varios drivers de `state_ns` en la
fábrica. La simulación funcional del netlist posterior a PAR (`ldbanno` más `iverilog`) no aclaró nada, porque la
fábrica no se mueve ni en simulación.

**Arreglo defensivo.** En `cpu_dmem_adapter.v` (18, 19, 21 y 30):

```verilog
assign rsp_ready = (state != ST_ISSUE);   // antes: (state == ST_WAIT)
```

Solo en `ST_ISSUE` no se acepta, porque ahí una respuesta de rechazo por dirección ya puede estar válida un ciclo
antes de que el adaptador pase a `ST_WAIT`. En cualquier otro estado la respuesta es huérfana y se descarta, para
que la fábrica no se quede en `RESP`. En la placa con Diamond: 18 → 30/30, 19 → 45/45, 21 → 71/71, 30 → 72/72.

**Qué no resuelve:**

- **La causa raíz.** El arreglo tolera el síntoma y no lo explica. Sigue abierto. Un experimento A/B en el 18
  (sección 4.7) apunta a la promoción del reset a red primaria.
- **La 34.** Falla 72/72 con y sin este arreglo (sección 4.6).
- **La 22.** Usa la misma `memory_fabric_4.v` (mismo hash que el 18) y su `gpu_lsu2.v` tiene el mismo patrón
  (`mem_rsp_ready = state==WAIT && !grp_mmio`), pero pasa 70/70 y no se ha tocado. `gpu_lsu2` tiene seis estados y
  reparte las respuestas entre memoria y MMIO, así que tirar una respuesta allí podría perder datos de un grupo.
  Antes de cambiarlo habría que reproducir el cuelgue con otro build.
- **35 a 38** no usan este adaptador: su protección es la cuenta de peticiones del bridge (sección 4.1).

### 4.7 Experimento A/B del 10 de noviembre: el reset en red primaria (18)

**Idea.** En el 18, Diamond promueve `reset_shift_iso[15]` (el `reset = reset_shift[15]` del RTL, el único net que
llega a `memory_fabric_4` y a `cpu_dmem_adapter`) a recurso primario de reloj (PCLK): 1070 cargas `LSR` más el
pin `GSR`. Se probó si el cuelgue de la sección 4.5 tiene que ver con eso.

**Montaje.** Mismo RTL sin el drenaje defensivo (`rsp_ready = (state == ST_WAIT)`), misma tabla de PAR (3), mismas
herramientas. Única diferencia: la línea `PROHIBIT PRIMARY NET "reset_shift_iso[15]" ;` en
`18.fpga-cpu-hdmi-bl8/diamond-constraints.txt`. La sintaxis sale de la documentación instalada
(`Constraints Ref\PROHIBIT_PRIMARY.htm`). Prueba de que se aplicó: la red desaparece de las `PRIMARY` del `.par` y la
línea figura en el `.prf`. Se programó cada variante 5 veces alternando y se midió el acceso mínimo (`read-word 0x0`)
antes de lanzar la suite.

| Variante | Acceso mínimo | Suite | Timing |
|---|---|---|---|
| A: sin preferencia (reset primario) | 0/5 | 0/30 | cierra |
| B: `PROHIBIT PRIMARY NET` | 5/5 | 30/30 | cierra por poco (`clk` 80,59 MHz, slack +0,092 ns) |
| Control: drenaje defensivo, build del 10-nov | — | 30/30 (3/3) | cierra |

**Lectura.** Apoya que el fallo participa de la promoción del reset a red primaria, y que se puede evitar sin lógica
defensiva. No es una prueba: hay **una sola colocación por variante**, así que no se descarta suerte de placement,
y el cierre de B es justo. Falta A′ y B′ con otra tabla de PAR.

**Análisis de TRACE sobre los `.ncd` (sin placa).** No explica el fallo:

- Quitar `BLOCK RESETPATHS` no cambia nada: los caminos del reset a los `LSR` síncronos ya se analizaban como
  caminos normales. No sirve para "ver" el timing del reset.
- Retardo del reset a los 1070 `LSR` (`MAXDELAY NET ... 0.1 ns` para forzar el listado): A, 5,66–5,76 ns, casi
  uniforme; B, 0,63–5,99 ns. Pin `GSR`: 6,22 ns en A y 6,43 ns en B. Ninguna violación de setup ni de hold, con
  12,5 ns de periodo.
- La red de reset también alimenta el `GSR` del chip. Los únicos registros con `GSR:ENABLED` son 9 slices del
  receptor de la UART (`uart_i/rx`: `state`, `shiftreg`, `data_strobe`), iguales en A y B. Es el único reset
  asíncrono del diseño (`uart.v`: `always @(posedge clk or posedge reset)`). Su liberación no la mide TRACE.
  **Pista sin verificar**, no causa.

**Cuidado al interpretar.** `halted=False` justo tras programar **no** es firma de fallo: también lo da el build
bueno con drenaje. Solo B arranca con `halted=True` (`cpu.v` dice que la CPU arranca parada tras el reset); por qué
difiere es una pregunta abierta.

**Cómo aplicarlo.** Si otro prototipo (19, 21, 30) vuelve a colgarse con Diamond, probar primero `PROHIBIT PRIMARY
NET` sobre su net de reset (el nombre sale del `.par`) antes de añadir lógica defensiva. El experimento no se dejó
en el repositorio: el 18 sigue con el drenaje y sin `PROHIBIT`, y su registro de build de Diamond quedó STALE.

### 4.6 La 34: no es este fallo

La 34 (fábrica FIFO de seis puertos) cierra timing con `diamond-constraints.txt` y la tabla 3 de PAR (`clk_mem`
100,38 MHz), pero en la placa una escritura de memoria termina bien y la lectura siguiente deja sin respuesta al
monitor. Falla los 72 casos, con y sin el arreglo de la sección 4.5, y los dos únicos registros de placa que tiene
son de esa prueba, con 0 aciertos: no hay constancia de que haya pasado nunca.

Usa la arquitectura antigua de SDRAM: `sdram_clk = clk`, captura del dato de lectura en el flanco de bajada, sin
la etapa previa a los pines y sin control de fase. Su `sdram_controller_128.v` tiene 728 líneas frente a las 871 de
35 y 38, no tiene `pll_phase_ctl.v` y su bridge no tiene `outstanding` ni `phantom`. Nunca recibió el port de 35–38.
El comentario de la 37 avisa de que con la fase a 0 "la SDRAM es marginal y, si falla, el fabric se cuelga", que
se parece al síntoma, pero no está comprobado. Arreglarla es portar esa arquitectura (unos 15 ficheros), que es lo
que ya es la 35 sin GPU.

## 5. Flujo de Diamond: lo práctico

- **Cierre de timing:** tras cambiar RTL hay que repetir el cierre. La tabla de coste de PAR
  (`--strategy par_place_iterator_start_pt=K`) importa: hoy cerraron 35 con la tabla 3 (`clk_mem` 111,8),
  36 con la 1 (117,2), 37 con la 1 (102,7), 38 con la 5 (104,1), 18, 19 y 21 con la 3, 30 con la de por
  defecto y la 34 con la 3.
  Un cambio mínimo de RTL puede mover una build de pasar a fallar por 0,1 MHz.
- **Un solo `apio` a la vez.** Lanzar varias builds de apio en paralelo choca en la instalación de paquetes
  de `~/.apio`; hizo falta `apio packages install --force`. Desde el 8 de noviembre `yosys` cae dentro de
  `apio build` (`std::system_error: Invalid argument` en `FLATTEN`) aunque funciona a mano. Ocurre también en el 6,
  que compilaba bien con apio el 5, así que no depende del tamaño ni del RTL. Lo que cambió en esos días fue el
  `.venv` (recreado el 8) y los paquetes de apio. Causa sin aclarar. Se puede reproducir el flujo a mano con
  yosys, nextpnr y ecppack, con los parámetros de `apio/scons/plugin_ecp5.py`.
- **Fase de la SDRAM** (35, 36, 37 y 38). Con Diamond el valor es el mismo en las cuatro: 10 pasos de 1/8 de
  ciclo de VCO, unos 208 ps cada uno. **Con Yosys/nextpnr no vale**: el 11 de noviembre `tools/phase-sweep`
  midió en la 38 una ventana 0–5 y la 10 fallaba (44 de 49 casos con `INVALID_ENCODING` en `pc = 0`). Desde
  entonces la 35 y la 38 llevan la fase en el bitstream (`SDRAM_PHASE` en `top.v`, con `ifdef DIAMOND`: 10 o 2)
  y su `version.json` ya no la declara. Antes, en 35 y 38 la PLL salía a 0 y el monitor aplicaba el `sdram_phase`
  de su `version.json` al conectar; sin ese paso la suite entera falla con `estado de fase no válido` y el registro de placa queda
  con un 0/N inválido. En 36 y 37 la PLL ya sale en 10 (`CLKOS_CPHASE(6)`, `CLKOS_FPHASE(2)` y
  `INITIAL_POS(6'd10)`), y no declaran fase en su `version.json`. No se ha medido el reloj en la placa. La 34 no
  tiene control de fase.
- **Builds en otro worktree:** los informes quedan en el `reports/` de ese worktree y salen STALE por los
  finales de línea. Copiar el informe al principal con los hashes LF, o no usar un segundo worktree.
- **`.diamond/impl1` bloqueado** en el worktree principal (WinError 32, causa desconocida): fue la razón
  de construir la 36 aparte.

## 6. Tablas de builds

- **STALE.** El hash cubre todo `.v`, `.sv`, `.vh`, `.lpf`, `.hex` y `apio.ini` de la carpeta. Ahora, para
  Diamond: cuenta `diamond-constraints.txt`, ignora las opciones de nextpnr de `apio.ini` (solo lee `board` y
  `top-module`) y compara con saltos de línea normalizados cuando el informe los guarda.
  No se pudo arreglar la 37 ni la 38 de Diamond de antes de hoy: sus informes no guardan los hashes LF.
- **Columna BOARD:** `-` si el prototipo no tiene CPU ni GPU; `UNTESTED` (amarillo) si tiene y no hay prueba
  registrada; `pasados/total fecha` si la hay. Se asocia por el SHA-256 del `.bit`.

## 7. Pendiente

1. **Causa raíz de la respuesta huérfana** en 18, 19, 21 y 30 (sección 4.5). El arreglo defensivo los deja
   funcionando, pero no explica por qué la fábrica entra en `RESP` sin petición. Sospecha sin demostrar: los
   varios drivers de `state_ns`. Pista más fuerte: el reset en red primaria (sección 4.7). Siguientes pasos:
   A′/B′ con otra tabla de PAR para descartar suerte de placement; variante con el reset de `uart_i/rx` síncrono
   (único consumidor del `GSR`); `PROHIBIT PRIMARY NET` en 19, 21 y 30.
2. **22:** mismo patrón en `gpu_lsu2` y misma fábrica, validada 70/70 y sin tocar. Reproducir antes de arreglar.
3. **34:** decidir entre portar la arquitectura de 35–38 o dejarla como no validada en la placa (sección 4.6).
4. **`apio build` falla** desde el 8 de noviembre dentro de yosys, también en el 6. Causa sin aclarar.
5. Que el runner use la imagen `--board` en la 36 para ejecutar los 10 casos que hoy omite.
6. El origen del fantasma del bridge y la causa exacta, dentro de Synplify, del reset ineficaz.
7. 16 y 30 siguen con `reset_shift` y no con `reset_sync` por dominio.

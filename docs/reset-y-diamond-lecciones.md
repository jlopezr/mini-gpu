# Reset en FPGA y flujo Diamond: lecciones del 8 de noviembre de 2026

Resumen de lo que se midió y se aprendió al llevar los prototipos 35, 36, 37 y 38 a Lattice Diamond
y probarlas en la placa ULX3S. Separa lo **medido en la placa** de lo que es **explicación probable**:
donde no se demostró, lo dice.

## 1. Qué pasó (en una página)

| Síntoma en la placa | Causa | Arreglo |
|---|---|---|
| La CPU ejecutaba corrida 16 B (`pc` final +0x10) con los registros bien | El bridge entregaba una **respuesta fantasma** retenida al arrancar; `instruction_buffer` la tomaba como contestación a su primera petición | `fabric_fifo_bridge` cuenta peticiones y respuestas (`outstanding`) y tira la respuesta que llega con la cuenta a 0 |
| Un kernel de GPU fallaba con error 4 y el siguiente también | El error de una lane (división por cero) **sobrevivía** a `GPU_CONTROL.RESET` | `gpu_sm` pasa `reset \|\| soft_reset` a las lanes; `instruction_buffer` invalida sus líneas en reset |
| `serial_port` arrancaba con `STATUS = 0x14000` (`rx_overrun` = 1) y `serial-empty-input` fallaba | El flop de `rx_overrun` **no se limpiaba con el reset** | El reset va dentro de la lógica de datos del flop (sección 3) |
| 10 casos de C fallaban en la 36 con `GPU_ERR_STATE` | La imagen usaba `WARP_START`, que la 36 (hito 1) no tiene; no era un fallo de hardware | Los casos declaran `requires: gpu_warp_start` |
| `workgroup-barrier-isolation` fallaba solo dentro de la suite | Carrera del propio programa: un `LOAD` de warp son 8 lecturas en olas distintas | Bucle de espera dentro de una región `SSY` |

Los tres primeros son **la misma clase de fallo**: estado interno que no está a su valor de reposo
cuando la lógica empieza a trabajar. Conviene tratarlo como una clase, no como tres incidencias.

Resultado en placa con builds de Diamond (todas con timing cerrado): 35 → 72/72, 36 → 79/79
(10 omitidos por `WARP_START`), 37 → 97/97, 38 → 49/49.

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

## 5. Flujo de Diamond: lo práctico

- **Cierre de timing:** tras cambiar RTL hay que repetir el cierre. La tabla de coste de PAR
  (`--strategy par_place_iterator_start_pt=K`) importa: hoy cerraron 35 con la tabla 3 (`clk_mem` 111,8),
  36 con la 1 (117,2), 37 con la 1 (102,7), 38 con la 5 (104,1), 18 con la 3 y 19 con la 2.
  Un cambio mínimo de RTL puede mover una build de pasar a fallar por 0,1 MHz.
- **Un solo `apio` a la vez.** Lanzar varias builds de apio en paralelo choca en la instalación de paquetes
  de `~/.apio`; hizo falta `apio packages install --force`. Tras reinstalar, `yosys` cae dentro de
  `apio build` (aunque funciona a mano): problema abierto.
- **Tras programar, aplicar la fase de la SDRAM** (35, 36 y 37). Sin ese paso la suite entera falla
  con `estado de fase no válido` y el registro de placa queda con un 0/N inválido.
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

1. **18, 19 y 21 en Diamond no arrancan:** la CPU se queda en `pc = 0` y no atiende `halt`; el primer comando
   de carga da timeout. La build vieja de apio de la 21 sí pasa. Usan `memory_fabric_4.v` y
   `sdram_controller_128.v`, sin los arreglos de reset ni del bridge de la 36/37. **Hipótesis sin comprobar:**
   es la misma clase de fallo de arranque. Primer paso: diagnosticar el estado de la fábrica en la placa.
2. **Apio no compila** desde la reinstalación de paquetes.
3. **19 y 21** tienen un `serial_port.v` distinto con el mismo `if (reset)` para `rx_overrun`.
4. Que el runner use la imagen `--board` en la 36 para ejecutar los 10 casos que hoy omite.
5. El origen del fantasma del bridge y la causa exacta, dentro de Synplify, del reset ineficaz.

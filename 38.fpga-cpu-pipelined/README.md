# CPU pipelined sobre la base del prototipo 35

Prototipo derivado de `35.fpga-cpu-fifo-sdram2`. Mantiene el mismo fabric FIFO,
SDRAM de cuatro bancos, consola de video, puerto serie, INPUT y mapa MMIO; su
objetivo es aislar la pregunta de microarquitectura: si la MiniCPU puede
convertirse en un nucleo segmentado que acepte una instruccion nueva por ciclo
en el caso comun.

La identificacion de placa es monitor `5.38`.

## Punto de partida

`cpu.v` ya no es la FSM multiciclo del 35: es una primera CPU segmentada
experimental con frontera IF/ID/EX/WB y punto de retiro arquitectonico. Mantiene
la interfaz externa del 35 para que `top.v`, monitor, contadores y adaptadores de
memoria sigan encajando.

El objetivo razonable no es que todas las instrucciones retiren en un ciclo,
sino que el front-end acepte una instruccion por ciclo mientras las instrucciones
de latencia variable introducen burbujas o se desacoplan. El primer hito deberia
medirse como CPI cercano a 1 en secuencias ALU simples desde el buffer de
instrucciones, no en programas con LOAD/STORE a SDRAM, divisiones o saltos
tomados.

Esta primera version es conservadora: las dependencias RAW insertan burbujas en
vez de resolverse con forwarding completo, las operaciones de memoria bloquean
el issue mientras esperan `dmem_ready`, y los saltos tomados vacian fetch/decode.
Eso preserva semantica y punto de retiro antes de optimizar throughput.

## Viabilidad

La transformacion parece viable, pero no es un cambio local:

- **Banco de registros.** Hay deteccion de dependencias, pero todavia no
  forwarding EX/MEM/WB completo. Es correcto, aunque conserva mas burbujas de las
  deseables en codigo dependiente.
- **Memoria.** `imem` y `dmem` ya son dos puertos logicos independientes hacia el
  fabric, pero ambos pueden esperar. El pipeline tiene que congelar etapas con
  `ready` bajo y resolver `LOAD` con al menos una burbuja si la siguiente
  instruccion consume el dato.
- **Control de flujo.** Los branches actuales calculan condicion y destino en
  varios estados. Para aceptar una instruccion por ciclo habra que decidir si se
  resuelven en EX con flush del fetch especulativo, o si se mantiene una burbuja
  fija hasta resolverlos.
- **Operaciones largas.** MUL/MULHI/MULFX y DIV/REM estan integradas
  funcionalmente en EX para cerrar el primer vertical slice. Antes de perseguir
  timing habra que volver a partirlas o convertirlas en unidades bloqueantes con
  handshake/scoreboard.
- **HALT/STEP/debug.** El monitor observa `instruction_retired`, `halted`, PC y
  registros arquitectonicos. En pipeline hay que definir el punto de retiro y
  hacer que `STEP` retire exactamente una instruccion aunque haya instrucciones
  jovenes prefetcheadas.
- **Excepciones.** Los errores actuales restauran PC a la instruccion culpable.
  En pipeline eso exige conservar `pc` por etapa y vaciar instrucciones jovenes
  al detectar `TRAP`, encoding invalido, division por cero o acceso de memoria.

## Plan de ataque

1. Compilar el banco `cpu_tb.v` con una herramienta HDL y corregir cualquier
   error de sintaxis/semantica.
2. Ejecutar los casos CPU existentes contra el prototipo 38.
3. Anadir forwarding para ALU inmediata/anterior y reducir burbujas RAW.
4. Sustituir DIV/REM combinacionales por una unidad bloqueante.
5. Medir CPI con `cpu_perf_counters` antes de tocar timing.
6. Rebarrer timing: cualquier conclusion del 35 deja de valer cuando cambia
   `cpu.v`.

## Pendiente

- Compilar/simular con `iverilog`, `yosys` o `apio test` en un entorno con
  herramientas HDL instaladas.
- Anadir contadores o trazas que distingan ciclos de issue, retiros, stalls de
  fetch, stalls de datos, stalls de control y stalls de unidad larga.

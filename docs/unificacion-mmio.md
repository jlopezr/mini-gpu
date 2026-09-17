# Plan de unificación del mapa de memoria y MMIO — lo que queda

Lista de trabajo para aplicar el **contrato objetivo** de
[`mapa-de-memoria.md`](mapa-de-memoria.md) §6 al RTL, a los monitores y a los
tests. Ese documento define *qué* debe quedar; este, *qué falta* y *en qué
orden*.

Objetivo declarado: **que el mismo programa valga en varios prototipos**. El
criterio para ordenar es ese, no la dificultad.

> **Este documento sólo contiene lo abierto.** Las fases 0, 1, 2, 3, 3.4, 3.5,
> 4a y el renumerado de la 5 están cerradas y se han quitado de aquí: lo que
> hacían vive ahora en el RTL, y **por qué** lo hacían vive en los comentarios
> de cada fichero y en las docstrings de los tests que las fijan
> (`x.tests/test_monitor_port.py`, `test_sysid_device.py`,
> `test_monitor_protocol.py`, `test_top_wiring.py`, `test_run_tests_parallel.py`).
> El historial completo está en git. Repetirlo aquí convertía el plan en un
> diario, y un diario de doscientas líneas de trabajo terminado esconde las
> quince que aún importan.

---

## Estado al 17/09/2026

Queda **una** cosa grande, **una** decisión y
**una** fase entera que hoy no tiene quien la pida.

| Qué | Dónde | Bloquea a |
|---|---|---|
| Ronda de placa (incluye la verificación pendiente de la 3.5) | abajo | cerrar 3.5 y 5 |
| Política de dirección inexistente | fase 4b / 5 | la lista blanca de accesos sueltos |
| `DEV_BITMAP` | fase 4b | nada: no tiene consumidor |

---

## Lo primero: la ronda de placa

Es lo que desbloquea cerrar dos fases, y **acumula tres cambios sin verificar en
hardware**. Va primero porque cuanto más se acumula, menos dice un fallo sobre
cuál de ellos lo causó.

Lo que hay que validar, y por qué cada cosa puede fallar sólo en placa:

- **Fase 3.5 entera.** Contadores en MMIO, `VIDEO_CTRL`, bases de framebuffer a
  cero. Cerrada en RTL, simuladores y pruebas; sin placa. Se dejó agrupada al
  final a propósito, para no pagar un `nextpnr` por cada punto.
- **El renumerado de versiones.** Un `top.v` que se olvide del parámetro
  contesta `x.0`, y eso sólo se ve preguntándoselo a la placa.
- **`SYS_ID` en 6 y 10.** Llegan por el camino del monitor, no por una ventana
  MMIO; en simulación no hay nada que lo distinga de estar bien.
- **`READ_WORD` en la 10 y la 16.** `mem_read_word` estaba **sin conectar** en
  sus `top.v`: en placa devolvía X. No se vio antes porque `monitor_tb` maneja
  esa señal él mismo y ningún banco instancia `top`. Hay ya un
  `test_top_wiring.py` que lo fija, pero quien tiene la última palabra es la
  placa.
- **La convergencia de los `monitor.v`** (ver abajo), que cambia el netlist de
  las diez carpetas.

Hace falta **resintetizar las diez**. Recordatorio que ya costó una vez: la
semilla de `nextpnr` es propiedad de un *netlist*, no de un diseño, así que
cualquier cambio de RTL invalida un barrido anterior. La 19 lleva `--seed 4`
fijada con una nota honesta en su `apio.ini` (3 de 8 semillas pasan); ese pin
hay que volver a ganárselo.

`yosys` y `nextpnr` son monohilo: se sintetiza en paralelo con `Start-Job`, una
carpeta por trabajo.

---

## Convergencia de los `monitor.v` (fase 5)

**Estado: validación en curso.** `x.tests` pasa: 223 tests unitarios y 35 casos
GPU (37 omitidos por arquitectura o capacidades). Los bancos RTL de 6, 10, 12,
14, 16, 17, 18, 19 y 21 pasan. En 19 y 21 hubo que actualizar los modelos de
los tests serie, que aún buscaban constantes retiradas de `monitor.py`; sus
12 tests Python por carpeta pasan tras la corrección. La 6 cubre además el
rechazo de `RUN` y `STEP` con error latcheado, sin emitir peticiones al núcleo.

La suite normal de la 22 sigue en segundo plano, registro
`reports/20260917-161544-861325-test/`: consultar con `build-status --prototype 22`
y `build-log --prototype 22`. No incluye el banco marcado lento `gpu_plasma_tb`.
Síntesis y placa siguen pendientes.

Lo que se hizo: un `monitor.v` único, **copia idéntica en las diez carpetas** con
juego de comandos (6, 10, 12, 14, 16, 17, 18, 19, 21, 22). Todo lo que distingue
a un prototipo entra por parámetro desde su `top.v`: `VERSION_MAJOR`/`MINOR`,
`HAS_SERIAL`, `RAM_END` y cinco ventanas MMIO.

Tres decisiones que conviene revisar antes de darlo por bueno, porque las tres
cambian comportamiento:

- **La base es el de la 19, no el de la GPU.** El plan suponía lo contrario —el
  de la GPU ya era el parametrizado— pero el de la familia CPU tiene dos cosas
  que el otro no: la decodificación de comando **segmentada** (`command_decoded`
  one-hot registrado) y la validación de bloque **segmentada**
  (`STATE_CALCULATE_BLOCK_END` / `STATE_VALIDATE_BLOCK`). Las dos existen para
  cumplir a 120 MHz. Partir del de la GPU habría metido el sumador ancho en el
  camino del byte de UART justo donde ya se sabe que no cumple.

  Coste: las cuatro GPU ganan dos etapas de pipeline por comando. Sobre un
  enlace de 1 Mbaud —10 µs por byte— dos ciclos a 25 MHz no se miden.

- **La familia CPU gana lista blanca de bloques, y es permisiva.** Antes
  rechazaba todo lo que no fuera RAM (`mem_address[31:25] != 0`), así que un
  `READ_BLOCK` sobre MMIO daba NACK. Ahora pasa por las ventanas declaradas. Es
  el cambio que el plan temía; resultó **acotado**, porque la comprobación sólo
  gobierna bloques: los accesos byte a byte y `READ_WORD` no pasan por ella en
  ninguna de las dos familias, y siguen filtrándose aguas abajo. Eso es también
  lo que deja viva la decisión de la sección siguiente.

- **`RUN` y `STEP` ahora exigen parado Y sin error, en las dos familias.** La
  GPU ya lo hacía; la CPU no. Arrancar sobre un error latcheado contestaba `b0`
  y volvía a parar en el acto: el host veía un arranque que no arrancó. Con `ff`
  sabe que tiene que resetear primero. **Es visible en el protocolo** sin que
  cambie el juego de comandos, así que merece mirarse con cuidado en los bancos
  de la familia CPU.

De paso se cerró un cabo suelto: 6 y 10 tenían `MONITOR_REGIONS = ()` en su
`monitor.py` aunque ya llevaban `sysid`. No daba la cara porque `read_word` no
valida, pero `read_memory` y `read_block` sí, así que leer la identificación por
bloque se habría rechazado en el host antes de llegar al cable.

### Lo que falta de este punto

- [ ] Correr los bancos de las diez carpetas y `x.tests`.
- [ ] Síntesis de las diez y ronda de placa.

---

## La decisión abierta: dirección inexistente

Hoy una dirección sin dispositivo **lee cero en CPU** y **levanta `bad` en GPU**.

Esto ya no es lo que era cuando se escribió. El truco de compatibilidad que lo
sostenía —«leer cero en `0x80000F00` significa prototipo antiguo»— **ya no hace
falta dentro del repo**: las diez carpetas con juego de comandos y los tres
simuladores tienen `SYS_ID`. Sigue sirviendo para un **bitstream viejo ya
flasheado**, y sólo ahí. Y ni siquiera en las dos familias: en la GPU nunca
funcionó, porque una dirección fuera de las ventanas declaradas levanta `bad` en
vez de leer cero.

**Recomendación:** unificar **sólo dentro del slot de identificación** —cero
ahí— y mantener `bad` en el resto de la página. Razón: es lo que preserva el
diagnóstico que convierte un error de programa GPU en un error visible del host,
y es lo mismo que ya se hizo con `HALT_AT` en la 22. Unificar hacia «error en
toda la página» rompería el truco justo donde hoy funciona.

- [ ] Decidirlo y escribirlo en `mapa-de-memoria.md` §6.
- [ ] Aplicarlo. Afecta a los accesos **sueltos**, que es lo que la lista blanca
      de bloques dejó sin tocar.

---

## Fase 4b — `DEV_BITMAP`

**No tiene hoy ningún consumidor que la pida.** Se deja escrita porque el hueco
existe en el contrato (`+0x08`, lee cero, que con `CONTRACT = 1` significa «sin
declarar» y no «ningún dispositivo»), no porque haga falta ya.

- [ ] **Generarlo desde `capabilities.json`**, no a mano: escrito a mano en cada
      sitio sería una tercera gemela que mantener junto a las ventanas y
      `MONITOR_REGIONS`, justo lo que §6.5 quiere quitar.

      **Ojo, esto contradice lo que se decidió en 4a**, y la contradicción es
      deliberada, así que hay que resolverla antes de empezar: `sysid.v` e
      `ISA_PROFILE` se escribieron **a mano y contrastados con un test**, con el
      argumento de que un fichero generado se desincroniza en silencio si
      alguien toca el RTL y no regenera, mientras que un test que compara falla
      a gritos. Si ese argumento valía para `ISA_PROFILE`, hay que explicar por
      qué no vale para `DEV_BITMAP` — o generar los dos, o ninguno.
- [ ] Hace falta maquinaria que **no existe**: hay `.vh` generados, pero sólo de
      fixtures de simulación, y `generate-docs` sólo toca Markdown. No hay
      precedente de Verilog **sintetizable** generado, ni de un test que
      compruebe que lo generado está al día.
- [ ] `capabilities.json` no tiene números de bit. Hay que añadirlos y
      comprometerse a no reutilizarlos nunca.
- [ ] Si se hace, **hacerlo a la vez que lo que quede de la fase 5**: las dos
      quieren derivar su lista de la misma tabla, y por separado se construye el
      generador dos veces.

---

## Fuera de esta ronda, y por qué

Esto no está pendiente: está **descartado con motivo**. Se deja escrito para no
volver a proponerlo sin argumento nuevo.

- **`WRITE_WORD`.** El puerto host escribe con `expanded_data={4{write_data}}`
  más un strobe de byte, así que una escritura real de 32 bits obliga a llevar
  máscara de bytes hasta el puerto aux y hasta la RAM, en las dos familias. Y
  sólo evita el desgarro de *escritura*, que ya se evita escribiendo con el
  núcleo parado. El de *lectura* no tenía esa salida —`frame_count` avanza con
  el núcleo parado— y por eso `READ_WORD` sí entró. Se añadirá cuando haya un
  motivo concreto.
- **Control de lanzamiento GPU por registros** (`0x80001080–0x80001FFF`). Hoy
  run/halt/step/reset llegan por señales del monitor. Convertirlos en registros
  choca de frente con que la interfaz host es byte a byte y sólo funciona con la
  GPU parada. Es rediseño, no reubicación.
- **Convivencia CPU+GPU en el mismo bitstream.** El contrato se diseña para no
  cerrarle la puerta —por eso lo exclusivo de la GPU va a una segunda página en
  vez de a un slot libre de la primera— pero los siete puntos de «lo que falta
  por resolver» de §6 (arbitraje, dominios de reloj, orden de escrituras, quién
  pide los swaps) son otro proyecto.
- **Aceptar MMIO sin modelar el dispositivo.** No se debe añadir una ventana
  que simplemente acepte accesos para que un programa deje de fallar. Esto no
  descarta simular periféricos: 2, 11 y 25 comparten `VideoDevice` (con captura)
  y `SerialDevice`, accesibles por MMIO cuando se instancian. El pipeline de la
  25 enruta MMIO y difiere los efectos de UART hasta el commit. La paridad se
  comprueba ejecutando programas en `x.tests/test_sim_peripherals.py`, no solo
  construyendo objetos de dispositivo.
  Los modelos deben respetar offsets y efectos de los registros implementados;
  el vídeo funcional no reproduce contienda, underflow ni desgarro, y la serie
  no reproduce el tiempo de llegada de los bytes. `plasma_nommio.asm` sirve
  para ejecutar sin dispositivo de vídeo, no como argumento contra modelarlo.

---

## Apunte suelto

- **Por qué `urgent_r` se dispersa tanto en la 19.** Su barrido da 3 de 8
  semillas, peor que cualquier barrido anterior de esa carpeta, y el camino
  crítico es 84 % rutado (2,18 ns de lógica contra 11,70 de rutado). No bloquea
  nada, pero es la clase de cosa que un día deja de pasar del todo.

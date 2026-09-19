# TODO

Por orden de prioridad. Repasado entero el 19/09/2026 contra el árbol: lo que
estaba hecho se quitó, lo que era pregunta de ISA se movió a
[`1.isa/propuesta-v0.3.md`](1.isa/propuesta-v0.3.md), y lo que quedaba se
reescribió contra el estado real. Al final hay un apartado con lo que se cerró,
para no volver a abrirlo por error.

## 1. Snapshots de ejecución (simulador)

Guardar y restaurar memoria, PC, registros, máscaras y estado del scheduler.

**Es lo de mayor impacto de la lista, y ya no hay nada que lo bloquee.** Estuvo
el último mientras `SSY` estaba en diseño activo, porque un snapshot tiene que
serializar `region_stack` y `path_stack`. Eso se acabó:
[`11.gpu-sim-func/docs/ssy-reusable-regions-design.md`](11.gpu-sim-func/docs/ssy-reusable-regions-design.md)
abre con «semántica vigente de MiniISA v0.1» y la da por implementada en el
funcional de 11, en `gpu_sm.v` de 12, 14, 17 y 22, y en `simt.py` de 25. El
formato ya se puede congelar.

Para qué sirve, en concreto: `mandelbrot` son ~100 s y el 99,8 % del tiempo de
la suite GPU. Hoy, depurar un fallo tardío es relanzar con `--trace-detail`,
esperar 100 s, formular una hipótesis y volver a esperar 100 s. Veinte
iteraciones de «¿y si es esto?» son 35 minutos de espera pura. Con snapshot se
para una vez cerca del fallo y **cada iteración posterior arranca ahí**. No
encuentra fallos que antes no se encontraran; convierte una tarde en diez
minutos.

Extensión del fichero de lanzamiento, con un propósito distinto.

## 2. Segmentar el cauce del SM

El diseño está escrito y sin implementar:
[`22.fpga-gpu-bl8/sm-pipeline.md`](22.fpga-gpu-bl8/sm-pipeline.md), y el README
de la 22 lo llama v2.1 (`pending_spec`, preparación en la sombra).

**Este punto sustituye al antiguo «optimizar LSU», que está hecho.** Los tres
módulos —`gpu_lsu2.v`, `gpu_aux_adapter_128.v` y `gpu_imem_buffer.v`— sobre
`memory_fabric_4` y
`sdram_controller_128` están en la 22 y midieron −42 % de ciclos, −17 % de Fmax,
**x1,44 neto**. Y el camino crítico se mudó: ya no vive en la LSU, vive en el SM
([`lsu-v2.md`](22.fpga-gpu-bl8/lsu-v2.md)). O sea que seguir puliendo la LSU es
donde estaban los rendimientos decrecientes, y el SM es donde está lo que queda.

Hay con qué predecir la ganancia antes de escribir RTL: el simulador de ciclos
de [`25.gpu-sim-cycle-uarch`](25.gpu-sim-cycle-uarch) existe, con su `DESIGN.md`
y su `VALIDATION.md`.

## 3. Unificar la documentación por prototipo, y barrer inexactitudes

Los dos puntos que antes eran 6 y 7: son el mismo trabajo. Hoy la estructura no
sigue ninguna regla:

| Documento | Dónde está | Dónde falta |
|---|---|---|
| `cycles.md` | 6, 10, 16, 18, 19, 21 | **toda la GPU**: 12, 14, 17, 22 |
| `timing.md` | 6, 10, 16, 18, 19, 21 | GPU; 14 y 17 usan `sintesis.md` para algo parecido |
| `validation.md` | 12, 14, 17 | CPU entera, y la 22 |
| `memory-interface.md` | 12, 14, 17 | la 22 |

Y la **ubicación** tampoco: casi todos los prototipos lo meten todo en `docs/`,
pero la 17 tiene `lsu.md` en la raíz y `optimizacion.md` en `docs/`, y la 22
tiene siete `.md` en la raíz y solo `intro-gpu.md` en `docs/`. Además 18, 19 y
21 arrastran `plan-18-bl8.md` y `medida-inicial.md` copiados tal cual: eran el
plan de la 18 y ya no son plan de nada.

La propuesta es decidir **qué documentos tiene un prototipo por definición** y
dónde viven, y luego aplicarlo. No es renombrar ficheros: es decidir si
`optimizacion.md` se generaliza o es específico de la 17, y qué se hace con los
documentos de plan una vez ejecutado el plan.

Va junto con buscar inexactitudes entre doc y código, que es el mismo barrido.
En el repaso del 19/09 salieron cuatro solo de pasada, y **las cuatro ya están
arregladas** —la cabecera de `lsu-v2.md` que seguía diciendo «nada está
implementado», `VIDEO_CTRL` como «solo 22» en `mapa-de-memoria.md` cuando está
en las cuatro CPU desde la fase 3.5, el `8.ulx3s_w9825g6kh_test` del README de
la 8, y un `MULX` fantasma en este mismo fichero—, pero cuatro en una tarde sin
buscarlas dice que hay más. `tools/check-links.py` valida enlaces; el contenido
no lo valida nadie.

## 4. SDRAM: aprovechar la fila abierta

Hoy cada transacción activa una fila, la usa y la cierra: el controlador de
[`7.ulx3s_w9825g6kh_test`](7.ulx3s_w9825g6kh_test) ya hacía auto-precharge en
cada acceso, y `sdram_controller_128.v` sigue siendo una activación por ráfaga
BL8. Accesos consecutivos a la misma fila pagan `tRP + tRCD` que no harían falta.

Las dos preguntas de diseño, que es donde está el trabajo de verdad:

- **Interfaz controlador↔fabric:** el controlador tendría que exponer qué fila
  tiene abierta, y aceptar una petición nueva sin cerrarla. Deja de ser una
  interfaz sin estado.
- **Interfaz fabric↔masters:** el árbitro tendría que poder conceder por
  **afinidad de fila** y no solo por prioridad, o toda la ganancia se pierde en
  cuanto dos masters alternan. Y eso choca con la equidad: un master que
  siempre acierta de fila podría dejar sin turno a otro.

Ahí está el riesgo: `memory_fabric_4.v` es hoy un árbitro genérico que no sabe
qué hay detrás de cada puerto, y esto lo acopla a la SDRAM.

## 5. `apio lint` no pasa en ningún prototipo

Medido el 19/09/2026 con `tools/lint`:

| Prototipo | 6 | 10 | 16 | 18 | 19 | 21 | 22 |
|---|--:|--:|--:|--:|--:|--:|--:|
| Diagnósticos | 18 | 41 | 66 | 40 | 36 | 38 | 31 |

Los siete salen con exit 1. Casi todo es `PINMISSING` en los `*_tb.v`:
testbenches que instancian módulos a los que se les añadieron puertos después y
no se actualizaron —`cpu_burst_system_tb.v:131` no conecta `perf_read_data`,
`video_registers_tb.v:44` no conecta `video_mode`—.

**El único que no es ruido de banco es el `CASEINCOMPLETE` de la 16**, en
`sdram_system_adapter.v:285`: `state` es de 4 bits con 12 estados y el `case` no
tiene `default`, así que 12–15 no los cubre nadie. No es un fallo vivo —esos
valores son inalcanzables por construcción— pero si se alcanzaran la FSM se
congelaría sin recuperación, y es el único camino a la SDRAM de esa carpeta.
**El arreglo está decidido y escrito como comentario en el propio fichero**: se
aplica al próximo cambio de RTL de la 16, porque lleva semilla fija y dos
palabras de arreglo obligan a rebarrer las ocho semillas de un diseño que hoy
cierra y está verificado en placa.

**El problema que este punto describía antes está arreglado:** ya no aparece
`Can't resolve module reference: 'sdram_model'` en ninguno de los siete, pese a
que `sdram_model.v` conserva su guarda `` `ifndef SYNTHESIZE ``.

## 6. Ejecución paso a paso o N pasos

Avanzar una instrucción de warp, inspeccionar registros y memoria, y detenerse
en un PC o un warp concreto. `TextTrace` ya hace el trabajo sucio.

Debe ser una herramienta **aparte**, no una opción de `run_tests.py`: el
runner responde pasa/falla y un depurador interactivo es otro oficio.

**Parcial.** `monitor.py step` ya existe (un paso de CPU en placa real), pero
es el primitivo de bajo nivel, no la herramienta descrita aquí: no inspecciona
registros/memoria automáticamente ni para en un PC/warp concreto.

Prioridad baja a propósito: no encuentra fallos, ayuda a entenderlos una vez
encontrados, y con las expectativas actuales `--trace-detail` ya cubre casi
todos los casos.

## 7. `DEV_BITMAP` — lo único que queda de la unificación MMIO

La fase 4b de [`docs/unificacion-mmio.md`](docs/unificacion-mmio.md). Las fases
0, 1, 2, 3, 3.4, 3.5, 4a y el renumerado de la 5 están cerradas; de todo el plan
solo quedan esto y una ronda de placa que ya tiene dueño en ese documento.

**No tiene consumidor**, y por eso está aquí abajo: nadie lo pide todavía. Antes
de construirlo conviene decidir si hace falta.

## 8. Herramienta para testear y dibujar componentes RTL por separado

Los dos puntos 13 que había, que eran el mismo:

- **Testear un componente aislado** (p. ej. la LSU) con su `*_tb.v`, sin
  arrastrar el proyecto entero.
- **Dibujar el grafo de bloques**: cómo se conecta la LSU con el resto y el
  resto entre sí.

Parten de lo mismo —saber qué instancia a qué—, que es lo que `tools/rtl_facts.py`
ya empieza a leer.

Y hay media hecha: [`tools/interface-diagram.ps1`](tools/interface-diagram.ps1)
saca el SVG de la **interfaz** de un módulo con `yosys` blackbox + `show`. Lo
que no hace es el grafo de conexiones **entre** módulos. Además es la única
herramienta del repo sin lanzador y fuera del sistema de `tools/`
([`AGENTS.md`](AGENTS.md)), así que integrarla cierra también esa anomalía.

## 9. Volcado de estado SIMT en placa

Separado del punto 1 a propósito, porque el coste es muy distinto. **Volcar**
`region_stack`/`path_stack` por MMIO es leer, y es barato. **Restaurarlos** es
escribir estado arquitectónico desde fuera, y eso obliga a abrir ventanas y
comandos nuevos en `monitor.v` para algo que solo sirve para depurar.

Solo con el volcado se puede comparar simulador y FPGA **en un punto intermedio**
en lugar de solo al final, que es lo que convierte «la placa da otra cosa» en
«divergen en el frame 47». Con bisección sobre `run_until.swap`, cuatro paradas
localizan el frame. Eso vale la pena por sí solo; restaurar, probablemente no.

---

## Cerrado — no reabrir sin motivo nuevo

- **Optimizar la LSU.** Hecha en la 22 (`gpu_lsu2.v`), x1,44 neto. Lo que
  queda es el punto 2, que es otra cosa.
- **Revisar los inmediatos de la ISA.** La pregunta que quedaba abierta tenía
  respuesta: `ADDI/ANDI/ORI/XORI` son opcodes base `0x11–0x14` desde v0.1. El
  único inmediato que faltaba era el de comparación, y `SLTI/SLTIU` están ahora
  propuestos en [`propuesta-v0.3.md`](1.isa/propuesta-v0.3.md) §5, con su
  justificación y su coste en opcodes.
- **Divergencias entre versiones / `MULX`.** `MULX` no existía en ninguna parte
  del repo salvo en este fichero. Lo que hay es `MULFX` y `MULHI`, y están en
  las dos familias. La duda real que había detrás —por qué no hay `DIVFX`, y si
  sumar en coma fija necesita algo— está contestada en
  [`propuesta-v0.3.md`](1.isa/propuesta-v0.3.md) §5: es el ancho del dividendo
  (48 bits, no 32), `ADD`/`SUB` funcionan tal cual, y las conversiones son un
  `SHLI`/`SARI`.
- **Revisar `MONITOR_REGIONS`.** Resuelto. La ventana quedó abierta a la página
  entera (`0x80000000–0x80001000`) en 16, 18, 19 y 21, no a los 24 bytes que
  este fichero llegó a decir: `perf` lee `0x80000300` y con la ventana estrecha
  se rechazaba en el cliente.
- **Tests de capacidad en `x.tests`.** El mecanismo está sano (34 `test.json`
  con `requires`) y los tres pendientes que quedaban se cerraron: el smoke test
  es `cases/basics/smoke`, y `swap_demo`/`swap_demo_fast` son
  `cases/video/swap-demo` y `cases/video/swap-demo-fast`, apuntando al `.asm` de
  la 21 sin copiarlo. `tear_demo` **no se puede convertir en caso** y no es una
  tarea pendiente: no pide `SWAP` nunca —es justo lo que demuestra—, así que
  `run_until.swap` no se dispara, y lo que enseña es una carrera que el
  simulador no modela. Razonado en
  [`x.tests/cases/video/README.md`](x.tests/cases/video/README.md).
- **«¿VVP qué ejecuta?»** Sí, el RTL: `vvp` corre el binario que compila
  `iverilog` a partir del RTL y su testbench.

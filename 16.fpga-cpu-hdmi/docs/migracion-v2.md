# Migración de la 16 a MMIO v2

Log de trabajo, escrito **durante** la migración.

Contrato de referencia: [`../../1.isa/mmio.md`](../../1.isa/mmio.md).

**Este fichero es el sexto y sólo escribe la diferencia.** La
[bitácora de la 6](../../6.fpga-cpu/docs/migracion-v2.md) lleva **la fase 0 de
las tres carpetas** de este encargo y los dos analizadores compartidos que hubo
que arreglar; la [de la 10](../../10.fpga-cpu-ram/docs/migracion-v2.md), lo que
cuesta una gemela. Antes están [la 21](../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md)
—el camino completo—, [la 19](../../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md),
[la 18](../../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md) y
[la validación en placa](../../docs/validacion-mmio-v2-placa.md).

**Alcance de cada decisión:**

- `[TODAS]` vale para las diez carpetas.
- `[CPU]` vale para la familia CPU.
- `[16]` es específico de esta carpeta.

---

## La decisión del bitmap de vídeo, que es lo que el encargo pide que escriba

### Lo que el encargo plantea

> «Decide explícitamente si la 16 gana los cinco registros nuevos de v2
> (`FRAME_COUNT`, `SWAP_COUNT`, `HALT_AT`, `HALT_TARGET`, `VIDEO_TX`) o se queda
> con los cinco que tiene. Lo segundo es conforme —§20 pide "el periférico que
> tengas, en v2"— y **es más barato**; lo primero le daría `frame_capture`.»

**La decisión es adoptar los diez.** Pero el motivo principal no es el que el
encargo pone en la balanza, porque el «es más barato» está al revés.

### Por qué conservar cinco es la opción CARA

`video_registers.v` es **byte a byte idéntico en la 18, la 19 y la 21**. No es
casualidad ni suerte: es la propiedad que la 21 defendió como «la decisión de
alcance más importante del log», y que hace que un arreglo en ese fichero se
aplique a todas las carpetas a la vez. La validación en placa lo cobró hace
literalmente un día: el bug del error que vivía un ciclo de menos se arregló con
**una línea** y se aplicó a las tres «porque el fichero es byte a byte idéntico
y hay un test que lo exige».

Conservar los cinco registros de la 16 significa **escribir una cuarta variante
de v2, exclusiva de esta carpeta, y mantenerla al día con los arreglos
compartidos**. Adoptar los diez es un `Copy-Item`.

| | Conservar cinco | Adoptar diez |
|---|---|---|
| `video_registers.v` | cuarta variante que mantener | `Copy-Item`, byte a byte |
| Arreglos compartidos futuros | hay que portarlos a mano | llegan solos |
| `frame_capture` | no | **sí** |
| Coste de área | menor, sin medir | ~+90 LUT, medido en la 18 |

El encargo acierta en que conservar cinco es **conforme**. Lo que no sostiene es
que sea barato: es más barato hoy y más caro cada día después.

### La razón que de verdad decide, y no es el coste

La 16 es una de las tres carpetas de este encargo donde **ningún `test.json`
apunta a sus `examples`** y ningún caso del runner la ejecuta. Adoptar los diez
registros le da `frame_capture`, y con ello **los casos de vídeo del runner
empiezan a aplicarle**. Pasa de una carpeta con vídeo que nadie prueba a una
carpeta con vídeo cubierta por la misma suite que la 18.

O sea que la opción «cara» compra cobertura automática en la carpeta que menos
tiene. Esa es la razón.

### Lo que casi la tumba, y por qué no

Al copiar el fichero apareció que el `video_registers.v` de v2 pide dos cosas
que el subsistema de vídeo de la 16 no tenía:

- **`underflow_clear`**, un pulso al dominio de píxel. El `video_scanout.v` de
  la 16 no tiene esa entrada: su `underflow` es pegajoso hasta `rst_pix`. Sin
  ella, el bit W1C de `STATUS` no se borra nunca.
- **`halt_request`**, la parada de la CPU al llegar a `HALT_AT`. La 16 no tenía
  ninguna ruta de vídeo a la CPU. Sin ella, `frame_capture` **no captura**.

Eso importa mucho más de lo que parece: declarar el bitmap `0x3ff` con esas dos
señales al aire sería **declarar registros que responden y no hacen nada**, que
es peor que no tenerlos. Un host que lea `DEVICES` y el bitmap creería que puede
capturar un frame, armaría la alarma y se colgaría — que es exactamente el
timeout que la validación en placa se pasó una hora persiguiendo.

Medido antes de decidir, el hueco es mucho menor de lo que parecía:

```text
video_scanout.v, 16 contra 21:  +30 lineas, -1
la unica linea borrada es un comentario
la unica diferencia de puertos es `input wire underflow_clear`
```

El `video_scanout.v` de la 21 es un **superconjunto estricto** del de la 16, y
el añadido es sólo el cruce de dominio del borrado. Así que también es copia. Y
`halt_request` es un término OR en la instanciación de la CPU, que es
literalmente lo que hace el `top.v` de la 21.

> Antes de rechazar una copia porque «ese módulo pide señales que aquí no
> existen», mira **cuántas** y de dónde salen. Aquí eran dos, una venía en otra
> copia igual de limpia y la otra era un OR. La alternativa que parecía barata
> —conservar cinco registros— costaba un fichero bifurcado para siempre.
> `[TODAS]`

---

## La forma de la 16, que sí es distinta `[16]`

El encargo dice que la 16 «es otra forma», y lo es, pero no donde dice.

**Donde NO es distinta:** tres de sus cinco ficheros de MMIO son byte a byte los
pre-migración de la 18, la 19 y la 21, medido con `git hash-object` contra
`5fc229f^`. `mmio_decoder.v`, `cpu_perf_counters.v` y `sysid.v` se copian ya
migrados, y con la decisión de arriba también `video_registers.v` y
`video_scanout.v`. **Cinco copias limpias.**

**Donde sí:** no tiene `mmio_mux.v` ni `cpu_dmem_adapter.v`. El arbitraje entre
CPU, monitor y vídeo, y la detección de MMIO, viven dentro de
`sdram_system_adapter.v`, que es su bloque único **y el que se sintetiza**. Ahí
fue el trabajo a mano:

```verilog
- localparam [19:0] MMIO_PREFIX = 20'h80000;
- wire cpu_dmem_mmio = cpu_dmem_address[31:12] == MMIO_PREFIX && ...
+ wire cpu_dmem_mmio = cpu_dmem_address[31] && ...
- output reg [11:0] mmio_address,
+ output reg [31:0] mmio_address,
```

Veinte bits comparados pasan a uno, y la dirección va entera. Es el mismo cambio
que en la 21 **devolvió 66 LUT**.

### La regla de la 18, invertida `[16]`

La bitácora de la 18 dejó escrito:

> «Que un banco contenga `0x8000_0000` no significa que esté sin migrar. En
> este repo conviven dos mapas a propósito: el de `top.v`, que es v2, y el del
> adaptador de la 16, que **se queda en v1 porque mide el diseño anterior**.»

Correcto allí, y **exactamente al revés aquí**: en la 16 ese adaptador no es el
diseño anterior, es el diseño. Así que `sdram_system_adapter_tb.v` —que en la
18, la 19 y la 21 se queda en v1 con toda la razón— en la 16 **hay que
migrarlo**, y es el banco con más direcciones de todos, veintiocho.

> La misma frase de una bitácora puede ser cierta en tres carpetas y falsa en la
> cuarta, sin que la frase esté mal. Lo que cambia no es el fichero, es **si ese
> módulo está instanciado en el `top.v` de esa carpeta**. Es la misma regla de
> siempre —mira qué módulo decodifica la dirección— aplicada al revés.
> `[TODAS]`

### El banco que obligó a cambiar lo que AFIRMA, no la dirección

`sdram_system_adapter_tb.v` comprobaba esto:

```verilog
// Fuera de la ventana, una direccion alta sigue siendo un error.
monitor_address = 32'h9000_0000;
if(!monitor_error) $fatal(1,"monitor accepted an address outside the MMIO window");
```

En v1 era correcto: la ventana era `address[31:12] == 0x80000`, así que
`0x90000000` caía fuera y acababa en la SDRAM, que da error. En v2 la
pertenencia al espacio MMIO es **un bit**, así que `0x90000000` **sí es MMIO** —
y está bien que lo sea: quien decide si ese bloque existe es `mmio_decoder.v`,
que este banco no monta, y que lo rechaza.

O sea que la afirmación vieja ya no describe un fallo, **describe el reparto
anterior de responsabilidades**. Cambiar la dirección para que siguiera fallando
habría sido conservar la letra y perder el sentido. Se sustituye por las dos que
sí le tocan a este módulo: que una dirección con `address[31]` se **encamine** a
MMIO, y que una dirección baja fuera de los 32 MiB siga dando error.

> Al migrar un banco, hay aserciones que no cambian de número sino de dueño.
> Si una comprobación dejó de ser de este módulo, muévela o bórrala; ajustarle
> la dirección para que siga en verde es quedarse con un test que ya no prueba
> nada y encima parece que sí. `[TODAS]`

### El otro banco, y la trampa de la instrucción a mano

`cpu_video_tb.v` lleva el programa **ensamblado a mano en hexadecimal**, que es
la forma en que una dirección MMIO se esconde de cualquier búsqueda:

```verilog
write_word(32'h0000_0000, 32'h5E80_8000); // MOVHI R20,0x8000
```

La 21 lo avisó y aquí se cobró. Se aplicó su consejo, que es el que hace el
resto mecánico: **nombrar los offsets como `localparam` antes de tocar
ninguno**, y construir las instrucciones con ellos. Ahora el programa dice
`{16'h5434, OFF_FB_FRONT}` y mover un registro es cambiar una línea, no
recalcular siete palabras a mano.

Es donde más fácil habría sido equivocarse sin enterarse: `CTRL` pasa a `+0x00`
y empuja a `FB_FRONT`, `FB_BACK` y `SWAP`. Ninguno da error al moverse mal —
contesta el registro de al lado.

### La copia que estaba mal, y la cazó el compilador

Se copió `video_mode_switch_tb.v` de la 21 sin comparar en las dos direcciones,
que es justo lo que la 19 dejó escrito que no se hiciera. Falló al instante:

```text
video_mode_switch_tb.v:139: error: Unknown module type: video_line_source_burst
```

La 21 tiene el camino de ráfagas y la 16 no. Restaurado el suyo y migrado a
mano, que fueron **dos ediciones**: el offset de `CTRL` de `8'h18` a `8'h00`, y
los puertos nuevos. La lección de la 19 sigue siendo la misma y esta vez la
cobró el compilador en cuatro segundos en vez de un banco en verde probando otra
cosa, que es la versión cara del mismo error.

`video_registers_tb.v`, en cambio, **sí** es copia limpia: el dispositivo es
ahora byte a byte el de la 21, así que su banco también debe serlo.

---

## Lo que esta migración le hizo a los tests compartidos `[TODAS]`

Tres tests fallaron al ganar la 16 `frame_capture`, y **los tres tenían razón en
fallar**: codificaban «la 16 no captura», que era verdad y dejó de serlo.

Dos se actualizan y ya. El tercero es más interesante:

`test_una_capacidad_no_se_declara_por_nombrarla_en_un_comentario` es un control
negativo cuyo **sujeto era la 16**. Existe porque un comentario de
`16/video_registers.v` que decía que `HALT_AT` *no* está allí hacía casar el
patrón, y la 16 declaraba `frame_capture` sin tenerlo. Al migrar, la 16 tiene el
registro de verdad: **el sujeto del control negativo dejó de ser negativo**.

No se arregla buscando otra carpeta —cualquiera puede ganar la capacidad mañana
por el mismo camino y el test volvería a romperse por una razón que no es la
suya—. Se reconstruye la **forma** del fallo en un fichero sintético: un módulo
que menciona el registro sólo en un comentario, más su mitad positiva, un módulo
que sí lo implementa, para que el test no pueda pasar por no ver nada.

> Un control negativo anclado en un caso real caduca cuando el caso real se
> arregla, y caduca **en verde o en rojo según la suerte**. Si el caso puede
> dejar de serlo, ancla la forma y no el caso. `[TODAS]`

### Y un fallo que no es de MMIO, destapado por haber sintetizado

Tras construir la 6, `test_apio_ausente_da_mensaje_util` empezó a fallar en la
suite completa y a pasar en aislado. La causa no era interacción entre tests
sino **estado del disco**: `board.upload` tiene dos ramas —con bitstream fresco
llama a `fujprog` directo, y si no a `apio upload`— y cuál se toma depende de si
la carpeta está construida.

El test se escribió contra un árbol sin construir, así que siempre medía la rama
de `apio`, donde el `FileNotFoundError` **sí** estaba tratado. La de `fujprog`
no lo estaba. En cuanto alguien sintetiza la 6, la misma prueba deja de
comprobar el mensaje y se lleva una traza.

Arreglados los dos: el `try/except` que faltaba en la rama de `fujprog`, y el
test, que ahora fuerza **las dos ramas** en vez de dejar que la elija el disco.
Control negativo: quitado el `try/except`, falla ese test y sólo ése.

> Un test cuyo camino lo elige un artefacto que no está en git mide una cosa
> distinta cada día, y lo hace en silencio: el día que cambia de rama no avisa
> de que ha cambiado, sólo de que falla. `[TODAS]`

### Y el mismo analizador roto por tercera vez, ahora en `tools/`

Al regenerar la documentación al cerrar, la tabla de
`docs/resumen-prototipos.md` salió diciendo que el monitor de la **6** es
**1.0**. Es 3.6.

La causa es la misma de la bitácora de la 6, en una **tercera copia** del mismo
analizador: `tools/rtl_facts.py` busca `monitor #(` sobre el texto crudo. El
comentario del `top.v` de la 6 que explica de dónde sale `MONITOR_VERSION`
ganaba, y como esa coincidencia no lleva `VERSION_MAJOR`, la función **se caía
al `localparam` de `monitor.v`, que son los valores por defecto**.

Lo que lo hace peor que las otras dos veces: **no reventó**. Un `1.0` es una
versión perfectamente plausible, y se publicó en una tabla generada. Las otras
dos copias fallaron ruidosamente; ésta escribió un número falso y se quedó tan
ancha.

Dos arreglos, y el control negativo separa cuál hace qué:

| | Efecto |
|---|---|
| `re.search` → `re.finditer` | recorre todas las coincidencias y se queda con la que lleva los parámetros. **Es lo que cura el síntoma real** |
| `sin_comentarios()` | impide que gane un comentario que **sí** parezca completo — un comentario de bloque con `VERSION_MAJOR` dentro, que el `finditer` aceptaría |

Medido: con el filtro de comentarios quitado pero el `finditer` puesto, la 6
vuelve a decir 3.6 y **sólo falla el test nuevo**, que es el que cubre el
segundo caso. Las dos mitades hacen falta y ninguna sustituye a la otra.

Y lo que evita la cuarta copia: `sin_comentarios` vive ahora **una sola vez**,
en `tools/rtl_facts.py`, y `x.tests/test_monitor_port.py` la importa en vez de
tener la suya, que es lo que `AGENTS.md` lleva pidiendo desde el principio.

> Tres analizadores con el mismo fallo en el mismo día, y **el que importaba era
> el silencioso**. Los dos que reventaron se arreglaron en minutos; el que
> escribió un número plausible en un documento generado sólo se vio porque
> alguien miró la tabla. Cuando encuentres un fallo de parser, **busca sus
> copias antes de darlo por arreglado**. `[TODAS]`

---

## Lo que costó cero: los cinco `.asm`

Medido antes de tocarlos, y es la regla de la 18 confirmándose por tercera vez:
**los seis `examples` de la 16 son byte a byte los de la 18 y la 19
pre-migración**. Así que la fase entera fue copiar los ya migrados de la 18 y
cambiarles el `.include` a `mmio_v1.inc` para quedarse en el punto intermedio.

Validado palabra a palabra contra un «esperado» construido del original —no por
tamaño ni por `pc`, que es lo que la 19 demostró que no comprueba nada:

| Programa | Palabras | Crecimiento | Veredicto |
|---|---:|---:|---|
| `swap_demo_fast` | 75 | +1 | idéntico |
| `tear_demo_fast` | 62 | +1 | idéntico |
| `swap_demo` | 42 | +1 | idéntico |
| `tear_demo` | 37 | +1 | idéntico |
| `swap_smoke` | 19 | +1 | idéntico |

Los cinco crecen +1, que es la regla de la 21 —se alargan los que cargaban la
base con un `MOVHI` suelto— cumpliéndose por cuarta vez. Y los cinco números son
**los mismos que midió la 18**, como tenían que ser.

Control negativo, con el detalle que importa en la tercera columna:

| Mutación | Resultado | Palabras |
|---|---|---:|
| `SWAP` simbolizado como `FB_BACK` | **DIFIERE en 2 palabras** | 42 |
| base de VIDEO cambiada por la de SERIAL | **DIFIERE en 1 palabra** | 42 |

**42 palabras en los dos casos.** Una comprobación de tamaño o de `pc` final
habría pasado las dos.

Con el RTL ya en v2, los cinco pasaron de `mmio_v1.inc` a `mmio.inc` —una línea
por fichero— y quedaron **byte a byte los de la 18**. Es la tercera migración
independiente que converge al mismo texto.

La guarda se añadió **antes** de tocar nada, como manda el encargo, y falló al
instante nombrando los cinco ficheros. A partir de ahí fue la lista de trabajo:
cuando dejó de fallar, la fase estaba hecha.

---

## Temporización

La semilla 1 queda invalidada por el cambio de RTL, y esta vez no es
precautorio: con ella la síntesis post-migración da **98,07 MHz contra 100
exigidos, FAIL**.

La 16 es la carpeta con menos holgura de las tres —iba a +5,0 %— y la única que
se lleva área de verdad: `cpu_perf_counters` (+180 LUT en la 18) y
`video_registers` (+90).

### v2 SÍ cuesta frecuencia aquí, y es la primera carpeta donde pasa

Las cinco anteriores dijeron que no. La 16 dice que sí, y con el mismo juego de
ocho semillas que su `apio.ini` tenía escrito:

| | Cumplen | Rango | Mejor |
|---|---|---|---|
| v1 (su `apio.ini`, mismas 8 semillas) | 7 de 8 | 96,58 – 105,03 | **+5,0 %** |
| v2, recién migrada | **0 de 8** | 93,54 – 99,63 | ninguna |
| v2, ampliado a 9–16 | **0 de 8** | 90,32 – 96,08 | ninguna |

**Cero de dieciséis.** No es la semilla: la distribución entera se fue por
debajo de la restricción. Ampliar el barrido, que es lo primero que uno
intenta, no salva esto y sólo sirvió para descartarlo.

No hizo falta rehacer el control de v1 como en la 6: **el de la 6 ya demostró
ese mismo día que la herramienta reproduce los números antiguos al dígito**, así
que el `7 de 8, 96,58 – 105,03` escrito en el `apio.ini` es comparable.

### Dónde está el camino crítico, medido y no supuesto

El `apio.ini` de la 16 deja una pista escrita, de cuando perdió 15 MHz con
WRITE_WORD:

> «Si hace falta recuperar holgura aqui, ese mux [`req_wdata`/`req_wmask`] es el
> primer sitio donde mirar: se puede registrar a costa de un ciclo por acceso
> del monitor.»

**Y la pista es falsa hoy.** Extraído el camino crítico del `build.log`
post-migración, ese mux no aparece por ningún lado:

```text
adapter_i.mmio_address_TRELLIS_FF_Q_28.Q          <- el bit 28 de la direccion
  -> mmio_decoder.v:69                            <- eleccion de bloque
  -> registers_i.video_mode ...
  -> adapter_i.saved_cpu_read ...
  -> adapter_i.mmio_select ...
```

Empieza en **`mmio_address[28]`**, un bit que sólo existe porque v2 ensancha la
dirección de 12 a 32, cruza el decodificador y el dispositivo, y **vuelve a
entrar en la lógica de próximo estado del propio adaptador**. Es un lazo
combinacional de un ciclo entero.

Y ahí está la razón de que esto le pase a la 16 y no a las otras cinco:

> La 18, la 19 y la 21 tienen `mmio_mux` entre el adaptador y el decodificador,
> y ese mux **parte ese camino**. La 16 no tiene mux: su arbitraje vive dentro
> de `sdram_system_adapter.v`, así que el adaptador habla con el decodificador
> y con el dispositivo y se escucha a sí mismo, todo en el mismo ciclo. `[16]`

O sea que el coste no es el área de `cpu_perf_counters` ni la de
`video_registers`, que era la sospecha razonable y la que el propio encargo
insinúa. Es **estructural**, y es exactamente la diferencia de forma que el
encargo señala sin saber que tenía esta consecuencia.

> Una nota de `apio.ini` que dice «si hace falta holgura, mira aquí» es una
> hipótesis con fecha, igual que todo lo demás. Aquélla era correcta para el
> netlist de WRITE_WORD y dejó de serlo cuando el mapa cambió lo que entra al
> decodificador. **Extrae el camino crítico del `build.log` antes de tocar
> nada**: cuesta un `Select-String` y evita optimizar el sitio equivocado.
> `[TODAS]`

### El arreglo: un ciclo, y dónde NO ponerlo

Se parte el lazo registrando **la respuesta** del MMIO dentro del adaptador:
`STATE_MMIO_WAIT` ya sólo captura `mmio_read_data` y `mmio_error` en dos
registros nuevos, y un estado nuevo, `STATE_MMIO_DONE`, decide qué hacer
mirando **únicamente registros propios**.

Dos cosas que no se hicieron, y las dos por lecciones ya pagadas:

- **No se alarga `mmio_select`.** Sigue siendo un pulso de un ciclo: alargarlo
  dispararía dos veces los registros con efecto secundario, que es el bug que
  `mmio_mux.v` documenta —un `LOAD` comiéndose dos caracteres y un `STORE`
  mandando el byte dos veces—.
- **Se captura con `select` alto**, no después. El error del dispositivo es
  combinacional y vive poco; mirarlo un ciclo tarde es literalmente el bug de
  RTL que la fase 8 de la validación en placa acaba de arreglar.

El coste es **un ciclo por acceso MMIO**, que es lo que la nota del `apio.ini`
ya daba por aceptable cuando proponía registrar el otro mux.

### Y el camino se movió a su gemelo, que era lo esperable

Con el registro puesto, el crítico pasa a ser el lado de **escritura**:

```text
adapter_i.mmio_address[28] -> logica de mmio_write
  -> registers_i.fb_front_TRELLIS_FF_Q_13.CE
```

La misma forma por el otro lado: de la dirección registrada al clock-enable de
un registro del dispositivo, cruzando el decodificador. Partirlo del todo sería
registrar también los `select` del decodificador, o sea **darle a la 16 el mux
que tienen las otras tres** — que ya no es migrar un mapa, es rehacer su
arquitectura de bus.

No hizo falta llegar ahí:

| | Cumplen | Rango | Mejor |
|---|---|---|---|
| v2 sin registro | 0 de 16 | 90,32 – 99,63 | ninguna |
| **v2 con registro** | **3 de 8** | 96,48 – 102,24 | **102,24 (s8, +2,2 %)** |

**La 16 vuelve a cerrar**, con menos holgura que antes —+2,2 % contra el +5,0 %
de v1—, y eso es el precio honesto de v2 en esta carpeta.

Y la trampa de lectura, otra vez: el `build.log` trae la temporización **dos
veces** y la buena es la última. Aquí la estimación pre-rutado daba 80,53 MHz,
casi veinte por debajo del número real.

---

## Verificación al cerrar

| Qué | Base (fase 0) | Ahora |
|---|---|---|
| `tools/test --prototype 16` | SUCCESS, 12 bancos | **SUCCESS**, 12 bancos |
| `tools/lint --prototype 16` | 35 PIN / 29 WIDTH / 1 CASE / 1 MISINDENT | **idéntico por tipo** |
| `unittest` de `x.tests` | 284 OK | **284 OK** |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | 53 casos, 0 fallos |
| `unittest` de `1.isa` / `2` / `11` | 61 / 44 / 62 | 61 / 44 / 62 OK |
| `generate-mmio --check` | al día | al día |
| Guarda de `.asm` cableados | no cubría la 16 | **la cubre y pasa** |

---

## Qué salió más barato y qué más caro `[16]`

**Más barato de lo estimado:**

- **Los `.asm`**, que el encargo trata como una fase y fueron un `Copy-Item`.
- **Tres de los cinco ficheros MMIO**, que el encargo no cuenta como copiables.
- **El subsistema de vídeo**, que parecía el bloqueo de la decisión del bitmap y
  resultó ser otra copia más un OR.

**Más caro de lo estimado:**

- **`sdram_system_adapter_tb.v` y `cpu_video_tb.v`**, que son los dos bancos que
  la 16 no comparte con nadie. Los bancos siguen siendo donde se va el tiempo,
  quinta carpeta seguida.
- **Los tests compartidos que rompió ganar una capacidad.** No estaba en ninguna
  estimación: migrar una carpeta puede hacer **verdadera** una afirmación que
  tres tests tenían escrita como falsa.
- **Razonar el bitmap.** El encargo lo presenta como una decisión de coste y es
  una decisión de mantenimiento; medirlo bien costó más que aplicarlo.

# Migración de la 6 a MMIO v2

Log de trabajo, escrito **durante** la migración. El orden de las secciones es
el orden real, no el del plan.

Contrato de referencia: [`../../1.isa/mmio.md`](../../1.isa/mmio.md).

**Este fichero es el cuarto y sólo escribe la diferencia.** Los tres anteriores
son [la bitácora de la 21](../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md) —el
camino completo—, [la de la 19](../../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md)
—lo que cambió al repetirlo— y [la de la 18](../../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md)
—hasta dónde llega el atajo de copiar—. Encima de las tres está
[la validación en placa](../../docs/validacion-mmio-v2-placa.md), que es lo que
sólo se ve cuando el bitstream existe.

La **fase 0 de este documento cubre las tres carpetas** de este encargo —la 6,
la 10 y la 16—, porque se verificó una vez. Las bitácoras de la
[10](../../10.fpga-cpu-ram/docs/migracion-v2.md) y la
[16](../../16.fpga-cpu-hdmi/docs/migracion-v2.md) enlazan aquí en vez de
repetirla.

**Alcance de cada decisión**, con la misma marca que las otras tres:

- `[TODAS]` vale para las diez carpetas.
- `[CPU]` vale para la familia CPU (6, 10, 16, 18, 19, 21).
- `[6]` es específico de esta carpeta.

---

## Fase 0 — Verificación del punto de partida `[TODAS]`

El encargo se declara hipótesis y pide verificar cada dato. Hecho, **sin
modificar nada**. Es la fase 0 más limpia de las cuatro: de las afirmaciones
concretas del encargo **no falla ninguna**. Lo que aparece son cinco cosas que
el encargo no dice, y dos de ellas cambian el plan.

### Lo que se confirma, dato a dato

| Afirmación del encargo | Medido |
|---|---|
| Monitores 3.6 / 3.10 / 3.16 | ✓ exactos |
| Capacidades `mul_div` / — / `mul_div`+`video`+`perf_counters` | ✓ exactas |
| `.v` sin bancos / bancos: 11/7, 11/7, 20/12 | ✓ las tres |
| `examples`: 0 / 0 / 6, y **5 tocan MMIO** | ✓ (`fpga_smoke_test.asm` es el que no) |
| Semillas fijadas 4 / 2 / 1 | ✓ |
| Los siete `sysid.v` de v1 comparten hash | ✓ `E79538C7B9F0…`, los siete |
| `sysid_selected` en `6/top.v:83` y `10/top.v:140` | ✓ línea exacta |
| La 6 y la 10 no tienen `mmio_decoder.v`, `mmio_mux.v` ni `video_registers.v` | ✓ |
| La 16 no tiene `mmio_mux.v` ni `cpu_dmem_adapter.v`, y monta `sdram_system_adapter.v` | ✓ |
| `VIDEO_REGISTERS(64'h4f)` correcto hoy, y faltan `DEVICES`/`MEM_*`/`MONITOR_VERSION` | ✓ `16/top.v:379` |
| `MONITOR_VERSION` de la 16 = `0x0310` | ✓ el `monitor #(...)` dice 3.16 |
| El bitmap de la 16 quedaría contiguo, `0x1f` | ✓ comprobado contra `mmio_map.vh`, no creído |
| Cero `test.json` apuntan a 6/10/16 | ✓ |
| `CARPETAS` no cubre los `examples` de la 16 | ✓ |
| 53 casos de `cpusim` con 0 fallos, 61 / 44 / 62 | ✓ |

### Lo que el encargo no dice, y cambia el plan

**1. El árbol no estaba limpio: la ronda de placa entera estaba sin commitear.**
16 ficheros modificados y 4 sin seguimiento —el arreglo de RTL de
`video_registers.v` ×3, los tres `mmio_error_ack_tb.v`, los tres arreglos de
`backends/fpga.py`, los dos `monitor.py`, las tres semillas y el propio
documento de validación—. Es exactamente el riesgo que la fase 0 de la 18
escaló: cuatro migraciones acumuladas y ningún punto de retorno, justo antes de
tocar `x.tests` y RTL compartido. Se hizo checkpoint (`4c89282`) antes de nada,
como se hizo con `5fc229f` antes de la 18.

> Van **dos de dos**: las dos veces que una migración ha ido a empezar, el
> trabajo de la anterior estaba sin commitear. No es despiste de nadie en
> concreto, es que declarar una carpeta terminada y commitearla son dos actos
> distintos y sólo el primero tiene quien lo recuerde. `[TODAS]`

**2. La base de `x.tests` es 284, no 279.** No es una contradicción: el fichero
sin versionar `x.tests/test_run_tests_prototype.py` aporta exactamente cinco, y
el encargo se escribió antes. El número a no empeorar es **284**.

**3. El atajo de copiar llega a la 16 mucho más lejos de lo que dice el
encargo.** Medido con `git hash-object` contra `5fc229f^`:

| Fichero de la 16 | ¿Es el pre-migración de 18/19/21? |
|---|---|
| `mmio_decoder.v` | **sí**, `1c3c2f0704` idéntico en las cuatro |
| `cpu_perf_counters.v` | **sí**, `66f67e4320` |
| `sysid.v` | **sí**, `a3930bc25f` |
| `video_registers.v` | **no** — el suyo, cinco registros |
| `sdram_system_adapter.v` | **no** — su bloque único |

El encargo dice «la 16 sí es una migración de verdad, pero con otra forma». Es
cierto, pero la forma distinta se reduce a **dos ficheros**: tres de los cinco
se copian ya migrados.

**4. La decisión del bitmap de la 16 tiene el coste al revés.** El encargo dice
que conservar los cinco registros «es más barato». Medido, es lo contrario, y
está desarrollado en [la bitácora de la 16](../../16.fpga-cpu-hdmi/docs/migracion-v2.md).

**5. Dos cosas del punto de partida que el encargo no mide y cambian la
estimación:**

- **La restricción de las tres es 100 MHz, no los 80 de la familia 18/19/21.**
  Y los márgenes de partida son cortos: la 6 iba a +4,4 % y la 16 a +5,0 %.
- **El lint de la 10 y de la 16 ya trae avisos de anchura**, 21 y 29
  `WIDTHEXPAND`. Las tres migradas partían de cero, así que «no empeorar por
  tipo» aquí arranca de otro sitio. Bases medidas: **6** → 18 `PINMISSING`;
  **10** → 20 `PINMISSING` + 21 `WIDTHEXPAND`; **16** → 35 `PINMISSING` +
  29 `WIDTHEXPAND` + 1 `CASEINCOMPLETE` + 1 `MISINDENT`.

### Estado de la fase 0

Verificación hecha. Lo único que se modificó fue crear el checkpoint.

---

## Qué es migrar la 6, exactamente `[6]`

El encargo lo dice bien y conviene repetirlo porque es lo que hace a esta
carpeta la más barata que existe en el repo: **migrarla no es darle MMIO**. Su
`top.v` lo dice con todas las letras y sigue diciéndolo. Es mover el bloque de
identificación de `0x80000F00`, donde eran cuatro palabras, a `0x80000000`,
donde son siete. No aparece ningún dispositivo, ningún decodificador y ninguna
página de periféricos.

Lo tocado, entero:

| Fichero | Qué le pasa |
|---|---|
| `sysid.v` | copiado ya migrado de la 21, byte a byte |
| `top.v` | la selección, los parámetros del bloque y la ventana del monitor |
| `monitor.py` | la región, y por qué **no** gana `MMIO_BASE`/`MMIO_LIMIT` |
| `sysid_host_tb.v` | las siete palabras, y dónde acaba el bloque |
| `monitor_tb.v` | una línea, la ventana |

Y dos ficheros compartidos que esta migración tuvo que arreglar, más abajo.

---

## La decisión de diseño de la 6: siete palabras no son una potencia de dos `[CPU]`

Es la única decisión de esta carpeta, y no está en el encargo.

En v1 la selección era una comparación limpia:

```verilog
wire sysid_selected = mem_address[31:4] == 28'h800_00f0;   // 16 B = 4 palabras
```

Cuatro palabras ocupan dieciséis bytes, así que un solo comparador acota el
bloque exacto. **Siete palabras ocupan veintiocho**, que no es potencia de dos.
Lo barato sería:

```verilog
wire sysid_selected = mem_address[31:5] == 27'h400_0000;   // 32 B = 8 palabras
```

…y eso cubre **ocho**. La palabra 7, en `+0x1C`, no existe: contestaría el
`default` del módulo, que es **cero**. §5 lo prohíbe expresamente —«el resto del
bloque da error: no devuelve cero ni repite las palabras por alias»— y hay una
razón concreta detrás: **cero es un valor perfectamente legítimo para varios de
los registros de al lado**, así que un host que sondee no distingue «no existe»
de «vale cero». Es §5.6 con un ejemplo.

Lo que se hizo, en la 6 y en la 10:

```verilog
wire sysid_selected = (mem_address[31:5] == 27'h400_0000) &&
                      (mem_address[4:2] != 3'd7);
```

Con eso `+0x1C` cae en `memory_map`, que ya da error de dirección para todo lo
que no es RAM. No hay ruta de error nueva: se reutiliza la que existía, que es
la misma estructura que tenía v1 para las palabras 4 a 63 del slot. Y es el
mismo criterio que `mmio_decoder.v` aplica con `offset[7:2] > 6'd6` en las
carpetas que sí tienen decodificador — sólo que aquí no hay decodificador donde
escribirlo.

> Un bloque cuyo tamaño no es potencia de dos necesita **dos** comparaciones, y
> la segunda es la que cumple el contrato. La primera sola compila, sintetiza,
> pasa todos los bancos que había y contesta un cero plausible en la dirección
> que no existe. `[TODAS]`

### El control negativo, que es el que justifica el párrafo anterior

El banco pasó a la primera después de mover el bloque entero, que es justo
cuando hay que desconfiar. Devuelta la selección a la versión barata de
`[31:5]`:

```text
FATAL: sysid_host_tb.v:33: SYS_ID 8000001c wr 0 err 0
```

Falla **exactamente** en `8000001c` —la palabra 7—, en la lectura, con
`err 0`, y **no falla nada más**. Eso es lo que lo hace un banco y no una
alarma. Lo mismo, clavado, en la 10.

---

## Los dos ficheros compartidos que esta migración tuvo que arreglar `[TODAS]`

Los dos son analizadores, los dos fallan por lo mismo, y **uno de ellos lo
escribí yo en esta misma sesión**. Es el patrón que las tres bitácoras
anteriores llevan documentando: la herramienta que vigila un fallo silencioso lo
comete.

### 1. `monitor_instantiations` encontraba una instancia que no existe

Al migrar la 6, `test_python_and_rtl_agree` falló diciendo que al RTL le faltaba
la ventana que `top.v` declara dos líneas más arriba. La causa: el comentario
que puse en la instanciación de `sysid` para explicar de dónde sale
`MONITOR_VERSION` dice *«con los mismos números que el `monitor #(...)` de más
abajo»*, y el parser busca `\bmonitor\s*#\(` sobre el **texto**. Casó con el
comentario, fabricó una instancia fantasma con la lista de parámetros vacía, y
esa instancia declara **cero** ventanas.

Es el mismo fallo que la migración de la 19 le encontró a
`puertos_del_monitor`, y por la misma causa. Arreglado donde toca —en el
analizador, `sin_comentarios()`— y **no reescribiendo el comentario**, porque
lo segundo obliga a todo el que edite un `top.v` a saber que hay un parser
mirando y a esquivarlo. Que el `top.v` de la 21 diga «el mismo que `monitor_i`»
en vez de «el mismo que el `monitor #(...)`» sugiere que alguien ya esquivó este
charco sin decirlo.

### 2. La guarda que escribí para la 6 saltó contra su propio comentario

La 6 y la 10 no tienen `parse_address`: su CLI valida con `MAX_ADDRESS` a secas.
Así que
`test_monitor_protocol.test_la_ventana_del_cli_cubre_los_bloques_que_decodifica`,
que exige `MMIO_BASE`/`MMIO_LIMIT`, iba a reventar con `AttributeError` en
cuanto la 6 entrara en su alcance.

**Se descartó darles el par de constantes.** Nada las leería: sería declarar un
filtro que esta carpeta no tiene, que es exactamente cómo el
`SERIAL_BASE = 0x8000_0200` de la 19 sobrevivió hasta que costó una sesión de
placa. Lo que se hizo es comprobar la **misma invariante** contra la constante
que esta carpeta usa de verdad, sin saltarse la carpeta —un filtro cuyo modo de
fallo por defecto es no ver es lo que dejó pasar esto la primera vez—.

Y la guarda que acompaña a eso, «si algún día gana un `parse_address`, declara
el par», la escribí con `assertNotIn("parse_address", fuente)`. Saltó
inmediatamente: **encontró la cadena dentro del comentario que acababa de
escribir para explicar que esta carpeta no tiene `parse_address`**. Reescrita
con `ast` para mirar las **definiciones**, que es la misma regla que
`test_mmio_map` aprendió con INT_MIN: no es el literal lo que distingue una
cosa, es el uso.

> Dos analizadores rotos en una tarde, los dos por mirar texto donde había que
> mirar estructura, y el segundo lo rompió el comentario que documentaba el
> primero. Si un comentario puede romper tu test, tu test lee el fichero
> equivocado. `[TODAS]`

Controles negativos de los dos, con `__pycache__` borrado entre pasadas:

| Mutación | Resultado |
|---|---|
| M1 `WINDOW0_END` de la 6 devuelta a `0x8000_0f10` | **falla**, y sólo `test_python_and_rtl_agree` |
| M2 la 6 define un `parse_address` sin declarar el par | **falla**, y sólo esa aserción |
| árbol restaurado | pasa |

M1 importa especialmente: demuestra que ignorar comentarios **no cegó** el test,
que era el riesgo del arreglo.

---

## Temporización: el resultado es el contrario del temido, y por eso hay control

Esta es la parte cara de la 6 y la que corrige la estimación del encargo.

### Por qué había que medirlo

El encargo estima que «la 6 y la 10 deberían costar casi nada — sólo tocan
`sysid`». En **área** acierta: las siete palabras son constantes y la validación
en placa ya midió que el bloque SYSTEM cuesta **+6 LUT**. En **temporización**
no lo sabía nadie, y esta carpeta es el peor sitio para suponerlo:

> «OJO, esto es lo mas justo del repositorio y hay que tratarlo como tal: aqui
> la semilla NO elige margen, elige si el diseno cumple.»
> — `6.fpga-cpu/apio.ini`

Y el mismo fichero nombra su camino crítico:
`mem_address -> sysid_ready -> memory_map_i.release_wait`. O sea **el camino al
que la migración le añade una comparación**. Con una carpeta que cumplía una de
ocho, la expectativa razonable era perder.

### Medido

`tools/build` primero y `build-sweep` después, en ese orden, porque el barrido
no sintetiza —re-ruta el último build archivado— y el de esta carpeta era
pre-migración. Las dos carpetas en paralelo en una sola llamada, que es la
corrección que dejó escrita la validación de placa.

| | v1, según su `apio.ini` | v2, hoy |
|---|---|---|
| Cumplen | **1 de 8** | **8 de 8** |
| Rango | 92,51 – 104,41 | **111,04 – 117,55** |
| Mediana | 97,05 | **115,54** |
| Mejor | 104,41 (s4, +4,4 %) | **117,55 (s4, +17,6 %)** |

La semilla fijada no cambia: la 4 sigue siendo la mejor. Lo que cambia es que
ya no es la única que cumple.

### Por qué esto no se dio por bueno

**Las ocho semillas de ahora baten al mejor de antes.** Eso no lo explica la
colocación, y una mejora que no se sabe explicar es tan sospechosa como un
empeoramiento. Pero hay una explicación aburrida y probable que el número de
arriba no descarta: **el `1 de 8` viene de una sesión antigua**, y compararlo
contra un barrido de hoy puede estar comparando dos versiones de la herramienta.

Es la trampa de «un máximo contra una muestra» que la validación de placa dejó
escrita, con otro disfraz: allí el error era comparar una semilla fijada contra
un barrido; aquí sería comparar dos barridos **separados en el tiempo por todo
lo demás que ha cambiado en la máquina**.

Así que se midió el control: la **6 pre-migración**, sacada del checkpoint a un
worktree, construida y barrida **el mismo día, con las mismas ocho semillas y la
misma herramienta**.

### El control, y reproduce el `apio.ini` dígito a dígito

La 6 de `4c89282` en un worktree, `tools/build` y después `build-sweep` con las
mismas ocho semillas, el mismo día y la misma herramienta:

| Semilla | v1, hoy | | v2, hoy | |
|---|---:|---|---:|---|
| 1 | 97,47 | NO | 115,85 | OK |
| 2 | 99,32 | NO | 117,30 | OK |
| 3 | 95,67 | NO | 114,80 | OK |
| **4** | **104,41** | **OK** | **117,55** | **OK** |
| 5 | 94,98 | NO | 115,23 | OK |
| 6 | 92,51 | NO | 113,33 | OK |
| 7 | 99,29 | NO | 116,90 | OK |
| 8 | 96,64 | NO | 111,04 | OK |
| **Cumplen** | **1 de 8** | | **8 de 8** | |
| **Mediana** | **97,05** | | **115,54** | |

El barrido de v1 medido hoy da **92,51 a 104,41, mediana 97,05**. El `apio.ini`
dice, escrito hace meses: «A 100 cumple UNA de ocho: la 4, con 104,41 MHz. El
resto va de 92,51 a 99,29, mediana 97,05». **Coincide dígito a dígito**,
incluidos los tres números del rango.

O sea que la hipótesis aburrida queda descartada: la herramienta no ha cambiado,
el registro histórico era válido, y **la mejora es del cambio**. La 6 pasa de
1 de 8 a 8 de 8 y de mediana 97,05 a 115,54, un **+19 %**.

### Por qué mejora: lo que se sabe y lo que no

Lo que **sí** está medido:

- No es que el diseño encogiera. Al contrario: **5 978 → 6 042 LUT**, +64, y los
  FF pasan de 2 622 a 2 624. Creció y va más rápido.
- No es la colocación: son ocho semillas contra ocho, y las ocho mejoran.

La hipótesis, que **no está verificada** y se deja escrita como tal: la
comparación de v1 es una igualdad de 28 bits contra `28'h800_00f0`, una
constante con unos repartidos, mientras que la de v2 es
`address[31] && ~|address[30:5]`, o sea **un bit y un NOR ancho** — la forma que
mejor mapea en un ECP5 — más un término de tres bits. Tener que comparar contra
ceros en vez de contra un patrón puede salir más barato aunque sean dos
comparaciones en vez de una.

Lo que haría falta para afirmarlo: un barrido de un tercer árbol con el `sysid.v`
de v2 pero la selección de v1. **No se ha hecho**, porque no cambia ninguna
decisión de esta migración y cuesta otro barrido entero. Queda anotado por si
alguien quiere el mecanismo, y sobre todo por si alguna de las de GPU sale al
revés: ahí sí habría que saber por qué.

> Un barrido anterior escrito en un `apio.ini` no es una linea base, es un
> **registro histórico**. Vale para saber qué pasó; no vale para atribuir una
> diferencia a tu cambio, porque entre las dos medidas cambió también todo lo
> demás. Si la diferencia es grande, reconstruye el estado anterior y mídelo
> hoy. `[TODAS]`

---

## Verificación al cerrar

| Qué | Base (fase 0) | Ahora |
|---|---|---|
| `tools/test --prototype 6` | SUCCESS, 7 bancos | **SUCCESS**, 7 bancos |
| `tools/lint --prototype 6` | 18 `PINMISSING`, 0 anchura | **18 `PINMISSING`, 0 anchura** |
| `unittest` de `x.tests` | 284 OK | **284 OK** |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | 53 casos, 0 fallos |
| `unittest` de `1.isa` / `2` / `11` | 61 / 44 / 62 | 61 / 44 / 62 OK |
| `check-links` | 660 en 184 `.md` | 660, ninguno roto |
| `generate-mmio --check` | al día | al día, los cuatro destinos |
| Barrido | 1 de 8 | **8 de 8**, semilla 4 fijada con su párrafo |

---

## Qué salió más barato y qué más caro `[6]`

**Más barato de lo estimado:**

- **El RTL.** Un `Copy-Item` de `sysid.v`, una comparación, cinco parámetros y
  una ventana. Es, como decía el encargo, la migración más pequeña del repo.
- **La temporización**, que era el riesgo señalado y salió a favor.

**Más caro de lo estimado, y es todo el tiempo de esta carpeta:**

- **Los dos analizadores compartidos.** No estaban en ninguna estimación y no
  son de la 6: son del repo. Que los destapara la carpeta más pequeña es la
  señal de que estaban esperando a cualquiera.
- **El control de temporización.** Un worktree, un build y un barrido enteros
  para poder afirmar una frase. Es caro y era obligatorio: sin él la línea
  «v2 mejora la 6 un 18 %» es una anécdota.
- **Decidir que la 6 NO lleva `MMIO_BASE`/`MMIO_LIMIT`.** Añadir dos constantes
  era un minuto; razonar que no deben estar y extender el test compartido para
  que la carpeta siga comprobada costó bastante más, y es lo que evita la
  siguiente gemela rancia.

**Lo que costó cero**, y conviene decirlo por cuarta vez: el mapa generado,
`.equ`, el test de anchuras, el de copias de `sysid.v` y el mapa de transición.

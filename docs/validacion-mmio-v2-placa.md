# Validación de MMIO v2 en silicio — barrido, síntesis y placa

Log de trabajo del encargo [`encargo-validacion-placa-v2.md`](encargo-validacion-placa-v2.md),
escrito **durante**, no al final. Cubre las tres carpetas que ya conforman con
[`1.isa/mmio.md`](../1.isa/mmio.md): la [18](../18.fpga-cpu-hdmi-bl8), la
[19](../19.fpga-cpu-hdmi-ls) y la [21](../21.fpga-cpu-hdmi-alu).

No repite las tres bitácoras de migración; las enlaza:
[21](../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md) (el camino completo),
[19](../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md) (lo que cambió al repetirlo),
[18](../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md) (la deuda de la que sale este
encargo).

---

## Fase 0 — Verificación del punto de partida

El encargo se declara hipótesis y pide verificar cada dato. Hecho, **sin
modificar nada**. A diferencia de la fase 0 de la 18 —donde cinco de nueve
afirmaciones no se sostuvieron—, aquí **el encargo sale limpio**: todos los
números que da se confirman. Lo que aparece es una cosa que el encargo no dice
y que cambia cómo hay que leer la tabla de áreas (ver más abajo).

### El árbol

| Qué | Esperado | Medido |
|---|---|---|
| Commit | `bfca66c` | **`bfca66c`** «18.fpga-cpu-hdmi-bl8: migracion a MMIO v2» |
| Árbol limpio | — | **sí**: un solo fichero sin seguimiento, este encargo |

El checkpoint `5fc229f` que la 18 negoció está ahí, un commit por debajo. Esta
vez sí hay a dónde volver antes de gastar una síntesis.

### Los números base, comando a comando

| Comando | Encargo | Medido | ¿Cuadra? |
|---|---|---|---|
| `tools/lint --prototype 18` | 39 `PINMISSING`, 0 de anchura | **39 `PINMISSING`**, único tipo, exit 1 | sí |
| `unittest` de `x.tests` | 278 OK | **Ran 278, OK** | sí |
| `run_tests.py --backend cpusim` | 53 casos, 0 fallos | **53 casos, 0 fallos**, 34 omitidos, 20,5 s | sí |
| `unittest` de `1.isa` / `2.cpu-sim-func` / `11.gpu-sim-func` | verdes | **61 / 44 / 62 OK** | sí |
| `check-links.py` | — | 644 enlaces en 182 `.md`, ninguno roto | — |
| `generate-docs --check` | al día | **al día** | sí |
| `generate-mmio --check` | al día | **al día**, los cuatro destinos | sí |

Un detalle de lectura que cuesta un susto: la salida de `unittest` de `x.tests`
contiene las cadenas `FAILED: fixtures` y `FAILED: tests Python, apio test`.
**No son fallos**: son texto que un test imprime al ejercitar su propio
verificador. El veredicto es la última línea, `Ran 278 tests ... OK`.

### El FAIL de la 21 se confirma, y el 79,90 está en el sitio que no se ve

`reports/20260920-101323-955327-build`, `exit_code: 1`, `state: failed`,
semilla 13. Pero el log tiene **dos** informes de temporización y sólo el
segundo vale:

```text
línea 192:  ... '$glbnet$sdram_clk$TRELLIS_IO_OUT': 65.32 MHz (FAIL at 80.00 MHz)
línea 623:  Warning: ... '$glbnet$sdram_clk$TRELLIS_IO_OUT': 79.90 MHz (FAIL at 80.00 MHz)
```

El primero es la estimación **antes de rutar**; el segundo, el número real
post-rutado, y es el que `generate-docs` recoge. Quien busque «Max frequency» en
un `build.log` y se quede con el primer acierto se lleva 65,32 MHz y un susto
que no es.

> Un `build.log` de nextpnr contiene la temporización **dos veces**. La buena es
> la última, y la primera es entre 10 y 20 MHz más pesimista. `[TODAS]`

`docs/synthesis-report.md` ya registra el FAIL, y el área `11 590 / 5 236` LUT/FF
está en `docs/resumen-prototipos.md`. Los dos datos del encargo, confirmados.

### Lo que el encargo no dice: la tabla de áreas mezcla v1 y v2

La fila de `resumen-prototipos.md` que sostiene el «+6,7 % de LUT» es ésta:

| | 6.ebr | 10.sdram | 16.hdmi | 18.bl8 | 19.subword | 21.alu |
|---|---|---|---|---|---|---|
| **LUT / FF** | 5 978 / 2 622 | 5 342 / 2 477 | 7 496 / 3 566 | 9 830 / 4 918 | 10 535 / 5 001 | **11 590 / 5 236** |

**Sólo la última columna es de v2.** La 18 y la 19 no se han sintetizado desde
su migración, así que sus 9 830 y 10 535 LUT son cifras **pre-migración**. O sea
que la tabla, tal como está hoy, invita a comparar la 21 migrada contra dos
vecinas sin migrar, y cualquier lectura de «cuánto cuesta v2» sacada de ahí
mezcla dos efectos: el mapa nuevo y la ALU extendida de la 21.

El único par comparable hoy es la 21 contra sí misma —10 867 → 11 590 LUT,
5 066 → 5 236 FF—, y es de donde sale el +6,7 %. Los barridos de la 18 y la 19
de este encargo son, de paso, lo que arregla la tabla: en cuanto terminen habrá
tres columnas de v2 y el coste se podrá repartir de verdad.

### Lo único que no se sostiene: la trampa 4 del encargo

El encargo dice que la receta de placa «está corregida en los README de las
tres; si la de alguna no lo está, es que se quedó atrás». Medido:

| Carpeta | Referencias al mapa v2 en el README | Receta |
|---|---:|---|
| 18 | 17 | `write-word` a `0x80200004/8/0/C` — **v2, correcta** |
| 19 | 17 | idéntica, **v2, correcta** |
| **21** | **0** | `write-byte 0x80000008 1` — **v1, la vieja** |

O sea que la que se quedó atrás es **la primera que se migró**, y no es un
descuido nuevo: la bitácora de la 19 ya lo anotó —«su README sigue documentando
`FB_FRONT` en `0x80000000`»— en la lista de cosas «anotadas y sin tocar». El
encargo hereda la frase optimista y no la vuelve a medir.

Importa para la sesión de placa, y en las dos direcciones:

- La **21** es la carpeta que el encargo manda llevar a placa primero, y su
  README es la única fuente escrita de la receta. Seguirlo tal cual escribe en
  `0x80000008`, que en v2 es **SYSTEM**.
- Eso es, literalmente, el **control negativo** que el encargo pide en su
  apartado «valida lo que midas»: escribir en la dirección de v1 y confirmar que
  da error de acceso. La receta caducada del README es el control negativo ya
  escrito, por accidente.

> Un encargo que dice «si alguna no está corregida es que se quedó atrás» está
> pidiendo que lo midas, no informándote. La que se queda atrás es la primera
> carpeta migrada, siempre, porque las lecciones que la corrigen se aprenden
> después de darla por buena. `[TODAS]`

### Estado de la fase 0

Verificación hecha, **nada modificado**. Ningún rojo que justifique parar antes
de gastar la primera síntesis.

---

## Fase 1 — Barrido de la 21

`tools/build-sweep --prototype 21 --seeds 1 2 3 4 5 6 7 8 --background`,
informe `20260920-105248-185024-sweep`. El propio lanzador avisa de lo que ya
sabíamos, que es la señal de que barre lo que toca:

```text
Aviso: el build de partida NO cumple timing; se barre igual.
```

Un detalle de lectura que cuesta diez minutos de confusión: el campo `Elapsed`
de `tools/build-status` es **`mm:ss`**, no `hh:mm`. Un `Elapsed: 00:11` recién
lanzado el barrido es **once segundos**, y leerlo como once minutos hace pensar
que la primera semilla se ha colgado. La forma de comprobar que nextpnr vive de
verdad es mirar su CPU acumulada dos veces separadas: si sube ~30 s en 30 s,
está trabajando a pleno.

### Resultado: 3 de 8, y la mediana por debajo del objetivo

| Semilla | `sdram_clk` | Margen | |
|---|---:|---:|---|
| 5 | **84,04 MHz** | **+5,1 %** | OK |
| 6 | 80,87 | +1,1 % | OK |
| 1 | 80,53 | +0,7 % | OK |
| 7 | 79,10 | −1,1 % | NO |
| 2 | 78,88 | −1,4 % | NO |
| 4 | 77,90 | −2,6 % | NO |
| 3 | 75,87 | −5,2 % | NO |
| 8 | 70,09 | −12,4 % | NO |

Rango 70,09 a 84,04, **mediana 78,99**, o sea por debajo de los 80 exigidos.
Los otros dos relojes van sobrados en las ocho (`clk_pix` 96,5–109,8 contra 25;
`clk_pix_5x` 255,7–381,5 contra 125), así que el único que decide es `sdram_clk`,
el handshake de memoria de siempre.

Leído a solas, esto es el «para y dímelo» del encargo: **una** semilla con
holgura de verdad y dos raspadas. Pero leerlo a solas es justo el error.

### La comparación que cambia la respuesta

El `apio.ini` de la 21 es una bitácora de barridos y lleva años siéndolo. El
último barrido **anterior a la migración** —el de después de SLT/SLTU, con el
RTL en v1— está ahí escrito, con las mismas ocho semillas:

| Semilla | v1 (pre-migración) | v2 (hoy) | |
|---|---:|---:|---|
| 1 | 79,37 FALLA | **80,53 OK** | mejora |
| 2 | 77,45 FALLA | 78,88 NO | mejora |
| 3 | 78,19 FALLA | 75,87 NO | empeora |
| 4 | 75,99 FALLA | 77,90 NO | mejora |
| 5 | 79,91 FALLA | **84,04 OK** | mejora |
| 6 | 79,57 FALLA | **80,87 OK** | mejora |
| 7 | 72,12 FALLA | 79,10 NO | mejora |
| 8 | 80,42 (+0,5 %) | 70,09 NO | empeora |
| **Cumplen** | **1 de 8** | **3 de 8** | |
| **Mejor** | 80,42 (+0,5 %) | **84,04 (+5,1 %)** | |
| **Mediana** | 78,78 | 78,99 | |

> **v2 no cuesta frecuencia en la 21.** Sobre el mismo juego de ocho semillas,
> el mapa nuevo pasa de **1 de 8 a 3 de 8**, el mejor margen sube de **+0,5 % a
> +5,1 %** y la mediana no se mueve (78,78 → 78,99). Seis de las ocho semillas
> van mejor que antes.

Eso responde la pregunta que abre el encargo, y con el número en vez de con una
impresión. Lo que el 79,90 de la semilla 13 medía no era el coste de v2: era que
**la 21 ya vivía al límite de los 80 MHz antes de migrar**. Su propio `apio.ini`
lo dice con todas las letras: las ocho de siempre dieron «SIETE fallos y un
aprobado raspado», y hubo que barrer hasta la 16 para encontrar margen. La 13
fue la única con holgura comparable al resto de la familia, y era holgura del
**netlist de v1**.

La migración cambió el netlist, la 13 perdió su suerte, y eso es exactamente la
lección que ese mismo fichero lleva escrita desde hace tres barridos:

> «La semilla NO es una propiedad del diseño, es una propiedad de un netlist
> concreto. Cualquier cambio de RTL, por tonto que parezca, invalida el barrido
> anterior.»

El FAIL del 20/09 es esa frase cumpliéndose por enésima vez, no un síntoma del
mapa nuevo. Y el corolario incómodo: si el criterio para alarmarse hubiera sido
«¿cumple la semilla fijada?», la 21 habría dado la alarma **también en v1**, y de
hecho la dio — por eso existe el barrido de dieciséis.

> Antes de atribuir un barrido malo al último cambio, busca el barrido anterior
> del **mismo juego de semillas**. Comparar «la semilla fijada de antes» contra
> «un barrido de ahora» compara un máximo contra una muestra, y siempre sale
> mal. `[TODAS]`

Como en v1 hizo falta llegar a la semilla 16 para encontrar los +8,9 %, se
extiende el barrido a **9–16** para que la comparación sea mejor-de-16 contra
mejor-de-16 y no mejor-de-16 contra mejor-de-8.

---

## Fase 2 — Barridos de la 18 y la 19, y la trampa que los precede

### El último build archivado de las dos es de ANTES de migrar

`build-sweep` no sintetiza: **re-ruta el `hardware.json` del build archivado más
reciente**. Y el más reciente de estas dos carpetas es del **17/09**:

| Carpeta | Último build archivado | ¿Post-migración? |
|---|---|---|
| 18 | `20260917-233848-504987-mmio-addr12` | **no** |
| 19 | `20260917-224349-689106-build` | **no** |
| 21 | `20260920-101324-045280-build` | sí, de hoy a las 08:13 |

O sea que lanzar `build-sweep --prototype 18` sin más habría barrido **el
netlist de v1**, y habría salido bien: la 18 daba 84,0 MHz antes de migrar. Un
barrido verde, ocho semillas medidas, un número para fijar en el `apio.ini`… de
un diseño que ya no existe. No hay nada en la salida que lo delate.

La 21 se libra por casualidad: alguien la sintetizó esta mañana, y por eso es la
única de las tres con un dato real de silicio. Es la misma casualidad que hizo
que `generate-docs --check` saliera rojo en la fase 0 de la 18.

> Un barrido no sintetiza. Antes de barrer una carpeta que ha tocado RTL,
> **comprueba la fecha del build de partida contra la del último cambio**, o
> ejecuta `tools/build` primero. El modo de fallo es un número plausible y
> completamente falso, y es peor que un error. `[TODAS]`

El encargo no lo menciona, y su paso 3 dice «barrido de la 18 y de la 19» a
secas. Aquí se ejecuta `tools/build` y después `build-sweep`, en el mismo trabajo.

### La 18: ocho de ocho

Síntesis con la semilla 4 de siempre: **85,21 MHz, PASS**. O sea que la semilla
que la bitácora daba por invalidada seguía cumpliendo.

| Semilla | MHz | | Semilla | MHz | |
|---|---:|---|---|---:|---|
| **6** | **88,76** | +11,0 % | 3 | 85,00 | +6,3 % |
| 1 | 87,29 | +9,1 % | 5 | 84,67 | +5,8 % |
| 4 | 85,21 | +6,5 % | 2 | 84,40 | +5,5 % |
| | | | 7 | 83,86 | +4,8 % |
| | | | 8 | 82,11 | +2,6 % |

**8 de 8**, 82,11 a 88,76, mediana 84,83. Se fija la **6**, +11,0 %.

Contra el barrido anterior (v1: 8 de 8, 81,34 a 94,53): mismo 8-de-8, el suelo
sube (81,34 → 82,11) y el techo baja unos 6 MHz. **Es la carpeta con más margen
de las tres.**

### La 19: de tres de ocho a seis de ocho

| Semilla | MHz | | Semilla | MHz | |
|---|---:|---|---|---:|---|
| **5** | **85,02** | +6,3 % | 7 | 81,52 | +1,9 % |
| 8 | 84,55 | +5,7 % | 4 | 81,51 | +1,9 % |
| 3 | 83,72 | +4,7 % | 1 | 78,32 | NO |
| 2 | 82,10 | +2,6 % | 6 | 77,58 | NO |

**6 de 8**, 77,58 a 85,02, mediana 81,81. Se fija la **5**, +6,3 %.

Y aquí está el resultado que más dice de todo el encargo, porque el barrido
anterior de esta carpeta es el peor que ha tenido y su `apio.ini` lo dejó escrito
con todas las letras: «tres de ocho es peor que cualquier barrido anterior de
esta carpeta y la mediana, 79,9, cae **por debajo** de la restricción. Este
netlist está al borde de verdad, no sólo mal colocado».

| | v1 (fase 3.5) | v2 (hoy) |
|---|---:|---:|
| Cumplen | 3 de 8 | **6 de 8** |
| Mediana | 79,9 (bajo el objetivo) | **81,81 (sobre el objetivo)** |
| Peor | 72,06 | 77,58 |
| Mejor | 84,99 | 85,02 |

**v2 arregla el 3-de-8 de la 19.** El diseño creció ~650 LUT y aun así el
barrido mejora en las cuatro columnas. O sea que aquel «al borde de verdad» era
colocación, que es justamente la primera de las dos razones que aquella misma
nota daba para no tocar RTL. La nota acertó en no tocarlo y se equivocó en el
diagnóstico.

### La respuesta a la pregunta que abre el encargo

> **v2 no cuesta frecuencia.** En ninguna de las tres, y en la 19 la gana.

| Carpeta | v1 cumplen | v2 cumplen | v1 mediana | v2 mediana | v1 mejor | v2 mejor |
|---|---|---|---:|---:|---|---|
| 18 | 8 de 8 | **8 de 8** | — | 84,83 | 94,53 (s4) | 88,76 (s6) |
| 19 | 3 de 8 | **6 de 8** | 79,90 | **81,81** | 84,99 (s4) | 85,02 (s5) |
| 21 | 7 de 16 | **7 de 16** | 79,74 | 79,50 | 87,09 (s13) | 84,04 (s5) |

Lo único que v2 se lleva de forma consistente es **el techo**: 6 MHz en la 18, 3
en la 21, cero en la 19. Lo que no se mueve es lo que decide si el diseño
funciona, que es cuántas semillas cumplen. Y el techo bajando con el área
subiendo es el mecanismo que estos `apio.ini` llevan años describiendo: el camino
crítico es el mismo handshake de memoria de siempre, sin un solo bloque de MMIO
dentro, y lo que cambia es cómo se coloca.

El FAIL de la 21 del 20/09 era **la semilla**. Y como control de que el barrido
mide el mismo netlist que aquel build, la semilla 13 reproduce **79,90 MHz
exacto**, al céntimo.

---

## Fase 4 — De dónde sale el +6,7 % de LUT, medido

El encargo pide repartir el coste entre tres sospechosos: el bloque SYSTEM (4 →
7 palabras), el decodificador (16 dispositivos de 256 B → bloques de 64 KiB) y
`video_registers` (+3 registros). **Dos de los tres son casi gratis, y el que
manda no está en la lista.**

### Cómo se midió

El área por módulo no está en ningún `build.log`: el flujo de apio aplana. Se
sintetizó el árbol **entero** de la 18 dos veces con
`synth_ecp5 -top top -noflatten`, una con el árbol pre-migración
(`git archive 5fc229f`) y otra con el de hoy, usando la lista de fuentes exacta
que apio le pasa a yosys —incluido `-DSYNTHESIZE`, sin el cual `sdram_model.v`
no compila—.

Se eligió la 18 porque es la que menos ruido mete: no tiene puerto serie, así
que ningún delta viene de ahí.

Dos avisos de método:

- Sintetizar un módulo **suelto** no vale: con los parámetros por defecto,
  `sysid` se colapsa a dos celdas porque sus salidas son constantes. Hace falta
  el árbol entero con las instanciaciones reales.
- yosys reporta los módulos parametrizados como `$paramod$<hash>\nombre`, y
  **el hash cambia cuando cambian los parámetros**. Comparar por nombre completo
  da módulos «que aparecen y desaparecen» y cuentas dobles; hay que agrupar por
  el nombre base.

La métrica son celdas `LUT4` y `TRELLIS_FF` a la salida de síntesis, antes de
empaquetar. No coincide en valor absoluto con los LUT post-rutado del informe
(+411 aquí frente a +634 empaquetados) porque el empaquetado mete `CCU2C` y
demás; lo que vale es **el reparto**.

### El reparto

| Módulo | ΔLUT4 | ΔFF | Qué cambió |
|---|---:|---:|---|
| `cpu_perf_counters` | **+180** | +33 | array en +0, `PERF_CTRL` en +0x100, `PERF_OVF0/1`, banderas de desbordamiento |
| `monitor_mem_adapter_128` | +91 | +19 | dirección de 12 a 32 bits |
| `video_registers` | +90 | **+80** | `HALT_TARGET`, `VIDEO_TX`, `FRAME_COUNT` propio de 32 bits |
| `monitor` | +42 | 0 | cuatro ventanas de 33 bits en vez de una (el `.v` **no se tocó**) |
| `mmio_decoder` | +40 | 0 | bloques de 64 KiB, `block = address[26:16]` |
| `mmio_mux` | +20 | +20 | `ADDR_BITS = 32` |
| `instruction_buffer` | +8 | 0 | colateral |
| `sysid` | **+6** | 0 | 4 → 7 palabras |
| `cpu_dmem_adapter` | **−66** | +20 | `address[31]` en vez de `address[31:12] == 20'h80000` |
| **Total submódulos** | **+411** | **+172** | |
| **Diseño entero** | **+411** | **+172** | cuadra sin residuo |

Los submódulos suman **exactamente** el delta del diseño, en LUT y en FF. No hay
nada escondido en el `top`.

### Las tres cosas que dice esta tabla

**1. El sospechoso principal del encargo es inocente.** El bloque SYSTEM pasa de
cuatro palabras a siete y cuesta **+6 LUT**, o sea el 1,5 % del total. Es obvio
en cuanto se mide: las siete palabras son **constantes**, y una constante no
cuesta lógica, cuesta cable. Que un registro «crezca» en el mapa no dice nada
sobre lo que cuesta en silicio.

**2. El que manda no lo menciona nadie.** `cpu_perf_counters` se lleva **+180
LUT, el 44 % del total** — más que el decodificador, el bloque SYSTEM y
`video_registers` juntos. Y es el módulo del que menos se ha hablado en las tres
bitácoras: sólo aparece en la 21, y como una línea de tabla.

**3. El camino de dirección salió a devolver.** `cpu_dmem_adapter` **encoge 66
LUT**. Detectar MMIO pasó de comparar veinte bits a mirar uno, que es
exactamente lo que la bitácora de la 21 predijo —«es más barato **y** más seguro:
un bit no se puede truncar al conectar un puerto»—. Es la única predicción de las
tres bitácoras que se puede comprobar con un número, y es correcta.

> Al estimar lo que cuesta un mapa nuevo, el número de registros engaña en las
> dos direcciones. Siete palabras de constantes son gratis; tres contadores con
> control y banderas de desbordamiento son casi la mitad del coste. **Cuenta
> lógica, no entradas de tabla.** `[TODAS]`

Y el corolario para las siete carpetas que quedan: el grueso del área de v2 vive
en los **contadores de rendimiento**, que son opcionales. Una carpeta sin
`cpu_perf_counters` —la 6, la 10— se lleva el mapa nuevo por bastante menos de lo
que costó aquí.

---

## Fase 5 — Semillas fijadas, síntesis y documentación

Las tres semillas fijadas con su párrafo en el `apio.ini`, como pide el paso 4
del encargo. Los tres builds definitivos salen **exactamente** donde dijo el
barrido:

| Carpeta | Semilla | Síntesis | Antes |
|---|---:|---:|---|
| 18 | **6** | **88,76 MHz** PASS | 84,01 (s4, v1) |
| 19 | **5** | **85,02 MHz** PASS | 83,92 (s4, v1) |
| 21 | **5** | **84,04 MHz** PASS | **79,90 (s13) FAIL** |

Y la trampa de lectura otra vez, por si alguien mira el log del build: los tres
imprimen primero una estimación pre-rutado de **65,25 / 60,88 / 65,09 MHz**, que
es un FAIL aparatoso y no significa nada. El número bueno es el segundo.

`tools/generate-docs` regenerado. `docs/synthesis-report.md` pasa de registrar el
FAIL de la 21 a **cero FAIL en todo el fichero**, y la fila de área de
`resumen-prototipos.md` queda por fin con las tres columnas en v2:

| | 18.bl8 | 19.subword | 21.alu |
|---|---|---|---|
| antes (mezclado v1/v2) | 9 830 / 4 918 | 10 535 / 5 001 | 11 590 / 5 236 |
| ahora (las tres en v2) | **10 464 / 5 088** | **11 182 / 5 171** | 11 590 / 5 236 |

Con eso el +6,7 % de la 21 deja de ser un número suelto: son **+6,5 %, +6,1 % y
+6,7 %**, y los FF suben **+170 en las tres, exactamente**. Tres migraciones
independientes con el mismo coste al flip-flop.

---

## Fase 6 — Placa

### El bitstream y la SDRAM

Programada la 21 con la semilla 5. La placa desaparece y vuelve sola, como
estaba anotado; no hay que replugar nada, hay que esperar.

**La matriz de DQ sale limpia: 128 casillas en 4 direcciones.** Es la
comprobación que el encargo pone por delante de todas, y con razón: el barrido
mide caminos dentro del chip y esto mide el pin.

### Lo que se confirmó, y lo que sólo se ve aquí

| Qué | Resultado |
|---|---|
| Bloque SYSTEM, las siete palabras de §20 | ✓ magic `0x4d474155`, id 21, `DEVICES 0x235`, monitor 4.21 |
| `HALT_TARGET` y `VIDEO_TX` responden | ✓ leen **y escriben**; el bug del bitmap `0x7f` está muerto en silicio |
| Serie en su sitio nuevo `0x80100000` | ✓ `DATA`/`STATUS`/`PEEK` responden; los 3 casos de serie pasan |
| Las cuatro ventanas del monitor | ✓ SYSTEM, SERIAL, VIDEO y CPU PERF dejan pasar lo suyo |
| Control negativo: escribir en `0x80000000` | ✓ **error de acceso**, el magic no se mueve, `FB_FRONT` intacto |
| `HALT_TARGET` tras reset | ✓ **cero**, o sea que no para a nadie (trampa 3, confirmada) |
| Matriz de DQ | ✓ 128/128 limpias |
| Los `.asm` de `examples/` | parcial — ver los dos `-fast` más abajo |

### La regresión que la placa destapó, y es la más importante de la sesión

`x.tests/backends/fpga.py` es **único y compartido por las diez carpetas**, y la
migración a v2 le cambió las **direcciones** y no la **semántica**. Tres cosas a
la vez, y ninguna daba error:

| Línea | Qué hacía | Por qué está mal en v2 |
|---|---|---|
| `_write_register(VIDEO_HALT_AT, swap or 0)` | metía un número de **intercambios** en `HALT_AT` | `HALT_AT` cuenta **frames** desde §9.6 |
| — | **nunca** escribía `HALT_TARGET` | arranca a cero: la alarma se consume y no para a nadie |
| `"frames": estado >> 16` | leía los frames de `STATUS[31:16]` | en v2 `FRAME_COUNT` es registro propio; ahí se lee **cero siempre** |

El síntoma eran **nueve `ERROR: La CPU no terminó en 20/30 segundos`**, uno por
cada caso de `cases/video/` —o sea todos los que usan `run_until: {swap: N}`—,
248 s de reloj tirados en esperar paradas que nadie iba a ordenar. Es palabra por
palabra lo que la trampa 3 del encargo anuncia: «el síntoma es un timeout, que no
se parece a la causa». Lo que el encargo no dice es que **el arnés que se cuelga
es el suyo**.

Y hay una asimetría que explica cómo sobrevivió: el **simulador sí** recibió las
dos correcciones en su día —`stop_after_swaps`, que no es MMIO, y el filtro por
`halt_target & HALT_TARGET_CPU`— con sus comentarios explicando exactamente esta
trampa. El backend de placa, gemelo suyo, no recibió ninguna. Nadie lo notó
porque **ningún camino automático ejecuta el backend de placa**: hace falta una
placa enchufada.

> Cuando una migración toca una pareja de gemelos —simulador y placa— y sólo uno
> tiene ejecución automática, el otro se queda atrás en silencio y con el mapa
> nuevo puesto, que es peor que quedarse con el viejo: las direcciones responden,
> así que parece migrado. **Migrar una dirección no es migrar su semántica.**
> `[TODAS]`

### El arreglo, y por qué no es armar la alarma

Se hizo lo mismo que el simulador y por el mismo motivo escrito en su código:
`run_until` es una **condición de observación del arnés**, no un registro que el
programa vea, así que no se traduce al contrato. El host sondea `SWAP_COUNT`
mientras la CPU corre y la para al llegar. `HALT_AT` y `HALT_TARGET` se escriben
a **cero** siempre, para desarmar y no heredar la alarma del caso anterior.

Y una segunda mordida, que costó una pasada entera: `SWAP_COUNT` y `FRAME_COUNT`
son del **dispositivo de vídeo**, no de la CPU. `reset_cpu` no los toca y sólo el
reset de la placa los pone a cero, así que llegan al caso valiendo miles —se
midió `0x29ea`, 10 730—. Con la condición escrita como `swaps >= N` la parada
saltaba **en el primer sondeo**, antes de que el programa dibujara nada: nueve
frames en blanco fallando en el píxel 0. Hay que medir el **delta** contra una
línea base tomada justo antes de arrancar, y lo mismo para lo que se informa.

Se consideró poner los contadores a cero en vez de restar. **No se puede, y lo
decide el RTL:** `SWAP_COUNT` es de solo lectura
(`video_registers.v:383`). `FRAME_COUNT` sí se puede, pero sólo como efecto
secundario de escribir `HALT_AT` (`:377`) — y escribir `HALT_AT` es justamente lo
que este arreglo elimina; usarlo para reiniciar un contador sería armar una
alarma de refilón.

Lo bonito es que el RTL ya tenía este mismo fallo, para `FRAME_COUNT`, y lo
arreglaron en hardware. El comentario de `video_registers.v:366-374` dice:

> «Sin esto un programa sólo puede usarla una vez por arranque de la placa. El
> simulador construye el dispositivo de cero en cada ejecución, así que allí no
> se nota — **es un fallo que sólo da la placa, y ya lo dio una vez**.»

En `SWAP_COUNT` no podían arreglarlo en hardware, porque es de solo lectura por
contrato. Y ahí es donde el arnés volvió a pisarlo, cinco meses después.

### Resultado

| | Antes | Parada | Doble buffer | Memoria a cero |
|---|---|---|---|---|
| Casos | 53 | 53 | 53 | 53 |
| **Fallos** | **12** | 5 | 3 | **1** |
| Timeouts de vídeo | **9** | 0 | 0 | **0** |
| Reloj | 248,4 s | 36,3 s | 36,3 s | **36,6 s** |

**Tres arreglos independientes en el mismo fichero compartido**, y ninguno tenía
que ver con MMIO:

1. **La parada** (`HALT_AT`/`HALT_TARGET` con semántica de v1): nueve timeouts.
2. **El doble buffer**, en dos vueltas: la paridad del intercambio pendiente y
   después la espera a que no quede ninguno, porque la primera corrección metió
   su propia carrera.
3. **La memoria de los volcados**, que el simulador da a cero y la placa no: los
   dos `bresenham-*-core`, y 29 casos más que fallaban por suerte.

El único fallo que queda, `shared-video-fb-desalineada`, es el que **no** es del
arnés, y sale igual en las tres carpetas.

Los nueve casos de vídeo paran, y **paran exactos**: instrumentado el sondeo,
`pedidos=24 detectado=24 tras_halt=24` y `40/40`, en los rápidos y en los lentos.
No hay sobrepaso.

### Los cinco que quedan, y lo que se sabe de cada uno

**1 y 2. `video-starfield-fast` y `video-swap-demo-fast`** — **resuelto, y mi
primer diagnóstico era falso.** Se deja escrito el error porque es instructivo.

Lo que escribí con el árbol rojo: que los dos comparan contra el frame esperado
de su variante lenta, que el README tabula 240 líneas de repinte contra 32, y
que por tanto la igualdad «rápido == lento» sólo se sostiene con el modelo de
frames sintético del simulador. Sonaba bien, encajaba con el README y con el
determinismo del fallo, y **estaba mal**. Era una explicación construida sin
mirar los frames.

Al volcarlos, el dato desmonta la hipótesis en dos líneas:

```text
swap-demo      : swaps=24  fb_front=0x01000000  -> IDENTICO al esperado, 0 pixeles
swap-demo-fast : swaps=25  fb_front=0x01025800  -> 1280 pixeles, 4 filas
```

La primera línea ya la mata: **la variante lenta reproduce el frame esperado byte
a byte en la placa**, y los dos ficheros esperados son idénticos entre sí. O sea
que la referencia **sí** es alcanzable en hardware y no es un artefacto del
simulador.

Y la imagen dice el resto. Es una banda verde de dieciséis filas sobre fondo
azul:

| | Banda |
|---|---|
| Esperado | filas **46–61** |
| Placa, variante rápida | filas **48–63** |

Un **desplazamiento rígido de dos filas**: sólo difieren las cuatro filas de los
dos bordes, que es la firma de una banda movida y no de datos corruptos.

La causa está en el `swaps=**25**`, y no es sobrepaso del sondeo —eso ya estaba
descartado midiéndolo: `detectado=24, tras_halt=24`—. Es que **parar la CPU no
para el doble buffer**:

> Una petición de intercambio se atiende en la **frontera de frame siguiente**,
> y esa frontera la decide el barrido, no la CPU. Si el programa escribió `SWAP`
> justo antes de que llegara el `halt_cpu` del arnés, el intercambio se completa
> con la CPU ya parada, `FB_FRONT` pasa a apuntar al buffer que el programa
> estaba pintando a medias, y el arnés captura ése.

Por qué sólo muerde a los rápidos, que es lo que hacía parecer que la culpa era
de la variante: `swap_demo` repinta 240 líneas y tarda **96 ms** en volver a
pedir intercambio, así que la parada cae siempre dentro de esa ventana.
`swap_demo_fast` repinta 32 y vuelve a pedirlo en **13 ms**, que es el orden del
viaje de ida y vuelta por el puerto serie. Es una carrera, y el programa rápido
la gana casi siempre —de ahí que el fallo fuera perfectamente reproducible, que
es justo lo que me hizo descartar una carrera—.

**El arreglo es de paridad, no una heurística.** Cada intercambio de más cambia
de sitio el buffer que se busca, que es el que quedó completo tras el intercambio
N; con la CPU parada su contenido ya no cambia. Si sobran un número impar de
intercambios, el frame se lee de `FB_BACK` en vez de `FB_FRONT`.

Con eso **pasan los dos**, en las tres carpetas, y no hizo falta tocar ninguna
referencia.

**Y la corrección de paridad trajo su propia carrera, peor que la original.**
Tras aplicarla, `video-swap-demo-fast` empezó a fallar **una de cada dos veces**,
que es peor que fallar siempre porque parece ruido. La causa es que el
intercambio pendiente puede completarse **entre dos lecturas nuestras**: si cae
entre leer `SWAP_COUNT` y leer `FB_FRONT`, el contador dice que no sobró ningún
intercambio y la base ya está volteada, así que la paridad corrige al revés.

Arreglado esperando, antes de leer nada, a que el bit de «intercambio pendiente»
de `STATUS` se apague. Con la CPU parada y nada pendiente, el dispositivo de
vídeo está quieto y todo lo que se lea es coherente. Tres pasadas seguidas de la
suite completa dan el mismo resultado.

> Compensar un efecto de carrera con una cuenta leída **después** del efecto
> mete una segunda carrera entre la cuenta y lo que se compensa. Lo que hay que
> hacer es esperar a que el sistema esté quieto, y sólo entonces leer. `[TODAS]`

> Un fallo perfectamente reproducible **no descarta una carrera**: sólo dice que
> uno de los dos corredores gana casi siempre. Lo que descarta una carrera es
> medir los dos tiempos. Y antes de explicar por qué dos imágenes diferen,
> **vuélcalas y mira en qué difieren**: dos filas de desplazamiento y cuatro
> filas distintas no se parecen en nada a «los programas divergen». `[TODAS]`

**3. `shared-video-fb-desalineada`** — **resuelto: era un bug de RTL, y es el
hallazgo de silicio de esta validación.** La investigación completa está en la
fase 8; lo que sigue es cómo se veía antes de entenderlo.

El caso escribe `0x01100004` en `FB_BACK`
y espera que la CPU pare con error `0x02`. En placa la CPU **no toma el error**.
Y aquí hay que separar dos cosas, porque la primera sonda que hice estaba mal
diseñada y dio la respuesta contraria:

- Sondeado desde el monitor, dejando antes `FB_BACK` en un valor **distinguible**
  (`0x01000000`) y escribiendo luego `0x01025804`: el registro **se queda en
  `0x01000000`**. O sea que el silicio **rechaza** la escritura desalineada, no la
  trunca. §4.3 se cumple en el registro.
  (Mi primera sonda dejó antes el valor alineado `0x01025800`, con lo que
  «rechazado» y «truncado» daban el mismo resultado y parecía v1. **Un control
  necesita que los dos desenlaces se distingan**, que es la misma lección de las
  mutaciones del mismo número de caracteres.)
- Lo que **no** ocurre es que el error llegue al núcleo por el camino de la CPU.
  Y el camino existe en RTL, entero:
  `video_registers.error` → `top.v:610 mmio_video_error` → `top.v:583` →
  `mmio_decoder.v:194 error = error_direccion || (es_video && video_error)` →
  `mmio_error` → CPU. Con `palabra_completa = (write_mask == 4'b1111)`
  (`video_registers.v:261`), que un `STORE` de palabra cumple.
- Y el contraste que acota el fallo: **`shared-mmio-absent-store` pasa**, o sea
  que el error de **dirección** sí llega a la CPU. El que no llega es el error de
  **dato** del dispositivo.

Queda **abierto y sin explicar**, con la evidencia anotada. Es el hallazgo de
silicio de esta sesión: ninguna simulación lo ve porque ningún banco instancia
`top`, que es la razón de ser de `test_top_wiring.py`.

**4 y 5. `program-bresenham-circles-core` y `program-bresenham-lines-core`** —
**resuelto.** La no-determinación era la pista, no el problema.

El `pc` esperado cuadra en los dos, así que el programa corre entero; lo único
que falla es el volcado de memoria. Y el valor esperado en el offset que falla es
**cero** en ambos. Mirando los `expected.hex`:

| Caso | Palabras | A cero | Offset que falla | Palabra |
|---|---:|---:|---|---:|
| circles | 896 | **673** | `0x24` | **9** |
| lines | 416 | **294** | `0x8` | **2** |

Los dos ficheros son «una cuenta, N entradas, y el resto ceros», y **la palabra
que falla es exactamente la primera que el programa no escribe**: la 9 tras la
cuenta más ocho entradas, la 2 tras la cuenta más una.

O sea que el caso da por hecho que **la memoria no escrita vale cero**. El
simulador lo cumple —`self.memory = bytearray(memory_size)`, todo a cero— y la
placa no: `reset_cpu` no toca la SDRAM, así que esas palabras llevan lo que dejó
el caso anterior.

El control que lo demuestra, en dos mitades:

```text
lines-core a solas, dos veces  -> 47, 47     (mismo predecesor, mismo residuo)
circles-core y luego lines-core -> 32         (otro predecesor, otro residuo)
poniendo 0x00100000 a cero a mano y corriendo circles -> PASS
```

La primera línea explica de paso por qué lines parecía determinista y circles no:
las dos lo son, **condicionadas a lo que corriera antes**. Circles cambiaba
porque la suite completa no siempre lo precede igual.

> Un valor que cambia entre ejecuciones no siempre es no-determinismo del
> diseño. Aquí el programa es perfectamente determinista y lo que variaba era
> **el estado inicial**, que nadie estaba fijando. `[TODAS]`

**El arreglo va en el arnés, no en los dos casos**, porque no son dos casos: hay
**31 con `memory_dumps`**, y a los otros 29 el residuo les cuadraba por suerte,
que es peor que fallar. Ahora las regiones que el caso va a volcar se ponen a
cero antes de cargar el programa, igual que el arnés ya encendía SCANOUT y
borraba el underflow: el caso declara lo que espera, no cómo dejar la placa
preparada. Va antes del programa y de `initial_memory` para que los dos ganen si
alguna región los solapa.

---

## Fase 7 — La 18 y la 19 en placa, y van igual

El encargo dejaba la 18 y la 19 como opcionales («si sólo da tiempo a una
carpeta, que sea la 21»). Se llevaron las dos igualmente, y la conclusión es que
**van igual** — lo cual, como se ve más abajo, es justo lo que hacía falta para
cerrar dos de los hallazgos abiertos.

### Las tres identidades, leídas de silicio

| | 18 | 19 | 21 |
|---|---|---|---|
| Semilla / Fmax | 6 / **88,76** | 5 / **85,02** | 5 / **84,04** |
| `SYSTEM_ID` | `0x12` = 18 | `0x13` = 19 | `0x15` = 21 |
| `DEVICES` | **`0x225`** | `0x235` | `0x235` |
| `MONITOR_VERSION` | `0x312` = 3.18 | `0x413` = 4.19 | `0x415` = 4.21 |
| Ventanas de monitor | **3** | 4 | 4 |
| `0x80100000` (SERIAL) | **error de acceso** | responde | responde |
| Matriz de DQ | **128/128** | **128/128** | **128/128** |

El `0x225` de la 18 —`0x235` sin el bit 4— y sus tres ventanas de monitor,
confirmados en el chip y no en el `top.v`.

### El caso negativo de la 18, que no lo cubre nadie más

Es lo que el encargo pide de esta carpeta y lo único que aporta ella sola: que un
acceso a un bloque **ausente** conteste error y no cero (§4.3). En la misma
sesión y contra la misma placa:

```text
0x80200000  VIDEO      -> 0x00000002    responde
0x81010000  CPU PERF   -> 0x00000055    responde
0x80100000  SERIAL     -> Error: The FPGA rejected the command
```

El contraste que lo cierra: **la 19 contesta en esa misma dirección**. Mismo
mapa, misma placa, misma sesión; lo único que cambia es el bit 4 de `DEVICES`.

### Y el resto de v1 que estaba tapando justo esa comprobación

Al ir a hacer esa medición, el `monitor.py` de la 18 la rechazó **sin llegar a la
placa**:

```text
Error: Address must be between 0 and 0x1ffffff,
       or inside the MMIO register window 0x80000000-0x80000fff
```

Esa ventana es la página de 4 KiB de **v1**. Medido, las dos carpetas la tenían:

| Constante | 18 | 19 | 21 |
|---|---|---|---|
| `MMIO_LIMIT` | `0x8000_0FFF` | `0x8000_0FFF` | derivado del mapa |
| `SERIAL_BASE` | — | **`0x8000_0200`** | derivado del mapa |

O sea que desde la línea de órdenes de la 18 y de la 19 eran inalcanzables
**VIDEO, SERIAL y CPU PERF**: todo el mapa nuevo menos SYSTEM. La 19 además
declaraba el puerto serie en su dirección de v1.

Por qué no lo cazó nadie, y son tres razones que se suman:

1. `MONITOR_REGIONS` **sí** estaba migrado en las dos, y es lo que los tests
   contrastan —contra el mapa generado y contra los `WINDOWn_*` del `top.v`—.
   Este otro par de constantes no lo mira ningún test.
2. Sólo se usan desde el **CLI**. La suite de placa va por `MonitorClient` y no
   pasa por `parse_address`, así que pasaba entera con el CLI roto.
3. **El síntoma era idéntico al éxito que se buscaba.** Comprobar «SERIAL da
   error en la 18» da `exit=1`; el host rechazando la dirección **también** da
   `exit=1`. Sin mirar el texto del mensaje, el resto de v1 se lee como la
   confirmación de §4.3 que se venía a buscar.

> El tercer punto es el que hay que recordar. Un resto sin migrar en el **host**
> puede producir exactamente el fallo que tu prueba espera ver, y entonces la
> prueba sale «bien» sin haber tocado la placa. Cuando lo que mides es un error,
> comprueba **de quién** es el error. `[TODAS]`

Arreglado en las dos: las constantes se derivan del mapa generado, como en la 21.
Y es el arreglo el que hace medible el caso negativo de la 18 — antes no se podía
distinguir.

### Las suites de placa de las tres

| | Casos | Fallos | Omitidos | Timeouts | Reloj |
|---|---:|---:|---:|---:|---:|
| 18 | 26 | **1** | 61 | **0** | 18,0 s |
| 19 | 38 | **1** | 49 | **0** | 22,6 s |
| 21 | 53 | **1** | 34 | **0** | 36,6 s |

**Ni un timeout en ninguna, y un único fallo en las tres, que es el mismo**:
`shared-video-fb-desalineada`. Los arreglos del arnés valen para las tres, como
tenía que ser siendo un fichero compartido. Tres pasadas seguidas de la suite de
la 21 dan el mismo resultado exacto.

### Lo que esto cierra de los hallazgos abiertos

Que las tres vayan igual no es sólo una confirmación, es **evidencia nueva**,
porque las tres migraron por separado y con semanas de diferencia:

- **`video-swap-demo-fast` fallaba en las tres, y en el píxel idéntico: 14720
  (x=0, y=46).** Tres carpetas con distinto RTL, distinta ALU, distinta semilla y
  distinta frecuencia, fallando en el mismo píxel. Eso descartaba que fuera de
  una carpeta, de la temporización o del barrido, y apuntaba a lo compartido —que
  resultó ser el **arnés**, no el par programa + referencia como supuse primero—.
  Volcados los frames, era el doble buffer completando un intercambio pendiente
  con la CPU ya parada; **arreglado**, y pasa en las tres. El detalle, con el
  diagnóstico falso que hubo por medio, está en la fase 6.
- **`shared-video-fb-desalineada` falla en las tres.** No es una rareza de la 21:
  el error de **dato** del dispositivo no llega al núcleo en **ninguna** carpeta
  de la familia CPU, mientras que el de **dirección** sí llega en las tres
  (`shared-mmio-absent-store` pasa en las tres). Eso acota el fallo a la mezcla
  del error de dispositivo, común a las tres, y lo convierte de anomalía en
  **deuda del contrato**.
- Los tres fallos extra de la 21 (`video-starfield-fast` y los dos
  `program-bresenham-*-core`) **se omiten** en la 18 y la 19 por capacidades, así
  que esta ronda no dice nada nuevo sobre ellos.

---

## Fase 8 — El error que vivía un ciclo de menos

El único fallo que no era del arnés, y el que justifica el encargo entero: un bug
de RTL que **sólo existe cuando las piezas se juntan**, invisible para las 21, 24
y 29 pruebas de banco de las tres carpetas, y que la placa enseñó a la primera.

### El síntoma, que era contradictorio

`shared-video-fb-desalineada` escribe `0x01100004` en `FB_BACK` —bit 2 puesto,
o sea desalineado a 16— y espera que la CPU pare con error `0x02` (§9.2). En
placa:

```text
FB_BACK tras el caso : 0x01025800   <- NO se movio, la escritura se rechazo
CPU                  : halted=True error=False error_code=0x00 pc=0x00000018
```

Las dos líneas juntas son lo desconcertante, y son la pista: **el dispositivo
hace su trabajo y el aviso no llega**. Es el peor de los dos mundos —la
escritura no surte efecto y el programa no puede enterarse— y no se parece ni a
«el RTL no lo implementa» ni a «el decodificador no lo mezcla», que era por donde
yo estaba buscando.

### La causa: duración, no lógica

El RTL está bien escrito de punta a punta. Lo que falla es **cuánto dura** el
aviso:

| Ciclo | `select` | `write` | `bus_write` | `error` | `ack` |
|---|---|---|---|---|---|
| 1 | **1** | 1 | 1 | **1** → bloquea la escritura ✓ | 0 |
| 2 | **0** | 1 (retenido) | **0** | **0** | **1** ← el cliente muestrea aquí |

`mmio_mux` fabrica `select` como un **pulso de un ciclo** y confirma al cliente
**al siguiente**; `cpu_dmem_adapter` hace `dmem_error <= mmio_error` en el ciclo
del `ack`. Y `video_registers` colgaba su error de
`bus_write = select && write`, así que el error subía y bajaba **el ciclo antes
de que nadie lo mirase**.

Por qué el error de **dirección** nunca estuvo roto, que es lo que hacía el
diagnóstico difícil: el decodificador lo saca de `address` y `write`, y ésos el
mux **sí** los retiene. De ahí que `shared-mmio-absent-store` pase y que escribir
en `0x80000000` desde el monitor conteste «The FPGA rejected the command»,
mientras la escritura desalineada conteste «Written» a algo que había rechazado.
**Los dos clientes perdían el error de dato y los dos conservaban el de
dirección**, lo cual ya estaba medido en la fase 6 sin que yo supiera leerlo.

Y el aviso estaba escrito, para otra señal, en el propio `mmio_mux`:

> «Mantener dirección Y tipo de acceso hasta que el cliente consume `ack`. Si
> `write` bajase con `select`, un `STORE` a solo lectura **perdería su error
> combinacional un ciclo antes** de que lo muestree el adaptador.»

Alguien pisó exactamente este charco, lo arregló para `write` y `address`, y
dejó `select` —del que cuelga el error del dispositivo— sin tocar.

### El arreglo, una línea

```verilog
// video_registers.v
-    if (bus_write) begin      // bus_write = select && write  -> muere con select
+    if (write) begin          // write/address/mask/data los retiene el mux
```

Es correcto porque `write`, `address`, `write_mask` y `write_data` los retiene el
mux hasta la siguiente concesión, y el decodificador ya filtra por dispositivo
con `es_video`, que también sale de la dirección retenida. **La escritura de
verdad sigue usando `bus_write`**, así que no cambia cuándo se escribe el
registro: sólo cuánto dura el aviso. Sin cambio de interfaz, y aplicado a las
tres carpetas porque el fichero es byte a byte idéntico y hay un test que lo
exige.

No se tocó `select`: alargarlo habría disparado **dos veces** los registros con
efecto secundario, que es el bug que el propio `mmio_mux` documenta —«un `LOAD`
se comía dos caracteres y un `STORE` mandaba el byte dos veces»—.

### El banco que faltaba

`mmio_error_ack_tb.v`, nuevo en las tres carpetas. Monta **la cadena entera**
—mux + decodificador + `video_registers`, como la monta `top.v`— y mira el error
**donde lo mira el cliente**: en el ciclo del `ack`.

Por qué no lo veía ninguno de los que había: `cpu_mmio_error_tb` instancia el
decodificador suelto y le pone `select` a mano, así que el error y la
comprobación caen en el mismo ciclo y el bug es invisible. Y ningún banco
instancia `top`, que es la razón de ser de `test_top_wiring.py`.

Siete comprobaciones, y las dos mitades a propósito: tres que deben dar error
(FB_BACK y FB_FRONT desalineadas, CTRL con modo reservado), tres que no (las
mismas bien alineadas, modo válido, una lectura) y una de **contraste** con el
error de dirección, que nunca estuvo roto — si esa fallara, lo roto sería el
banco.

Control negativo, devolviendo el RTL a `bus_write`:

| | Resultado |
|---|---|
| Las **tres** de error de dato | **FALLAN**, con `mmio_error en el ack = 0` |
| La de error de **dirección** | pasa |
| Las tres de «sin error» | pasan |

O sea que el banco no sólo salta: salta **exactamente en la familia rota** y deja
quieta la que funcionaba. Eso es lo que lo hace un banco y no una alarma.

> Un error combinacional tiene una **vida**, y el que lo mira puede llegar tarde.
> Cuando un banco pone `select` a mano, el error y la comprobación caen en el
> mismo ciclo y la vida no se mide nunca. Para probar un error hay que montarlo
> con el árbitro real y mirarlo **donde lo mira el cliente**. `[TODAS]`

Y la lección de lectura, que es la que más me costó: **que el dispositivo rechace
la escritura y el cliente no se entere no son dos síntomas, es uno.** Yo lo leí
como «el RTL sí lo implementa, luego el fallo está en el cableado» y me puse a
mirar `top.v`, que estaba bien. Lo que distinguía los dos casos no era *qué*
señal, era *cuándo*.

### Lo que costó, y lo que salió gratis

El cambio de RTL invalida las tres semillas que se acababan de fijar, así que
hubo que rehacer la ronda entera: rebarrer, resintetizar, refijar y revalidar.

**Rebarrido, y el resultado es la mejor ilustración de la regla de estos
`apio.ini`.** Una línea que no toca ningún camino crítico —el error es
combinacional y muere en el adaptador— y aun así:

| | Antes | Después | |
|---|---|---|---|
| 18 | 8 de 8, mediana 84,83 | **8 de 8**, mediana 84,03 | semilla **2**, 87,67 (+9,6 %) |
| 19 | 6 de 8, mediana 81,81 | **8 de 8**, mediana 85,31 | semilla **4**, 88,87 (+11,1 %) |
| 21 | 3 de 8, mediana 78,99 | **7 de 8**, mediana 83,44 | semilla **1**, 87,34 (+9,2 %) |

La 21 pasa de **3 de 8 a 7 de 8** por una línea que no cambia ningún camino.
No es que el diseño haya mejorado: es que este netlist se coloca mejor, que es
exactamente lo que estos ficheros llevan años repitiendo. Y la 19 cierra el
ciclo que abrió aquel 3-de-8 de la fase 3.5 —cuando su `apio.ini` declaró el
netlist «al borde de verdad, no sólo mal colocado»— llegando a 8 de 8 con la
mejor mediana que ha tenido la carpeta. **Era colocación, las dos veces.**

**Y el área baja**, porque quitar `select` de la condición simplifica la lógica:

| | Con el bug | Arreglado |
|---|---|---|
| 18 | 10 464 / 5 088 | **10 319 / 5 088** |
| 19 | 11 182 / 5 171 | **11 129 / 5 171** |
| 21 | 11 590 / 5 236 | **11 382 / 5 236** |

Los FF no se mueven —el arreglo es puramente combinacional— y el LUT baja entre
53 y 208. O sea que el bug **costaba área además de corrección**.

### El resultado en placa

| | Casos | Fallos | Antes de esta fase |
|---|---:|---:|---:|
| 18 | 26 | **0** | 1 |
| 19 | 38 | **0** | 1 |
| 21 | 53 | **0** | 1 |

**Cero fallos en las tres**, y la 21 dos veces seguidas. Matriz de DQ 128/128 en
las tres. Y la sonda directa por el camino del monitor, que antes contestaba
«Written» a una escritura rechazada:

```text
FB_BACK = 0x01000000                      (valor distinguible)
write-word 0x80200008 0x01025804  -> Error: The FPGA rejected the command (exit 1)
read-word  0x80200008             -> 0x01000000   (no se ha movido)
write-word 0x80200008 0x01025800  -> Written      (exit 0, la alineada funciona)
```

§9.2 es ahora observable desde los dos caminos, que es lo que el contrato pide.

---

## Verificación al cerrar

| Qué | Base (fase 0) | Ahora |
|---|---|---|
| `tools/test` 18 / 19 / 21 | SUCCESS 131 / 135 / 138 s | sin tocar RTL |
| `tools/lint --prototype 18` | 39 PINMISSING, 0 anchura | sin tocar RTL |
| `unittest` de `x.tests` | 278 OK | **278 OK** |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | **53 casos, 0 fallos** |
| `unittest` de `1.isa` / `2` / `11` | 61 / 44 / 62 | **61 / 44 / 62 OK** |
| `check-links` | 644 en 182 `.md` | 652 en 183, ninguno roto |
| `generate-docs --check` | al día | **al día** (tras regenerar) |
| `generate-mmio --check` | al día | **al día**, los cuatro destinos |
| `synthesis-report.md` | **1 FAIL** (la 21) | **0 FAIL** |
| `unittest` de `x.tests` (tras el test nuevo) | 278 OK | **279 OK** |
| `tools/test` 18 / 19 / 21 (con el banco nuevo) | SUCCESS | **SUCCESS**, 21 / 24 / 29 + 1 bancos |
| `tools/lint --prototype 18` | 39 PINMISSING, 0 anchura | **39 PINMISSING, 0 anchura** |
| `run_tests --backend cpu-fpga` (21) | 12 fallos, 248 s | **0 fallos, 37 s** |
| `run_tests --backend cpu-fpga` (19) | — | **0 fallos, 23 s** |
| `run_tests --backend cpu-fpga` (18) | — | **0 fallos, 18 s** |
| Matriz de DQ, las tres | — | **128/128 limpias** |
| `synthesis-report.md` | 1 FAIL | **0 FAIL**, las tres PASS |

Ficheros tocados:

| Fichero | Qué |
|---|---|
| `x.tests/backends/fpga.py` | parada, doble buffer y memoria de los volcados |
| `18`, `19` `monitor.py` | la ventana del CLI, que seguía en v1 |
| `x.tests/test_monitor_protocol.py` | el test que faltaba para esa ventana |
| `video_registers.v` ×3 | **la línea del error**, el único cambio de RTL |
| `mmio_error_ack_tb.v` ×3 | **banco nuevo**, el que caza ese bug |
| 3 `apio.ini` | semillas nuevas, con su párrafo |

El lint vuelve exactamente a la línea base: el banco nuevo trajo un
`PINMISSING` de más —el `write_mask` del decodificador sin conectar— y se ató en
las tres copias a la vez, que es como hay que arreglar un aviso en un fichero
replicado.

### El test que faltaba, añadido

`test_la_ventana_del_cli_cubre_los_bloques_que_decodifica` fija la invariante
que el resto de v1 rompía: **la ventana que acepta el CLI tiene que cubrir todas
las regiones que la propia carpeta declara en `MONITOR_REGIONS`**. Es interna al
fichero, así que vale igual para la 18 —tres regiones— que para la 21 —cuatro—
sin listar ninguna; y se ancla además contra el mapa generado para que las dos no
puedan estar mal a la vez de forma consistente. Sólo mira las carpetas cuyo
`sysid.v` lleva el magic de v2, así que las siete que faltan no fallan mientras
dure la travesía.

Controles negativos, con `__pycache__` borrado entre pasadas:

| Mutación | Resultado |
|---|---|
| M1 `MMIO_LIMIT` de la 18 de vuelta a `0x8000_0FFF` (**el fallo real**) | **falla**, nombrando la región y dando el `read-word` que reventaría |
| M2 `SERIAL_BASE` de la 19 de vuelta a `0x8000_0200` | **falla**, y sólo esa aserción |
| M3 `MMIO_BASE` de la 18 movida a `0x9000_0000` | **falla**, y sólo esa aserción |
| árbol restaurado | pasa |

---

## Las siete carpetas sin migrar, que es deuda que no estaba anotada

El encargo lo pide explícitamente y tiene razón en que hoy no lo señala nada.

`x.tests/backends/fpga.py` es **único y compartido**, y ya está en v2. Las siete
carpetas con placa que siguen en v1 —**6, 10, 16**, más las de GPU **12, 14, 17,
22**— tienen por tanto sus tests de placa rotos, y lo estarán hasta que migren.
El propio fichero lo dice en su cabecera (`fpga.py:97-100`) y lo declara «sabido y
aceptado, no una regresión», que es la mitad correcta de la historia.

Lo que esta sesión añade es la otra mitad, y es peor de lo que esa nota sugiere:

1. **No es sólo que las direcciones no cuadren.** Hasta hoy el fichero además
   armaba la parada mal **para todas**, incluidas las que sí están en v2. O sea
   que la nota tranquilizaba sobre un problema conocido mientras tapaba uno que
   no lo era.
2. **El arreglo de hoy sólo afecta a carpetas con `frame_capture`.** Las que no
   lo tienen siguen por la rama `estado >> 16`, que para ellas es correcta.
3. **Nada lo señala como deuda**, porque ningún camino automático ejecuta este
   backend: hace falta una placa. Queda anotado en `TODO.md`.

---

## Si el orden fue el correcto

El encargo propone 21 → (18, 19) → placa, con la 21 primero por ser la única con
dato de silicio. **Fue el correcto, y por una razón distinta de la que da.**

La 21 primero acertó, pero no porque fuera la que fallaba: porque es la **única
cuyo build archivado era post-migración**. Barrerla no necesitaba sintetizar, así
que dio la respuesta a la pregunta de fondo —¿cuesta v2 frecuencia?— en once
minutos, antes de gastar dos síntesis. Si se hubiera empezado por la 18, el
barrido habría re-rutado el netlist de v1 y habría devuelto ocho números buenos y
falsos.

Lo que **sí** haría distinto, en dos sitios:

- **Los tres barridos en paralelo desde el principio.** `yosys` y `nextpnr` son
  monohilo, pero la máquina tiene 16 núcleos: tres barridos a la vez cuestan lo
  mismo de reloj que uno. La regla de `Start-Job` del encargo está pensada para
  no lanzarlos en llamadas sueltas, no para serializarlos.
- **La placa antes que los barridos de la 18 y la 19, no después.** La placa ya
  tenía un bitstream de v2 y podía contestar la mitad de las preguntas —bloque
  SYSTEM, bitmap de vídeo, serie, control negativo— sin esperar a nada. Y sobre
  todo: la regresión del arnés compartido habría aparecido **una hora antes**, y
  es lo que más tiempo se llevó. El encargo pone la placa en el paso 6 de 7,
  cuando es el único paso que mide algo que ninguna otra cosa mide.

> Cuando un paso es el único que puede descubrir una clase entera de fallos,
> ponerlo al final garantiza que sus fallos se descubran tarde. Si hay una placa
> enchufada, pregúntale lo que ya pueda contestar antes de gastar una síntesis.

---

## Qué falló que parecía funcionar

La lista corta, que es lo que el encargo pide de verdad:

| Qué parecía | Qué era |
|---|---|
| «Los bitstreams programados son de v1» (trampa 2) | La placa llevaba **v2** desde el build fallido de las 08:13 |
| «La receta de placa está corregida en los README de las tres» (trampa 4) | El de la **21** sigue entero en v1, 0 referencias al mapa nuevo |
| «El +6,7 % sale de SYSTEM, el decodificador y `video_registers`» | SYSTEM cuesta **+6 LUT**; el 44 % es `cpu_perf_counters`, que no se menciona |
| El FAIL de la 21 es el coste de v2 | Es **la semilla**; sobre 16 semillas v1 y v2 cumplen **las mismas 7** |
| La 19 estaba «al borde de verdad» (su `apio.ini`) | Era colocación: con v2 y ~650 LUT más pasa de **3 de 8 a 6 de 8** |
| El backend de placa estaba migrado | Tenía las direcciones de v2 y la **semántica de v1**, en tres sitios |
| El lado host de la 18 y la 19 estaba migrado | `MONITOR_REGIONS` sí; `MMIO_LIMIT` y `SERIAL_BASE` **seguían en v1** |
| El `exit=1` de «SERIAL da error en la 18» confirmaba §4.3 | Era **el host** rechazando la dirección, sin llegar a la placa |
| Los dos fallos de placa eran cosa de la 21 | Salen **iguales en las tres**, y uno en el píxel idéntico |
| La escritura desalineada se trunca en placa (mi primera sonda) | **Se rechaza**; mi sonda no distinguía los dos desenlaces |
| Los `-fast` divergen del lento por cómo dibujan (mi primer diagnóstico) | La lenta reproduce el esperado **byte a byte**; era el arnés capturando el buffer equivocado |
| Un fallo reproducible al píxel no puede ser una carrera | Puede: sólo significa que un corredor gana casi siempre |
| `bresenham-circles-core` es no determinista en placa | El programa es determinista; lo que variaba era **el estado inicial de la SDRAM** |
| Eran dos casos de memoria los afectados | Son **31**; a 29 el residuo les cuadraba por suerte |
| `tools/build-sweep` mide el diseño de hoy | Re-ruta el **último build archivado**, que en la 18 y la 19 era del 17/09 |

---

## Estado contra la definición de terminado

| Criterio del encargo | Estado |
|---|---|
| Bitstream que corresponde a su RTL en las tres | ✓ |
| Semilla fijada con su párrafo en `apio.ini` | ✓ las tres |
| `generate-docs --check` al día | ✓ |
| `docs/synthesis-report.md` sin FAIL | ✓ cero en todo el fichero |
| Matriz de DQ limpia en la carpeta llevada a placa | ✓ **128/128 en las tres** |
| Lint no ha empeorado por tipo | ✓ no se tocó RTL |
| Suites de simulación verdes | ✓ todas |
| `TODO.md` refleja el estado nuevo | ✓ incluida la deuda del backend compartido y la del lado host |
| **Tests de vídeo en placa pasan en la 21** | ✓ **los nueve**, y la suite entera: 53 casos, 0 fallos, dos pasadas |
| El puerto serie con ellos | ✓ los 3 casos de serie pasan |
| Acceso a SERIAL en la **18** da error, no cero | ✓ confirmado en silicio, con la 19 como contraste |
| La 18 y la 19 en placa | ✓ **0 fallos** las dos, aunque el encargo las daba por opcionales |

**Todo lo que el encargo pedía está cerrado.** El único fallo que quedaba abierto
al escribir la fase 6 resultó ser un bug de RTL, está arreglado, tiene banco que
lo caza y las tres carpetas pasan la suite de placa entera.

---

## Fase 3 — Placa, primera pasada: la trampa 2 del encargo no es cierta

Esta fase se adelantó al hueco en que los tres barridos ocupaban la CPU, y lo
que encontró cambia el plan de placa.

### Lo que el encargo da por hecho

> «Todo test de vídeo en placa escribe hoy en `0x80200004`, y **los bitstreams
> programados son de v1**, con el vídeo en `0x80000000`. En la 18, 19 y 21 esos
> tests no pueden pasar hasta que programes un bitstream nuevo.»

Medido contra la placa, con `COM3` presente y sin programar nada:

```text
monitor.py read-word 0x80000000  ->  0x4d474155
monitor.py read-word 0x80200000  ->  0x00000002
```

`0x4d474155` es el **MAGIC de SYSTEM de v2**. Si el bitstream fuera de v1, esa
dirección sería `FB_FRONT` y devolvería una base de framebuffer. Y `0x80200000`,
que en v1 no es nada, contesta `2` = `SCANOUT`.

**La placa ya lleva un bitstream de v2 de la 21.** Es el del build de las 08:13
—el que no cumple temporización con la semilla 13—, que se sintetizó con
`--timing-allow-fail` y por tanto produjo bitstream igualmente, y alguien lo
programó.

O sea que el premiso de la trampa 2 es falso para la 21, y con él su
consecuencia: los tests de vídeo en placa de la 21 **sí podían pasar hoy**. Lo
que no se puede es fiarse del resultado, por la razón contraria a la que dice el
encargo: no porque el mapa no cuadre, sino porque **ese bitstream es el que se
queda a 79,90 MHz**.

### El bloque SYSTEM entero, leído de silicio

| Offset | Registro | Silicio | Esperado para la 21 | |
|---|---|---|---|---|
| +0x00 | `MAGIC` | `0x4d474155` | `0x4D474155` | ✓ |
| +0x04 | `MMIO_VERSION` | `0x00000200` | 2.00 | ✓ |
| +0x08 | `SYSTEM_ID` | `0x00000015` | 21 | ✓ |
| +0x0C | `DEVICES` | `0x00000235` | `0x235` | ✓ |
| +0x10 | `MEM_BASE` | `0x00000000` | 0 | ✓ |
| +0x14 | `MEM_SIZE` | `0x02000000` | 32 MiB | ✓ |
| +0x18 | `MONITOR_VERSION` | `0x00000415` | 4.21 | ✓ |

Las siete palabras del bloque nuevo de §20, en silicio, con los valores de esta
carpeta. El `DEVICES = 0x235` del encargo se confirma **en el chip**, no en el
`top.v`.

### El control negativo del encargo, y sale limpio

El encargo pide, antes de declarar nada: escribir en `0x80000000` —la dirección
de `FB_FRONT` en v1, que ahora es SYSTEM— y confirmar que **da error de acceso**
en vez de mover el framebuffer.

```text
monitor.py write-word 0x80000000 0x01000000  ->  Error: The FPGA rejected the command  (exit 1)
monitor.py read-word  0x80000000             ->  0x4d474155   (el magic no se ha movido)
monitor.py read-word  0x80200004             ->  0x01000000   (el FB_FRONT de verdad, intacto)
```

Las tres líneas importan y la tercera es la que lo convierte en un control y no
en un «falló algo»: el decodificador **rechaza** la escritura vieja, el bloque
de solo-lectura no se deja escribir, y el registro que la receta vieja creía
estar tocando sigue donde debe. Si `0x80000000` hubiera aceptado la escritura,
el decodificador no estaría haciendo lo que creemos.

### Los tres registros que mató el bug del bitmap, vivos

Es la primera línea de la tabla «qué hay que confirmar en placa», y es el fallo
que la 21 tuvo de verdad: con `VIDEO_REGISTERS(64'h7f)` en su `top.v`, los
índices 7, 8 y 9 contestaban error de acceso aunque el RTL los implementara.

| Offset | Registro | Lectura | Escritura |
|---|---|---|---|
| +0x14 | `FRAME_COUNT` | `0x000274e0` (contando) | — |
| +0x18 | `SWAP_COUNT` | `0x000029ea` | — |
| +0x1C | **`HALT_AT`** | `0x00000000` | `0x3e8` escrito y releído ✓ |
| +0x20 | **`HALT_TARGET`** | `0x00000000` | `0x1` escrito y releído ✓ |
| +0x24 | **`VIDEO_TX`** | `0x00346333` | — |

Los tres responden, y los dos escribibles se leen de vuelta. **El bug del bitmap
está muerto en silicio**, no sólo en el RTL. Se restauraron los dos a cero tras
la prueba.

Y se confirma de paso la trampa 3 del encargo con el número delante:
`HALT_TARGET` vale **cero** tras reset, o sea que no para a nadie. Un arnés que
arme `HALT_AT` y espere una parada se cuelga.

### El puerto serie en su sitio nuevo

`0x80100000` responde: `DATA` = 0, `STATUS` = `0x4000`, `PEEK` = 0. El bloque
está donde v2 dice, por el camino real del monitor.

### Lo que esta pasada NO vale para declarar

Todo lo anterior se midió sobre el bitstream que **no cumple temporización**.
Los caminos de registro MMIO son cortos y no dependen de `sdram_clk`, así que lo
que se ha comprobado —decodificación, bloque SYSTEM, bitmap de vídeo, serie— es
válido. Lo que **no** se puede dar por bueno desde aquí es nada que pase por la
SDRAM: la matriz de DQ y los programas de `examples/` se repiten sobre el
bitstream de la semilla buena.

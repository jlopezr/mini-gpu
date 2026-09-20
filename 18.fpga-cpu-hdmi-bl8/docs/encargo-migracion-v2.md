# Encargo: aplicar MMIO v2 a la 18

Aplica el contrato [`1.isa/mmio.md`](../../1.isa/mmio.md) (MMIO v2) a
`18.fpga-cpu-hdmi-bl8`.

**Antes de nada, lee los dos logs, en este orden:**

1. [`19.fpga-cpu-hdmi-ls/docs/migracion-v2.md`](../../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md)
   — el más corto y el más útil para ti. Es la segunda migración, escrita para
   que la tercera vaya con ella delante, y su sección final mide lo que cuesta
   cada trozo **de esta carpeta en concreto**.
2. [`21.fpga-cpu-hdmi-alu/docs/migracion-v2.md`](../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md)
   — el camino completo, con las piezas compartidas y el porqué de cada
   decisión. Léelo entero una vez; luego consúltalo.

No repitas su trabajo. `.equ`, el generador de constantes, el mapa de
transición, los tests de anchuras y de fixtures, y los periféricos del
simulador ya existen y valen para todas.

**No sintetices hasta que te lo diga.** Y hay una deuda previa: la 19 y la 21
también están sin sintetizar desde su migración. Si vamos a pagar un barrido,
decidiremos si se pagan los tres juntos.

## Regla primera: este prompt es una hipótesis

Lo medí el **2026-09-20** sobre el árbol. Verifica cada dato antes de actuar
sobre él, y si algo no cuadra, **dímelo antes de seguir**.

Y hay un precedente concreto que justifica la regla: el log de la 21 dice que
la 18 tiene «`HALT_AT` con el mismo bug de `==` que se arregló aquí».
**Es falso.** La 18 usa `>=`, con un comentario en `video_registers.v:241`
explicando que es defensa deliberada, y la 21 migrada usa `>=` también. Lo que
de verdad cambia es contra **qué** compara. Un dato de un log anterior no es
más fiable que un dato de este prompt.

### Lo que medí

**El punto de partida está verde:**

| Comando | Resultado |
|---|---|
| `tools/test --prototype 18` | **SUCCESS**, 42 s, 21 bancos |
| `tools/lint --prototype 18` | **40 `%Warning-PINMISSING`, 0 de anchura** |

Ése es el número base a no empeorar, **mirando el reparto por tipo, no el
total**: en la 21 el total no se movió mientras aparecían dos `WIDTHTRUNC`
nuevos.

**Inventario:**

- **8 `.asm` en `examples/`**, de los cuales **6 tocan MMIO**. Los dos que no
  son `fpga_smoke_test.asm` y `perf_loop.asm`, exactamente como en la 19.
- **21 bancos** `*_tb.v` (la 19 tiene 24).
- `apio.ini`: semilla **4**, `default-testbench = cpu_sdram_system_tb.v`.
- `video_registers.v` implementa **siete** registros (bitmap `0x7f`), así que
  el `VIDEO_REGISTERS(64'h7f)` de su `top.v` es **correcto hoy**. En v2 pasan a
  ser diez y tiene que quedar en `0x3ff`. Hay un test que lo vigila.
- `monitor.py` tiene `MONITOR_REGIONS` con **una sola** ventana.

## El atajo, que es la mitad del trabajo

**Seis de los ocho ficheros RTL de MMIO de la 18 son byte a byte idénticos a
los de la 19 antes de migrarla** (comprobado con `git hash-object` contra
`HEAD:19.fpga-cpu-hdmi-ls/...`, no con un diff de texto, que engaña por los
finales de línea):

| Fichero | Qué hacer |
|---|---|
| `mmio_decoder.v`, `mmio_mux.v`, `sysid.v` | **copiar de la 19 ya migrada** |
| `video_registers.v`, `cpu_perf_counters.v`, `monitor_mem_adapter_128.v` | **copiar de la 19 ya migrada** |
| `cpu_dmem_adapter.v` | difiere: migrar a mano, pero el diff con el de la 19 es pequeño |
| `top.v` | a mano; lleva valores propios de la carpeta |

Copiar **no es un atajo sucio, es lo que el repo quiere**: estos ficheros están
pensados para ser idénticos entre carpetas y hay un test que lo exige,
agrupando por versión del contrato. Cuando termines, los seis deben ser byte a
byte los de la 19 y la 21.

Y de los 21 bancos, **11 son idénticos a los de la 19 pre-migración**, así que
sus versiones ya migradas sirven. Los que difieren y hay que mirar a mano:
`cpu_burst_system_tb`, `cpu_mmio_error_tb`, `cpu_sdram_system_tb`, `cpu_tb`,
`cpu_video_tb`, `monitor_tb`, `perf_probe_tb`, `video_fullframe_tb`,
`video_registers_tb`, `video_sdram_tb`, `write_combine_tb`.

> **Antes de migrar nada, haz el diff contra la 19.** Si las diferencias son
> sólo la migración, es una copia y no media tarde. Pero **compara en las dos
> direcciones**: en la 19, `monitor_tb.v` tenía 84 líneas MÁS que el de la 21
> porque llevaba cobertura de atomicidad de `WRITE_WORD` que la 21 no tiene, y
> copiarlo habría borrado pruebas reales.

## Orden

1. **Verifica el punto de partida** y apunta los números: los comandos de abajo
   en verde y el reparto de lint. Si algo ya está rojo, dímelo.
2. **Los `.asm`**, contra `mmio_v1.inc` primero, **sin mover ninguna
   dirección**, y añade `18.fpga-cpu-hdmi-bl8/examples` a `CARPETAS` en
   `x.tests/test_mmio_map.py` **antes** de tocar ningún fichero, para que la
   guarda haga de lista de trabajo. Valida comparando el binario ensamblado
   palabra a palabra: simbolizar mal **no cambia el tamaño** del programa, así
   que comprobar el `pc` final o la longitud no prueba nada.
3. **El camino de dirección.** Corre `x.tests/test_top_wiring.py` **antes** de
   tocar la anchura. Ya mira los bancos además de `top.v`, y la 18 tiene dos
   desajustes suyos anotados en `DEUDA_EN_BANCOS`: **vacía esa lista de tus
   entradas antes de darte por terminado.** Hay tres más, de `perf_probe_tb.v`,
   que son ajenas a MMIO y copia compartida entre 18, 19 y 21: ésas se quedan.
4. **El RTL**: las seis copias, `cpu_dmem_adapter.v` y `top.v`.
5. **Los bancos.** Nombra los offsets como `localparam` al principio antes de
   migrar ninguno; en la 19 eso convirtió `video_registers_tb.v` —diez offsets
   repartidos por 350 líneas— en una edición pequeña.
6. **El lado host**: `monitor.py`. En la 19 fueron los dos últimos fallos de la
   suite, y es lo único que ningún test cubre hasta el final.
7. **Los documentos.** Ver abajo; es más caro de lo que parece.

## Lo que la 18 tiene y la 19 no

**`sdram_system_adapter.v` sigue en su `top.v`.** La 19 lo sacó —su `apio.ini`
lo dice— y la 18 no. Es un camino MMIO más que la 19 no ejercitó, con su propio
banco (`sdram_system_adapter_tb.v`, 9 apariciones de direcciones MMIO) y su
`cpu_sdram_system_tb.v`, que además es el **banco por defecto** de `apio.ini`.
Éste es el trozo sobre el que ninguno de los dos logs tiene nada que decirte, y
por tanto donde más probable es que aparezca algo.

## Trampas, en orden de lo que más duele

**1. Un parámetro que `top.v` pisa no se delata al migrar.** Es el fallo que la
19 encontró en la 21, y ya está en placa: `top.v` pasaba
`VIDEO_REGISTERS(64'h7f)` —los siete registros de v1— pisando el `0x3ff` de v2,
y `HALT_AT`, `HALT_TARGET` y `VIDEO_TX` contestaban **error de acceso** aunque
el RTL los implementa. No lo vio nadie porque `0x7f` **sigue siendo un bitmap
perfectamente válido**: no hay nada de qué quejarse.

> Un `MMIO_PREFIX` desaparece al migrar porque el código no compila sin él; un
> parámetro que sólo cambia de número sobrevive callado. **Repasa uno a uno los
> parámetros que `top.v` pisa.** En la 18 son `VIDEO_REGISTERS` (de `0x7f` a
> `0x3ff`), y hay que añadir `DEVICES`, `MEM_BASE`, `MEM_SIZE` y
> `MONITOR_VERSION`, que en v1 no existían.

Hay un test, `test_el_top_no_estrecha_el_bitmap_de_video`, que compara el
bitmap contra lo que implementa el `video_registers.v` de esa carpeta. Hoy la
18 pasa con `0x7f` porque implementa siete; en cuanto copies el de v2, saltará
hasta que corrijas `top.v`.

**2. `HALT_TARGET` arranca a cero, así que no para a nadie.** En v1 bastaba
escribir `HALT_AT`. Todo banco o arnés que arme la alarma y espere una parada
se queda colgado, y el síntoma es un **timeout**, que no se parece a la causa.
Y `HALT_AT` pasa a contar **frames**, no intercambios: no son intercambiables,
porque mientras la CPU dibuja un frame entero pasan varios frames de barrido
sin ningún swap. En el `video_fullframe_tb` de la 21 hubo que subir el umbral
de 2 a 6.

**3. Las fixtures versionadas mienten sobre su origen.** La 18 tiene siete
ficheros generados en la raíz: `fullframe.hex`, `perf_loop.hex`,
`frame_full.hex`, `frame_full.bin`, `fb_bars.bin`, `fb_checker.bin` y
`fb_frame.bin`. **No tiene `fullframe_tb.asm`**, igual que le pasaba a la 19, y
su README dice de dónde sale `fullframe.hex`.

En la 21 esa frase era falsa y regenerar el `.hex` «como ponía ahí» dio *60 009
violaciones JEDEC*, que en realidad eran 60 009 accesos a una fila inexistente
contados por la misma función de error. **Antes de regenerar una fixture,
comprueba de qué fuente sale de verdad y en qué formato la lee su consumidor.**

`x.tests/test_fullframe_fixture.py` ya **descubre solo** las carpetas con el
trío completo, así que cubrirá la 18 el día que crees su `fullframe_tb.asm` —
pero **no antes**, y ése es justo el momento en que hace falta. Créalo pronto.

**4. `monitor.v` es copia idéntica en las diez carpetas** y hay un test que lo
guarda. Si la migración necesita tocarlo, tiene que ser **por parámetro desde
`top.v`**, nunca con una copia divergente. No hizo falta ni en la 21 ni en la
19: ya tiene cinco ranuras `WINDOWn_BASE/END` parametrizadas y v2 necesita
cuatro. Si crees que no hay salida por parámetro, para y dímelo.

**5. Una dirección MMIO aparece en cinco formas distintas**, y buscar sólo la
primera encuentra menos de la mitad: literal (`32'h8000_0000`), dentro de una
instrucción ensamblada a mano (`32'h5E80_8000`), partida en bytes de protocolo
(`send_byte(8'h80); send_byte(8'h00); …`), como offset de 16 bits sobre una
base implícita, y en constantes de Python.

**6. Los documentos son más caros de lo que parecen.** El README de la 18 tiene
**7** apariciones de direcciones v1 y `docs/plan-18-bl8.md` una más. En la 19 el
README tenía una tabla de registros entera en v1 **y una receta de placa que ya
no funcionaba** —escribía `SWAP` sin poner antes `FB_FRONT`, `FB_BACK` ni
`CTRL`, que tras reset valen cero y PATTERN—. Ningún test lo cubre.

## Valida lo que escribas con un control negativo

Rompe la referencia a propósito y comprueba que falla, **y que falla por el
motivo correcto**. Aplícalo sobre todo a la anchura del bus y a las fixtures,
que son lo que falla en silencio.

Dos avisos de método que costaron tiempo antes:

- **Verifica que la mutación se aplicó**, y si pasa por un generador, que la
  **regeneración tuvo éxito**. Un generador que rechaza la mutación deja los
  ficheros generados intactos, los tests leen datos rancios y no falla ninguno
  — que es indistinguible de un control negativo superado.
- **Borra `__pycache__` entre pasadas.** Una mutación del mismo número de
  caracteres puede quedar enmascarada por el bytecode viejo.

## Verificación, sin saltarte ninguna

```
./tools/test --prototype 18
python x.tests/run_tests.py --backend cpusim
./tools/lint --prototype 18          # compara el reparto por tipo, no el total
python tools/check-links.py && ./tools/generate-docs --check
./tools/generate-mmio --check
python -m unittest discover -s x.tests -p "test_*.py"
```

Y las suites de `1.isa`, `2.cpu-sim-func` y `11.gpu-sim-func`.

**Usa los lanzadores de `tools/`, no el `.py` a mano.** `generate_mmio.py` no
tiene bloque `__main__`: ejecutarlo directamente sale con 0 sin hacer nada, y
como 0 es lo que se espera de un `--check`, el falso verde es indistinguible
del bueno. Pasó en la 19.

Al terminar, corre también `./tools/test --prototype 19` y `--prototype 21`:
tocas ficheros compartidos y tests comunes, y las dos tienen que seguir verdes.

Síntesis y barrido **sólo cuando te lo diga**. Placa después.

## El entregable es el log

`18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md`, escrito **mientras** trabajas, no
al final. No repitas lo que ya dicen los otros dos: enlázalos. Lo que quiero de
éste es la diferencia:

- el orden real, si no fue el que propongo aquí;
- **cuánto del atajo se sostuvo**: cuántos de los seis ficheros se copiaron
  limpios de verdad, y qué hubo que tocar después;
- qué salió más barato de lo estimado y qué más caro, y por qué;
- qué se rompió, incluido lo que parecía funcionar y no;
- **lo que aparezca en `sdram_system_adapter`**, que es el trozo ciego;
- qué es específico de la 18 frente a lo universal, marcado con su alcance;
- lo que esta migración descubra de la 19 y la 21 — migrar una carpeta audita
  las anteriores, y en la 19 eso destapó cinco cosas de la 21, una de placa;
- el barrido, cuando lo paguemos, y lo que sólo se ve en placa;
- y la estimación corregida para la 17, que es la siguiente y es de otra
  familia.

## Definición de terminado

La 18 conforma; su fila en `docs/resumen-prototipos.md` lo dice; ningún `.asm`
lleva la dirección cableada; `DEUDA_EN_BANCOS` no tiene entradas suyas salvo
las tres de `perf_probe_tb`; los comandos de arriba pasan y lint no ha
empeorado por tipo; la 19 y la 21 siguen verdes; `TODO.md` refleja el estado
nuevo; y el log sirve para migrar la 17 con él delante.

Al terminar, dime qué tres cosas del log crees que van a fallar en la 17.

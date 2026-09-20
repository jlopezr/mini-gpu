# Encargo: cerrar MMIO v2 en silicio — barrido, síntesis y placa

Tres carpetas conforman con [`1.isa/mmio.md`](../1.isa/mmio.md) (MMIO v2) y
**ninguna se ha confirmado en hardware**: la `21.fpga-cpu-hdmi-alu`, la
`19.fpga-cpu-hdmi-ls` y la `18.fpga-cpu-hdmi-bl8`. Tu trabajo es cerrar eso, o
decir por qué no se puede.

**Antes de nada, lee las tres bitácoras de migración**, en este orden:

1. [`18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md`](../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md)
   — la más reciente y la más corta. Su última sección lista la deuda que queda
   sin pagar, que es de donde sale este encargo.
2. [`19.fpga-cpu-hdmi-ls/docs/migracion-v2.md`](../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md)
   — lo que cambió al repetir la migración.
3. [`21.fpga-cpu-hdmi-alu/docs/migracion-v2.md`](../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md)
   — el camino completo y el porqué de cada decisión. Léelo una vez entero;
   luego consúltalo.

Y [`AGENTS.md`](../AGENTS.md) antes de invocar `yosys`, `nextpnr` o `apio` a
mano: **casi seguro que ya existe un lanzador en `tools/`**.

## Regla primera: este prompt es una hipótesis

Todo lo que sigue se midió el **2026-09-20** sobre el árbol, en el commit
`bfca66c`. Verifica cada dato antes de actuar sobre él, y si algo no cuadra,
**dímelo antes de seguir**.

El precedente que justifica la regla está en la fase 0 de la bitácora de la 18:
de nueve afirmaciones concretas del encargo anterior, **cinco no se sostuvieron**,
y dos de ellas describían mal el estado del repositorio, no el plan. Un dato que
viaja de bitácora en bitácora sin volver a medirse envejece igual que el código,
y es más difícil de auditar porque suena a conclusión.

## Por qué esto va antes que seguir migrando

Porque hay un número que dice que puede haber un problema de fondo, y no es una
precaución abstracta:

> La 21 se sintetizó el 20/09/2026 y **no cumple temporización**: `sdram_clk`
> a **79,90 MHz contra los 80,00** del objetivo, con la semilla 13. Y el área
> sube de **10 867/5 066** a **11 590/5 236** LUT/FF, un **+6,7 % de LUT**.

El informe es `reports/20260920-101323-955327-build`, `exit_code: 1`.

Las tres carpetas corren a 80 MHz con poco margen. Si ese +6,7 % es el precio
de v2 y no cabe, la respuesta no es «rebarrer y ya»: es una decisión de diseño
que hay que tomar **antes** de aplicar el mismo patrón a las siete carpetas que
quedan. Rehacer tres carpetas es caro; rehacer nueve es otra cosa.

## Lo que medí

**El punto de partida en simulación está verde**, y es la línea base a no
empeorar:

| Comando | Resultado |
|---|---|
| `tools/test --prototype 18` | SUCCESS, 123 s, 21 bancos |
| `tools/test --prototype 19` | SUCCESS, 127 s |
| `tools/test --prototype 21` | SUCCESS, 130 s |
| `tools/lint --prototype 18` | **39 `%Warning-PINMISSING`, 0 de anchura** |
| `unittest` de `x.tests` | 278 OK |
| `run_tests.py --backend cpusim` | 53 casos, 0 fallos |
| `generate-docs --check` / `generate-mmio --check` | al día |

**Las semillas fijadas hoy**, y las tres están invalidadas porque las tres
carpetas tocaron RTL:

| Carpeta | Semilla | Objetivo | Último dato conocido |
|---|---|---|---|
| `18.fpga-cpu-hdmi-bl8` | 4 | 80 MHz | 84,0 MHz, de **antes** de migrar |
| `19.fpga-cpu-hdmi-ls` | 4 | 80 MHz | 83,9 MHz, de **antes** de migrar |
| `21.fpga-cpu-hdmi-alu` | 13 | 80 MHz | **79,90 MHz, FAIL, ya migrada** |

## Orden

1. **Verifica el punto de partida** y apunta los números. Si algo ya está rojo,
   dímelo antes de gastar una síntesis.
2. **Barrido de la 21 primero**, que es la única con un dato real de silicio:

   ```
   tools/build-sweep --prototype 21 --seeds 1 2 3 4 5 6 7 8 --background
   tools/build-status
   tools/build-log --follow
   ```

   `--background` no es opcional en la práctica: un barrido de ocho semillas son
   decenas de minutos y bloquear una llamada esperando no sirve para nada.

   **Lo que decide este paso.** Si cierran varias semillas con holgura, el 79,90
   era la semilla y seguimos. Si no cierra ninguna, o cierran una o dos por los
   pelos, **para y dímelo**: eso ya no es una semilla, es el coste de v2, y lo
   que hay que mirar entonces es de dónde sale el +6,7 % de LUT.
3. **Barrido de la 18 y de la 19**, sólo si el de la 21 cierra. Se pueden lanzar
   a la vez, pero **no con `&` ni en llamadas separadas**: `yosys` y `nextpnr`
   son monohilo, así que van con `Start-Job` en **una sola** llamada de
   PowerShell, esperando con `Wait-Job`.
4. **Fija la mejor semilla por margen en cada `apio.ini`**, y **escribe el
   porqué en el comentario de al lado**. Ese fichero es una bitácora de barridos
   y lleva años siéndolo; una semilla nueva sin su párrafo es una regresión
   documental.
5. **Regenera la documentación**: `tools/generate-docs`. Los informes de
   síntesis se leen de `reports/`, así que **un barrido pone `--check` en rojo
   automáticamente**. Esto no es cosmético: es cómo se supo que la 21 fallaba.
6. **Placa**, que es el único paso que mide algo que ninguna simulación ve.
7. **El log.** Ver abajo.

## Trampas, en orden de lo que más duele

**1. Una semilla que cumple no dice que la SDRAM se lea bien.** Está escrito en
el `apio.ini` de la 18 y merece repetirse, porque es el fallo que esta carpeta
ya tuvo en placa:

> El barrido mide caminos **dentro** del chip. El fallo que tuvo esta carpeta
> estaba en la captura de DQ, que entra por un pin, y con el diseño roto el
> barrido daba +14,5 % de holgura igual.

Lo que sí lo dice es la matriz de 128 casillas (8 beats × 16 DQ) que documenta el
README de la 18. El script está en las **tres** carpetas, así que se corre en la
que toque: `21.fpga-cpu-hdmi-alu/sdram_dq_matrix.py --port COM3`. **No des por
buena la SDRAM porque la temporización cierre.**

**2. Los tests de vídeo en placa están rotos hoy, y no es un síntoma de nada.**
`x.tests/backends/fpga.py` es **único y compartido por las diez carpetas**, e
importa `tools.mmio_map`, que es **v2**. O sea que todo test de vídeo en placa
escribe hoy en `0x80200004`, y los bitstreams programados son de v1, con el
vídeo en `0x80000000`.

Consecuencias, las dos importantes:

- En la 18, 19 y 21 esos tests **no pueden pasar hasta que programes un
  bitstream nuevo**. Si los corres antes, vas a leer un fallo que ya sabemos
  explicar y no mide nada.
- En las **siete carpetas sin migrar** van a seguir rotos aunque todo salga
  perfecto, porque su RTL sigue en v1. Es una regresión que nos hicimos nosotros
  al migrar el backend compartido, se cura sola según migren, y **hoy no hay
  nada que la señale como deuda**. Anótala donde toque.

**3. `HALT_TARGET` arranca a cero, así que no para a nadie.** En v1 bastaba
escribir `HALT_AT`. Cualquier arnés que arme la alarma y espere una parada se
cuelga, y el síntoma es un **timeout**, que no se parece a la causa. Y `HALT_AT`
cuenta **frames**, no intercambios: mientras la CPU dibuja un frame entero pasan
varios frames de barrido sin ningún swap.

**4. La receta de placa del README cambió, y la vieja parecía funcionar.** Antes
era una línea, `write-byte 0x80000008 1`. Ahora hay que poner **`FB_FRONT`,
`FB_BACK` y `CTRL` antes del `SWAP`**, porque tras reset las dos bases valen cero
y el modo es PATTERN. Está corregida en los README de las tres; si la de alguna
no lo está, es que se quedó atrás.

**5. La 18 no tiene puerto serie, y eso se nota en placa.** Es la primera carpeta
migrada con `HAS_SERIAL(0)`: su `DEVICES` es `0x225` —sin el bit 4— y tiene
**tres** ventanas de monitor, no cuatro. Lo que hay que confirmar en placa es que
un acceso al bloque SERIAL **da error de acceso** y no cero, que es lo que pide
§4.3. Ningún banco de simulación prueba eso contra el bitstream real.

**6. La placa desaparece sola tras programar.** COM3 se va y vuelve por su
cuenta. **No pidas replugar el USB**: espera.

## Qué hay que confirmar en placa, y por qué no lo ve la simulación

Esta es la lista corta. **Si sólo da tiempo a una carpeta, que sea la 21**, por
dos razones que se suman:

- **Es la que más periféricos tiene.** `HAS_SERIAL(1)`, `DEVICES = 0x235` y
  **cuatro** ventanas de monitor: SYSTEM, SERIAL, VIDEO y CPU PERFORMANCE. O sea
  que ejercita el mapa de v2 entero, mientras que la 18 y la 19 dejan bloques
  sin tocar. Una placa que valide la 21 valida más contrato por sesión.
- **Es la única con un dato real de silicio, y es un FAIL.** Necesita la placa de
  todos modos.

La **18** va después, y por el motivo contrario: es la única sin puerto serie, y
lo que aporta es el caso negativo —que un bloque **ausente** conteste error y no
cero—, que es más estrecho pero no lo cubre nadie más.

| Qué | Por qué ningún banco lo cubre |
|---|---|
| `HALT_TARGET` y `VIDEO_TX` responden de verdad | El bug del bitmap `VIDEO_REGISTERS(64'h7f)` vivía sólo en `top.v`, y **ningún banco instancia `top`**. Es literalmente el fallo que la 21 tuvo en placa |
| Las **cuatro** ventanas del monitor de la 21 dejan pasar lo que deben | Son parámetros de `top.v`; los bancos instancian `monitor` con los suyos |
| El puerto serie sigue respondiendo en su sitio nuevo, `0x80100000` | Sólo la 21 y la 19 lo tienen, y en placa pasa por el camino real del monitor |
| Un acceso a SERIAL en la **18** da error, no cero | Sólo lo prueba `cpu_mmio_error_tb` contra un decodificador de banco |
| La captura de DQ de la SDRAM | Entra por un pin; el barrido no la ve |
| Los `.asm` de `examples/` de las tres carpetas | **Ningún `test.json` los ejecuta.** Sus únicos consumidores son la placa y las personas |

El último merece subrayado: los seis programas de la 18 y los diez de la 19 no
los corre ningún caso automático. La placa es su **única** red.

## Valida lo que midas con un control negativo

Lo mismo que en las tres migraciones: rompe la referencia a propósito y
comprueba que falla, **y que falla por el motivo correcto**. Aquí el control que
importa es el de la trampa 2 invertido:

> Antes de declarar que el vídeo funciona en placa, comprueba que **sabes
> hacerlo fallar**: programa el bitstream nuevo, escribe en `0x80000000` —la
> dirección de v1, que ahora es SYSTEM— y confirma que **da error de acceso** en
> vez de mover el framebuffer. Si eso escribe algo, el decodificador no está
> haciendo lo que crees.

Y los dos avisos de método que ya costaron tiempo: **verifica que la mutación se
aplicó**, y **borra `__pycache__` entre pasadas**, que una mutación del mismo
número de caracteres queda enmascarada por el bytecode viejo.

## Verificación, sin saltarte ninguna

```
./tools/test --prototype 18      # y --prototype 19, y --prototype 21
./tools/lint --prototype 18      # compara el reparto por tipo, no el total
python x.tests/run_tests.py --backend cpusim
python -m unittest discover -s x.tests -p "test_*.py"
python tools/check-links.py && ./tools/generate-docs --check
./tools/generate-mmio --check
```

Y las suites de `1.isa`, `2.cpu-sim-func` y `11.gpu-sim-func`.

**Usa los lanzadores de `tools/`, no el `.py` a mano.** `generate_mmio.py` no
tiene bloque `__main__`: ejecutarlo directamente sale con 0 sin hacer nada, y
como 0 es lo que se espera de un `--check`, el falso verde es indistinguible del
bueno.

## El entregable es el log

`docs/validacion-mmio-v2-placa.md`, escrito **mientras** trabajas, no al final.
Va en `docs/` y no dentro de una carpeta porque cubre las tres. No repitas lo que
dicen las tres bitácoras: enlázalas. Lo que quiero de éste:

- **el barrido, carpeta por carpeta**: cuántas semillas cumplen, el rango de
  frecuencias, y cuál se fija y por qué;
- **si v2 cuesta frecuencia o no**, que es la pregunta que abre este encargo, con
  el número y no con una impresión;
- **de dónde sale el +6,7 % de LUT**, si el barrido no lo desactiva como
  problema — el bloque SYSTEM pasa de cuatro palabras a siete, el decodificador
  de dieciséis dispositivos de 256 B a bloques de 64 KiB, y `video_registers`
  gana tres registros: reparte el coste entre ellos;
- **lo que sólo se ve en placa**, que es la lista de arriba, con lo que pasó de
  verdad en cada línea;
- **qué falló que parecía funcionar**, incluido lo que hayas tenido que
  desmontar para creerte un verde;
- **el estado de las siete carpetas sin migrar** respecto del backend compartido
  en v2, que es deuda que hoy no está anotada en ningún sitio;
- y **si el orden 18 → 19 → 21 → placa fue el correcto**, o había uno mejor.

## Definición de terminado

Las tres carpetas tienen un bitstream que corresponde a su RTL y una semilla
fijada con su párrafo en `apio.ini`; `generate-docs --check` está al día y
`docs/synthesis-report.md` ya no registra un FAIL; los tests de vídeo en placa
pasan **en la 21**, y el puerto serie con ellos; la matriz de DQ está limpia en
la carpeta que se haya llevado a placa; lint no
ha empeorado por tipo; las suites de simulación siguen verdes; `TODO.md` refleja
el estado nuevo, incluida la deuda del backend compartido; y el log sirve para
decidir si seguimos migrando carpetas o si v2 necesita otra cosa antes.

Al terminar, dime **si migrarías las siete carpetas que quedan con este mismo
patrón, o si lo que has visto en silicio pide cambiar algo primero.**

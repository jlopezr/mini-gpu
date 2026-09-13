# Encargo: carpeta 18, memoria con ráfagas BL8

Prompt de arranque para una sesión nueva. Está escrito para alguien que no ha
visto este repositorio: todo lo que necesita saber está aquí o dicho dónde
buscarlo.

---

## El encargo en una frase

Crear `18.fpga-cpu-hdmi-bl8` como copia de [`16.fpga-cpu-hdmi`](../../16.fpga-cpu-hdmi)
y sustituir su camino de memoria por uno de ráfagas BL8, de modo que la CPU
dibuje bastante más rápido sin que el vídeo se rompa.

Es el punto 0 del [`TODO.md`](../../TODO.md) del repositorio: «Que la CPU no esté tanto
esperando a la SDRAM. Usar BL8».

## Cómo funciona este repositorio

Las carpetas numeradas son hitos de aprendizaje **en orden cronológico**, y cada
una es una copia completa y autónoma de la anterior más un paso. `14` es copia de
`12` con SDRAM; `17` es copia de `14` para subir frecuencia. Por eso la 18 es una
copia de la 16, no una modificación de ella: **la 16 debe seguir funcionando
exactamente igual cuando termines**.

Los ficheros se duplican a propósito. La ventaja es poder preguntar «¿qué cambió
del 16 al 18?» con un diff de directorio, y esa propiedad se usa a menudo para
demostrar que un fallo es anterior a un cambio. No la rompas reorganizando.

Convenciones dentro de cada carpeta:

- un solo `README.md` en la raíz, junto al código;
- documentación de apoyo en `docs/`;
- programas en ensamblador en `examples/`, y sus `.bin` **no** se versionan;
- `..\.venv\Scripts\apio.exe test <banco>.v` para simular, `apio build` para
  sintetizar;
- `.venv/Scripts/python.exe tools/check-links.py` comprueba que los enlaces de
  todos los `.md` resuelven. Ejecútalo antes de terminar.

Hardware: ULX3S-85F (ECP5 LFE5U-85F) con SDRAM W9825G6KH, que es de **16 bits**.
La anchura del bus no es negociable; solo se puede usar mejor.

## De qué se parte: la carpeta 16

Una MiniCPU multiciclo con SDRAM de 32 MiB y salida HDMI 640×480p60, con
framebuffer RGB565 de 320×240 escalado 2×, doble búfer e intercambio
sincronizado con el vblank.

| | |
|---|---|
| Reloj de CPU | 100 MHz, semilla 5 fijada en `apio.ini`; cierran 7 de 8 semillas |
| Monitor UART | versión 1.10 a 1 Mbaud |
| Framebuffer | RGB565 320×240 en `0x01000000`, 153 600 bytes |
| Registros de vídeo | MMIO en `0x80000000`: `FB_FRONT`, `FB_BACK`, `SWAP`, `STATUS` |
| Bancos de prueba | 9, todos en verde |
| Suite de CPU en placa | 12 de 12 |

Lee su [`README.md`](../../16.fpga-cpu-hdmi/README.md) entero antes de tocar nada, y en
particular `docs/timing.md`.

## El problema, medido

Estas cifras son medidas en la placa, no estimaciones. La herramienta es
`16.fpga-cpu-hdmi/measure-demo.ps1`.

El bucle interior de `examples/swap_demo_fast.asm` rellena el framebuffer:

```asm
draw_word:
    STORE R13, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, draw_word
```

Cuatro instrucciones por palabra de 32 bits, o sea por dos píxeles. Como la
SDRAM es de 16 bits, **cada acceso de 32 bits son dos accesos físicos**:

| | accesos de 16 bits |
|---|---|
| Buscar las 4 instrucciones | 8 |
| Escribir el píxel doble | 2 |
| **Total por palabra** | **10** |

Resultados: 5 120 palabras en 13,2 ms, y 38 400 en 96,6 ms. Eso da **258 y 252
ciclos por palabra** respectivamente —dos medidas independientes que coinciden al
2 %—, o sea **~26 ciclos por acceso de 16 bits**.

La comparación que señala al culpable: en [`6.fpga-cpu`](../../6.fpga-cpu), que ejecuta
desde EBR, una instrucción ordinaria cuesta **9 ciclos**. En la 16 cuesta **~64**.
Los 55 de diferencia son memoria.

Y el reparto importa: **el framebuffer es 2 de los 10 accesos, el 20 %. El otro
80 % es ir a buscar instrucciones.** Cualquier mejora que solo toque el camino de
datos ataca una quinta parte del problema.

La causa está escrita en la primera línea de
`16.fpga-cpu-hdmi/sdram_controller.v`:

> Burst length is one and every READ/WRITE uses auto-precharge.

Cada acceso paga activación de fila y precarga enteras, aunque el siguiente sea
la palabra contigua.

## Lo que ya existe y no hay que escribir

En [`pruebas/sdram`](../../pruebas/sdram) hay tres ficheros, unos 48 KB de Verilog, que
el README de esa carpeta no menciona. **Están sin verificar: no hay ni un banco
de pruebas en toda la carpeta.** Trátalos como un borrador serio, no como código
de producción.

**`sdram_controller.v`** define `sdram_controller_128`: controlador BL8, con el
registro de modo programado a ráfaga de ocho (`A2:A0 = 011`) y estados
`ST_READ_BURST` / `ST_WRITE_BURST`. Su interfaz lógica transfiere **128 bits =
16 bytes por petición**, con máscara de byte de 16 bits para escribir menos de
una palabra completa. Exige `req_addr[2:0] == 3'b000`.

**`memory_fabric_4.v`** es un árbitro de cuatro puertos con round-robin sobre el
mismo bus de 128 bits. El puerto 2, pensado para vídeo, tiene una entrada
`urgent` que le permite saltarse el turno. Es la versión ordenada de lo que hoy
hace `VIDEO_RUN = 4` en la 16 por fuerza bruta.

**`monitor_mem_adapter.v`** traduce los accesos byte a byte del monitor a
peticiones de 128 bits, usando la máscara para no destruir los otros quince.

Aviso importante: **el controlador nuevo sigue usando auto-precarga en cada
ráfaga** (`A10 = 1`). La ganancia viene de repartir la activación y la precarga
entre ocho palabras en vez de una, no de mantener la fila abierta. Mantenerla
abierta entre ráfagas de la misma página sería un escalón más, y no está hecho.

## Lo que falta, que es justo lo interesante

No hay nada que convierta las peticiones de 32 bits de `imem` y `dmem` de la CPU
en peticiones de 128. **BL8 por sí sola no mejora nada**: un cliente que pide dos
palabras y espera el `ready` no puede aprovechar una ráfaga de ocho.

### Búferes, no cachés

La interfaz de 128 bits ya impone la decisión: todo cliente habla de 16 bytes de
una vez, que *es* un búfer de una línea. No hacen falta tags, asociatividad,
política de reemplazo ni escritura diferida.

Y hay una coincidencia que conviene aprovechar: **16 bytes son exactamente las
cuatro instrucciones del bucle interior**, y exactamente cuatro `STORE`
consecutivos con `+4`.

**Lado de instrucciones.** Un búfer de una línea con su dirección base guardada
basta para que el bucle entero viva dentro y el `BLT` salte dentro del propio
búfer: a partir de la primera iteración, cero búsquedas en SDRAM. El punto débil
es la alineación —si el bucle cae a caballo entre dos líneas de 16 bytes, fallas
en cada iteración—, así que dos o cuatro líneas lo vuelven robusto. Hay que
vaciarlo al arrancar la CPU, porque el monitor escribe memoria de programa
mientras está parada.

**Lado de datos: combinar escrituras, y no una caché.** El motivo no es el coste:
es que **el subsistema de vídeo lee el framebuffer de la SDRAM por su cuenta**.
Una caché con escritura diferida guardaría píxeles que el barrido no puede ver, y
tendrías la imagen a medias sin que el programa haya hecho nada mal. Un búfer de
combinación acaba escribiéndolo todo, solo que a tandas, y necesita tres vaciados
forzados con su sitio natural:

- al escribir en el registro `SWAP`, para que el frame esté completo;
- al parar la CPU, para que el monitor lea memoria de verdad;
- en cualquier acceso MMIO, que nunca debe combinarse.

## Orden de trabajo propuesto

**0. Medir antes de escribir RTL.** Instrumentar `cpu_sdram_system_tb.v` para
separar, de esos ~26 ciclos por acceso, cuántos son comandos de SDRAM y cuántos
son el handshake del adaptador y de la máquina de estados. **La ráfaga solo ataca
los primeros.** Si el grueso resulta ser el handshake, todo este plan rinde mucho
menos de lo que promete y conviene saberlo antes, no después. Este paso puede
cambiar el encargo: dilo si pasa.

**1. Banco de pruebas del controlador BL8.** Partiendo de
`16.fpga-cpu-hdmi/sdram_controller_tb.v`, que cubre la temporización JEDEC. Son
48 KB de RTL sin verificar y un controlador de SDRAM es el peor sitio donde
descubrir errores en la placa.

**2. El adaptador de vídeo primero.** `video_line_source_sdram.v` lee 320
palabras consecutivas por línea, sin bifurcaciones: es el cliente más simple, ya
tiene su `urgent` en el árbitro, y **un fallo se ve en pantalla** en lugar de
corromper el programa en silencio.

**3. El búfer de instrucciones.** Aquí está el 80 %.

**4. La combinación de escrituras.** El más delicado, por los vaciados.

## Criterios de aceptación

- Los 9 bancos de la 18 en verde, más el nuevo del controlador BL8.
- `run_gpu_tests.py --backend cpu-fpga --version <nueva> --port COM3` a 12 de 12.
- `STATUS` bit 0 (`underflow`) a cero tras varios minutos, y `led[0]` apagado.
- `measure-demo.ps1` sobre `tear_demo_fast`, que es la medida limpia porque no
  espera al vídeo: hoy da **75,7 fps / 13,2 ms**. Ése es el número a batir.
- La carpeta 16 intacta y sus 9 bancos aún en verde.
- `tools/check-links.py` sin enlaces rotos.
- Temporización: barrer semillas con
  `.\tools\seed-sweep.ps1 -ProjectDir 18.fpga-cpu-hdmi-bl8 -Seeds (1..8)` y fijar
  la mejor en `apio.ini`, documentando cuántas cierran.

## Trampas conocidas, todas pagadas ya una vez

- **El monitor pide memoria con un pulso de un ciclo**, no con un nivel mantenido
  hasta el `ready` como la CPU y el vídeo. Si el árbitro no lo engancha, se
  pierde cuando cae en un ciclo ocupado y la placa se queda muda. El síntoma
  desconcierta: `ping` funciona y cualquier lectura de memoria cuelga.
- **El divisor de UART debe ser múltiplo de cuatro**, porque la recepción usa
  sobremuestreo 4×. Y además el baudio resultante tiene que ser de los que el
  FTDI genera exactos. `uart.v` lo comprueba al elaborar; no quites esa guarda.
- **`underflow` es pegajoso** hasta el reset de la placa. `monitor.py reset`
  resetea la CPU, no el vídeo: para borrarlo hace falta recargar el bitstream.
- **`apio build` usa `--timing-allow-fail`**, así que genera bitstream aunque
  nextpnr diga `FAIL`. Hay que leer siempre la frecuencia alcanzada. Esto ya pasó
  desapercibido una vez en la carpeta 6.
- **Al medir con `halt`/`read-register`/`run`, parar el cronómetro en el `halt`**,
  no después de leer el registro: la lectura cuesta ~250 ms por el puerto serie y
  contarlos hunde la medida un 20 %. Ese error produjo una tanda entera de cifras
  falsas y coherentes entre sí.
- **Comprueba que un banco nuevo falla sin el arreglo** que pretende cubrir. Un
  detector que no se dispara nunca no vale nada, y aquí ya ha aparecido dos veces.

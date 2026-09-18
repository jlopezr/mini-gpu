# Casos de vídeo

Ocho casos, y cada uno cubre algo que los otros no. Todos declaran una
[capacidad](../../README.md#capacidades), así que se omiten solos donde no hay
con qué ejecutarlos.

| Caso | Capacidad | Qué cubre que los demás no |
|---|---|---|
| [`registers`](registers) | `video` | La ventana de registros desde un programa. **Corre también en la 16.** |
| [`band`](band) | `frame_capture` | La cadena completa hasta el framebuffer, con la imagen más simple posible |
| [`bounce`](bounce) | `frame_capture` | Pitch, bordes y escrituras parciales de línea |
| [`bresenham-lines`](bresenham-lines) | `frame_capture` | Ocho octantes, llamadas y píxeles RGB565 individuales |
| [`bresenham-circles`](bresenham-circles) | `frame_capture` | Punto medio, simetría de ocho y tres niveles de llamadas |
| [`starfield`](starfield) | `frame_capture` | `DIV` con dividendo negativo repartido por la pantalla, y estado que sobrevive entre frames |
| [`starfield-fast`](starfield-fast) | `frame_capture` | Borrado incremental: que el buffer trasero es el frame de hace **dos** |
| [`cube`](cube) | `frame_capture` | `MULFX` y coma fija Q16.16, y las dos reglas de redondeo de la ISA a la vez |

## Por qué ocho y no uno

**`registers`** no dibuja nada. Comprueba lo único que un programa necesita
saber de los registros: que las bases arrancan donde dice el hardware, que
escribir `FB_BACK` funciona y se alinea, y que al aplicarse un `SWAP` las dos
bases **se intercambian** en lugar de copiarse una sobre la otra.

Es el único que usa solo los cuatro registros que existen desde la 16, así que
corre también allí. Es lo que justifica que `video` y `frame_capture` sean
capacidades distintas y no una sola.

Y hay algo que **no** comprueba a propósito: que `SWAP` quede pendiente justo
después de pedirlo. Entre la escritura y la lectura pasan unos microsegundos, y
el intercambio ocurre al arrancar un frame, cada 16,7 ms. La probabilidad de que
caiga justo en medio es diminuta pero no cero, y un caso que falla una vez de
cada mil es peor que no tenerlo. Lo que hace es **esperar** a que se aplique,
que además es lo que hace un programa de verdad.

**`band`** pinta una banda verde fija sobre fondo azul. Es la imagen más simple
que ejercita la cadena entera, y es fija a propósito: las demos de la 16 mueven
la banda, así que el frame esperado dependería de en qué intercambio pares.

**`bounce`** es el cuadrado de siempre, rebotando en los cuatro bordes. Cubre
tres cosas que una banda horizontal no puede:

- **Errores de pitch.** En una banda todos los píxeles de una línea son iguales,
  así que una zancada de línea equivocada casi no se nota. Un cuadrado se
  deforma o se parte inmediatamente.
- **Los bordes.** El rebote ocurre exactamente en 0 y en el máximo. Un error de
  uno en el recorte se ve como un cuadrado que se sale o que rebota una fila
  antes.
- **Escrituras parciales de línea.** El cuadrado se pinta encima del fondo ya
  escrito y ocupa 16 palabras de las 160 de una línea, lo que obliga al búfer de
  combinación de escrituras a volcar y empezar línea en cada pasada.

Para en el intercambio **80** porque a esas alturas ya ha rebotado en los dos
ejes —la `y` en el paso 52 y la `x` en el 72—, y después del primer rebote el
cuadrado deja de estar en la diagonal, así que el caso distingue un eje del
otro. Antes del paso 52, `x` e `y` valen lo mismo y un intercambio de ejes
pasaría desapercibido.

**`bresenham-lines`** ejecuta directamente la demo de la 21 y compara el
primer abanico completo. Sus 36 extremos recorren los ocho octantes, y de paso
el caso integra llamadas, `MUL`, `STOREH`, RGB565 y doble buffer. El modelo de
referencia calcula las rectas por separado; no captura la salida del programa.

**`bresenham-circles`** hace lo mismo con las seis circunferencias del ejemplo.
Cubre el algoritmo del punto medio, los ocho puntos simétricos y tres niveles
de llamadas. Los dos Bresenham tienen además casos `*-core` en `cases/programs`:
esos dejan la secuencia exacta de puntos en RAM, sin depender del vídeo.

**`starfield`** ejecuta la demo del campo de estrellas de la 21 y para en el
intercambio 40. Aporta dos cosas que los Bresenham no:

- **`DIV` con dividendo negativo, 256 veces por frame y repartido por la
  pantalla.** La proyección es `160 + x/z` con `x` de signo cualquiera. Un
  truncamiento hacia menos infinito en vez de hacia cero desplaza un píxel las
  estrellas de la mitad izquierda y de la mitad superior, y sólo ésas. Un caso
  de ALU que compara cocientes sueltos mira el signo del resultado pero no su
  reparto espacial, así que ese fallo se le escapa.
- **Estado que sobrevive entre frames.** Es el único caso de vídeo cuyo frame N
  no se puede calcular sin haber calculado los N-1 anteriores: la `z` de cada
  estrella se acumula y las reapariciones consumen tiradas del PRNG. Eso fija
  también el contrato del xorshift — si alguien lo toca, el campo entero cambia.

**`starfield-fast`** es el mismo campo con borrado incremental, y **compara
contra el `expected/frame.bin` de `starfield`**, no contra uno propio. Eso no es
por ahorrar un fichero: es todo el caso.

El 95% del frame de `starfield` es pintar de negro 38 400 palabras para volver a
encender 256 píxeles. La versión rápida borra sólo esos 256 y pasa de 123 000 a
16 000 instrucciones por frame —medido, 4 930 000 contra 641 000 hasta el
intercambio 40—. Lo que cuesta ese ahorro es contabilidad: con doble buffer, el
buffer trasero contiene el frame de **hace dos**, así que cada estrella guarda
dos direcciones y se borra la más vieja. Y los borrados van todos en una pasada
previa a los dibujos: entrelazados, el borrado de una estrella apagaría el píxel
que otra acaba de encender cuando coinciden.

Un fallo en esa contabilidad no se ve a ojo —el campo sigue pareciendo un campo
de estrellas, con algún píxel de más o de menos—, pero sí se ve contra el frame
de la versión que repinta entero. Que los dos programas den la imagen idéntica
es la prueba, y es exactamente la razón que da `bounce` para repintar entero:
sin un caso así, un fallo de contabilidad se confundiría con uno del hardware.

**`cube`** ejecuta el cubo en alambre de la 21 y para en el intercambio 24. Es
el único caso de vídeo que ejercita **coma fija**: `MULFX` en Q16.16 para las
dos rotaciones, tabla de senos en `.rodata`, y perspectiva con `DIV`.

Lo que cubre y ningún otro toca son **las dos reglas de redondeo de la ISA a la
vez**. `MULFX` y `SARI` desplazan aritméticamente, o sea hacia menos infinito;
`DIV` trunca hacia cero. Una implementación que aplique la misma regla a las
tres —lo natural si se escribe deprisa— desplaza un píxel las aristas del lado
negativo y sólo ésas. El modelo de referencia las escribe por separado y lo
dice en el comentario, porque es el error que este caso existe para atrapar.

Para en el 24 porque con pasos 1 y 3 los dos ángulos valen ahí 23 y 69: ni
múltiplos ni simétricos, así que ninguna cara queda de canto y las doce aristas
tienen longitud distinta de cero.

## Aislamiento: la placa no arranca de cero entre casos

El simulador construye un `VideoDevice` nuevo en cada ejecución. La placa no:
`FB_FRONT`, `FB_BACK` y `SWAP_COUNT` sólo los reinicia el reset del bitstream,
así que un caso le pasa su estado al siguiente. Eso dio dos fallos de verdad, y
ninguno era del hardware:

- **`registers` fallaba una de cada dos veces.** Comprueba valores absolutos de
  las bases, y `band` o `bounce` dejaban un número impar de intercambios, con lo
  que llegaban cruzadas. Ahora el backend las devuelve a sus valores de reset
  antes de cada ejecución. A cambio, este caso ya **no** verifica el valor de
  encendido: verifica que se leen y que un `SWAP` las intercambia.
- **`bounce` sólo pasaba la primera vez por encendido.** Era un fallo de
  hardware en `HALT_AT`, no de aislamiento, pero salió por lo mismo: el caso
  suponía un contador a cero. Está contado en el README de la 18.

La regla que queda: **un caso de vídeo no puede suponer nada del estado
inicial** más allá de lo que el backend normaliza explícitamente.

## Las referencias no se capturan, se calculan

Cada caso con `expect.frame` lleva un `reference.py` que genera el fichero
esperado. **No se genera capturando la placa**: si el esperado saliera de una
captura, el caso solo comprobaría que la placa sigue haciendo lo que hacía,
incluido lo que haga mal.

La excepción es `starfield-fast`, que no tiene `reference.py` porque apunta al
esperado de `starfield`. No rompe la regla: ese fichero lo sigue calculando un
modelo: lo que `starfield-fast` añade es que dos programas distintos tienen que
coincidir con él.

```bash
python cases/video/bounce/reference.py                  # regenera expected/frame.bin
python cases/video/bounce/reference.py --trayectoria    # las posiciones y los rebotes
python cases/video/bounce/reference.py --ppm mirar.ppm  # para verlo
```

Cuando un caso falle, el runner dice en qué píxel está la primera diferencia.
Para ver el mapa completo de diferencias:

```bash
python ../../tools/compare-frames.py --rgb565 320x240 \
    cases/video/bounce/expected/frame.bin capturado.bin --diff diff.ppm
```

## Ejecución

```bash
# Los tres casos base, en la 18
python run_tests.py --backend cpu-fpga --version bl8 --port COM3 cases/video

# Los ocho, incluida la ISA que necesitan los Bresenham, en la 21
python run_tests.py --backend cpu-fpga --version alu --port COM3 cases/video

# Solo el que corre en la 16
python run_tests.py --backend cpu-fpga --version hdmi --port COM3 \
    cases/video/registers/test.json
```

Los ocho corren también en el simulador, sin placa:

```bash
python run_tests.py --backend cpusim cases/video
```

Pero el simulador **no modela el tiempo**: allí `underflow` es siempre cero y el
desgarro no existe. Lo que un verde suyo prueba, y lo que no, está en
[el README de `x.tests`](../../README.md#el-simulador-tiene-vídeo-pero-no-tiene-tiempo).

`bounce` necesita `max_instructions: 20000000` por eso mismo: repinta el fondo
entero 80 veces, que son 12,5 millones de instrucciones y unos 11 segundos de
simulación. En la placa esas mismas 80 frames son 2,6 segundos.

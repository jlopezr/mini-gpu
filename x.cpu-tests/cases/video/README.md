# Casos de vídeo

Tres casos, y cada uno cubre algo que los otros no. Todos declaran una
[capacidad](../../README.md#capacidades), así que se omiten solos donde no hay
con qué ejecutarlos.

| Caso | Capacidad | Qué cubre que los demás no |
|---|---|---|
| [`registers`](registers) | `video` | La ventana de registros desde un programa. **Corre también en la 16.** |
| [`band`](band) | `frame_capture` | La cadena completa hasta el framebuffer, con la imagen más simple posible |
| [`bounce`](bounce) | `frame_capture` | Pitch, bordes y escrituras parciales de línea |

## Por qué tres y no uno

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

## Las referencias no se capturan, se calculan

Cada caso con `expect.frame` lleva un `reference.py` que genera el fichero
esperado. **No se genera capturando la placa**: si el esperado saliera de una
captura, el caso solo comprobaría que la placa sigue haciendo lo que hacía,
incluido lo que haga mal.

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
# Los tres, en la 18
python run_gpu_tests.py --backend cpu-fpga --version bl8 --port COM3 cases/video

# Solo el que corre en la 16
python run_gpu_tests.py --backend cpu-fpga --version hdmi --port COM3 \
    cases/video/registers/test.json
```

Los tres corren también en el simulador, sin placa:

```bash
python run_gpu_tests.py --backend cpu-simulator cases/video/bounce/test.json
```

Pero el simulador **no modela el tiempo**: allí `underflow` es siempre cero y el
desgarro no existe. Lo que un verde suyo prueba, y lo que no, está en
[el README de `x.cpu-tests`](../../README.md#el-simulador-tiene-vídeo-pero-no-tiene-tiempo).

`bounce` necesita `max_instructions: 20000000` por eso mismo: repinta el fondo
entero 80 veces, que son 12,5 millones de instrucciones y unos 11 segundos de
simulación. En la placa esas mismas 80 frames son 2,6 segundos.

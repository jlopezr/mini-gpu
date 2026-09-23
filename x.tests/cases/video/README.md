# Casos de vídeo

Once casos, y cada uno cubre algo que los otros no. Todos declaran una
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
| [`swap-demo`](swap-demo) | `frame_capture` | Una imagen que **se mueve**: fija el desfase entre el swap N y lo que se ve |
| [`swap-demo-fast`](swap-demo-fast) | `frame_capture` | El mismo frame por redibujo incremental sobre **dos** buffers |
| [`pacman`](pacman) | `frame_capture` | Un programa largo y con estado, sin frame esperado: el único que se mira a ojo |

## Por qué diez y no uno

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
que ejercita la cadena entera, y es fija a propósito: quita del caso la
pregunta de en qué intercambio paras, para que un fallo solo pueda venir de la
cadena hasta el framebuffer. Esa pregunta la responden los dos casos
siguientes, que son las demos de la 16 sin tocar.

**`swap-demo` y `swap-demo-fast`** son [`swap_demo.asm`](../../../21.fpga-cpu-hdmi-alu/examples/swap_demo.asm)
y [`swap_demo_fast.asm`](../../../21.fpga-cpu-hdmi-alu/examples/swap_demo_fast.asm)
ejecutados tal cual, sin copiarlos: la misma banda de `band`, pero **bajando
dos píxeles por frame**. Son demos que no terminan nunca y a la vez casos de
test, porque `run_until.swap` los para donde haga falta.

Lo que aportan es el **desfase**. Con una imagen fija, parar en el swap 24 o en
el 25 da lo mismo, y el caso no puede ver un error de uno en el doble buffer.
Con una imagen que se mueve, el frame esperado solo cuadra si se acierta que
tras el swap `N` se ve la banda en `2*(N-1)` y no en `2*N`: el intercambio hace
visible lo que se dibujó **antes** del incremento. Comprobado al revés, que es
lo que hace que el caso valga: generando la referencia con el desfase corrido
uno, falla en `y=46`.

Y el par no es redundante, por el mismo motivo que `starfield`/`starfield-fast`:
`swap_demo` repinta las 240 líneas y `swap_demo_fast` solo 32, borrando la banda
vieja y dibujando la nueva. El fallo clásico de esa optimización —borrar usando
la posición del otro buffer, olvidando que hay dos— deja un rastro de bandas
verdes que no se borran nunca. Contra un frame esperado eso es un fallo; a ojo,
en una demo que corre, es algo que hay que fijarse en mirar. Los dos comparten
`expected/frame.bin` precisamente porque deben dibujar lo mismo.

Sus hermanos `tear_demo.asm` y `tear_demo_fast.asm` **no se pueden convertir en
casos**, y conviene saber por qué: no piden `SWAP` nunca —es justo lo que
demuestran— así que `run_until.swap` no se dispara. Y lo que enseñan es una
carrera entre la CPU y el barrido, que depende de la velocidad relativa de los
dos y que el simulador no modela. Se quedan como demos de mirar a ojo, que es
lo que son.

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

**`pacman`** es la excepción de la lista: una demo que se juega sola —Pac-Man
busca pastillas, cuatro fantasmas se mueven al azar— y el único caso de vídeo
**sin `expect.frame`**. Comprueba lo que sí es barato de comprobar en un
programa así: que no da error, que no hay underflow y que sigue pidiendo
intercambios 300 veces seguidas.

No tiene frame esperado a propósito. El estado del que depende cada frame
—1200 tiles, cinco entidades, la cola del recorrido en anchura, el PRNG— es
tan grande que un `reference.py` sería una segunda implementación completa del
juego en Python, y entonces lo que fallaría sería la sincronía entre las dos y
no el hardware. Lo que este caso aporta es lo otro: **un programa largo**
—unas 1 400 instrucciones de código, con llamadas anidadas, pila propia,
accesos sub-palabra y `REMU`— corriendo millones de instrucciones sin
desviarse. Los casos con frame esperado son cortos; ninguno ejercita eso.

Los dos fallos que encontró mientras se escribía dicen bien qué clase de error
vive en esta franja, y ninguno de los dos se veía en una captura suelta:

- **Una rutina de dibujo usaba `R10` de temporal**, y quien la llamaba llevaba
  ahí el índice del bucle. El bucle se quedaba sin condición de salida. Un
  frame capturado en los primeros intercambios sale perfecto; el programa se
  cuelga después.
- **Al reposicionar tras una colisión se olvidaban las posiciones anteriores**,
  así que los sprites ya pintados en los dos buffers no se borraban nunca. A
  los 900 intercambios había ocho fantasmas en pantalla. Es exactamente el
  fallo de contabilidad de doble buffer contra el que existe `starfield-fast`,
  pero aquí aparece por una vía que aquél no tiene: el teletransporte.

Y una tercera cosa que solo se ve mirando el estado, no la pantalla: la
primera versión elegía el camino con un vistazo de ocho tiles en línea recta,
y en cuanto Pac-Man limpiaba su rincón se quedaba dando vueltas por él para
siempre. Las pastillas se congelaban en 167 de 468 y la imagen seguía
pareciendo una partida normal. Por eso la búsqueda de pastillas es un
recorrido en anchura sobre la rejilla y no un vistazo local; los fantasmas sí
se esquivan mirando en línea recta, que para eso sí basta.

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

`pacman` queda fuera de esta sección entera: no declara `expect.frame`, así que
no hay nada que calcular. Lo que se mira allí está más arriba.

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

Los once corren también en el simulador, sin placa:

```bash
python run_tests.py --backend cpusim cases/video
```

Pero el simulador **no modela el tiempo**: allí `underflow` es siempre cero y el
desgarro no existe. Lo que un verde suyo prueba, y lo que no, está en
[el README de `x.tests`](../../README.md#el-simulador-tiene-vídeo-pero-no-tiene-tiempo).

`bounce` necesita `max_instructions: 20000000` por eso mismo: repinta el fondo
entero 80 veces, que son 12,5 millones de instrucciones y unos 11 segundos de
simulación. En la placa esas mismas 80 frames son 2,6 segundos.

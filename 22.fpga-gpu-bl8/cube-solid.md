# Cubo sólido: evolución software y consecuencias para el hardware

El cubo sólido compara estrategias de rasterización sobre el mismo framebuffer
RGB565, con doble buffer y `SCANOUT` activo. La referencia CPU es
`21.fpga-cpu-hdmi-alu/examples/cube_solid.asm`.

| Versión | Cambio aislado | FPS en placa | Instrucciones de warp, primer frame |
|---|---|---:|---:|
| CPU 21 | Triángulos incrementales escalares | 12,01 | — |
| GPU v1 | Cuatro triángulos estáticos sobre pantalla completa | 2,25 | 733.000 |
| GPU v2 | Cuatro triángulos estáticos y caja limitada | 4,20 | 483.000 |
| [`v3_animated`](examples/cube_solid_v3_animated.asm) | 64 orientaciones, seis slots; descriptor recargado por palabra | 2,15 | 861.000 |
| [`v4_incremental`](examples/cube_solid_v4_incremental.asm) | Triángulo por pasada, caja propia y bordes incrementales | **13,41** | **190.000** |
| [`v5_integer`](examples/cube_solid_v5_integer.asm) | Rotación, perspectiva, culling y setup calculados en la GPU | 12,30 | 191.000 |
| [`v6_vertex_simt`](examples/cube_solid_v6_vertex_simt.asm) | Un warp transforma los ocho vértices, una lane por vértice | 12,30 | 191.000 |
| [`v7_face_simt`](examples/cube_solid_v7_face_simt.asm) | Seis lanes procesan seis caras; dos slots fijos por cara | 12,30 | 192.000 |

Las cifras de instrucciones del primer frame incluyen la limpieza inicial de
los dos buffers. Los FPS se midieron mediante `SWAP_COUNT` durante unos diez
segundos; no incluyen una simulación de tiempo ni desactivan el vídeo.

Condiciones de la medida: prototipo 22 `top_bl8`, reloj de sistema de 25 MHz,
ocho warps de ocho lanes, framebuffer 320×240 RGB565 y salida 640×480@60 con
duplicación 2×. El bit de underflow estaba pegajoso desde una ejecución anterior
y el monitor rechazó limpiarlo en marcha, por lo que no se atribuye a v4; una
medida específica de underflow debe empezar tras reset del subsistema de vídeo.

## Lectura arquitectónica de las medidas

La comparación importante es v3 frente a v4. Ambas muestran las mismas 64
orientaciones, usan los mismos colores, doble buffer y `SCANOUT`, y consumen la
misma tabla geométrica. Solo cambia la organización del rasterizado:

| Magnitud | v3 | v4 | Mejora |
|---|---:|---:|---:|
| FPS en placa | 2,15 | 13,41 | 6,24× |
| Tiempo por frame | 465 ms | 74,6 ms | 6,24× |
| Ciclos/frame a 25 MHz | ≈11,6 M | ≈1,86 M | 6,2× |
| Instrucciones del primer frame | 861 k | 190 k | 4,53× menos |

En una medida de v3 los contadores dieron aproximadamente 801.000 instrucciones
de warp y 222.600 transacciones LSU por frame, 7,76 lanes activas de ocho y
`STALL_MEM=0`. Es decir:

- la divergencia era pequeña;
- la LSU podía aceptar todo lo que emitía el SM;
- el cuello estaba en emitir demasiadas instrucciones y accesos, no en esperar
  a la SDRAM;
- disponer de ocho lanes no compensa recalcular y recargar lo mismo por píxel.

La v4 supera a la CPU 21 (13,41 frente a 12,01 FPS); la v5 queda en 12,30 FPS
a cambio de hacer programable todo el frontend geométrico. Ambas continúan lejos del
presupuesto de 60 Hz: a 25 MHz un frame dispone de unos 420.000 ciclos físicos y
la v4 emplea alrededor de 1,86 millones, unas 4,4 veces ese presupuesto. Esto
deja una meta cuantitativa para hardware: no basta con ganar otro 20 %.

## Qué cambia en v4

La v3 recorría cada palabra de la caja general y, para cada uno de seis slots,
volvía a cargar diez palabras y recalculaba tres bordes con seis `MUL`. La v4:

1. borra la caja una vez por frame;
2. carga cada descriptor una sola vez por hilo;
3. expande la caja X a bloques completos de ocho palabras;
4. asigna una fila distinta a cada warp y palabras consecutivas a sus lanes;
5. calcula los bordes al entrar en la fila;
6. avanza 16 píxeles mediante `E += A*16`;
7. ejecuta `BAR` entre triángulos para que no se solapen escrituras de fases
   distintas.

La imagen del primer frame de v4 coincide byte a byte con la referencia CPU:
0 diferencias sobre 153.600 bytes.

## Reproducir

Regenerar las 64 orientaciones y ensamblar la versión recomendada:

```powershell
.\.venv\Scripts\python.exe .\22.fpga-gpu-bl8\examples\make_cube_solid_frames.py
.\tools\miniisa.ps1 .\22.fpga-gpu-bl8\examples\cube_solid.asm -o cube_solid.bin
```

Cargarla en un bitstream 22 ya presente:

```powershell
.\tools\board-load.ps1 --prototype 22 --program cube_solid --port COM3
```

`examples/cube_solid.asm` es el nombre estable y apunta a la mejor versión. Las
versiones numeradas conservan los hitos que aportan una medición distinta. Los
`.bin` no se versionan.

## Qué añade v5

La v5 elimina los 64 frames precalculados. La lane global 0 calcula cada frame:

1. obtiene seno y coseno de una tabla Q2.14 de 256 entradas;
2. rota los ocho vértices con `MUL` y `SAR`;
3. proyecta con `DIV` entera;
4. hace back-face culling de los doce triángulos;
5. genera coeficientes de borde y bounding boxes en RAM;
6. sincroniza con `BAR` y entrega los seis slots al rasterizador de v4.

El binario baja de 22.124 bytes en v4 a 3.040 bytes en v5. El primer frame
coincide byte a byte con v4; en orientaciones posteriores puede variar un píxel
en algunos bordes porque v5 redondea durante la rotación Q2.14, mientras la
tabla v4 se generó en Q16.16. La penalización medida es 1,11 FPS (8,3 %).

La primera fricción observada fue arquitectónica: el ensamblador acepta
`SHLI/SHRI/SARI`, pero el núcleo 22 no implementa esa capability. La versión
final usa sumas para multiplicar por 4/8 y shifts por registro. La siguiente
medida útil es paralelizar los ocho vértices entre ocho lanes; después conviene
probar por separado `MULFX`, `RCPFX`/recíproco y `MIN/MAX`, sin mezclarlos con
otra reorganización del rasterizador.

## Resultado de v6: paralelizar los vértices no basta

V6 asigna los vértices 0–7 a las lanes 0–7 del primer warp. Cada lane calcula
su rotación y sus dos divisiones de perspectiva y escribe un par `(x,y)`
distinto; tras un `BAR`, la lane 0 conserva el culling y triangle setup de v5.
El framebuffer del primer frame coincide byte a byte con v5.

En placa dio los mismos **12,30 FPS**. Una muestra de 124 frames midió unos
2,019 millones de ciclos y 123.000 instrucciones de warp por frame, sin ciclos
`STALL_MEM`; las pequeñas diferencias entre v5 y v6 quedan dentro del corte de
la muestra en mitad de un frame. La transformación de solo ocho vértices era
demasiado pequeña frente al borrado y rasterizado para afectar al tiempo total.

Esto acota la siguiente optimización: repartir únicamente vértices no justifica
cambios de ISA ni de hardware. Tiene más potencial paralelizar el setup de las
seis caras, eliminar el `LOAD`–modificación–`STORE` RGB565 o acelerar el
recorrido de bordes y el borrado.

## Resultado de v7: slots fijos frente a compactación

V7 asigna una cara a cada una de las lanes 0–5. Cada lane hace culling y genera
dos descriptores en posiciones fijas; una cara oculta escribe dos slots
inactivos. Esto evita atómicos y compactación, pero obliga al rasterizador a
recorrer doce slots en vez de seis.

Los frames 1 y 10 coinciden byte a byte con v6. En placa mantiene **12,30 FPS**,
pero sube de aproximadamente 2,019 a **2,035 millones de ciclos por frame**
(+0,8 %), 123.800 instrucciones de warp y 21.300 transacciones LSU, con
`STALL_MEM=0`. El trabajo extra de cargar y sincronizar seis slots inactivos
supera el ahorro del setup paralelo.

La lección para una futura cola de primitivas es concreta: producir en paralelo
solo ayuda si las caras visibles se compactan antes del rasterizador. Para este
cubo pequeño, una compactación software probablemente costaría tanto como el
setup serial; un append/contador o una cola de triángulos en hardware sí podría
cambiar ese balance. El alias estable continúa apuntando a v6.

## Qué hardware fijo queda justificado

El experimento da sentido concreto a algunas etapas descritas de forma general
en [`../15.isa-v2/integracion_3d.md`](../15.isa-v2/integracion_3d.md). El orden
de prioridad siguiente parte de medidas del cubo, no de intentar reproducir una
GPU comercial completa.

### 1. Edge walker y generador de cobertura de ocho píxeles

Es el bloque mejor justificado. Recibiría por triángulo:

```text
A0 B0 C0
A1 B1 C1
A2 B2 C2
bbox
color o primitive_id
```

y recorrería la caja en grupos alineados con las ocho lanes:

```text
lane 0 -> (x+0,y)   ...   lane 7 -> (x+7,y)
```

Después del valor inicial, los bordes solo necesitan incrementos:

```text
E(x+1,y) = E(x,y) + A
E(x,y+1) = E(x,y) + B
```

La salida natural es un paquete, no ocho escrituras independientes:

```text
x_base, y, coverage_mask[7:0], color/primitive_id
```

La v3→v4 demuestra exactamente el beneficio de mover multiplicaciones y cargas
fuera del bucle interior. Un bloque hardware podría ir más lejos: mantener los
tres acumuladores, producir una máscara por grupo y no gastar ninguna
instrucción del SM en edge walking, comparaciones o reconvergencia.

### 2. Cola de fragmentos conectada al scheduler

El paquete anterior encaja directamente en un warp de ocho lanes cuya máscara
inicial es `coverage_mask`. El shader seguiría siendo programable:

```text
rasterizador -> fragment queue -> warp FRAGMENT -> color/textura/iluminación
```

Así el hardware fijo genera trabajo regular y el SM se reserva para operaciones
que sí cambian entre materiales. La cola también desacopla el ritmo del
rasterizador del SM y permite medir por separado quién deja esperando a quién.

Una primera integración no necesita inventar todavía un command processor
completo. Puede reutilizar la idea de descriptores y arranque de warps ya
presente en el MMIO de MiniGPU, con una fuente adicional de trabajos internos.

### 3. Color write/ROP mínimo con máscaras de byte

La GPU 22 no dispone de `STOREH`, por lo que el programa empaqueta dos píxeles
RGB565 y, en v4, hace `LOAD`–modificación–`STORE` cuando solo una mitad está
cubierta. Sin embargo, el camino BL8 ya transporta máscaras de escritura.

Un bloque de salida mínimo podría aceptar:

```text
direccion de palabra, color izquierdo, color derecho, mask[1:0]
```

y convertir la cobertura en byte enables sin leer primero el framebuffer. No
es aún blending: solo escritura enmascarada RGB565. Reduciría tráfico, evitaría
read-modify-write y resolvería de forma natural los bordes de los triángulos.

### 4. Motor 2D de fill/clear

Cada frame de v4 comienza borrando la caja de 128×224 palabras. Es trabajo muy
regular que no usa capacidad SIMT interesante. Un motor pequeño con:

```text
base, stride, ancho, alto, valor
```

podría emitir ráfagas BL8 mientras el SM prepara geometría. Es un bloque más
sencillo que el rasterizador y también sirve para limpiar color/depth, rellenar
rectángulos y fondos. Debe compartir el fabric como otro cliente y exponer
finalización o barrera; no conviene bloquear el MMIO esperando toda la copia.

### 5. Triangle setup: prometedor, pero falta una medida

El setup calcula orientación, culling, bounding box, `A/B/C` y deltas. La tabla
actual los trae precalculados, así que este benchmark todavía no mide su coste.
Antes de fijarlo en hardware hay que implementar el siguiente hito programable:

```text
8 lanes transforman 8 vértices
-> BAR
lanes preparan las caras/triángulos
-> BAR
rasterizado
```

Si el setup resulta pequeño frente al raster, puede permanecer programable y
beneficiarse de `MIN/MAX`, `MACFX/MSUBFX` y `RCPFX`. Si impide alimentar de
forma continua al edge walker, entonces sí queda justificada una unidad de
Triangle Setup delante de él.

## Qué no está justificado todavía

### Z-buffer y depth test

El cubo es convexo y el back-face culling basta: las caras visibles solo
comparten aristas. Este caso no aporta evidencia para dedicar RAM y lógica a Z.
La prueba que lo justificaría debe contener triángulos solapados, orden de envío
adverso y profundidad interpolada. Solo entonces se puede medir si conviene un
depth test/write fijo y qué formato necesita.

### Texturas e interpoladores

Los colores son planos. No se interpolan `z`, color, `u/v` ni `1/w`. El edge
walker debe dejar prevista la asociación con interpolantes, pero añadir ahora
una texture unit o interpolación perspectiva sería diseñar sin workload.

### Transformación matricial fija

Solo hay ocho vértices por frame. La transformación debe implementarse primero
en las lanes y medirse. `MULFX`, una futura `MACFX/MSUBFX` y `RCPFX` mantienen
el vertex stage general; un multiplicador matricial dedicado no está respaldado
por los datos actuales.

### Binning/tiled rendering

La v4 usa cajas y bloques alineados, pero solo hay seis triángulos. No existe
presión suficiente sobre listas de primitivas ni sobre locality de depth para
justificar un tiler. Será relevante con escenas de muchos triángulos o cuando
se introduzca Z.

## Pipeline mínimo sugerido

La evolución razonable, sin saltar directamente a una GPU 3D completa, es:

```text
vertex/setup programable
        |
        v
descriptor de triángulo
        |
        v
edge walker HW -> coverage_mask de 8 píxeles
        |
        v
fragment queue -> warp programable opcional
        |
        v
color write enmascarado -> FB_BACK -> SWAP -> scanout
```

Para un primer prototipo aún más pequeño, el edge walker puede recibir un color
plano y escribir directamente mediante el color writer, sin fragment shader.
Eso reproduce exactamente este cubo y permite validar cada frontera. Después se
intercala la fragment queue sin cambiar el setup ni el recorrido.

## Contadores necesarios para evaluar el prototipo hardware

Además de los actuales, convendría contar:

| Contador | Pregunta que responde |
|---|---|
| `TRI_SUBMITTED` | ¿Cuántos triángulos recibe setup/raster? |
| `TRI_CULLED` | ¿Cuánto trabajo elimina el culling? |
| `RASTER_GROUPS` | ¿Cuántos grupos de ocho candidatos se recorren? |
| `FRAG_COVERED` | ¿Cuántos píxeles sobreviven cobertura? |
| `FRAG_QUEUE_STALL` | ¿El rasterizador espera al SM? |
| `RASTER_STARVED` | ¿El SM/setup deja al rasterizador sin trabajo? |
| `COLOR_TX` | ¿Cuánto tráfico genera el color writer? |
| `CLEAR_CYCLES` | ¿Cuánto cuesta el borrado por frame? |

El criterio de éxito no debe ser solo FPS. Hay que conservar comparación de
framebuffer, ciclos/frame, instrucciones de warp, utilización de lanes,
transacciones LSU/vídeo/color y ausencia de underflow nuevo.

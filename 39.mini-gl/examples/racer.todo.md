## PENDIENTE
- carreteras en diagonal u otros angulos, cruces? rotondas?
- paisaje real
- señales de verdad?
- tunel
- dia/noche
- vacas pastando
- estacion de servicio
- policia
- ciudad?
- modo camara? que pongas el piloto automatico y puedas mover la camara y donde apunta, para ver cosas.

- la dinamica del coche no me acaba de convencer. creo que acelera/frena muy rapido.

## HECHO
- ralentizarlos un poco con < >
- es posible activar piloto automatico
- modo debug.
- varios niveles
- trigonometría rápida (`mgl_sin_fast`/`mgl_cos_fast`/`mgl_sincos_fast`) en dirección, `relative()`, `visible()` y animaciones (7b0c368)

----

1) **[HECHO]** I-cache (17 %). Antes de mis cambios había 2,1 M fallos; ahora 4,9 M, por el solape de código que vimos. Con una de 16 KB o de 2 vías debería volver a niveles de antes o mejores: +12–15 %.
2) **[EN PARTE]** Saltos (16,6 %). Sin tocar el hardware: MIN/MAX en `udiv_shift` y al acotar la z de cada span, y `raster_triangle_area` sin repetir los descartes de `triangle()`: fallos 11,1 → 10,3 %, burbujas 0,253 → 0,238 por instrucción (7f36ae8). Queda el `if (!ready)` de `raster_triangle_area` (89 % de fallos, se arregla sacando el bloque con un `goto`) y BTB/gshare. La BTB de 512 entradas que modelamos bajaba los fallos de predicción del 10,7 % a ~4–5 %. Eso sería +8–10 %. Las burbujas de los saltos bien predichos dependen de cómo esté hecho el fetch; puedo mirarlo. **[PENDIENTE]** Ahora: BTB de 64 entradas + estática BTFN + RAS de 8; burbujas 1/3/6.
   → Hecho: I-cache y D-cache de 16 KB (f30f10a). racer fijo 6,00 → 7,32 fps; tie_fighter 5,39 → 7,68 fps.
3) **[HECHO]** Espera del swap (5,5 %). Triple buffer por defecto en MiniGPU, `frameBuffers(2)` para volver al doble (7bfbc3d): racer 9,46 → 10,74 fps. Ojo al medir: con triple buffer `SWAP_WAIT` es el tiempo que el swap pasa pendiente hasta el vblank (~8 ms por frame), no CPU parada; la CPU ya no espera (mmio.md §13.2).

---

En racer el **75 % del frame es el renderer 3D** y la lógica del juego apenas pesa. Lo saco del perfil de racer en coma fija con el piloto automático: 3,83 M instrucciones por frame, sumando el código C y el runtime.

**Dónde se va el tiempo:**

| Bloque | % | Detalle |
|---|---:|---|
| **Rasterizado** | **42 %** | `fragment_span` 19,6 % (unos 64.000 píxeles por frame, 9 instrucciones por píxel); `raster_triangle` 13 % propio (970 instrucciones por triángulo: preparación y 3 divisiones por fila); `depth_plane` **9,8 %** (906 por triángulo, aritmética de 64 bits) |
| **Vértices** | ~16 % | `transform_vertex_q` 7,1 % y `viewport_map_q` 7,4 % (1.458 vértices por frame, 193 instrucciones cada uno, con su división) |
| **`draw_indexed` propio** | 8,4 % | unas 300 instrucciones por triángulo de gestión: índices, caché de vértices, copias de estructuras, y vaciar la caché de 64 entradas en cada dibujo |
| **Float por software** | ~12 % | P×V×M con dos productos 4×4 cada vez que cambia el modelo (3,6 %); las colisiones del juego (3,5 %); `visible`/`rotateY` (~4 %) |
| **Borrados y 2D** | ~7 % | borrar color y profundidad (3,7 %); el cielo y el agua se pintan encima con `rect` (`row_fill` 2,4 %), así que la pantalla se rellena dos veces |
| **Juego** | ~5 % | sobre todo `blocked()` |

**Mejoras de software**, de más a menos ganancia estimada:

1. **[HECHO]** **`mgr_depth_plane` más barato (−5–6 %).** Calcula el plano de profundidad de cada triángulo con multiplicaciones de 64 bits partidas (`mulr`) y un recíproco con Newton. Para triángulos pequeños sobra precisión. Podría hacerse con 32 bits y una sola `udiv_shift`, y así bajaría de ~900 a ~300 instrucciones.
2. **[PENDIENTE]** **El LOD de vacas, ciervo, coches y gasolinera (−4,8 %).** Ya medido; es cambiar los modelos de tu juego.
3. **[HECHO]** **La gestión por triángulo en `draw_indexed` y la preparación de `raster_triangle` (−3–5 %).** Menos copias de estructuras, no vaciar la caché de vértices en cada dibujo, y algún atajo para triángulos de una o dos filas. Hecho: caché de vértices persistente (no se vacía en cada dibujo) y punteros a entradas en vez de copias. Falta: la preparación de `raster_triangle` y el atajo de triángulos de una o dos filas. Probado también quitar las divisiones por fila de `raster_triangle` (aristas incrementales tipo Bresenham, mismos píxeles): +16 % de instrucciones en la función y un DIV aquí cuesta solo ~10 ciclos (salida temprana), así que no compensa; descartado. Quitados los `?:` del bucle de filas (lcc los pasa por la pila): −0,4 %.
4. **[PENDIENTE]** **`blocked()` en racer (−3,4 %).** En cada llamada recorre los ~230 objetos del mapa con float por software. Con una lista de objetos por casilla solo miraría los 2–3 cercanos.
5. **[HECHO]** **Guardar P×V (−1,8 %).** Proyección y vista cambian una vez por frame, así que por cada modelo bastaría un producto 4×4 en vez de dos.
6. **[HECHO]** **No borrar el color si el sketch pinta la pantalla entera (−1,8 %).** racer ya cubre el fondo con el cielo y el agua. Nuevo `mgl_clear_depth()` (CLEAR con `MGL_CLEAR_KEEP_COLOR`) y racer pinta el cielo con `rect` en vez de `background()`: −1,9 %.

En total, unos −20 % de instrucciones. 1 y 3 son de mini-gl y benefician a todos los sketches. 2 y 4 son cambios en tu juego. 5 es de mini-gl. 6 toca racer o la capa Processing, porque implica no borrar el color.

**Una advertencia por lo que hemos visto en la placa:** menos instrucciones no siempre significa más fps. Lo que hagamos debería también **reducir el tamaño** del código caliente (`raster_triangle` y `depth_plane` ya ocupan unos 4 KB), o volveremos a chocar con la I-cache de 8 KB. Por eso conviene hacer antes, o a la vez, la I-cache de 16 KB.

----

1) **[HECHO]** FP32 que el compilador use de verdad. `--fp32` genera FADD/FSUB/FMUL/FDIV (01b6df3; racer float 4,69 → 7,36 fps) y ahora también FEQ/FLT/FLE (`0x3C`) y FTOI/ITOF (`0x3D`, con `fbits` para Q16.16), mismos bits que softfloat (7618258, u.lcc a889a12). En coma fija, `q_from_f32` es FMUL por 65536 + FTOI. racer en el simulador: float + fp32 3,17 → 2,52 M instr/frame; coma fija + fp32 2,95 → 2,81.

conversiones int↔float (FCVT/FTOI): __floatsisf, __fixsfsi y q_from_f32, ~4 % del frame;
comparación (FLT/FLE/FEQ, que dejan 0/1 en un registro): __sfa_cmp y similares.
En racer en coma fija el float por software es ~12 % del frame. En float es más o menos la mitad: 6,9 M frente a 3,7 M instrucciones por frame. Es la que más gana con diferencia, pero hay que cambiar el compilador.

2) **[PENDIENTE]** Accesos a memoria con post-incremento (LOADH Rd, (Ra)+2) o con índice por registro (base + Rb). En el bucle por píxel de fragment_span, 2 de las 9 instrucciones solo avanzan punteros (ADDI c, ADDI d). Pasaría de 9 a 7 por píxel, unos −4 % del frame, y también ayudaría a clear_buffer y row_fill.
   Decidido: solo **store** con postincremento (`STOREBP/STOREHP/STOREP` de la propuesta v0.4, que encaja en 2 lecturas + 1 escritura); en el mapa compatible iría en `0x1F` (`0x1E` ya es EXT). El load con postincremento pide un segundo puerto de escritura y solo quitaría 1 instrucción en los píxeles ocultos. En el bucle de z: `if (v < *d) { *d++ = v; *c++ = fill; } else { d++; c++; }` → 7 por píxel visible. `mini_opt` lo generaría con un patrón `STOREH + ADDI`. Alternativa sin ISA: desenrollar ×2 leyendo la profundidad con un LOAD de 32 bits (~8 visible / 6 oculto).

3) **[HECHO]** CLZ (contar ceros iniciales). `EXT` func6 `0x09`, capability `clz`; intrínseco `__mini_clz` (`mini_ext.h`) y `EXT=1` en mini-gl. racer coma fija + fp32: 2,81 → 2,69 M instr/frame (−4 %, más de lo estimado). clz32 cuesta unas 28 instrucciones y se llama más de 2.000 veces por frame, dentro de udiv_shift y la normalización. Con una instrucción serían −2–3 %, y en hardware es muy barata.

4) **[PENDIENTE]** Una división Q16 o 64/32 en hardware (DIVFX, o una DIVU que devuelva cociente y resto con desplazamiento). Sustituiría udiv_shift y lo que queda de __mini_divfx (~4–5 % del frame). Se aprovecharía el divisor que ya existe, con unos ciclos más.

5) **[HECHO]** MIN/MAX o selección condicional. MIN/MAX/MINU/MAXU en `EXT` (`0x1E`), intrínsecos `__mini_min`... Para que salgan en una instrucción hizo falta el pase `retarget` de `mini_opt` y los marcadores `ret32`/`clobber` (04a5002); sin ellos el intrínseco costaba más que el `if`. Usados en la caja del triángulo y `EDGE_SPAN`: −0,2 % de instrucciones, y menos saltos. Selección condicional (`SEL`) sigue pendiente: necesita 3 lecturas. El recorte de la profundidad, la caja del triángulo y las saturaciones están hechos ahora con saltos. Supondría −1–2 % de instrucciones, pero sobre todo menos saltos, que son el 16,6 % de los ciclos perdidos.

6) **[PENDIENTE]** Escribir dos píxeles de 16 bits a la vez (SIMD 2×16). En el relleno de spans y el borrado ya se hace con palabras de 32 bits. En el bucle con test de profundidad sería más complicado: haría falta `MINU.H2`, una comparación por mitades y una selección bit a bit, y leer el color viejo; ~8 instrucciones por píxel, sin saltos por píxel. De momento no compensa frente a `STOREHP`.

Mi recomendación:

- **[HECHO]** A corto plazo: CLZ y MIN/MAX.
- **[HECHO]** Lo que más rinde: terminar FP32 (comparaciones y conversiones) y que lcc la use.
- Coste en la 38: la CPU baja de 57,20 a 52,94 MHz (semilla 9, una ejecución; objetivo 50). Probar semillas, o sacar CLZ de la ALU de un ciclo si hace falta margen.
- Post-incremento: da buen resultado en el bucle más caliente, pero toca el formato de las instrucciones de memoria.



----

**Hecho después (racer en la 38, coma fija + fp32 + EXT, triple buffer):**

- **[HECHO]** `flush_state` con marcas: las matrices se comparan en `mgl_set_matrix` (9afacc0) y el resto con una máscara `dirty` (d2f8c95); `shape()` encuentra su modelo con una pista en vez de recorrer 64 huecos. racer 10,74 → 10,90 fps.
- **[HECHO]** Color por vértice: formato `POSITION_F32_XYZ_RGB565`, y `shape()` dibuja un modelo con un solo `DRAW_INDEXED` en vez de uno por color (236 → 37 dibujos por frame en racer); `disableStyle()`/`enableStyle()` (7f36ae8). racer 2,622 → 2,470 M instr/frame, 10,87 → 11,08 fps.
- **[DESCARTADO]** Filas de `fragment_span` sumando el stride en vez de multiplicar: los punteros acaban en la pila y no gana. `mgl_sqrt` sin FDIV: en marcha solo se llama 4 veces por frame.
- **[DESCARTADO]** Modo 3D directo (sin command buffer): grabar e interpretar los comandos es ~6 % de las instrucciones, y se perdería grabar/reproducir y la GPU.
- **[HECHO]** `hint(DISABLE_DEPTH_TEST)`/`DISABLE_DEPTH_MASK` en Processing (9afacc0).
- **[HECHO]** I-cache de la 38 a 32 KB (antes 16 KB, mapeo directo): con 16 KB el código caliente se pisaba según cómo cayera (±4 % de fps al mover una función). Fallos por cada mil instrucciones: racer 2,35 → 0,78, tanks 7,67 → 1,85, skimmer 6,67 → 1,51; tanks 40,8 → 42,9 fps, skimmer 20,0 → 21,5, racer CPI 1,82 → 1,79. CPU 53,62 MHz. Pendiente quizá: D-cache (5-7 fallos por mil instrucciones; simularla antes de tocarla).
- **[HECHO]** `make board-<sketch>`: compila, sube el bitstream si la placa no lo tiene y arranca; racer con `FIXED=1 FP32=1 EXT=1`.

**¿Algoritmo del pintor en vez del Z-buffer?** Ningún ejemplo lo usaba. Ahora hay `hint(ENABLE_DEPTH_SORT)` (`MGL_STATE_DEPTH_SORT`): el renderer guarda los triángulos y los pinta de lejos a cerca antes de lo 2D, sin Z-buffer si además va `hint(DISABLE_DEPTH_TEST)`. Activado en tanks (35,6 → 40,8 fps) y skimmer (18,2 → 20,0 fps), con la imagen cambiada en unos pocos píxeles de borde.
- **[PENDIENTE]** Probarlo en racer: allí el 99,4 % de los píxeles pasa el test (casi nada se tapa) y la profundidad cuesta ~20 % de las instrucciones, pero el relieve del terreno puede tapar objetos y los chunks del terreno necesitarían un orden por triángulo; hay que ver las imágenes a lo largo de una vuelta.

**¿Hemos implementado SEL?** No: está definida (v0.2, EXT func6 `0x04`) pero no en el RTL, simuladores, ensamblador ni lcc, y necesita 3 lecturas de registro. En racer no hace falta: los saltos que más fallaban eran mínimos y acotados (resueltos con MIN/MAX), banderas a bits (`mgr_outcode_q`, con `SLT`, que ya existe) y saltos de una vez por triángulo fuera de la BTB.
- **[PENDIENTE]** lcc no genera `SLT` nunca (sus comparaciones son siempre saltos): un pase de `mini_opt` que cambie salto + `MOVI 1`/`MOVI 0` por `SLT`/`SLTU` (`mgr_outcode_q`, ~0,4 %).


# `cube-solid` (GPU)

## Objetivo

Un cubo sólido animado para la MiniGPU, con un rasterizador paralelo **medible**.
La carpeta guarda la evolución del programa, de la v3 a la v8; cada versión mide
algo distinto.

## Versiones

| Fichero | Qué cambia |
|---|---|
| [`cube_solid_v3_animated.asm`](cube_solid_v3_animated.asm) | 64 orientaciones precalculadas (seis descriptores por frame, `A*x+B*y+C`). Cada uno de los 64 hilos posee 600 palabras RGB565 (`tid`, `tid+64`...); los ocho lanes de un warp escriben palabras consecutivas y la LSU BL8 las coalesce. Escribe también el fondo, sin pasada de borrado |
| [`cube_solid_v4_incremental.asm`](cube_solid_v4_incremental.asm) | Procesa un triángulo completo antes del siguiente: carga su descriptor una vez, recorre solo su caja y actualiza las tres funciones de borde con sumas |
| [`cube_solid_v5_integer.asm`](cube_solid_v5_integer.asm) | **La GPU calcula la geometría**: la lane 0 rota y proyecta los ocho vértices, hace *back-face culling* y genera los descriptores. Sin tabla de frames |
| [`cube_solid_v6_vertex_simt.asm`](cube_solid_v6_vertex_simt.asm) | Las lanes 0..7 rotan y proyectan un vértice cada una; la lane 0 hace el culling |
| [`cube_solid_v7_face_simt.asm`](cube_solid_v7_face_simt.asm) | Además, las lanes 0..5 procesan una cara cada una |
| [`cube_solid_v8_tight_clear.asm`](cube_solid_v8_tight_clear.asm) | Geometría SIMD y *setup* de v6, pero limpia solo `xword = 24..135`, `y = 16..223`: 23 296 palabras frente a 28 672 (-18,75 %) |
| [`cube_solid.asm`](cube_solid.asm) | Alias estable de «la mejor versión actual»: hoy incluye v6 |

## Ficheros de apoyo

- [`make_cube_solid_frames.py`](make_cube_solid_frames.py) genera las tablas
  `cube_solid_frames_v3.inc` y `cube_solid_frames_v4.inc` (los descriptores
  precalculados) y `cube_sine_q14.inc` (seno en Q2.14, 1 KiB, que usan v5 en
  adelante). Los `.inc` están marcados «no editar a mano».
- `cube_v6_ref*.bin` y `cube_v8_frame*.bin`: frames de 150 KB (RGB565 320x240) de
  referencia y capturas de v6 y v8. Ningún script ni test los referencia; parecen
  volcados de cuando se afinaron esas versiones.

## Por qué no hay `test.json`

No hay un modelo independiente del frame final: el generador solo calcula los
descriptores de v3 y v4. Un esperado grabado del simulador serviría de regresión,
pero no de verificación. El cubo equivalente de CPU, que sí es caso, está en
[`cases-cpu/demos/cube-solid`](../../../cases-cpu/demos/cube-solid/).

Contexto: [README de la categoría](../README.md).

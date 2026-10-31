# Command buffer

**Importante:** la autoridad sobre el formato es [`src/mgl_commands.h`](../src/mgl_commands.h): constantes,
tamaños y offsets de cada campo. Este documento lo explica; si no coinciden, manda la cabecera.

## Reglas generales

- Todo es **little-endian**. Cada campo de 16 o 32 bits va alineado a su tamaño dentro del comando, y cada
  comando empieza en un múltiplo de 4.
- **No se copian estructuras C.** Cada campo se escribe y se lee por su offset (`WR16`/`WR32`/`RD16`/`RD32`
  de [`mgl_bytes.h`](../src/mgl_bytes.h)), así que el padding del compilador no importa. En el host se hace
  byte a byte; en MiniGPU, con accesos de 16 y 32 bits.
- **Sin punteros nativos ni handles.** Las direcciones son de 32 bits en el espacio de la RAM compartida de
  MiniGPU ([3d-recursos.md](3d-recursos.md)). La dirección 0 significa «nada».
- **Reservados a 0.** Un renderer comprueba los campos reservados: un valor distinto es un buffer de una
  versión que no conoce.
- Se recorre por `size_bytes`; un renderer valida que cada comando cabe en `used_bytes` y que su tamaño es el
  de su opcode.

## Cabeceras

Cabecera de buffer, 16 bytes en el offset 0:

| Offset | Campo | |
|---|---|---|
| +0 | u32 `magic` | `0x4D474C30` (`"0LGM"` en memoria) |
| +4 | u32 `version` | 1: solo comandos 2D. 2: algún comando 3D |
| +8 | u32 `used_bytes` | cabecera incluida |
| +12 | u32 `capacity` | |

Cabecera de comando, 16 bytes, la tienen todos:

| Offset | Campo |
|---|---|
| +0 | u16 `opcode` |
| +2 | u16 `flags` |
| +4 | u32 `size_bytes` (cabecera incluida) |
| +8 | u32 `arg0` |
| +12 | u32 `arg1` |

Tras ella, `size_bytes - 16` bytes de payload.

### Versiones

La versión 1 usaba `opcode` de 32 bits. Con `flags = 0` es el mismo byte a byte, así que **los comandos 2D
no cambian**: un buffer sin 3D sigue saliendo idéntico al de antes, con versión 1, y lo siguen ejecutando V1
(`mgl_cmd_render_cpu`) y V2 (`mgl_gpu_render`). El primer comando 3D sube la cabecera a la versión 2;
`mgl_cmd_reset` la devuelve a 1. V1 y V2 solo aceptan la versión 1, así que rechazan un buffer 3D en vez de
interpretarlo mal; el renderer 3D ([renderer/](../renderer/)) solo acepta la 2.

## Comandos

| Opcode | Comando | Bytes | Versión |
|---|---|---|---|
| `0x01` | CLEAR | 16 | 1 (con `flags`, 2) |
| `0x02` | BATCH (primitiva 2D) | 40 | 1 |
| `0x10` | SET_RENDER_TARGET | 32 | 2 |
| `0x11` | SET_VIEWPORT | 16 | 2 |
| `0x12` | SET_MATRIX | 80 | 2 |
| `0x13` | SET_RENDER_STATE | 16 | 2 |
| `0x14` | SET_COLOR | 16 | 2 |
| `0x15` | DRAW_INDEXED | 32 | 2 |
| `0x16` | END_FRAME | 16 | 2 |

No hay opcodes de transformar, recortar ni de primitivas de Processing (`box`): son trabajo del renderer o
de la capa de arriba.

### CLEAR (16)

`arg0` = color RGB565. Con `flags = 0` (el CLEAR de siempre) `arg1 = 0` y solo borra el color. Con
`flags = MGL_CLEAR_DEPTH` (1) borra también la profundidad: `arg1` es el valor en Q16.16 sin signo, de `0`
(cerca) a `0x10000` (lejos). Borra todo el destino; no depende del viewport.

### BATCH (40)

Una primitiva 2D en píxeles, como siempre: `arg0` = 1 (primitivas), `arg1` = 0; `+16` tipo (`MGL_PRIM_*`),
`+20/+24/+28` coordenadas empaquetadas (dos `s16` por palabra), `+32` relleno, `+34` contorno, `+36` flags
(`MGL_BATCH_FILL`, `MGL_BATCH_STROKE`), `+38` grosor. `IMAGE` lleva en `+24` un handle del contexto V1, no
una dirección: el renderer 3D lo rechaza (`MGR_ERR_UNSUPPORTED`) hasta que los sprites pasen a direcciones.

### SET_RENDER_TARGET (32)

| Offset | Campo |
|---|---|
| `arg0` | dirección del color |
| `arg1` | dirección de la profundidad (0: sin profundidad) |
| +16 | u16 ancho |
| +18 | u16 alto |
| +20 | u16 stride del color, en píxeles |
| +22 | u16 stride de la profundidad, en píxeles (0 sin ella) |
| +24 | u16 formato del color: `MGL_COLOR_RGB565` (1) |
| +26 | u16 formato de la profundidad: `MGL_DEPTH_NONE` (0) o `MGL_DEPTH_U16` (1: 0 cerca, 65535 lejos) |
| +28 | u32 reservado |

Afecta también a lo 2D que venga después. Deja el viewport en todo el destino. Ancho, alto y strides de 1 a
1024.

### SET_VIEWPORT (16)

`arg0` = `PACK(x, y)`, `arg1` = `PACK(ancho, alto)`: dos `s16` por palabra, `x`/`y` en la mitad baja. En
píxeles del destino; puede salirse de él (se recorta al dibujar). Profundidad siempre de 0 a 1.

### SET_MATRIX (80)

| Campo | |
|---|---|
| `arg0` | cuál: `MGL_MATRIX_MODEL` (1), `VIEW` (2), `PROJECTION` (3) |
| `arg1` | formato de los componentes: `MGL_FORMAT_FLOAT32` (1); `MGL_FORMAT_Q16_16` (2) está reservado y se rechaza |
| +16..+79 | 16 componentes de 32 bits, **column-major** (`m[columna * 4 + fila]`) |

Un solo opcode para las tres matrices. La matriz va por valor: MiniGL la copia al emitirla.

### SET_RENDER_STATE (16)

`arg0` = bits, `arg1` = reservado:

| Bit | |
|---|---|
| `MGL_STATE_DEPTH_TEST` (1) | prueba de profundidad LESS |
| `MGL_STATE_DEPTH_WRITE` (2) | escritura de profundidad |
| `MGL_STATE_BLEND` (4) | reservado: se rechaza |
| `MGL_STATE_CULL_BACK` (8) | descarta caras traseras |
| `MGL_STATE_CULL_FRONT` (16) | descarta caras delanteras |

De frente = antihorario en coordenadas normalizadas (y hacia arriba), como OpenGL.

### SET_COLOR (16)

`arg0` = color uniforme RGB565 (16 bits bajos; el resto, 0), `arg1` = reservado.

### DRAW_INDEXED (32)

| Offset | Campo |
|---|---|
| `arg0` | dirección de los vértices (alineada a 4) |
| `arg1` | dirección de los índices (alineada a 2) |
| +16 | u32 número de vértices (1..65536) |
| +20 | u32 número de índices (múltiplo de 3) |
| +24 | u16 formato de vértice: `MGL_VERTEX_POSITION_F32_XYZ` (1); `POSITION_Q16_16_XYZ` (2) reservado |
| +26 | u16 formato de índice: `MGL_INDEX_UINT16` (1); `UINT32` (2) reservado |
| +28 | u16 stride del vértice en bytes (≥ 12, múltiplo de 4) |
| +30 | u16 topología: `MGL_TOPOLOGY_TRIANGLES` (1) |

El stride es explícito para poder añadir atributos tras la posición sin cambiar el comando. Un índice fuera
de rango detiene la ejecución (`MGR_ERR_LIMIT`).

### END_FRAME (16)

`arg0` = número de frame (no cambia lo que se dibuja; pensado para fences), `arg1` = reservado. Tras él el
estado vuelve al inicial.

## Estado inicial

Al empezar a ejecutar un buffer, y tras cada END_FRAME: sin destino, viewport vacío (lo fija
SET_RENDER_TARGET), las tres matrices identidad, `MGL_STATE_DEPTH_WRITE` y color blanco. Dibujar sin destino
es un error (`MGR_ERR_STATE`).

MiniGL no da nada por emitido al empezar un frame: cada frame lleva todo el estado que usa y se puede
ejecutar solo (`mgl-replay` lo hace sin MiniGL). Dentro del frame no repite lo que ya emitió.

## Ejemplo: el frame del cubo

`examples/rotating_cube.c`, 400 bytes:

```text
HEADER                magic, version 2, used 400, capacity 65536
SET_RENDER_TARGET     0x01000000, 0x0105B000, 320x240, strides 320, RGB565, U16
CLEAR  flags=DEPTH    color 0x10A2 (20,20,20), profundidad 0x10000
SET_VIEWPORT          0, 0, 320, 240
SET_MATRIX            PROJECTION, FLOAT32, 16 valores
SET_MATRIX            VIEW, FLOAT32, 16 valores
SET_MATRIX            MODEL, FLOAT32, 16 valores
SET_RENDER_STATE      DEPTH_TEST | DEPTH_WRITE
SET_COLOR             0xFC65 (255,140,40)
DRAW_INDEXED          vértices en el heap de MiniGL, índices detrás; 8 vértices, 36 índices,
                      POSITION_F32_XYZ, UINT16, stride 12, TRIANGLES
END_FRAME             número de frame
```

`tests/test_commands.c` y `tests/test_cube.c` comprueban esta secuencia campo a campo.

## Errores al ejecutar (renderer 3D)

| Código | Cuándo |
|---|---|
| `MGR_ERR_FORMAT` | magic, versión, tamaños, opcode desconocido, flags o reservados distintos de 0 |
| `MGR_ERR_MEMORY` | dirección fuera de la RAM compartida o mal alineada |
| `MGR_ERR_UNSUPPORTED` | formato o estado reservado (Q16.16, UINT32, blending, IMAGE) |
| `MGR_ERR_STATE` | dibujar o borrar sin destino |
| `MGR_ERR_LIMIT` | tamaño de destino o viewport fuera de rango, índice fuera de la malla |

`error_offset` dice qué comando falló. Lo dibujado hasta ahí se queda.

## Sprites (2D)

En V1 los sprites se referencian por handles locales al contexto CPU. V2 usa `mgl_gpu_sprite_t` (rellenada
por `mgl_gpu_sprites_from_cmd`) para resolver esos handles. En MiniGPU la CPU y la GPU comparten la memoria,
así que los punteros de la tabla valen tal cual (lo prueba `shapes`, que dibuja imágenes). Una GPU con su
propia memoria necesitaría copiar o traducir la tabla y los píxeles, y fijar cuánto tiempo siguen siendo
válidos. Para que IMAGE entre en el contrato de la versión 2 tiene que llevar una dirección (como
DRAW_INDEXED), con el modelo de recursos de [3d-recursos.md](3d-recursos.md).

## Historia: el diseño inicial

El diseño conceptual consideró batches con N primitivas y atributos opcionales, para amortizar el coste de
estado y decodificación. V1 emite un batch por primitiva; **el agrupamiento N>1 no está implementado**.

## Precauciones

Verificar layout y ancho de punteros/enteros en CPU y GPU. La emulación host de ocho lanes (V2) no prueba
sincronización SIMT, SSY ni coherencia de memoria: eso lo prueba `make check-minigpu V=2` en el simulador de
CPU + GPU.

# Command buffer: implementación actual y diseño inicial

**Importante:** la implementación real de V1/V2 es la autoridad sobre el formato actual; no debe confundirse con la propuesta conceptual temprana.

## Formato implementado (versión 1)
- Buffer: cabecera de 16 bytes (magic, version, used_bytes, capacity).
- Comandos: `CLEAR` de 16 bytes o `BATCH` de 40 bytes, con una sola primitiva por batch.
- Codificación little-endian por bytes.
- Descriptor de primitiva y atributos de estado: consultar `src/minigl.c` para campos y validaciones exactos.
- El buffer no lleva dirección del framebuffer: la proporciona el trabajo de render.
- El orden de los comandos se respeta para primitivas solapadas.

## Evolución discutida
El diseño conceptual consideró comandos de 16 bytes y primitivas de 16 bytes, batches con N primitivas y atributos opcionales, para amortizar el coste de estado y decodificación. La implementación actual emite un batch por primitiva; **el agrupamiento N>1 no está implementado**.

## Sprites
En V1 los sprites se referencian por handles locales al contexto CPU. V2 usa `mgl_gpu_sprite_t` (rellenada por `mgl_gpu_sprites_from_cmd`) para resolver esos handles. En MiniGPU la CPU y la GPU comparten la memoria, así que los punteros de la tabla valen tal cual (lo prueba `shapes`, que dibuja imágenes). Una GPU con su propia memoria necesitaría copiar o traducir la tabla y los píxeles, y fijar cuánto tiempo siguen siendo válidos.

## Precauciones
Verificar layout y ancho de punteros/enteros en CPU y GPU. Validar longitud, opcode, tamaños, límites y referencias antes de renderizar. La emulación host de ocho lanes no prueba sincronización SIMT, SSY ni coherencia de memoria: eso lo prueba `make check-minigpu V=2` en el simulador de CPU + GPU.

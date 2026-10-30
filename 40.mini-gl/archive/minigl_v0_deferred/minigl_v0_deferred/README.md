# MiniGL V0: directo y diferido (C89)

Se conserva la API `processing.h` y el rasterizador CPU de la versión directa.

## Flujo

- **Directo:** `mg_set_deferred(NULL)` y llamadas `draw()` que rasterizan inmediatamente.
- **Diferido:** `mg_cmd_init`, `mg_cmd_reset` al comienzo de cada frame, `mg_set_deferred(&cmd)`, `draw()`, `mg_cmd_render_cpu(&cmd)` y presentación del backbuffer cuando haya terminado.
- `mg_bind(backbuffer,width,height,stride)` configura el destino RGB565; `stride` se mide en píxeles.
- El renderer CPU reproduce exactamente el mismo código de rasterización (`raster.c`) en ambos modos.
- Comprobar `mg_cmd_status` después de grabar. Si el buffer se llena, no se renderiza parcialmente.

```c
static unsigned char command_memory[8192];
static mg_cmd_buffer_t commands;

/* Al inicializar: */
mg_bind(backbuffer, 320, 240, 320);
mg_cmd_init(&commands, command_memory, sizeof(command_memory));

/* En cada frame: */
mg_cmd_reset(&commands);
mg_set_deferred(&commands);
draw();
if (mg_cmd_status(&commands) == MG_OK)
    mg_cmd_render_cpu(&commands);
/* La plataforma espera vblank e intercambia buffers. */
```

## Formato provisional

Todos los campos enteros se serializan little-endian. Cabecera del buffer: `magic`, `version`, `used_bytes`, `capacity` (16 B). Comando `CLEAR`: opcode=1, tamaño=16, color RGB565 en arg0. Comando `BATCH`: opcode=2, tamaño=40, count=1, seguido de descriptor de 16 B (`type,p0,p1,p2`) y atributos de 8 B (fill RGB565, stroke RGB565, flags, strokeWeight). Coordenadas empaquetadas como pares signed 16-bit.

**Limitaciones intencionales de esta primera iteración:** se emite un batch por primitiva (todavía sin agrupación); sprites usan un handle de un registro local de hasta 256 punteros en `mg_cmd_buffer_t` y por tanto **no son todavía comandos autocontenidos ni ejecutables por la GPU**. Antes de V1 hay que reemplazar esos handles por direcciones/referencias de memoria compartida y fijar el ABI del comando. El buffer y los sprites deben seguir vivos hasta finalizar el render. No hay mezcla alfa, ni clipping configurable, ni antialiasing. El dibujo de círculo y triángulo conserva los algoritmos de V0 directo.

## Test en host

```sh
cc -std=c89 -Wall -Wextra -pedantic -O2 minigl.c raster.c processing.c test.c -o test
./test
```

El test comprueba que un mismo `draw()` produce un framebuffer idéntico en ambos modos.

#ifndef MINIGL_H
#define MINIGL_H

/* C89; RGB565; el host debe tener unsigned short=16 y unsigned int=32 bits. */
typedef unsigned short mgl_color_t;
typedef unsigned int mgl_u32;

typedef struct {
    const mgl_color_t *pixels;
    int width, height, stride;
} mgl_sprite_t;

/* Formato v0.1: header de buffer 16B; comandos CLEAR 16B o BATCH 16B +
   descriptor de primitiva 16B + atributos 8B. Enteros little-endian 32-bit.
   Esta version emite un BATCH de una primitiva (sin agrupacion todavia). */
typedef struct { mgl_u32 magic, version, used_bytes, capacity; } mgl_buffer_header_t;

typedef struct { mgl_u32 opcode, size_bytes, arg0, arg1; } mgl_command_t;

typedef struct { mgl_u32 type, p0, p1, p2; } mgl_primitive_t;

#define MGL_BUFFER_MAGIC 0x4D474C30U
#define MGL_BUFFER_VERSION 1U

#define MGL_OK 0
#define MGL_ERR_SPACE (-1)
#define MGL_ERR_ARGUMENT (-2)
#define MGL_ERR_SPRITES (-3)

/* El command buffer contiene solo bytes; el registro de sprites pertenece al
   contexto y resuelve handles para el renderer CPU. */
typedef struct {
    unsigned char *bytes;
    mgl_u32 capacity,used;
    const mgl_sprite_t *sprites[256];
    unsigned int sprite_count;
    int error;
} mgl_cmd_buffer_t;

void mgl_bind(mgl_color_t *pixels,int width,int height,int stride);
void mgl_set_deferred(mgl_cmd_buffer_t *buffer); /* NULL => directo */
/* Cambia el framebuffer de mgl_bind por otro del mismo tamaño sin tocar el
   estado de dibujo. Con previous != NULL, pixels no tiene el lienzo: lo tiene
   previous, y se copia antes de dibujar encima, salvo que antes llegue un
   mgl_clear (que lo tapa todo). mgl_finish hace la copia si sigue pendiente. */
void mgl_set_target(mgl_color_t *pixels,const mgl_color_t *previous);
void mgl_finish(void);

/* En MiniGPU, memory alineada a 4: se lee y escribe por palabras. */
int mgl_cmd_init(mgl_cmd_buffer_t *buffer,void *memory,mgl_u32 capacity);
int mgl_cmd_reset(mgl_cmd_buffer_t *buffer);
int mgl_cmd_render_cpu(const mgl_cmd_buffer_t *buffer);
int mgl_cmd_status(const mgl_cmd_buffer_t *buffer);

void mgl_clear(mgl_color_t color);
void mgl_fill(mgl_color_t color);
void mgl_no_fill(void);
void mgl_stroke(mgl_color_t color);
void mgl_no_stroke(void);
void mgl_stroke_weight(int width);
void mgl_point(int x,int y);
void mgl_line(int x0,int y0,int x1,int y1);
void mgl_rect(int x,int y,int w,int h);
void mgl_circle(int cx,int cy,int radius);
void mgl_triangle(int x0,int y0,int x1,int y1,int x2,int y2);
void mgl_image(const mgl_sprite_t *sprite,int x,int y);

#endif

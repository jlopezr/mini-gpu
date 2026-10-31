#ifndef MINIGL_H
#define MINIGL_H
/* C89; RGB565; el host debe tener unsigned short=16 y unsigned int=32 bits. */
typedef unsigned short mg_color_t;
typedef unsigned int mg_u32;
typedef struct { const mg_color_t *pixels; int width,height,stride; } mg_sprite_t;
/* Formato v0.1: header de buffer 16B; comandos CLEAR 16B o BATCH 16B +
   descriptor de primitiva 16B + atributos 8B. Enteros little-endian 32-bit.
   Esta version emite un BATCH de una primitiva (sin agrupacion todavia). */
typedef struct { mg_u32 magic,version,used_bytes,capacity; } mg_buffer_header_t;
typedef struct { mg_u32 opcode,size_bytes,arg0,arg1; } mg_command_t;
typedef struct { mg_u32 type,p0,p1,p2; } mg_primitive_t;
#define MG_BUFFER_MAGIC 0x4D474C30U
#define MG_BUFFER_VERSION 1U
#define MG_OK 0
#define MG_ERR_SPACE (-1)
#define MG_ERR_ARGUMENT (-2)
#define MG_ERR_SPRITES (-3)
/* El command buffer contiene solo bytes; el registro de sprites pertenece al
   contexto y resuelve handles para el renderer CPU. */
typedef struct {
    unsigned char *bytes;
    mg_u32 capacity,used;
    const mg_sprite_t *sprites[256];
    unsigned int sprite_count;
    int error;
} mg_cmd_buffer_t;
void mg_bind(mg_color_t *pixels,int width,int height,int stride);
void mg_set_deferred(mg_cmd_buffer_t *buffer); /* NULL => directo */
int mg_cmd_init(mg_cmd_buffer_t *buffer,void *memory,mg_u32 capacity);
int mg_cmd_reset(mg_cmd_buffer_t *buffer);
int mg_cmd_render_cpu(const mg_cmd_buffer_t *buffer);
int mg_cmd_status(const mg_cmd_buffer_t *buffer);
void mg_clear(mg_color_t color);
void mg_fill(mg_color_t color);
void mg_no_fill(void);
void mg_stroke(mg_color_t color);
void mg_no_stroke(void);
void mg_stroke_weight(int width);
void mg_point(int x,int y);
void mg_line(int x0,int y0,int x1,int y1);
void mg_rect(int x,int y,int w,int h);
void mg_circle(int cx,int cy,int radius);
void mg_triangle(int x0,int y0,int x1,int y1,int x2,int y2);
void mg_image(const mg_sprite_t *sprite,int x,int y);
#endif

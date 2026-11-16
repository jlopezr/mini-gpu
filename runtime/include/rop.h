/*
 * API C para la capability ROP de MiniISA (§7.5).
 *
 * Las funciones submit no esperan: los descriptores se copian a los registros
 * de envio y ROPSUBMIT toma su instantanea antes de que la funcion retorne.
 * El llamador puede por tanto reutilizar el descriptor inmediatamente.
 */
#ifndef MINIGPU_ROP_H
#define MINIGPU_ROP_H

/* En MiniABI, unsigned es una palabra de 32 bits. El include minimo de LCC
 * no ofrece stdint.h, por eso la API no depende de cabeceras del host. */
typedef unsigned rop_u32;

enum {
    ROP_Z_ALWAYS = 0,
    ROP_Z_EQ     = 1,
    ROP_Z_NE     = 2,
    ROP_Z_LT     = 3,
    ROP_Z_LE     = 4,
    ROP_Z_GT     = 5,
    ROP_Z_GE     = 6,

    ROP_MODE_COLOR_32 = 1u << 3,
    ROP_MODE_Z_32     = 1u << 4,
    ROP_MODE_WRITE_Z  = 1u << 5,
    ROP_MODE_WRITE_COLOR = 1u << 6,
    ROP_MODE_SIGNED_Z = 1u << 7,
    ROP_MODE_COMPACT  = 1u << 12,
    ROP_MODE_SAT      = 1u << 13,

    ROP_CONFIG_BASES   = 1u << 0,
    ROP_CONFIG_STRIDES = 1u << 1,
    ROP_CONFIG_COLOR   = 1u << 2,
    ROP_CONFIG_Z       = 1u << 3,
    ROP_CONFIG_MODE    = 1u << 4,

    ROP_STATUS_BUSY       = 1u << 0,
    ROP_STATUS_QUEUE_FULL = 1u << 1,
    ROP_STATUS_ERROR      = 1u << 2,
};

typedef struct {
    rop_u32 dst, bytes, rows, dst_stride, pattern, mode;
} rop_fill_t;

typedef struct {
    rop_u32 src, dst, bytes, rows, src_stride, dst_stride, mode;
} rop_copy_t;

typedef struct {
    rop_u32 dst, elements, rows, dst_stride, initial, dx, dy, mode;
} rop_generate_t;

/* SPAN explicito. mode usa ROP_Z_* y ROP_MODE_*; vease isa.md §7.5. */
typedef struct {
    rop_u32 color, z, pixels, rows, color_stride, z_stride;
    rop_u32 color_value, z_initial, dx, dy, mode;
} rop_span_t;

/* Configuracion persistente para los spans compactos. */
typedef struct {
    rop_u32 color_base, z_base, color_stride, z_stride, color_value;
    rop_u32 z_initial, dx, dy, render_mode, groups;
} rop_config_t;

/* SPAN compacto: offsets sobre CONFIG; z_initial sustituye el de CONFIG. */
typedef struct {
    rop_u32 color_offset, z_offset, pixels, rows, z_initial, mode;
} rop_span_compact_t;

void rop_submit_fill(const rop_fill_t *job);
void rop_submit_copy(const rop_copy_t *job);
/* Igual que COPY, pero confirma los STORE anteriores de la CPU antes de leer src. */
void rop_submit_copy_fenced(const rop_copy_t *job);
void rop_submit_generate(const rop_generate_t *job);
void rop_submit_span(const rop_span_t *job);
void rop_submit_config(const rop_config_t *config);
void rop_submit_config_fenced(const rop_config_t *config);
void rop_submit_span_compact(const rop_span_compact_t *job);

/* Espera todos los submits anteriores; INV invalida tambien la D-cache. */
void rop_wait(void);
void rop_wait_invalidate(void);

/* Estado anterior al borrado en la variante _clear. */
rop_u32 rop_status(void);
rop_u32 rop_status_clear(void);

#endif

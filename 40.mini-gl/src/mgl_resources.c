#include "minigl3d.h"
#include "mgl_bytes.h"
#include "mgl_internal.h"

/* Tabla de mallas: el handle es (generación << 16) | (hueco + 1). La generación
   cambia al destruir, así que un handle viejo no resuelve a la malla que ocupe
   después su hueco. */
typedef struct {
    mgl_mesh_desc_t desc;
    unsigned int generation;
    int used;
} mesh_slot;

static mesh_slot meshes[MGL_MAX_MESHES];
static mgl_memory_t memory;
static int has_memory;
static mgl_u32 heap_addr, heap_size, heap_used;
static mgl_u32 frame_addr, frame_size, frame_used;

/* Reparto lineal en [base, base + size), con *used lo ya repartido. */
static mgl_u32 bump(mgl_u32 base, mgl_u32 size, mgl_u32 *used, mgl_u32 bytes, mgl_u32 align) {
    mgl_u32 start;
    if (!bytes || !align || (align & (align - 1U)) || !size) return 0;
    start = (base + *used + align - 1U) & ~(align - 1U);
    if (start - base > size || bytes > size - (start - base)) return 0;
    *used = start - base + bytes;
    return start;
}

int mgl_resources_init(const mgl_memory_t *m, mgl_u32 addr, mgl_u32 size) {
    int i;
    for (i = 0; i < MGL_MAX_MESHES; i++) {
        meshes[i].used = 0;
        meshes[i].generation++;
    }
    has_memory = 0;
    heap_addr = heap_size = heap_used = 0;
    frame_addr = frame_size = frame_used = 0;
    if (!m) return MGL_ERR_ARGUMENT;
    if (size && !mgl_memory_ptr(m, addr, size, 4)) return MGL_ERR_MEMORY;
    memory = *m;
    has_memory = 1;
    heap_addr = addr;
    heap_size = size;
    return MGL_OK;
}

mgl_u32 mgl_alloc(mgl_u32 bytes, mgl_u32 align) {
    return bump(heap_addr, heap_size, &heap_used, bytes, align);
}

int mgl_frame_memory_init(mgl_u32 addr, mgl_u32 size) {
    frame_addr = frame_size = frame_used = 0;
    if (!has_memory || !size || !mgl_memory_ptr(&memory, addr, size, 4)) return MGL_ERR_MEMORY;
    frame_addr = addr;
    frame_size = size;
    return MGL_OK;
}

mgl_u32 mgl_frame_alloc(mgl_u32 bytes, mgl_u32 align) {
    return bump(frame_addr, frame_size, &frame_used, bytes, align);
}

void mgl_frame_reset_(void) {
    frame_used = 0;
}

/* Lo que el renderer de referencia sabe leer; el resto se rechaza aquí, antes
   de que llegue a un command buffer. */
static int check(const mgl_mesh_desc_t *d) {
    mgl_u32 vbytes, ibytes;
    if (!d) return MGL_ERR_ARGUMENT;
    if (d->vertex_format == MGL_VERTEX_POSITION_Q16_16_XYZ || d->index_format == MGL_INDEX_UINT32)
        return MGL_ERR_UNSUPPORTED;
    if (d->vertex_format != MGL_VERTEX_POSITION_F32_XYZ || d->index_format != MGL_INDEX_UINT16)
        return MGL_ERR_ARGUMENT;
    if (d->vertex_stride < 12U || d->vertex_stride > 65535U || (d->vertex_stride & 3U) ||
        !d->vertex_count || d->vertex_count > 65536U || !d->index_count ||
        d->index_count % 3U || d->index_count > 0x7fffffffU / 2U)
        return MGL_ERR_ARGUMENT;
    vbytes = (d->vertex_count - 1U) * d->vertex_stride + 12U;
    ibytes = d->index_count * 2U;
    if (!has_memory || !mgl_memory_ptr(&memory, d->vertex_addr, vbytes, 4) ||
        !mgl_memory_ptr(&memory, d->index_addr, ibytes, 2))
        return MGL_ERR_MEMORY;
    return MGL_OK;
}

static mgl_mesh_t add(const mgl_mesh_desc_t *d) {
    int i;
    for (i = 0; i < MGL_MAX_MESHES; i++)
        if (!meshes[i].used) {
            meshes[i].desc = *d;
            meshes[i].used = 1;
            meshes[i].generation = (meshes[i].generation & 0x7fffU) | 0x8000U; /* nunca 0 */
            return (mgl_mesh_t)meshes[i].generation << 16 | (mgl_u32)(i + 1);
        }
    return 0;
}

static mesh_slot *find(mgl_mesh_t h) {
    mgl_u32 i = (h & 0xffffU) - 1U;
    if (i >= (mgl_u32)MGL_MAX_MESHES || !meshes[i].used || meshes[i].generation != h >> 16) return 0;
    return &meshes[i];
}

mgl_mesh_t mgl_create_mesh(const mgl_mesh_desc_t *d) {
    return check(d) == MGL_OK ? add(d) : 0;
}

/* Copia posiciones e índices a [base, base + size) y crea la malla. Si algo
   no cabe o no vale, *used vuelve a como estaba. */
static mgl_mesh_t copy_mesh(mgl_u32 base, mgl_u32 size, mgl_u32 *used, const float *positions,
    mgl_u32 vertex_count, const unsigned short *indices, mgl_u32 index_count) {
    mgl_mesh_desc_t d;
    unsigned char *p;
    mgl_u32 i, mark = *used;
    mgl_mesh_t h;
    if (!positions || !indices || !vertex_count || vertex_count > 65536U || !index_count ||
        index_count > 0x10000000U)
        return 0;
    d.vertex_format = MGL_VERTEX_POSITION_F32_XYZ;
    d.index_format = MGL_INDEX_UINT16;
    d.vertex_stride = 12;
    d.vertex_count = vertex_count;
    d.index_count = index_count;
    d.vertex_addr = bump(base, size, used, vertex_count * 12U, 16);
    d.index_addr = bump(base, size, used, index_count * 2U, 4);
    if (!d.vertex_addr || !d.index_addr || check(&d) != MGL_OK) {
        *used = mark;
        return 0;
    }
    /* Se escribe el formato serializado (little-endian), no la representación del host. */
    p = (unsigned char *)mgl_memory_ptr(&memory, d.vertex_addr, vertex_count * 12U, 4);
    for (i = 0; i < vertex_count * 3U; i++, p += 4) WR32(p, mgl_real_to_f32(positions[i]));
    p = (unsigned char *)mgl_memory_ptr(&memory, d.index_addr, index_count * 2U, 2);
    for (i = 0; i < index_count; i++, p += 2) WR16(p, indices[i]);
    h = add(&d);
    if (!h) *used = mark;
    return h;
}

mgl_mesh_t mgl_create_mesh_copy(const float *positions, mgl_u32 vertex_count,
    const unsigned short *indices, mgl_u32 index_count) {
    return copy_mesh(heap_addr, heap_size, &heap_used, positions, vertex_count, indices, index_count);
}

mgl_mesh_t mgl_create_mesh_frame(const float *positions, mgl_u32 vertex_count,
    const unsigned short *indices, mgl_u32 index_count) {
    return copy_mesh(frame_addr, frame_size, &frame_used, positions, vertex_count, indices, index_count);
}

int mgl_destroy_mesh(mgl_mesh_t h) {
    mesh_slot *s = find(h);
    if (!s) return MGL_ERR_HANDLE;
    s->used = 0;
    s->generation++;
    return MGL_OK;
}

int mgl_mesh_info(mgl_mesh_t h, mgl_mesh_desc_t *d) {
    mesh_slot *s = find(h);
    if (!s) return MGL_ERR_HANDLE;
    if (d) *d = s->desc;
    return MGL_OK;
}

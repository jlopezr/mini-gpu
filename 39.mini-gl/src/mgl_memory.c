#include "mgl_memory.h"

int mgl_memory_init(mgl_memory_t *m, void *base, mgl_u32 addr, mgl_u32 size) {
    mgl_u16 probe = 1;
    if (!m || !base || !addr || !size || addr + size - 1U < addr) return -1;
    if (*(unsigned char *)&probe != 1) return -1; /* píxeles y profundidad: enteros nativos */
    m->base = (unsigned char *)base;
    m->addr = addr;
    m->size = size;
    return 0;
}

void *mgl_memory_ptr(const mgl_memory_t *m, mgl_u32 addr, mgl_u32 bytes, mgl_u32 align) {
    mgl_u32 off;
    if (!m || !m->base || !addr || (addr & (align - 1U)) || addr < m->addr) return 0;
    off = addr - m->addr;
    if (off > m->size || bytes > m->size - off) return 0;
    return m->base + off;
}

mgl_u32 mgl_memory_addr(const mgl_memory_t *m, const void *p) {
    const unsigned char *c = (const unsigned char *)p;
    if (!m || !m->base || c < m->base || c >= m->base + m->size) return 0;
    return m->addr + (mgl_u32)(c - m->base);
}

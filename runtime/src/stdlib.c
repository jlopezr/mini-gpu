/* stdlib.c - utilidades y heap freestanding para MiniISA.
 *
 * El heap no reserva memoria por sí mismo: mini_heap_init() recibe una arena
 * del programa. Así sirve igual para BRAM, SDRAM o una región dedicada a Doom.
 */
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define ALIGNMENT 4u
#define ALLOCATED 0x80000000u
#define SIZE_MASK 0x7fffffffu

typedef struct Block {
    unsigned size;              /* cabecera incluida; ALLOCATED fuera de la lista libre */
    struct Block *next;
} Block;

static Block *free_list;
static unsigned heap_size;

int atoi(const char *s) {
    unsigned value = 0;
    int negative = 0;

    while (*s == ' ' || (*s >= '\t' && *s <= '\r')) ++s;
    if (*s == '+' || *s == '-') {
        negative = *s == '-';
        ++s;
    }
    while (*s >= '0' && *s <= '9')
        value = value * 10U + (unsigned)(*s++ - '0');
    return negative ? -(int)value : (int)value;
}

int abs(int n) {
    return n < 0 ? -n : n;
}

void __mini_exit(void);

void exit(int status) {
    (void)status;
    __mini_exit();
    for (;;) {}
}

static unsigned align_size(unsigned size) {
    return (size + ALIGNMENT - 1u) & ~(ALIGNMENT - 1u);
}

void mini_heap_init(void *base, size_t size) {
    unsigned address = (unsigned)base;
    unsigned skip = (-address) & (ALIGNMENT - 1u);
    unsigned usable;

    free_list = 0;
    heap_size = 0;
    if (size <= skip) return;
    address += skip;
    usable = ((unsigned)size - skip) & ~(ALIGNMENT - 1u);
    if (usable < sizeof(Block) + ALIGNMENT) return;
    free_list = (Block *)address;
    free_list->size = usable;
    free_list->next = 0;
    heap_size = usable;
}

void *malloc(size_t requested) {
    Block **link = &free_list;
    Block *block;
    unsigned payload;
    unsigned needed;

    if (requested == 0 || requested > SIZE_MASK - sizeof(Block)) return 0;
    payload = align_size((unsigned)requested);
    needed = payload + sizeof(Block);
    for (block = *link; block; link = &block->next, block = block->next) {
        unsigned available = block->size;
        if (available < needed) continue;
        if (available - needed >= sizeof(Block) + ALIGNMENT) {
            Block *remainder = (Block *)((unsigned char *)block + needed);
            remainder->size = available - needed;
            remainder->next = block->next;
            *link = remainder;
            block->size = needed | ALLOCATED;
        } else {
            *link = block->next;
            block->size = available | ALLOCATED;
        }
        return block + 1;
    }
    return 0;
}

void free(void *ptr) {
    Block *block;
    Block **link;

    if (!ptr) return;
    block = (Block *)ptr - 1;
    if (!(block->size & ALLOCATED)) return;
    block->size &= SIZE_MASK;
    for (link = &free_list; *link && *link < block; link = &(*link)->next) {}
    block->next = *link;
    *link = block;
    if (block->next && (unsigned char *)block + block->size == (unsigned char *)block->next) {
        block->size += block->next->size;
        block->next = block->next->next;
    }
    if (link != &free_list) {
        Block *previous = free_list;
        while (previous->next != block) previous = previous->next;
        if ((unsigned char *)previous + previous->size == (unsigned char *)block) {
            previous->size += block->size;
            previous->next = block->next;
        }
    }
}

void *calloc(size_t count, size_t size) {
    void *result;
    if (count && size > SIZE_MASK / count) return 0;
    result = malloc(count * size);
    if (result) memset(result, 0, count * size);
    return result;
}

void *realloc(void *ptr, size_t size) {
    Block *block;
    unsigned old_size;
    void *result;
    if (!ptr) return malloc(size);
    if (size == 0) {
        free(ptr);
        return 0;
    }
    block = (Block *)ptr - 1;
    if (!(block->size & ALLOCATED)) return 0;
    old_size = (block->size & SIZE_MASK) - sizeof(Block);
    if (size <= old_size) return ptr;
    result = malloc(size);
    if (!result) return 0;
    memcpy(result, ptr, old_size);
    free(ptr);
    return result;
}

size_t mini_heap_bytes_free(void) {
    Block *block;
    unsigned total = 0;
    for (block = free_list; block; block = block->next) total += block->size;
    return total;
}

size_t mini_heap_bytes_used(void) {
    return heap_size - mini_heap_bytes_free();
}

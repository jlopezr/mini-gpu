#include "gfx.h"
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

void gfx_list_init(GfxDisplayList *list) {
    if (list) memset(list, 0, sizeof(*list));
}
void gfx_list_destroy(GfxDisplayList *list) {
    if (!list) return;
    free(list->commands);
    memset(list, 0, sizeof(*list));
}
int gfx_list_add(GfxDisplayList *list, GfxCommand command) {
    if (!list) return -1;
    if (list->count == list->capacity) {
        uint32_t cap = list->capacity ? list->capacity * 2u : 32u;
        if (cap < list->capacity || (uint64_t)cap * sizeof(GfxCommand) > SIZE_MAX) return -1;
        void *p = realloc(list->commands, (size_t)cap * sizeof(GfxCommand));
        if (!p) return -1;
        list->commands = p;
        list->capacity = cap;
    }
    list->commands[list->count++] = command;
    return 0;
}

/* Deterministic MOD renderer check: first 4096 stereo frames at 48 kHz. */
#include <stdint.h>
#include "modplay.h"

#define FRAMES 4096
#define HASH_L_ADDR (*(volatile uint32_t *)0x0001fff0u)
#define HASH_R_ADDR (*(volatile uint32_t *)0x0001fff4u)

static int16_t pcm[FRAMES * 2];

static uint32_t hash_channel(int channel) {
    uint32_t hash;
    int i;
    hash = 2166136261u;
    for (i = 0; i < FRAMES; i++) {
        hash ^= (uint16_t)pcm[i * 2 + channel];
        hash *= 16777619u;
    }
    return hash;
}

#ifdef HOST
#include <stdio.h>
static uint8_t mod_data[2 * 1024 * 1024];
int main(void) {
    FILE *f;
    long size;
    uint32_t left, right;
    f = fopen("axel.mod", "rb");
    if (!f) return 1;
    fseek(f, 0, SEEK_END); size = ftell(f); fseek(f, 0, SEEK_SET);
    if (size < 0 || size > (long)sizeof(mod_data) || fread(mod_data, 1, (size_t)size, f) != (size_t)size) return 2;
    fclose(f);
    if (!InitMOD(mod_data, 48000u)) return 3;
    RenderMOD((short *)pcm, FRAMES);
    left = hash_channel(0); right = hash_channel(1);
    printf("L=%08lx R=%08lx\n", (unsigned long)left, (unsigned long)right);
    return 0;
}
#else
extern unsigned mod[];
int main(void) {
    if (!InitMOD((const uint8_t *)mod, 48000u)) return 1;
    RenderMOD((short *)pcm, FRAMES);
    HASH_L_ADDR = hash_channel(0);
    HASH_R_ADDR = hash_channel(1);
    return 0;
}
#endif

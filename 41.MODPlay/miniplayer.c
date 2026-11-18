/* MODPlay -> MiniGPU AUDIO. C89, memoria estatica y sin asignacion dinamica. */
#include <stdint.h>
#include "modplay.h"

#define AUDIO_BASE 0x80700000u
#define AUDIO_ID       (*(volatile uint32_t *)(AUDIO_BASE + 0x00u))
#define AUDIO_CTRL     (*(volatile uint32_t *)(AUDIO_BASE + 0x08u))
#define AUDIO_RING_BASE (*(volatile uint32_t *)(AUDIO_BASE + 0x0cu))
#define AUDIO_RING_LOG2 (*(volatile uint32_t *)(AUDIO_BASE + 0x10u))
#define AUDIO_WRITE     (*(volatile uint32_t *)(AUDIO_BASE + 0x14u))
#define AUDIO_READ      (*(volatile uint32_t *)(AUDIO_BASE + 0x18u))

#ifndef MOD_SAMPLE_RATE
#define MOD_SAMPLE_RATE 48000u
#endif
#define AUDIO_RATE ((uint32_t)MOD_SAMPLE_RATE)
#define RING_LOG2 12u
#define RING_FRAMES (1u << RING_LOG2)
#define BLOCK_FRAMES 256u
#define PREFILL_FRAMES (RING_FRAMES - BLOCK_FRAMES)

extern unsigned mod[];
/* +8 words permiten redondear la direccion a 16 bytes sin salir del array.
 * audio_dma lee lineas de 128 bits, por lo que RING_BASE debe ser 16-aligned. */
static int16_t pcm_storage[RING_FRAMES * 2u + 8u];
static int16_t pcm_block[BLOCK_FRAMES * 2u];

int main(void) {
    uint32_t write_cursor;
    uint32_t read_cursor;
    uint32_t free_frames;
    uint32_t frame;
    uint32_t physical;
    int16_t *pcm_ring;

    if (AUDIO_ID != 0x41554431u) return 1; /* AUD1 */
    if (!InitMOD((const uint8_t *)mod, AUDIO_RATE)) return 2;

    pcm_ring = (int16_t *)(((unsigned long)pcm_storage + 15ul) & ~15ul);
    AUDIO_CTRL = 0u;
    AUDIO_RING_BASE = (uint32_t)(unsigned long)pcm_ring;
    AUDIO_RING_LOG2 = RING_LOG2;
    write_cursor = 0u;
    AUDIO_WRITE = 0u;

    /* Render a safety margin before enabling the consumer.  Starting it on
     * an empty ring can make the hardware lap the producer during the first
     * expensive MOD render, which replays old ring contents. */
    for (frame = 0u; frame < PREFILL_FRAMES; frame += BLOCK_FRAMES) {
        RenderMOD(pcm_block, BLOCK_FRAMES);
        for (physical = 0u; physical < BLOCK_FRAMES; physical++) {
            pcm_ring[(frame + physical) * 2u] = pcm_block[physical * 2u];
            pcm_ring[(frame + physical) * 2u + 1u] = pcm_block[physical * 2u + 1u];
        }
    }
    write_cursor = PREFILL_FRAMES;
    AUDIO_WRITE = write_cursor;
    AUDIO_CTRL = 1u;

    for (;;) {
        read_cursor = AUDIO_READ;
        free_frames = RING_FRAMES - (write_cursor - read_cursor);
        if (free_frames < BLOCK_FRAMES) continue;

        RenderMOD(pcm_block, BLOCK_FRAMES);
        for (frame = 0u; frame < BLOCK_FRAMES; frame++) {
            physical = (write_cursor + frame) & (RING_FRAMES - 1u);
            pcm_ring[physical * 2u] = pcm_block[frame * 2u];
            pcm_ring[physical * 2u + 1u] = pcm_block[frame * 2u + 1u];
        }
        write_cursor += BLOCK_FRAMES;
        AUDIO_WRITE = write_cursor;
    }
}

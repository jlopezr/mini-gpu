/* HDMI PCM diagnostic: exact 1 kHz square wave at 48 kHz. */
#include <stdint.h>

#define AUDIO_BASE 0x80700000u
#define AUDIO_ID        (*(volatile uint32_t *)(AUDIO_BASE + 0x00u))
#define AUDIO_CTRL      (*(volatile uint32_t *)(AUDIO_BASE + 0x08u))
#define AUDIO_RING_BASE (*(volatile uint32_t *)(AUDIO_BASE + 0x0cu))
#define AUDIO_RING_LOG2 (*(volatile uint32_t *)(AUDIO_BASE + 0x10u))
#define AUDIO_WRITE     (*(volatile uint32_t *)(AUDIO_BASE + 0x14u))
#define AUDIO_READ      (*(volatile uint32_t *)(AUDIO_BASE + 0x18u))

#define RING_LOG2 12u
#define RING_FRAMES (1u << RING_LOG2)
#define BLOCK_FRAMES 256u

static int16_t pcm_storage[RING_FRAMES * 2u + 8u];

int main(void) {
    int16_t *ring;
    uint32_t write_cursor, read_cursor, free_frames, frame, physical, phase;
    int16_t sample;
    if (AUDIO_ID != 0x41554431u) return 1;
    ring = (int16_t *)(((unsigned long)pcm_storage + 15ul) & ~15ul);
    AUDIO_CTRL = 0u;
    AUDIO_RING_BASE = (uint32_t)(unsigned long)ring;
    AUDIO_RING_LOG2 = RING_LOG2;
    AUDIO_WRITE = 0u;
    AUDIO_CTRL = 1u;
    write_cursor = 0u;
    for (;;) {
        read_cursor = AUDIO_READ;
        free_frames = RING_FRAMES - (write_cursor - read_cursor);
        if (free_frames < BLOCK_FRAMES) continue;
        for (frame = 0u; frame < BLOCK_FRAMES; frame++) {
            phase = (write_cursor + frame) % 48u;
            sample = (phase < 24u) ? 8192 : -8192;
            physical = (write_cursor + frame) & (RING_FRAMES - 1u);
            ring[physical * 2u] = sample;
            ring[physical * 2u + 1u] = sample;
        }
        write_cursor += BLOCK_FRAMES;
        AUDIO_WRITE = write_cursor;
    }
}

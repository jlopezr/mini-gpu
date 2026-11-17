/* audio.c - operaciones C89 sobre el ring PCM de audio.h. */
#include <audio.h>

void audio_ring_init(audio_ring_t *ring, int16_t *samples, uint32_t frames) {
    ring->samples = samples;
    ring->frames = frames;
    ring->read_index = 0;
    ring->write_index = 0;
}

uint32_t audio_ring_available(const audio_ring_t *ring) {
    uint32_t read_index = ring->read_index;
    uint32_t write_index = ring->write_index;
    if (write_index >= read_index) return write_index - read_index;
    return ring->frames - read_index + write_index;
}

uint32_t audio_ring_free(const audio_ring_t *ring) {
    if (ring->frames < 2) return 0;
    return ring->frames - audio_ring_available(ring) - 1;
}

uint32_t audio_ring_write(audio_ring_t *ring, const int16_t *frames, uint32_t count) {
    uint32_t index;
    uint32_t copied;
    uint32_t free_frames = audio_ring_free(ring);

    if (count > free_frames) count = free_frames;
    index = ring->write_index;
    for (copied = 0; copied < count; copied++) {
        ring->samples[index * AUDIO_CHANNELS] = frames[copied * AUDIO_CHANNELS];
        ring->samples[index * AUDIO_CHANNELS + 1] = frames[copied * AUDIO_CHANNELS + 1];
        index++;
        if (index == ring->frames) index = 0;
    }
    ring->write_index = index;
    return count;
}

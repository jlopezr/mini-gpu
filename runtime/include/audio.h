/* audio.h - ring PCM compartido entre el productor y el dispositivo de audio.
 *
 * El formato inicial de MiniGPU es siempre PCM firmado S16, estéreo
 * intercalado, a 48 kHz: { L0, R0, L1, R1, ... }. El dispositivo HDMI futuro
 * lee `read_index`; el programa publica frames completos avanzando
 * `write_index`. Se deja una ranura libre para distinguir lleno de vacío.
 */
#ifndef MINI_AUDIO_H
#define MINI_AUDIO_H

#include <stdint.h>

#define AUDIO_SAMPLE_RATE 48000u
#define AUDIO_CHANNELS 2u
#define AUDIO_BYTES_PER_FRAME 4u

typedef struct {
    int16_t *samples;
    uint32_t frames;
    volatile uint32_t read_index;
    volatile uint32_t write_index;
} audio_ring_t;

void audio_ring_init(audio_ring_t *ring, int16_t *samples, uint32_t frames);
uint32_t audio_ring_available(const audio_ring_t *ring);
uint32_t audio_ring_free(const audio_ring_t *ring);
uint32_t audio_ring_write(audio_ring_t *ring, const int16_t *frames, uint32_t count);

#endif

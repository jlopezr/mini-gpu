#include <stdio.h>
#include <string.h>

/* SDL 1 se instala como <SDL.h> o como <SDL/SDL.h>, segun el proveedor. */
#if defined(__has_include)
# if __has_include(<SDL.h>)
#  include <SDL.h>
# elif __has_include(<SDL/SDL.h>)
#  include <SDL/SDL.h>
# elif __has_include(<SDL2/SDL.h>)
#  include <SDL2/SDL.h>
# else
#  error "SDL headers not found"
# endif
#else
# include <SDL/SDL.h>
#endif

#include "modplay.h"

#define SAMPLERATE 44100
#define MAX_TUNE_SIZE (2 * 1024 * 1024)

static uint8_t tune[MAX_TUNE_SIZE];
static SDL_AudioSpec sdl_audio;

void SDL_Callback(void *data, uint8_t *stream, int len) {
	(void)data;
	RenderMOD((short *)stream, len / (sizeof(short) * 2));
}

int main(int argc, char *argv[]) {
	FILE *f;
	long tune_len;
	SDL_Event event;

	if(argc != 2) {
		printf("Usage: %s modfile\n", argv[0]);
		return 1;
	}

	f = fopen(argv[1], "rb");

	if(f == NULL) {
		printf("Error loading file!\n");
		return 1;
	}

	if(fseek(f, 0, SEEK_END) != 0 || (tune_len = ftell(f)) < 0 ||
		(unsigned long)tune_len > (unsigned long)sizeof(tune) || fseek(f, 0, SEEK_SET) != 0 ||
		fread(tune, 1, (size_t)tune_len, f) != (size_t)tune_len) {
		printf("Error loading file (maximum size is %lu bytes).\n", (unsigned long)sizeof(tune));
		fclose(f);
		return 1;
	}
	fclose(f);

	if(!InitMOD(tune, SAMPLERATE)) {
		printf("Invalid file!\n");
		return 1;
	}

	printf("Playing %s...\nPress Ctrl+C (or send SIGINT) to stop.\n", argv[1]);

	memset(&sdl_audio, 0, sizeof(sdl_audio));
	sdl_audio.freq = SAMPLERATE;
	sdl_audio.format = AUDIO_S16;
	sdl_audio.channels = 2;
	sdl_audio.samples = 1024;
	sdl_audio.callback = SDL_Callback;

	if(SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO) != 0 || SDL_OpenAudio(&sdl_audio, 0) != 0) {
		printf("Unable to initialize SDL audio: %s\n", SDL_GetError());
		SDL_Quit();
		return 1;
	}

	SDL_PauseAudio(0);
	
	for(;;) {
		while(SDL_PollEvent(&event)) {
			switch(event.type) {
				case SDL_QUIT:
					printf("Quitting.\n");
					SDL_CloseAudio();
					SDL_Quit();
					return 0;
			}
		}

		SDL_Delay(100);
	}
}

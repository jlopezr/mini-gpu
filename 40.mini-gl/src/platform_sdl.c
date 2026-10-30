/* Plataforma SDL2 para sketches Processing: ventana con el framebuffer RGB565
   escalado, setup() una vez y draw() en bucle a 60 fps, como en Processing.

   Uso: sketch-sdl [-v 0|1|2] [-s escala]
     -v N    versión de MiniGL (por defecto 0); también se cambia en marcha
             con las teclas 0, 1 y 2
     -s N    píxeles de pantalla por píxel del framebuffer (por defecto 3)
   El título muestra la versión, los fps y los bytes de comandos. Esc cierra. */

#include "platform.h"
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FPS 60

static int usage(const char *prog) {
    fprintf(stderr, "uso: %s [-v 0|1|2] [-s escala]\n", prog);
    return 2;
}

/* Con SDL_RenderSetLogicalSize, SDL ya entrega los eventos de ratón en
   coordenadas del framebuffer (escala, bandas negras y HiDPI incluidos): no
   hay que convertirlas. Fuera de la imagen pueden ser negativas o pasar de
   width/height. */
static void update_mouse(int x, int y) {
    mouseX = x;
    mouseY = y;
}

int main(int argc, char **argv) {
    SDL_Window *window;
    SDL_Renderer *renderer;
    SDL_Texture *texture;
    SDL_Event e;
    Uint32 next, fps_start;
    int i, version = 0, scale = 3, running = 1, frames = 0;
    char title[128];

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-v") && i + 1 < argc) {
            if ((version = platform_parse_version(argv[++i])) < 0) return usage(argv[0]);
        } else if (!strcmp(argv[i], "-s") && i + 1 < argc) {
            if ((scale = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else
            return usage(argv[0]);
    }

    /* setup() fija el tamaño con size(): primero se ejecuta y luego se abre la ventana. */
    platform_reset();
    if (platform_begin(version) != MGL_OK) return 1;
    setup();
    if (platform_end(version) != MGL_OK) return 1;

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    window = SDL_CreateWindow("MiniGL", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        width * scale, height * scale, SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI);
    /* Píxeles nítidos al escalar: hay que fijarlo antes de crear la textura. */
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");
    renderer = window ? SDL_CreateRenderer(window, -1, 0) : 0;
    texture = renderer ? SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGB565,
                             SDL_TEXTUREACCESS_STREAMING, width, height) :
                         0;
    if (!texture) {
        fprintf(stderr, "SDL: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }
    /* Relación de aspecto y escala entera al cambiar el tamaño de la ventana. */
    SDL_RenderSetLogicalSize(renderer, width, height);
    SDL_RenderSetIntegerScale(renderer, SDL_TRUE);

    next = fps_start = SDL_GetTicks();
    while (running) {
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT)
                running = 0;
            else if (e.type == SDL_KEYDOWN) {
                SDL_Keycode k = e.key.keysym.sym;
                if (k == SDLK_ESCAPE)
                    running = 0;
                else if (k >= SDLK_0 && k < SDLK_0 + PLATFORM_VERSIONS)
                    version = k - SDLK_0;
            } else if (e.type == SDL_MOUSEMOTION)
                update_mouse(e.motion.x, e.motion.y);
            else if (e.type == SDL_MOUSEBUTTONDOWN || e.type == SDL_MOUSEBUTTONUP) {
                update_mouse(e.button.x, e.button.y);
                mousePressed = e.type == SDL_MOUSEBUTTONDOWN;
            }
        }

        frameCount++;
        if (platform_begin(version) != MGL_OK) break;
        draw();
        if (platform_end(version) != MGL_OK) break;

        SDL_UpdateTexture(texture, 0, platform_frame, width * (int)sizeof *platform_frame);
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, 0, 0);
        SDL_RenderPresent(renderer);

        /* Título con fps medidos cada segundo. */
        frames++;
        if (SDL_GetTicks() - fps_start >= 1000) {
            sprintf(title, "MiniGL V%d - %d fps - %u bytes de comandos", version, frames,
                platform_command_bytes());
            SDL_SetWindowTitle(window, title);
            frames = 0;
            fps_start = SDL_GetTicks();
        }

        next += 1000 / FPS;
        if ((Sint32)(next - SDL_GetTicks()) > 0)
            SDL_Delay(next - SDL_GetTicks());
        else
            next = SDL_GetTicks();
    }

    SDL_DestroyTexture(texture);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}

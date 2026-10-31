/* Plataforma SDL2 para sketches 3D: lo mismo que platform3d_host.c (RAM
   emulada, MiniGL 3D y el renderer de referencia), pero con draw() en bucle a
   60 fps y el framebuffer en una ventana. SDL solo muestra la imagen: no
   rasteriza nada.

   Uso: sketch-sdl [-s escala]
     -s N    píxeles de pantalla por píxel del framebuffer (por defecto 3)
   El título muestra los fps, los bytes de comandos y los fragmentos del último
   frame. Esc cierra. El ratón actualiza mouseX/mouseY/mousePressed. */

#include "platform3d.h"
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FPS 60

static int usage(const char *prog) {
    fprintf(stderr, "uso: %s [-s escala]\n", prog);
    return 2;
}

static int frame(void) {
    int r;
    if (platform3d_begin(P3D_FB_A) != MGL_OK) return -1;
    if (frameCount)
        draw();
    else
        setup();
    r = platform3d_end(0);
    if (r != MGL_OK) {
        fprintf(stderr, "frame %d: error %d (comando en el offset %u)\n", frameCount, r,
            (unsigned)platform3d_renderer.error_offset);
        return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    SDL_Window *window;
    SDL_Renderer *renderer;
    SDL_Texture *texture;
    SDL_Event e;
    Uint32 next, fps_start;
    unsigned char *ram;
    int i, scale = 3, running = 1, frames = 0;
    char title[160];

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-s") && i + 1 < argc) {
            if ((scale = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else
            return usage(argv[0]);
    }

    /* setup() fija el tamaño con size(): primero se ejecuta y luego se abre la ventana. */
    ram = (unsigned char *)calloc(P3D_RAM_SIZE, 1);
    if (!ram || platform3d_init(ram)) {
        fputs("no se pudo preparar la RAM emulada\n", stderr);
        return 1;
    }
    if (frame()) return 1;

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    window = SDL_CreateWindow("MiniGL 3D", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        width * scale, height * scale, SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI);
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
    SDL_RenderSetLogicalSize(renderer, width, height);
    SDL_RenderSetIntegerScale(renderer, SDL_TRUE);

    next = fps_start = SDL_GetTicks();
    while (running) {
        pmouseX = mouseX;
        pmouseY = mouseY;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT || (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE))
                running = 0;
            else if (e.type == SDL_MOUSEMOTION) {
                mouseX = e.motion.x;
                mouseY = e.motion.y;
            } else if (e.type == SDL_MOUSEBUTTONDOWN || e.type == SDL_MOUSEBUTTONUP)
                mousePressed = e.type == SDL_MOUSEBUTTONDOWN;
        }

        frameCount++;
        mgr_reset_stats(&platform3d_renderer);
        if (frame()) break;

        SDL_UpdateTexture(texture, 0, platform3d_pixels(P3D_FB_A), width * (int)sizeof(mgl_color_t));
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, 0, 0);
        SDL_RenderPresent(renderer);

        frames++;
        if (SDL_GetTicks() - fps_start >= 1000) {
            sprintf(title, "MiniGL 3D - %d fps - %u bytes de comandos - %u fragmentos", frames,
                (unsigned)platform3d_commands.used, (unsigned)platform3d_renderer.stats.fragments);
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
    free(ram);
    return 0;
}

/* Driver SDL2 común a los contextos 2D y 3D: ventana con el framebuffer RGB565
   escalado, setup() una vez y draw() en bucle a 60 fps, como en Processing.

   Uso: sketch-sdl [-v 0|1|2] [-s escala]
     -v N    versión de MiniGL 2D (por defecto 0); también se cambia en marcha
             con F1, F2 y F3 (las demás teclas son del sketch)
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

/* Las teclas sin carácter de texto: los que tienen los da SDL_TEXTINPUT, ya
   con la distribución del teclado y las mayúsculas. */
static void key_down(SDL_Keycode k) {
    static const SDL_Keycode coded[] = {SDLK_UP, SDLK_DOWN, SDLK_LEFT, SDLK_RIGHT};
    static const int codes[] = {UP, DOWN, LEFT, RIGHT};
    static const SDL_Keycode plain[] = {SDLK_RETURN, SDLK_BACKSPACE, SDLK_TAB, SDLK_DELETE};
    static const int chars[] = {ENTER, BACKSPACE, TAB, DELETE};
    int i;
    for (i = 0; i < 4; i++)
        if (k == coded[i]) {
            key = CODED;
            keyCode = codes[i];
        } else if (k == plain[i]) {
            key = chars[i];
            keyCode = 0;
        }
}

/* keyPressed: alguna tecla pulsada ahora. */
static int any_key(void) {
    int i, n;
    const Uint8 *state = SDL_GetKeyboardState(&n);
    for (i = 0; i < n; i++)
        if (state[i]) return 1;
    return 0;
}

int main(int argc, char **argv) {
    SDL_Window *window;
    SDL_Renderer *renderer;
    SDL_Texture *texture;
    SDL_Event e;
    Uint32 next, fps_start;
    int i, version = 0, scale = 3, running = 1, frames = 0, status = 0;
    unsigned char *ram = 0;
    mgl_u32 ram_size = mgl_context_ram_size();
    mgl_context_info_t info;
    char title[128];

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-v") && i + 1 < argc) {
            if (mgl_context_is3d()) return usage(argv[0]);
            if ((version = platform_parse_version(argv[++i])) < 0) return usage(argv[0]);
        } else if (!strcmp(argv[i], "-s") && i + 1 < argc) {
            if ((scale = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else
            return usage(argv[0]);
    }

    /* setup() fija el tamaño con size(): primero se ejecuta y luego se abre la ventana. */
    if (ram_size) ram = (unsigned char *)calloc(ram_size, 1);
    if ((ram_size && !ram) || platform_init(ram, version) != MGL_OK) return 1;
    if (platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, frameCount ? draw : setup, 0) != MGL_OK) return 1;

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
        pmouseX = mouseX;
        pmouseY = mouseY;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT)
                running = 0;
            else if (e.type == SDL_KEYDOWN) {
                SDL_Keycode k = e.key.keysym.sym;
                if (k == SDLK_ESCAPE)
                    running = 0;
                else if (!mgl_context_is3d() && k >= SDLK_F1 && k < SDLK_F1 + PLATFORM_VERSIONS)
                    mgl_context_set_version(version = k - SDLK_F1);
                else
                    key_down(k);
            } else if (e.type == SDL_TEXTINPUT) {
                if ((unsigned char)e.text.text[0] < 128) { /* solo ASCII, como en el resto de plataformas */
                    key = e.text.text[0];
                    keyCode = 0;
                }
            } else if (e.type == SDL_MOUSEMOTION)
                update_mouse(e.motion.x, e.motion.y);
            else if (e.type == SDL_MOUSEBUTTONDOWN || e.type == SDL_MOUSEBUTTONUP) {
                update_mouse(e.button.x, e.button.y);
                mousePressed = e.type == SDL_MOUSEBUTTONDOWN;
            }
        }

        keyPressed = any_key();
        frameCount++;
        if (platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, frameCount ? draw : setup, 0) != MGL_OK) {
            status = 1;
            break;
        }

        SDL_UpdateTexture(texture, 0, mgl_context_pixels(), width * (int)sizeof(mgl_color_t));
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, 0, 0);
        SDL_RenderPresent(renderer);

        /* Título con fps medidos cada segundo. */
        frames++;
        if (SDL_GetTicks() - fps_start >= 1000) {
            mgl_context_info(&info);
            if (mgl_context_is3d())
                sprintf(title, "MiniGL 3D - %d fps - %u bytes de comandos", frames, (unsigned)info.command_bytes);
            else
                sprintf(title, "MiniGL V%d - %d fps - %u bytes de comandos", version, frames, (unsigned)info.command_bytes);
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
    platform_shutdown();
    free(ram);
    return status;
}

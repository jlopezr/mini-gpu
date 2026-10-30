/* Plataforma MiniGPU (CPU + GPU con vídeo por MMIO): proporciona main(), size()
   y el bucle setup()/draw() de Processing sobre el vídeo de 320x240 RGB565.
   Corre igual en el simulador (sim-sys) y en las placas 36/37. Se compila con
   build-c (mini-lcc), no con el compilador del host.

   La version se elige al compilar con MGL_VERSION (build-c -D, make V=):
     0  directo: la CPU rasteriza al llamar (por defecto)
     1  diferido: draw() se graba en un command buffer y la CPU lo interpreta
        (mgl_cmd_render_cpu) antes del swap
     2  GPU: el mismo buffer lo interpreta un warp de la GPU (mgl_gpu_render,
        gpu_renderer.c), que la CPU lanza y espera antes del swap

   La entrada sale de INPUT (mmio.md §25), si existe: en el simulador con
   --window (o --keyboard, --mouse, --input-script); sin él se queda a cero.
   El raton es relativo, asi que la posicion arranca en el centro y se lleva en
   medios pixeles: la ventana del simulador ensena el framebuffer a doble
   tamano, y asi sigue al puntero a su velocidad (como input_paint.asm).
   El teclado se traduce de USB HID a ASCII con la distribucion US.

   Se dibuja directamente en el buffer trasero. Processing conserva el lienzo de
   un frame al siguiente, pero el trasero tiene lo de hace dos frames: tras cada
   swap, mgl_set_target le apunta y deja pendiente copiarle el delantero. MiniGL
   solo copia si se dibuja algo antes de un background(), que lo tapa todo: en
   los sketches que borran cada frame no se copia nunca. */

#include "processing.h"
#include "mmio.h"

#define FB_W 320
#define FB_H 240
#define FB_WORDS (FB_W * FB_H / 2)

#ifndef MGL_VERSION
#define MGL_VERSION 0
#endif
#if MGL_VERSION < 0 || MGL_VERSION > 2
#error "MiniGPU: MGL_VERSION 0, 1 o 2"
#endif
#if MGL_VERSION == 2
#include "gpu_renderer.h"
#endif

/* En RAM, lejos del programa (como render.asm); alineados a 16 bytes. */
#define FB_A 0x01000000u
#define FB_B 0x01025800u     /* FB_A + 320*240*2 */
#define COMMANDS 0x0104B000u /* FB_B + 320*240*2: el command buffer de V1 y V2 */
#define COMMAND_BYTES 0x10000u

int width = FB_W, height = FB_H;
int frameCount, mouseX, mouseY, pmouseX, pmouseY, mousePressed;
int keyPressed, key, keyCode;

static int bad_size;

/* El vídeo es siempre de 320x240: otro tamaño hace que main() acabe con 1. */
void size(int w, int h) {
    if (w != FB_W || h != FB_H) bad_size = 1;
}

static void clear(unsigned address) {
    unsigned *p = (unsigned *)address;
    int n;
    for (n = FB_WORDS; n > 0; n -= 4, p += 4) { /* FB_WORDS es multiplo de 4; lcc no desenrolla */
        p[0] = 0;
        p[1] = 0;
        p[2] = 0;
        p[3] = 0;
    }
}

static int has_input;
static int half_x = FB_W, half_y = FB_H; /* el raton, en medios pixeles */

/* USB HID (Usage Page 0x07) a ASCII, distribucion US: de 0x1E (1) a 0x38 (/),
   sin y con Shift. 0x32 es la tecla de fuera de EE. UU.: no da caracter. */
static const char hid_plain[] = "1234567890\n\033\b\t -=[]\\\0;'`,./";
static const char hid_shift[] = "!@#$%^&*()\n\033\b\t _+{}|\0:\"~<>?";

#define HID_SHIFT 0x22 /* Shift izquierdo y derecho en el bitmap de modificadores */

static void key_down(int usage, int modifiers) {
    int shift = modifiers & HID_SHIFT, c = 0;
    if (usage >= 0x4F && usage <= 0x52) { /* derecha, izquierda, abajo, arriba */
        key = CODED;
        keyCode = usage == 0x4F ? RIGHT : usage == 0x50 ? LEFT : usage == 0x51 ? DOWN : UP;
        return;
    }
    if (usage >= 0x04 && usage <= 0x1D)
        c = (shift ? 'A' : 'a') + usage - 0x04;
    else if (usage >= 0x1E && usage <= 0x38)
        c = (shift ? hid_shift : hid_plain)[usage - 0x1E];
    else if (usage == 0x4C)
        c = DELETE;
    if (c) {
        key = c;
        keyCode = 0;
    }
}

/* Antes de cada draw(): vacia la cola de eventos y lee el estado. */
static void poll_input(void) {
    unsigned event, type;
    int i;
    pmouseX = mouseX;
    pmouseY = mouseY;
    if (!has_input) return;
    while (REG(INPUT_STATUS) & MMIO_INPUT_STATUS_COUNT_MASK) {
        event = REG(INPUT_EVENT_DATA);
        type = event >> 24;
        if (type == MMIO_INPUT_TYPE_MOUSE_MOVE) {
            half_x += (int)(event << 20) >> 20; /* DX y DY: 12 bits con signo */
            half_y += (int)(event << 8) >> 20;
            if (half_x < 0) half_x = 0;
            if (half_x > 2 * FB_W - 1) half_x = 2 * FB_W - 1;
            if (half_y < 0) half_y = 0;
            if (half_y > 2 * FB_H - 1) half_y = 2 * FB_H - 1;
        } else if (type == MMIO_INPUT_TYPE_KEY && (event & 0x1FF) > 0x100) /* KEY != 0 y DOWN */
            key_down(event & 0xFF, (event >> 16) & 0xFF);
    }
    mouseX = half_x / 2;
    mouseY = half_y / 2;
    mousePressed = REG(INPUT_MOUSE_BUTTONS) != 0;
    keyPressed = 0;
    for (i = 0; i < 8; i++)
        if (REG(INPUT_KEY_STATE0 + 4 * i)) keyPressed = 1;
}

static mgl_color_t *back = (mgl_color_t *)FB_B; /* donde se dibuja */

#if MGL_VERSION != 0
static mgl_cmd_buffer_t commands;
#endif
#if MGL_VERSION == 2
static mgl_gpu_sprite_t sprites[MGL_GPU_MAX_SPRITES];
static mgl_gpu_job_t job;
extern int gpu_timeout_polls; /* gpu_runtime.inc: 20000 sondeos no dan para un frame */

/* La GPU lo dibuja en el trasero; antes, la CPU le trae el lienzo si hace falta. */
static int render_gpu(void) {
    int status = mgl_gpu_sprites_from_cmd(&commands, sprites, MGL_GPU_MAX_SPRITES);
    if (status != MGL_OK) return status;
    mgl_cmd_ready(&commands);
    job.commands = commands.bytes;
    job.command_bytes = commands.used;
    job.framebuffer = back;
    job.width = FB_W;
    job.height = FB_H;
    job.pitch = FB_W;
    job.sprites = sprites;
    job.sprite_count = commands.sprite_count;
    return mgl_gpu_render(&job);
}
#endif
#if MGL_VERSION != 0
/* Interpreta lo grabado desde la ultima vez y vacia el buffer. 0 si va bien. */
static int render_commands(void) {
    int status = mgl_cmd_status(&commands);
#if MGL_VERSION == 1
    if (status == MGL_OK) status = mgl_cmd_render_cpu(&commands);
#else
    if (status == MGL_OK) status = render_gpu();
#endif
    mgl_cmd_reset(&commands);
    return status;
}
#endif

/* Termina el frame en el buffer trasero, pide el swap, espera a que se aplique
   y pasa a dibujar en el nuevo trasero. */
static void present(void) {
    mgl_finish();
    REG(VIDEO_SWAP) = 1;
    while (REG(VIDEO_SWAP))
        ;
    back = (mgl_color_t *)REG(VIDEO_FB_BACK);
    mgl_set_target(back, (const mgl_color_t *)REG(VIDEO_FB_FRONT));
}

int main(void) {
    /* En la placa la SDRAM no empieza a cero: el lienzo empieza negro, como en el
       host (calloc). Basta con el delantero: el trasero lo copia de él. */
    clear(FB_A);
    REG(VIDEO_FB_FRONT) = FB_A;
    REG(VIDEO_FB_BACK) = FB_B;
    REG(VIDEO_CTRL) = VIDEO_MODE_SCANOUT;

    mgl_bind((mgl_color_t *)FB_B, FB_W, FB_H, FB_W);
    mgl_set_target((mgl_color_t *)FB_B, (const mgl_color_t *)FB_A);
#if MGL_VERSION != 0
    if (mgl_cmd_init(&commands, (void *)COMMANDS, COMMAND_BYTES) != MGL_OK) return 2;
    mgl_set_deferred(&commands);
#endif
#if MGL_VERSION == 2
    gpu_timeout_polls = 100000000;
#endif
#if MGL_VERSION == 0
    mgl_set_deferred(0);
#endif
    has_input = (REG(SYSTEM_DEVICES) & DEV_INPUT) != 0;
    mouseX = pmouseX = FB_W / 2;
    mouseY = pmouseY = FB_H / 2;
    setup();
    if (bad_size) return 1;
#if MGL_VERSION != 0
    if (render_commands() != MGL_OK) return 2;
#endif
    for (;;) {
        frameCount++;
        poll_input();
        draw();
#if MGL_VERSION != 0
        if (render_commands() != MGL_OK) return 2; /* buffer lleno o comando malo */
#endif
        present();
    }
}

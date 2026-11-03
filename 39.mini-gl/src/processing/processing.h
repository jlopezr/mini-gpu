#ifndef PROCESSING_H
#define PROCESSING_H

#include "minigl.h"

/* API Processing, deliberadamente delgada sobre MiniGL.
   Colores como en Arduino TFT y en la forma (r,g,b) de Processing: canales
   0..255, convertidos a RGB565. Las variantes *565 reciben RGB565 directo;
   color565() es la de Adafruit_GFX. */

mgl_color_t color565(int r, int g, int b);
void background(int r, int g, int b);
void fill(int r, int g, int b);
void noFill(void);
void stroke(int r, int g, int b);
void background565(mgl_color_t color);
void fill565(mgl_color_t color);
void stroke565(mgl_color_t color);
void noStroke(void);
void strokeWeight(int width);
void point(int x, int y);
void line(int x0, int y0, int x1, int y1);
void rect(int x, int y, int w, int h);
void circle(int cx, int cy, int diameter);
void triangle(int x0, int y0, int x1, int y1, int x2, int y2);
void image(const mgl_sprite_t *sprite, int x, int y);

/* La aplicacion define setup() y draw(); el bucle lo proporciona la plataforma.
   La plataforma tambien proporciona size(), que se llama al principio de
   setup() como en Processing, y width/height con el tamano actual.
   frameCount vale 0 en setup() y 1, 2, 3... en cada draw().

   La entrada la actualiza la plataforma antes de cada draw() (SDL y MiniGPU;
   en la host no cambia). El raton empieza en el centro de la pantalla (en
   MiniGPU es relativo: no se sabe donde esta hasta que se mueve).
   pmouseX/pmouseY son mouseX/mouseY del frame anterior. keyPressed vale 1 mientras haya alguna tecla pulsada; key es la
   ultima pulsada: su caracter ASCII (con mayusculas si va con Shift; ENTER,
   BACKSPACE, TAB, ESC y DELETE tambien), o CODED, y entonces keyCode dice
   cual (UP, DOWN, LEFT, RIGHT).
   keyIsDown(k), como el de p5.js, dice si la tecla k esta pulsada ahora, para
   mirar varias a la vez (juegos); una pulsacion corta que empieza y acaba entre
   dos frames cuenta en el siguiente. k es un caracter ('w' y 'W' son la misma
   tecla, '1' y '!' tambien), ENTER, BACKSPACE, TAB, ESC, DELETE, SHIFT o UP,
   DOWN, LEFT, RIGHT (que tapan a '%', '&', '\'' y '('). En SDL, con la
   distribucion del teclado; en MiniGPU el periferico solo da la posicion de cada tecla y
   se toma la US (en la española, '-' es la tecla del '/' US). En la host,
   siempre 0. */
void setup(void);
void draw(void);
void size(int w, int h);
extern int width, height;
extern int frameCount;
extern int mouseX, mouseY, pmouseX, pmouseY, mousePressed;
extern int keyPressed, key, keyCode;
int keyIsDown(int k);

#define CODED 0xFFFF
#define UP 38 /* los keyCode de Processing (los de Java) */
#define DOWN 40
#define LEFT 37
#define RIGHT 39
#define BACKSPACE 8
#define TAB 9
#define ENTER 10
#define ESC 27
#define DELETE 127
#define SHIFT 16 /* solo para keyIsDown: cualquiera de los dos */

#endif

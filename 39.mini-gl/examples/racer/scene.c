/* Vuelve a dibujar en el host una escena de racer congelada con G (el modo
   debug): el texto del panel, tal cual, en la variable de entorno SCENE.
     make racer-scene SCENE="DEBUG LV 1 CAM 1 F 812 SC 0.33 CAR X 480.12 ..."
   deja racer-scene.ppm y, con CAPTURE=escena.mglx, la captura de comandos del
   frame para build/mgl-replay. Lo que no venga se queda como al empezar el
   nivel; lo que no se entiende (las instrucciones del panel) se salta. */
#define draw racer_draw
#include "../racer.c"
#undef draw
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char scene[4096];

/* El número que sigue a la etiqueta, o def si no está. */
static float after(const char *label, float def) {
    char copy[4096], *t;
    strcpy(copy, scene);
    for (t = strtok(copy, " \t\n"); t; t = strtok(0, " \t\n"))
        if (!strcmp(t, label)) return (t = strtok(0, " \t\n")) ? (float)atof(t) : def;
    return def;
}

/* Las X Z H A P R de un grupo (CAR, EYE, T0...): hasta la siguiente etiqueta de grupo. */
static void place(const char *group, float *x, float *z, float *h, float *a, float *p, float *r) {
    char copy[4096], *t, *v;
    int in = 0;
    strcpy(copy, scene);
    for (t = strtok(copy, " \t\n"); t; t = strtok(0, " \t\n")) {
        if (!strcmp(t, "CAR") || !strcmp(t, "EYE") || (t[0] == 'T' && t[1] >= '0' && t[1] <= '9' && !t[2]) ||
            !strcmp(t, "V") || !strcmp(t, "LV")) {
            in = !strcmp(t, group);
            continue;
        }
        if (!in || strlen(t) != 1 || !strchr("XZHAPR", t[0]) || !(v = strtok(0, " \t\n"))) continue;
        if (t[0] == 'X') *x = (float)atof(v);
        if (t[0] == 'Z') *z = (float)atof(v);
        if (t[0] == 'H') *h = (float)atof(v);
        if (t[0] == 'A') *a = (float)atof(v);
        if (t[0] == 'P' && p) *p = (float)atof(v);
        if (t[0] == 'R' && r) *r = (float)atof(v);
    }
}

void draw(void) {
    char group[3] = "T0";
    int i;
    if (frameCount == 1) {
        if (!getenv("SCENE") || strlen(getenv("SCENE")) >= sizeof scene) {
            fprintf(stderr, "falta SCENE (el texto del panel de G)\n");
            exit(2);
        }
        strcpy(scene, getenv("SCENE"));
        resetShapes();
        load_level((int)after("LV", 0.0f) % LEVELS);
        cam_mode = (int)after("CAM", 0.0f) % CAMS;
        anim = (int)after("F", 0.0f);
        car_scale = after("SC", car_scale);
        place("CAR", &car_x, &car_z, &car_h, &car_a, &car_pitch, &car_roll);
        place("EYE", &cam_x, &cam_z, &cam_h, &cam_a, &cam_p, 0);
        for (i = 0; i < MAX_TRAFFIC; i++) {
            group[1] = (char)('0' + i);
            place(group, &traffic[i].x, &traffic[i].z, &traffic[i].h, &traffic[i].a, 0, 0);
        }
        state = RACE;
        race_time = 60; /* sin el GO de la salida */
        level_shown = 0;
        debug = 1; /* congelado: la escena, tal cual */
    }
    racer_draw();
}

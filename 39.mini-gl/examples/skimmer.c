/* Deslizador: volar bajo sobre un planeta al atardecer. Hay que recoger las
   balizas (cristales que flotan a distintas alturas) mientras te atacan drones
   en el aire y torretas desde el suelo; con todas, nivel siguiente y un dron
   más. Mesetas, agujas y arcos por los que pasar por debajo; chocar quita
   escudo, y sin escudo se acaba. El mundo da la vuelta, como en tanks.c.

   Controles: A/D o izquierda/derecha, girar; arriba/abajo, morro arriba y
   abajo (suelto, vuelve solo a horizontal); W/S, acelerar y frenar (se puede
   quedar quieto en el aire); espacio, disparar. Tras GAME OVER, espacio.

   Como en tanks.c: modelos hechos en setup() como PShape con caras sombreadas,
   cielo y suelo en 2D debajo del 3D y el panel en 2D encima. Lo nuevo es la
   altura, el cabeceo y el alabeo: la cámara es translate al ojo,
   rotateZ(alabeo), rotateX(cabeceo), rotateY(-rumbo); el horizonte baja
   FOCAL * tan(cabeceo) al subir el morro y se inclina al girar, con el cielo
   (estrellas a su altura sobre el horizonte, sol, montañas) y el suelo detrás,
   en 2D girados alrededor del centro de la pantalla. Para ver a qué altura va cada cosa, una
   sombra en el suelo bajo todo lo que vuela (también la propia), alargada
   hacia el lado contrario al sol. Sin entrada (en la host) se vuela recto.
   Uso: skimmer [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
#include "processing3d.h"

#define PI 3.14159265f
#define TWO_PI 6.28318531f
#define WORLD 3000.0f
#define HALF_WORLD 1500.0f
#define FOCAL 207.846f /* (height / 2) / tan(30°): la distancia de la cámara de Processing */
#define VIEW 1900.0f   /* el plano lejano está a 10 FOCAL */
#define RADAR_RANGE 1200.0f
#define PANEL 44       /* alto del panel de abajo */
#define MIN_ALT 5.0f
#define MAX_ALT 260.0f
#define SUN_A 2.4f     /* rumbo hacia el sol */
#define SHADOW 1.3f    /* largo de la sombra por unidad de altura */

#define MAX_THINGS 32
#define MAX_SOLIDS 96
#define MAX_ROCKS 90
#define MAX_BEACONS 8
#define MAX_DRONES 4
#define MAX_TURRETS 6
#define MAX_SHELLS 14
#define MAX_DEBRIS 40
#define STARS 110
#define PEAKS 24

enum { PLAY, OVER };

/* Las alturas (h) van hacia arriba; en 3D, y = -h. */
typedef struct {
    float x, z, a;
    const PShape *shape;
} Thing;

typedef struct { /* lo que no se puede atravesar: cilindros verticales */
    float x, z, r, bottom, top;
} Solid;

typedef struct {
    float x, h, z, a, speed;
    int alive, timer, cooldown;
} Drone;

typedef struct {
    float x, z, a;
    int alive, cooldown;
} Turret;

typedef struct {
    float x, h, z;
    int taken;
} Beacon;

typedef struct {
    float x, h, z, dx, dh, dz;
    int life, enemy;
} Shell;

typedef struct {
    float x, h, z, dx, dh, dz;
    int life;
    mgl_color_t color;
} Debris;

static PShape drone, turret, mesa, needle, arch, rock, crystal;
static Thing things[MAX_THINGS], rocks[MAX_ROCKS];
static Solid solids[MAX_SOLIDS];
static Drone drones[MAX_DRONES];
static Turret turrets[MAX_TURRETS];
static Beacon beacons[MAX_BEACONS];
static Shell shells[MAX_SHELLS];
static Debris debris[MAX_DEBRIS];
static int n_things, n_solids;
static float star_a[STARS], star_e[STARS], peak_a[PEAKS]; /* rumbo y elevación */
static int peak_h[PEAKS], peak_w[PEAKS];

static float px, ph, pz, pa, pp, speed, bank; /* el jugador: posición, rumbo, cabeceo, velocidad */
static int state, shield, score, level, reload, hurt, banner, space_was_down;

/* ---- Utilidades ---- */

static unsigned int seed = 1986;

static float rnd(void) { /* 0 <= rnd() < 1, igual en la host y en MiniGPU */
    seed = seed * 1103515245u + 12345u;
    return (float)((seed >> 8) & 0xFFFF) / 65536.0f;
}

static float wrap(float d) { /* la diferencia más corta en el toro */
    while (d >= HALF_WORLD) d -= WORLD;
    while (d < -HALF_WORLD) d += WORLD;
    return d;
}

static float wrap_angle(float a) {
    while (a >= PI) a -= TWO_PI;
    while (a < -PI) a += TWO_PI;
    return a;
}

static float place(float v) { /* dentro de [0, WORLD) */
    while (v >= WORLD) v -= WORLD;
    while (v < 0.0f) v += WORLD;
    return v;
}

static float clampf(float v, float lo, float hi) {
    return v < lo ? lo : v > hi ? hi : v;
}

/* El rumbo a apunta a (-sin a, -cos a): con a = 0, hacia -z, de frente en la
   pantalla; a crece girando a la izquierda. */
static float dir_x(float a) { return -mgl_sin(a); }
static float dir_z(float a) { return -mgl_cos(a); }

/* ---- Modelos: caras sombreadas en un PShape (como en tanks.c) ---- */

#define POOL_V 400
#define POOL_I 800
#define POOL_G 128

static float pool_xyz[POOL_V * 3];
static unsigned short pool_idx[POOL_I];
static PShapeGroup pool_groups[POOL_G];
static int pool_v, pool_i, pool_g;
static PShape *building;
static float center_x, center_y, center_z;

static void begin_model(PShape *s) {
    building = s;
    s->positions = pool_xyz + 3 * pool_v;
    s->indices = pool_idx + pool_i;
    s->groups = pool_groups + pool_g;
    s->vertex_count = s->index_count = s->group_count = 0;
    s->cull = 0;
}

/* Una cara plana y convexa de n vértices con su propio color: la normal se
   orienta hacia fuera de (center_x, center_y, center_z) y la luz viene de
   arriba, a la izquierda y por delante (y hacia abajo). */
static void face(int n, const float *p, int r, int g, int b) {
    PShape *s = building;
    float ux = p[3] - p[0], uy = p[4] - p[1], uz = p[5] - p[2];
    float vx = p[6] - p[0], vy = p[7] - p[1], vz = p[8] - p[2];
    float nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    float cx = 0.0f, cy = 0.0f, cz = 0.0f, len, k;
    int i, base = (int)s->vertex_count;
    PShapeGroup *group;
    for (i = 0; i < n; i++) {
        pool_xyz[3 * pool_v] = p[3 * i];
        pool_xyz[3 * pool_v + 1] = p[3 * i + 1];
        pool_xyz[3 * pool_v + 2] = p[3 * i + 2];
        cx += p[3 * i];
        cy += p[3 * i + 1];
        cz += p[3 * i + 2];
        pool_v++;
    }
    s->vertex_count += n;
    if (nx * (cx / n - center_x) + ny * (cy / n - center_y) + nz * (cz / n - center_z) < 0.0f) {
        nx = -nx;
        ny = -ny;
        nz = -nz;
    }
    len = mgl_sqrt(nx * nx + ny * ny + nz * nz);
    k = len > 0.0f ? (-0.4f * nx - 0.82f * ny + 0.41f * nz) / len : 0.0f;
    if (k < 0.0f) k = 0.0f;
    k = 0.3f + 0.7f * k;
    for (i = 1; i + 1 < n; i++) {
        pool_idx[pool_i++] = (unsigned short)base;
        pool_idx[pool_i++] = (unsigned short)(base + i);
        pool_idx[pool_i++] = (unsigned short)(base + i + 1);
    }
    s->index_count += 3 * (n - 2);
    group = &pool_groups[pool_g++];
    group->r = (unsigned char)(r * k);
    group->g = (unsigned char)(g * k);
    group->b = (unsigned char)(b * k);
    group->end = (unsigned short)s->index_count;
    s->group_count++;
}

/* Un tronco de pirámide: base de bw x bl en y0 centrada en (cx, cz) y tapa de
   tw x tl en y1 (más arriba: y negativa) desplazada tz en z; con tw = 0, una
   pirámide. Sin cara de abajo. */
static void frustum(float cx, float cz, float bw, float bl, float tw, float tl, float tz, float y0,
    float y1, int r, int g, int b) {
    static const float sx[4] = {-0.5f, 0.5f, 0.5f, -0.5f}, sz[4] = {-0.5f, -0.5f, 0.5f, 0.5f};
    float bot[12], top[12], q[12];
    int i, j, k;
    center_x = cx;
    center_y = (y0 + y1) * 0.5f;
    center_z = cz;
    for (i = 0; i < 4; i++) {
        bot[3 * i] = cx + sx[i] * bw;
        bot[3 * i + 1] = y0;
        bot[3 * i + 2] = cz + sz[i] * bl;
        top[3 * i] = cx + sx[i] * tw;
        top[3 * i + 1] = y1;
        top[3 * i + 2] = cz + tz + sz[i] * tl;
    }
    for (i = 0; i < 4; i++) {
        j = (i + 1) % 4;
        for (k = 0; k < 3; k++) {
            q[k] = bot[3 * i + k];
            q[3 + k] = bot[3 * j + k];
            q[6 + k] = top[3 * j + k];
            q[9 + k] = top[3 * i + k];
        }
        face(tw > 0.0f ? 4 : 3, q, r, g, b);
    }
    if (tw > 0.0f) face(4, top, r, g, b);
}

/* Un octaedro centrado en (0, cy, 0) con semiejes rx, ry, rz: 8 triángulos. */
static void octahedron(float cy, float rx, float ry, float rz, int r, int g, int b) {
    float ring[12], q[9];
    int i, j, k;
    center_x = center_z = 0.0f;
    center_y = cy;
    for (i = 0; i < 4; i++) {
        ring[3 * i] = i == 0 ? rx : i == 2 ? -rx : 0.0f;
        ring[3 * i + 1] = cy;
        ring[3 * i + 2] = i == 1 ? rz : i == 3 ? -rz : 0.0f;
    }
    for (i = 0; i < 4; i++) {
        j = (i + 1) % 4;
        for (k = 0; k < 3; k++) {
            q[3 + k] = ring[3 * i + k];
            q[6 + k] = ring[3 * j + k];
        }
        q[0] = q[2] = 0.0f;
        q[1] = cy - ry;
        face(3, q, r, g, b);
        q[1] = cy + ry;
        face(3, q, r, g, b);
    }
}

static void build_models(void) {
    begin_model(&drone); /* de frente hacia -z */
    octahedron(0.0f, 16.0f, 4.0f, 18.0f, 125, 135, 160);
    octahedron(-3.0f, 5.0f, 4.0f, 7.0f, 255, 80, 60);
    frustum(-16.0f, 2.0f, 4.0f, 16.0f, 4.0f, 16.0f, 0.0f, 3.0f, -3.0f, 90, 95, 110);
    frustum(16.0f, 2.0f, 4.0f, 16.0f, 4.0f, 16.0f, 0.0f, 3.0f, -3.0f, 90, 95, 110);
    begin_model(&turret);
    frustum(0.0f, 0.0f, 22.0f, 22.0f, 15.0f, 15.0f, 0.0f, 0.0f, -8.0f, 95, 88, 84);
    frustum(0.0f, 2.0f, 12.0f, 12.0f, 7.0f, 7.0f, 1.0f, -8.0f, -15.0f, 210, 70, 50);
    frustum(0.0f, -8.0f, 3.0f, 14.0f, 3.0f, 14.0f, 0.0f, -10.5f, -13.5f, 60, 60, 60);
    begin_model(&mesa);
    frustum(0.0f, 0.0f, 84.0f, 84.0f, 62.0f, 62.0f, 0.0f, 0.0f, -58.0f, 175, 92, 58);
    begin_model(&needle);
    frustum(0.0f, 0.0f, 20.0f, 20.0f, 12.0f, 12.0f, 0.0f, 0.0f, -150.0f, 150, 104, 84);
    frustum(0.0f, 0.0f, 12.0f, 12.0f, 0.0f, 0.0f, 0.0f, -150.0f, -162.0f, 150, 104, 84);
    begin_model(&arch);
    frustum(-45.0f, 0.0f, 16.0f, 16.0f, 12.0f, 12.0f, 0.0f, 0.0f, -82.0f, 160, 110, 90);
    frustum(45.0f, 0.0f, 16.0f, 16.0f, 12.0f, 12.0f, 0.0f, 0.0f, -82.0f, 160, 110, 90);
    frustum(0.0f, 0.0f, 112.0f, 18.0f, 112.0f, 18.0f, 0.0f, -80.0f, -94.0f, 160, 110, 90);
    begin_model(&rock);
    frustum(0.0f, 0.0f, 14.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0.0f, -6.0f, 130, 78, 56);
    begin_model(&crystal);
    octahedron(0.0f, 6.0f, 11.0f, 6.0f, 70, 230, 255);
}

/* ---- Mundo ---- */

static void add_solid(const Thing *t, float lx, float lz, float r, float bottom, float top) {
    Solid *s = &solids[n_solids++];
    float c = mgl_cos(t->a), sn = mgl_sin(t->a);
    s->x = place(t->x + lx * c + lz * sn); /* como rotateY(t->a) */
    s->z = place(t->z - lx * sn + lz * c);
    s->r = r;
    s->bottom = bottom;
    s->top = top;
}

/* ¿Choca una esfera de radio r en (x, h, z) con algo sólido? */
static int hits_solid(float x, float h, float z, float r) {
    float dx, dz, d;
    int i;
    for (i = 0; i < n_solids; i++) {
        if (h + r < solids[i].bottom || h - r > solids[i].top) continue;
        dx = wrap(solids[i].x - x);
        dz = wrap(solids[i].z - z);
        d = solids[i].r + r;
        if (dx * dx + dz * dz < d * d) return 1;
    }
    return 0;
}

static int near_start(float x, float z, float r) {
    return wrap(x) * wrap(x) + wrap(z) * wrap(z) < r * r;
}

static void build_world(void) {
    Thing *t;
    int i, k;
    for (i = 0; i < MAX_THINGS; i++) {
        t = &things[n_things++];
        do {
            t->x = rnd() * WORLD;
            t->z = rnd() * WORLD;
        } while (near_start(t->x, t->z, 260.0f));
        t->a = rnd() * TWO_PI;
        k = i % 4;
        if (k == 0) {
            t->shape = &mesa;
            add_solid(t, 0.0f, 0.0f, 44.0f, 0.0f, 58.0f);
        } else if (k == 1 || k == 3) {
            t->shape = &needle;
            add_solid(t, 0.0f, 0.0f, 10.0f, 0.0f, 162.0f);
        } else {
            t->shape = &arch;
            add_solid(t, -45.0f, 0.0f, 9.0f, 0.0f, 94.0f);
            add_solid(t, 45.0f, 0.0f, 9.0f, 0.0f, 94.0f);
            add_solid(t, -30.0f, 0.0f, 10.0f, 80.0f, 94.0f);
            add_solid(t, 0.0f, 0.0f, 10.0f, 80.0f, 94.0f);
            add_solid(t, 30.0f, 0.0f, 10.0f, 80.0f, 94.0f);
        }
    }
    for (i = 0; i < MAX_ROCKS; i++) {
        rocks[i].x = rnd() * WORLD;
        rocks[i].z = rnd() * WORLD;
        rocks[i].a = rnd() * TWO_PI;
        rocks[i].shape = &rock;
    }
    for (i = 0; i < STARS; i++) {
        star_a[i] = rnd() * TWO_PI;
        star_e[i] = 0.3f + rnd() * 1.1f;
    }
    for (i = 0; i < PEAKS; i++) {
        peak_a[i] = (i + rnd()) * TWO_PI / PEAKS;
        peak_h[i] = 6 + (int)(rnd() * 26.0f);
        peak_w[i] = 16 + (int)(rnd() * 40.0f);
    }
}

static void spawn_drone(Drone *d) {
    float a = rnd() * TWO_PI, dist = 900.0f + rnd() * 300.0f;
    d->x = place(px + dir_x(a) * dist);
    d->z = place(pz + dir_z(a) * dist);
    d->h = 60.0f + rnd() * 120.0f;
    d->a = wrap_angle(a + PI);
    d->speed = 2.0f + 0.25f * (level < 8 ? level : 8);
    d->alive = 1;
    d->cooldown = 90;
}

static void new_level(void) {
    Beacon *b;
    Turret *t;
    int i;
    for (i = 0; i < MAX_BEACONS; i++) {
        b = &beacons[i];
        do {
            b->x = rnd() * WORLD;
            b->z = rnd() * WORLD;
            b->h = 15.0f + rnd() * 150.0f;
        } while (hits_solid(b->x, b->h, b->z, 20.0f));
        b->taken = 0;
    }
    for (i = 0; i < MAX_TURRETS; i++) {
        t = &turrets[i];
        do {
            t->x = rnd() * WORLD;
            t->z = rnd() * WORLD;
        } while (hits_solid(t->x, 5.0f, t->z, 20.0f) || near_start(t->x - px, t->z - pz, 400.0f));
        t->a = rnd() * TWO_PI;
        t->alive = 1;
        t->cooldown = 120;
    }
    for (i = 0; i < MAX_DRONES; i++) {
        drones[i].alive = 0;
        drones[i].timer = 200 + 150 * i;
    }
    banner = 150;
}

static void reset_game(void) {
    int i;
    px = pz = 0.0f;
    ph = 40.0f;
    pa = pp = bank = 0.0f;
    speed = 2.0f;
    shield = 100;
    score = 0;
    level = 1;
    reload = hurt = 0;
    state = PLAY;
    for (i = 0; i < MAX_SHELLS; i++) shells[i].life = 0;
    for (i = 0; i < MAX_DEBRIS; i++) debris[i].life = 0;
    new_level();
    beacons[0].x = place(px + dir_x(0.15f) * 360.0f); /* la primera, a la vista */
    beacons[0].z = place(pz + dir_z(0.15f) * 360.0f);
    beacons[0].h = 55.0f;
}

static void fire(float x, float h, float z, float dx, float dh, float dz, int life, int enemy) {
    int i;
    for (i = 0; i < MAX_SHELLS; i++)
        if (!shells[i].life) {
            shells[i].x = x;
            shells[i].h = h;
            shells[i].z = z;
            shells[i].dx = dx;
            shells[i].dh = dh;
            shells[i].dz = dz;
            shells[i].life = life;
            shells[i].enemy = enemy;
            return;
        }
}

/* Dispara de (x, h, z) hacia el jugador a la velocidad v. */
static void fire_at_player(float x, float h, float z, float v) {
    float dx = wrap(px - x), dh = ph - h, dz = wrap(pz - z);
    float d = mgl_sqrt(dx * dx + dh * dh + dz * dz);
    if (d > 0.0f) fire(x, h, z, dx * v / d, dh * v / d, dz * v / d, 260, 1);
}

static void burst(float x, float h, float z, int n, mgl_color_t c0, mgl_color_t c1, float power) {
    int i;
    for (i = 0; i < MAX_DEBRIS && n > 0; i++)
        if (!debris[i].life) {
            debris[i].x = x;
            debris[i].h = h;
            debris[i].z = z;
            debris[i].dx = (rnd() - 0.5f) * power;
            debris[i].dz = (rnd() - 0.5f) * power;
            debris[i].dh = rnd() * power;
            debris[i].life = 40 + (int)(rnd() * 40.0f);
            debris[i].color = n & 1 ? c0 : c1;
            n--;
        }
}

static void damage(int n) {
    shield -= n;
    hurt = 30;
    if (shield <= 0) {
        shield = 0;
        state = OVER;
        speed = 0.0f;
    }
}

/* ---- Actualización ---- */

static void update_player(void) {
    int turn = (keyIsDown(LEFT) || keyIsDown('a')) - (keyIsDown(RIGHT) || keyIsDown('d'));
    int climb = keyIsDown(UP) - keyIsDown(DOWN);
    float c = mgl_cos(pp), s = mgl_sin(pp), nx, nh, nz;
    int i, mine = 0;
    pa = wrap_angle(pa + 0.028f * turn);
    bank += (0.4f * turn - bank) * 0.1f;
    if (climb) pp = clampf(pp + 0.02f * climb, -0.7f, 0.7f);
    else pp *= 0.95f;
    if (keyIsDown('w')) speed = clampf(speed + 0.05f, 0.0f, 4.5f);
    if (keyIsDown('s')) speed = clampf(speed - 0.05f, 0.0f, 4.5f);
    nx = place(px + dir_x(pa) * c * speed);
    nz = place(pz + dir_z(pa) * c * speed);
    nh = clampf(ph + s * speed, MIN_ALT, MAX_ALT);
    if (hits_solid(nx, nh, nz, 6.0f)) {
        if (!hurt) {
            burst(place(px + dir_x(pa) * 8.0f), ph, place(pz + dir_z(pa) * 8.0f), 6, color565(255, 220, 120),
                color565(200, 200, 200), 2.0f);
            damage(20);
        }
        speed = 0.0f;
    } else {
        px = nx;
        ph = nh;
        pz = nz;
    }
    for (i = 0; i < MAX_SHELLS; i++)
        if (shells[i].life && !shells[i].enemy) mine++;
    if (reload) reload--;
    if (keyIsDown(' ') && !reload && mine < 3) {
        fire(place(px + dir_x(pa) * c * 40.0f), ph + s * 40.0f, place(pz + dir_z(pa) * c * 40.0f), /* en la mira */
            dir_x(pa) * c * (12.0f + speed), s * (12.0f + speed), dir_z(pa) * c * (12.0f + speed), 90, 0);
        reload = 10;
    }
}

static int wanted_drones(void) {
    return level < MAX_DRONES ? level : MAX_DRONES;
}

static void update_drones(void) {
    float dx, dz, dh, hd, along, side, nx, nz;
    Drone *d;
    int i;
    for (i = 0; i < MAX_DRONES; i++) {
        d = &drones[i];
        if (!d->alive) {
            if (i < wanted_drones() && --d->timer <= 0) spawn_drone(d);
            continue;
        }
        dx = wrap(px - d->x);
        dz = wrap(pz - d->z);
        dh = ph - d->h;
        hd = mgl_sqrt(dx * dx + dz * dz);
        along = dir_x(d->a) * dx + dir_z(d->a) * dz;
        side = -mgl_cos(d->a) * dx + mgl_sin(d->a) * dz; /* > 0: el jugador queda girando a la izquierda */
        if (state == PLAY) { /* siempre adelante, girando hacia el jugador: pasadas */
            if (side > hd * 0.05f) d->a += 0.02f;
            else if (side < -hd * 0.05f) d->a -= 0.02f;
            d->a = wrap_angle(d->a);
            d->h += clampf(dh + 10.0f, -1.0f, 1.0f);
        }
        d->h = clampf(d->h, 15.0f, MAX_ALT);
        nx = place(d->x + dir_x(d->a) * d->speed);
        nz = place(d->z + dir_z(d->a) * d->speed);
        if (hits_solid(nx, d->h, nz, 14.0f)) d->h += 2.0f; /* por encima de lo que estorba */
        else {
            d->x = nx;
            d->z = nz;
        }
        if (d->cooldown) d->cooldown--;
        if (state == PLAY && !d->cooldown && along > hd * 0.96f && hd < 800.0f) {
            fire_at_player(d->x, d->h, d->z, 5.0f);
            d->cooldown = 110 - 10 * (level < 6 ? level : 6);
        }
    }
}

static void update_turrets(void) {
    float dx, dz, hd, along, side;
    Turret *t;
    int i;
    if (state != PLAY) return;
    for (i = 0; i < MAX_TURRETS; i++) {
        t = &turrets[i];
        if (!t->alive) continue;
        dx = wrap(px - t->x);
        dz = wrap(pz - t->z);
        hd = mgl_sqrt(dx * dx + dz * dz);
        if (hd > 700.0f) continue;
        along = dir_x(t->a) * dx + dir_z(t->a) * dz;
        side = -mgl_cos(t->a) * dx + mgl_sin(t->a) * dz;
        if (side > hd * 0.03f) t->a += 0.025f;
        else if (side < -hd * 0.03f) t->a -= 0.025f;
        t->a = wrap_angle(t->a);
        if (t->cooldown) t->cooldown--;
        if (!t->cooldown && along > hd * 0.95f) {
            fire_at_player(t->x, 12.0f, t->z, 4.5f);
            t->cooldown = 150 - 10 * (level < 8 ? level : 8);
        }
    }
}

static void update_shells(void) {
    float dx, dh, dz;
    Shell *s;
    int i, j;
    for (i = 0; i < MAX_SHELLS; i++) {
        s = &shells[i];
        if (!s->life) continue;
        s->life--;
        s->x = place(s->x + s->dx);
        s->h += s->dh;
        s->z = place(s->z + s->dz);
        if (s->h < 0.0f || hits_solid(s->x, s->h, s->z, 1.0f)) {
            burst(s->x, s->h > 0.0f ? s->h : 0.0f, s->z, 3, color565(200, 150, 110), color565(255, 210, 120), 1.5f);
            s->life = 0;
            continue;
        }
        if (s->enemy) {
            dx = wrap(px - s->x);
            dh = ph - s->h;
            dz = wrap(pz - s->z);
            if (state == PLAY && dx * dx + dh * dh + dz * dz < 10.0f * 10.0f) {
                damage(15);
                s->life = 0;
            }
            continue;
        }
        for (j = 0; j < MAX_DRONES && s->life; j++) {
            if (!drones[j].alive) continue;
            dx = wrap(drones[j].x - s->x);
            dh = drones[j].h - s->h;
            dz = wrap(drones[j].z - s->z);
            if (dx * dx + dh * dh + dz * dz < 16.0f * 16.0f) {
                burst(drones[j].x, drones[j].h, drones[j].z, 12, color565(255, 180, 40), color565(125, 135, 160), 4.0f);
                drones[j].alive = 0;
                drones[j].timer = 300;
                s->life = 0;
                score += 5;
            }
        }
        for (j = 0; j < MAX_TURRETS && s->life; j++) {
            if (!turrets[j].alive || s->h > 18.0f) continue;
            dx = wrap(turrets[j].x - s->x);
            dz = wrap(turrets[j].z - s->z);
            if (dx * dx + dz * dz < 14.0f * 14.0f) {
                burst(turrets[j].x, 8.0f, turrets[j].z, 10, color565(255, 180, 40), color565(210, 70, 50), 3.0f);
                turrets[j].alive = 0;
                s->life = 0;
                score += 3;
            }
        }
    }
}

static void update_beacons(void) {
    float dx, dh, dz;
    int i, left = 0;
    if (state != PLAY) return;
    for (i = 0; i < MAX_BEACONS; i++) {
        if (beacons[i].taken) continue;
        dx = wrap(beacons[i].x - px);
        dh = beacons[i].h - ph;
        dz = wrap(beacons[i].z - pz);
        if (dx * dx + dh * dh + dz * dz < 20.0f * 20.0f) {
            beacons[i].taken = 1;
            burst(beacons[i].x, beacons[i].h, beacons[i].z, 8, color565(70, 230, 255), color565(255, 255, 255), 3.0f);
            shield = shield + 15 < 100 ? shield + 15 : 100;
            score += 10;
        } else
            left++;
    }
    if (!left) {
        level++;
        new_level();
    }
}

static void update_debris(void) {
    Debris *d;
    int i;
    for (i = 0; i < MAX_DEBRIS; i++) {
        d = &debris[i];
        if (!d->life) continue;
        d->life--;
        d->x = place(d->x + d->dx);
        d->z = place(d->z + d->dz);
        d->h += d->dh;
        d->dh -= 0.15f;
        if (d->h < 1.5f) { /* rebota en el suelo, cada vez menos */
            d->h = 1.5f;
            d->dh *= -0.4f;
            d->dx *= 0.6f;
            d->dz *= 0.6f;
        }
    }
}

static void update(void) {
    int space = keyIsDown(' ');
    if (state == PLAY) update_player();
    else if (space && !space_was_down)
        reset_game();
    space_was_down = space;
    if (hurt) hurt--;
    if (banner) banner--;
    update_drones();
    update_turrets();
    update_shells();
    update_beacons();
    update_debris();
}

/* ---- Dibujo ---- */

/* El cielo se dibuja sin alabeo, en coordenadas relativas al centro de la
   pantalla, y se gira como la cámara (rotateZ(bank)) al pasarlo a pantalla. */
static float roll_c = 1.0f, roll_s = 0.0f;

static int screen_x(float x, float y) {
    return width / 2 + (int)(roll_c * x - roll_s * y);
}

static int screen_y(float x, float y) {
    return height / 2 + (int)(roll_s * x + roll_c * y);
}

/* Un rectángulo sin alabeo, girado: dos triángulos. */
static void sky_quad(float x0, float y0, float x1, float y1) {
    int ax = screen_x(x0, y0), ay = screen_y(x0, y0), bx = screen_x(x1, y0), by = screen_y(x1, y0);
    int cx = screen_x(x1, y1), cy = screen_y(x1, y1), dx = screen_x(x0, y1), dy = screen_y(x0, y1);
    triangle(ax, ay, bx, by, cx, cy);
    triangle(ax, ay, cx, cy, dx, dy);
}

/* x sin alabeo de lo que está en el rumbo a. */
static float sky_x(float a) {
    return -wrap_angle(a - pa) * FOCAL;
}

/* y sin alabeo de lo que está a elevación e sobre el horizonte; si queda por
   encima de la pantalla con cualquier alabeo, -1000. */
static float sky_y(float e) {
    float d = pp - e;
    return d < -0.8f ? -1000.0f : FOCAL * mgl_sin(d) / mgl_cos(d);
}

#define SKY_W 400.0f /* más que media diagonal de la pantalla */

static void draw_sky(void) {
    float hy = sky_y(0.0f), x, y;
    int i, sx, sy;
    roll_c = mgl_cos(bank);
    roll_s = mgl_sin(bank);
    /* Sin background(): no hay Z-buffer que borrar (el pintor, ver setup). El color de arriba, un quad
       grande; el resto lo cubren las franjas y el suelo. */
    noStroke();
    fill(30, 14, 44);
    sky_quad(-SKY_W, hy - 2.0f * SKY_W, SKY_W, hy - 60.0f);
    fill(62, 24, 62);
    sky_quad(-SKY_W, hy - 60.0f, SKY_W, hy - 40.0f);
    fill(112, 40, 62);
    sky_quad(-SKY_W, hy - 40.0f, SKY_W, hy - 20.0f);
    fill(190, 80, 52);
    sky_quad(-SKY_W, hy - 20.0f, SKY_W, hy);
    stroke(220, 200, 230);
    for (i = 0; i < STARS; i++) {
        x = sky_x(star_a[i]);
        y = sky_y(star_e[i]);
        if (x < -SKY_W || x > SKY_W || y < -SKY_W) continue;
        sx = screen_x(x, y);
        sy = screen_y(x, y);
        if (sx >= 0 && sx < width && sy >= 0 && sy < height) point(sx, sy);
    }
    noStroke();
    x = sky_x(SUN_A);
    if (x > -SKY_W && x < SKY_W) {
        fill(255, 150, 80);
        circle(screen_x(x, hy - 6.0f), screen_y(x, hy - 6.0f), 44);
        fill(255, 215, 130);
        circle(screen_x(x, hy - 6.0f), screen_y(x, hy - 6.0f), 34);
    }
    fill(48, 20, 42);
    for (i = 0; i < PEAKS; i++) {
        x = sky_x(peak_a[i]);
        if (x < -SKY_W - peak_w[i] || x > SKY_W + peak_w[i]) continue;
        triangle(screen_x(x - peak_w[i], hy), screen_y(x - peak_w[i], hy), screen_x(x, hy - peak_h[i]),
            screen_y(x, hy - peak_h[i]), screen_x(x + peak_w[i], hy), screen_y(x + peak_w[i], hy));
    }
    fill(80, 40, 34);
    sky_quad(-SKY_W, hy, SKY_W, hy + 6.0f);
    fill(112, 60, 40);
    sky_quad(-SKY_W, hy + 6.0f, SKY_W, hy + 2.0f * SKY_W);
}

/* Coloca la matriz en (x, h, z) del mundo, si puede verse: la de la cámara ya
   está puesta (draw_world) y aquí se añade la posición relativa, envuelta en
   el toro. La prueba es en planta y holgada, porque con el cabeceo se ve
   también lo que está debajo. */
static int place_object(float x, float h, float z, float r) {
    float dx = wrap(x - px), dz = wrap(z - pz);
    float ahead = dx * dir_x(pa) + dz * dir_z(pa), side = dx * mgl_cos(pa) - dz * mgl_sin(pa);
    if (ahead < -r - 40.0f || ahead > VIEW) return 0;
    if (side > ahead * 1.3f + r + 60.0f || -side > ahead * 1.3f + r + 60.0f) return 0;
    pushMatrix();
    translate(dx, ph - h, dz);
    return 1;
}

/* La sombra de lo que vuela a altura h: un cuadrado oscuro en el suelo,
   desplazado en contra del sol. */
static void draw_shadow(float x, float h, float z, float a, float s) {
    if (!place_object(x - dir_x(SUN_A) * h * SHADOW, 0.3f, z - dir_z(SUN_A) * h * SHADOW, s)) return;
    rotateY(a);
    fill(70, 36, 26);
    beginShape(QUADS);
    vertex(-s, 0.0f, -s);
    vertex(s, 0.0f, -s);
    vertex(s, 0.0f, s);
    vertex(-s, 0.0f, s);
    endShape();
    popMatrix();
}

static void draw_world(void) {
    int i;
    float bob;
    translate(width / 2, height / 2, FOCAL); /* el ojo, en el origen */
    rotateZ(bank); /* al girar a la izquierda, el mundo gira a la derecha */
    rotateX(pp);
    rotateY(-pa);
    for (i = 0; i < MAX_ROCKS; i++)
        if (place_object(rocks[i].x, 0.0f, rocks[i].z, 10.0f)) {
            rotateY(rocks[i].a);
            shape(&rock);
            popMatrix();
        }
    for (i = 0; i < n_things; i++)
        if (place_object(things[i].x, 0.0f, things[i].z, 70.0f)) {
            rotateY(things[i].a);
            shape(things[i].shape);
            popMatrix();
        }
    if (state == PLAY) draw_shadow(px, ph, pz, pa, 7.0f);
    for (i = 0; i < MAX_TURRETS; i++)
        if (turrets[i].alive && place_object(turrets[i].x, 0.0f, turrets[i].z, 16.0f)) {
            rotateY(turrets[i].a);
            shape(&turret);
            popMatrix();
        }
    for (i = 0; i < MAX_DRONES; i++) {
        if (!drones[i].alive) continue;
        draw_shadow(drones[i].x, drones[i].h, drones[i].z, drones[i].a, 12.0f);
        if (place_object(drones[i].x, drones[i].h, drones[i].z, 20.0f)) {
            rotateY(drones[i].a);
            shape(&drone);
            popMatrix();
        }
    }
    for (i = 0; i < MAX_BEACONS; i++) {
        if (beacons[i].taken) continue;
        bob = beacons[i].h + 3.0f * mgl_sin(frameCount * 0.06f + i);
        draw_shadow(beacons[i].x, bob, beacons[i].z, 0.0f, 5.0f);
        if (place_object(beacons[i].x, bob, beacons[i].z, 12.0f)) {
            rotateY(frameCount * 0.04f + i);
            shape(&crystal);
            popMatrix();
        }
    }
    for (i = 0; i < MAX_SHELLS; i++)
        if (shells[i].life && place_object(shells[i].x, shells[i].h, shells[i].z, 4.0f)) {
            if (shells[i].enemy) fill(255, 70, 50);
            else fill(255, 240, 150);
            box(shells[i].enemy ? 3 : 2);
            popMatrix();
        }
    for (i = 0; i < MAX_DEBRIS; i++)
        if (debris[i].life && place_object(debris[i].x, debris[i].h, debris[i].z, 4.0f)) {
            rotateY(debris[i].life * 0.3f);
            rotateX(debris[i].life * 0.2f);
            fill565(debris[i].color);
            box(3);
            popMatrix();
        }
}

/* Letras de 3 x 5 píxeles: una cifra octal por fila, de arriba abajo. */
static int glyph(int c) {
    static const int digits[10] = {075557, 026227, 071747, 071717, 055711, 074717, 074757, 071111, 075757,
        075717};
    if (c >= '0' && c <= '9') return digits[c - '0'];
    switch (c) {
    case 'A': return 025755;
    case 'C': return 074447;
    case 'D': return 065556;
    case 'E': return 074647;
    case 'G': return 074557;
    case 'H': return 055755;
    case 'L': return 044447;
    case 'M': return 057755;
    case 'O': return 075557;
    case 'P': return 075744;
    case 'R': return 065655;
    case 'S': return 074717;
    case 'T': return 072222;
    case 'V': return 055552;
    }
    return 0;
}

static void draw_text(const char *s, int x, int y, int px_size) {
    int bits, row, col;
    for (; *s; s++, x += 4 * px_size) {
        bits = glyph(*s);
        for (row = 0; row < 5; row++)
            for (col = 0; col < 3; col++)
                if (bits >> (3 * (4 - row) + 2 - col) & 1) rect(x + col * px_size, y + row * px_size, px_size, px_size);
    }
}

static void number(int n, int x, int y, int px_size) {
    char s[8];
    int i = 7;
    s[i] = 0;
    do {
        s[--i] = (char)('0' + n % 10);
        n /= 10;
    } while (n && i > 0);
    draw_text(s + i, x, y, px_size);
}

/* Un punto del radar: (x, z) del mundo en planta, con el rumbo hacia arriba. */
static void blip(int cx, int cy, int r, float x, float z) {
    float dx = wrap(x - px), dz = wrap(z - pz);
    if (dx * dx + dz * dz > RADAR_RANGE * RADAR_RANGE) return;
    rect(cx + (int)((dx * mgl_cos(pa) - dz * mgl_sin(pa)) * r / RADAR_RANGE) - 1,
        cy - (int)((dx * dir_x(pa) + dz * dir_z(pa)) * r / RADAR_RANGE) - 1, 3, 3);
}

static void draw_radar(int cx, int cy, int r) {
    float sweep = frameCount * 0.07f;
    int i;
    fill(0, 26, 12);
    stroke(50, 150, 70);
    circle(cx, cy, 2 * r);
    stroke(30, 90, 45);
    line(cx, cy, cx - r * 3 / 5, cy - r * 4 / 5); /* el campo de visión */
    line(cx, cy, cx + r * 3 / 5, cy - r * 4 / 5);
    stroke(90, 230, 120);
    line(cx, cy, cx + (int)(mgl_cos(sweep) * r), cy + (int)(mgl_sin(sweep) * r));
    noStroke();
    fill(70, 230, 255);
    for (i = 0; i < MAX_BEACONS; i++)
        if (!beacons[i].taken) blip(cx, cy, r, beacons[i].x, beacons[i].z);
    fill(255, 160, 40);
    for (i = 0; i < MAX_TURRETS; i++)
        if (turrets[i].alive) blip(cx, cy, r, turrets[i].x, turrets[i].z);
    fill(255, 60, 50);
    for (i = 0; i < MAX_DRONES; i++)
        if (drones[i].alive) blip(cx, cy, r, drones[i].x, drones[i].z);
}

/* Una barra vertical con su rótulo: v de 0 a 1. */
static void gauge(const char *label, int x, int y, float v, int r, int g, int b) {
    int h = 26, filled = (int)(clampf(v, 0.0f, 1.0f) * h);
    fill(150, 150, 160);
    draw_text(label, x, y, 1);
    fill(16, 16, 20);
    rect(x + 1, y + 8, 9, h + 2);
    fill(r, g, b);
    rect(x + 2, y + 9 + h - filled, 7, filled);
}

/* El horizonte artificial: la línea baja al subir el morro y se inclina al girar. */
static void attitude(int x, int y, int w, int h) {
    int cx = x + w / 2, cy = y + h / 2;
    int hy = cy + (int)clampf(pp * 26.0f, -h / 2 + 2, h / 2 - 2);
    int ex = (int)(mgl_cos(bank) * (w / 2 - 3)), ey = (int)(mgl_sin(bank) * (w / 2 - 3));
    fill(16, 16, 20);
    stroke(90, 90, 100);
    rect(x, y, w, h);
    stroke(90, 230, 120);
    line(cx - ex, hy - ey, cx + ex, hy + ey); /* como el horizonte de verdad */
    stroke(255, 210, 60);
    line(cx - 12, cy, cx - 4, cy);
    line(cx + 4, cy, cx + 12, cy);
    point(cx, cy);
    noStroke();
}

static void draw_hud(void) {
    int cx = width / 2, cy = height / 2, top = height - PANEL, i;
    if (state == PLAY) {
        stroke(140, 255, 150);
        line(cx - 12, cy, cx - 5, cy);
        line(cx + 5, cy, cx + 12, cy);
        line(cx, cy - 9, cx, cy - 4);
        line(cx, cy + 4, cx, cy + 9);
    }
    noStroke();
    if (hurt > 20 || state == OVER) { /* el borde en rojo al recibir */
        fill(220, 40, 30);
        rect(0, 0, width, 3);
        rect(0, top - 3, width, 3);
        rect(0, 0, 3, top);
        rect(width - 3, 0, 3, top);
    }
    fill(30, 28, 34);
    rect(0, top, width, PANEL);
    fill(90, 88, 100);
    rect(0, top, width, 1);
    draw_radar(24, top + 22, 19);
    gauge("SPD", 52, top + 5, speed / 4.5f, 90, 230, 120);
    gauge("ALT", 72, top + 5, ph / MAX_ALT, 70, 180, 255);
    gauge("SHD", 92, top + 5, shield / 100.0f, 255, shield > 30 ? 200 : 60, 60);
    for (i = 0; i < MAX_BEACONS; i++) {
        if (beacons[i].taken) fill(50, 60, 70);
        else fill(70, 230, 255);
        rect(118 + 8 * (i % 4), top + 9 + 9 * (i / 4), 5, 6);
    }
    fill(150, 150, 160);
    draw_text("LV", 118, top + 31, 1);
    number(level, 128, top + 31, 1);
    fill(255, 210, 120);
    number(score, 160, top + 12, 3);
    attitude(width - 58, top + 5, 52, 34);
    if (banner && state == PLAY) {
        fill(70, 230, 255);
        draw_text("LEVEL", cx - 42, 40, 3);
        number(level, cx + 30, 40, 3);
    }
    if (state == OVER) {
        fill(255, 70, 50);
        draw_text("GAME OVER", cx - 72, cy - 34, 4);
        if (frameCount / 30 % 2) {
            fill(230, 230, 240);
            draw_text("PRESS SPACE", cx - 44, cy, 2);
        }
    }
}

void setup(void) {
    size(320, 240, P3D);
    /* El algoritmo del pintor en vez del Z-buffer, como en tanks.c (en la 38, de 18,2 a 20,0 fps; la imagen
       cambia en unos 25 píxeles de borde). */
    hint(DISABLE_DEPTH_TEST);
    hint(ENABLE_DEPTH_SORT);
    build_models();
    build_world();
    reset_game();
}

void draw(void) {
    update();
    draw_sky();
    draw_world();
    draw_hud();
}

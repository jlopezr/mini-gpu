/* Tanques en la llanura: un juego de tanques en primera persona. Una llanura
   de noche que da la vuelta (un toro de WORLD x WORLD), con bloques, pirámides
   y obeliscos para cubrirse, y tanques enemigos que giran hacia el jugador y
   le disparan obuses lentos, que se pueden esquivar. Cada tres derribados
   entra uno más, hasta MAX_ENEMIES; tres impactos y se acaba.

   Controles: W/S o arriba/abajo, avanzar y retroceder; A/D o izquierda/derecha,
   girar; espacio, disparar (un obús en el aire a la vez). Tras GAME OVER,
   espacio vuelve a empezar. Usa keyIsDown() para mirar varias teclas a la vez.

   Lo de lejos es 2D, debajo del 3D: cielo, estrellas, luna y montañas se
   desplazan con el rumbo y el horizonte está en height / 2, porque la cámara
   mira en horizontal. Los modelos se construyen en setup() como PShape, una
   cara por grupo con su color sombreado por una luz fija (no hay luces en
   MiniGL). Encima, el radar y el marcador, también 2D. Sin entrada (en la
   host) el jugador se queda quieto y los enemigos vienen a por él.
   Uso: tanks [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
#include "processing3d.h"

#define PI 3.14159265f
#define TWO_PI 6.28318531f
#define WORLD 2400.0f
#define HALF_WORLD 1200.0f
#define FOCAL 207.846f /* (height / 2) / tan(30°): la distancia de la cámara de Processing */
#define EYE 14.0f      /* altura de los ojos sobre el suelo, y = 0 */
#define SHELL_Y -10.0f
#define VIEW 1900.0f   /* lo de más lejos no se dibuja (el plano lejano está a 10 FOCAL) */
#define RADAR_RANGE 1200.0f

#define MAX_ENEMIES 3
#define MAX_OBSTACLES 28
#define MAX_ROCKS 80
#define MAX_SHELLS 8
#define MAX_DEBRIS 32
#define STARS 48
#define PEAKS 22

enum { PLAY, HIT, OVER };

typedef struct {
    float x, z, a, r;
    const PShape *shape;
} Thing;

typedef struct {
    float x, z, a, speed;
    int alive, timer, cooldown, turn; /* timer: muerto, para volver; vivo, rodeando un obstáculo */
} Enemy;

typedef struct {
    float x, z, dx, dz;
    int life, enemy;
} Shell;

typedef struct {
    float x, y, z, dx, dy, dz;
    int life;
    mgl_color_t color;
} Debris;

static PShape tank, block, pyramid, obelisk, rock;
static Thing obstacles[MAX_OBSTACLES], rocks[MAX_ROCKS];
static Enemy enemies[MAX_ENEMIES];
static Shell shells[MAX_SHELLS];
static Debris debris[MAX_DEBRIS];
static float star_a[STARS], peak_a[PEAKS];
static int star_y[STARS], peak_h[PEAKS], peak_w[PEAKS];

static float px, pz, pa; /* el jugador: posición y rumbo */
static int state, timer, score, lives, reload, space_was_down;

/* ---- Utilidades ---- */

static unsigned int seed = 2026;

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

/* El rumbo a apunta a (-sin a, -cos a): con a = 0, hacia -z, de frente en la
   pantalla; a crece girando a la izquierda. */
static float dir_x(float a) { return -mgl_sin(a); }
static float dir_z(float a) { return -mgl_cos(a); }

/* ---- Modelos: caras sombreadas en un PShape ---- */

#define POOL_V 320
#define POOL_I 640
#define POOL_G 96

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
   pirámide. Sin cara de abajo, que está contra el suelo o tapada. */
static void frustum(float cx, float cz, float bw, float bl, float tw, float tl, float tz, float y0,
    float y1, int r, int g, int b) {
    static const float sx[4] = {-0.5f, 0.5f, 0.5f, -0.5f}, sz[4] = {-0.5f, -0.5f, 0.5f, 0.5f};
    float bot[12], top[12], q[12];
    int i, j;
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
        q[0] = bot[3 * i];
        q[1] = bot[3 * i + 1];
        q[2] = bot[3 * i + 2];
        q[3] = bot[3 * j];
        q[4] = bot[3 * j + 1];
        q[5] = bot[3 * j + 2];
        q[6] = top[3 * j];
        q[7] = top[3 * j + 1];
        q[8] = top[3 * j + 2];
        q[9] = top[3 * i];
        q[10] = top[3 * i + 1];
        q[11] = top[3 * i + 2];
        face(tw > 0.0f ? 4 : 3, q, r, g, b);
    }
    if (tw > 0.0f) face(4, top, r, g, b);
}

static void build_models(void) {
    begin_model(&tank); /* de frente hacia -z */
    frustum(-11.0f, 0.0f, 8.0f, 38.0f, 8.0f, 30.0f, 0.0f, 0.0f, -7.0f, 70, 66, 60);
    frustum(11.0f, 0.0f, 8.0f, 38.0f, 8.0f, 30.0f, 0.0f, 0.0f, -7.0f, 70, 66, 60);
    frustum(0.0f, 1.0f, 17.0f, 34.0f, 14.0f, 22.0f, 3.0f, -5.0f, -13.0f, 190, 50, 36);
    frustum(0.0f, 4.0f, 11.0f, 13.0f, 7.0f, 8.0f, 1.0f, -13.0f, -19.0f, 225, 70, 48);
    frustum(0.0f, -10.0f, 2.6f, 16.0f, 2.6f, 16.0f, 0.0f, -14.5f, -17.0f, 110, 110, 110);
    begin_model(&block);
    frustum(0.0f, 0.0f, 40.0f, 40.0f, 40.0f, 40.0f, 0.0f, 0.0f, -40.0f, 110, 150, 170);
    begin_model(&pyramid);
    frustum(0.0f, 0.0f, 56.0f, 56.0f, 0.0f, 0.0f, 0.0f, 0.0f, -50.0f, 210, 170, 100);
    begin_model(&obelisk);
    frustum(0.0f, 0.0f, 18.0f, 18.0f, 11.0f, 11.0f, 0.0f, 0.0f, -96.0f, 160, 130, 190);
    frustum(0.0f, 0.0f, 11.0f, 11.0f, 0.0f, 0.0f, 0.0f, -96.0f, -106.0f, 160, 130, 190);
    begin_model(&rock);
    frustum(0.0f, 0.0f, 14.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0.0f, -6.0f, 120, 130, 80);
}

/* ---- Mundo ---- */

static void build_world(void) {
    static const PShape *kinds[3] = {&block, &pyramid, &obelisk};
    static const float radius[3] = {30.0f, 34.0f, 13.0f};
    int i, k;
    for (i = 0; i < MAX_OBSTACLES; i++) {
        k = i % 3;
        do {
            obstacles[i].x = rnd() * WORLD;
            obstacles[i].z = rnd() * WORLD;
        } while (wrap(obstacles[i].x) * wrap(obstacles[i].x) + wrap(obstacles[i].z) * wrap(obstacles[i].z) <
                 200.0f * 200.0f);
        obstacles[i].a = rnd() * TWO_PI;
        obstacles[i].r = radius[k];
        obstacles[i].shape = kinds[k];
    }
    for (i = 0; i < MAX_ROCKS; i++) {
        rocks[i].x = rnd() * WORLD;
        rocks[i].z = rnd() * WORLD;
        rocks[i].a = rnd() * TWO_PI;
        rocks[i].shape = &rock;
    }
    for (i = 0; i < STARS; i++) {
        star_a[i] = rnd() * TWO_PI;
        star_y[i] = (int)(rnd() * rnd() * 100.0f) + 4;
    }
    for (i = 0; i < PEAKS; i++) {
        peak_a[i] = (i + rnd()) * TWO_PI / PEAKS;
        peak_h[i] = 8 + (int)(rnd() * 30.0f);
        peak_w[i] = 18 + (int)(rnd() * 40.0f);
    }
}

/* ¿Choca un círculo de radio r en (x, z) con algo? skip: el enemigo que se
   mueve (-1 si es el jugador). */
static int blocked(float x, float z, float r, int skip) {
    float dx, dz, d;
    int i;
    for (i = 0; i < MAX_OBSTACLES; i++) {
        dx = wrap(obstacles[i].x - x);
        dz = wrap(obstacles[i].z - z);
        d = obstacles[i].r + r;
        if (dx * dx + dz * dz < d * d) return 1;
    }
    for (i = 0; i < MAX_ENEMIES; i++) {
        if (i == skip || !enemies[i].alive) continue;
        dx = wrap(enemies[i].x - x);
        dz = wrap(enemies[i].z - z);
        if (dx * dx + dz * dz < (r + 22.0f) * (r + 22.0f)) return 1;
    }
    if (skip >= 0) {
        dx = wrap(px - x);
        dz = wrap(pz - z);
        if (dx * dx + dz * dz < (r + 24.0f) * (r + 24.0f)) return 1;
    }
    return 0;
}

/* A dist del jugador, en el rumbo pa + rel, mirándolo. */
static void spawn_enemy(Enemy *e, float rel, float dist) {
    float a = pa + rel;
    int tries;
    for (tries = 0; tries < 8; tries++) {
        e->x = place(px + dir_x(a) * dist);
        e->z = place(pz + dir_z(a) * dist);
        if (!blocked(e->x, e->z, 22.0f, (int)(e - enemies))) break;
        a += 0.4f;
    }
    e->a = wrap_angle(a + PI + (rnd() - 0.5f) * 0.6f);
    e->alive = 1;
    e->timer = 0; /* vivo: los frames que le quedan rodeando un obstáculo */
    e->cooldown = 120;
    e->speed = 1.0f + 0.1f * (score < 8 ? score : 8);
    e->turn = rnd() < 0.5f ? 1 : -1;
}

static int wanted_enemies(void) {
    int n = 1 + score / 3;
    return n < MAX_ENEMIES ? n : MAX_ENEMIES;
}

static void reset_game(void) {
    int i;
    px = pz = 0.0f;
    pa = 0.0f;
    score = 0;
    lives = 3;
    reload = 0;
    state = PLAY;
    for (i = 0; i < MAX_SHELLS; i++) shells[i].life = 0;
    for (i = 0; i < MAX_DEBRIS; i++) debris[i].life = 0;
    for (i = 0; i < MAX_ENEMIES; i++) {
        enemies[i].alive = 0;
        enemies[i].timer = 60 + 120 * i;
    }
    spawn_enemy(&enemies[0], 0.2f, 480.0f); /* el primero, a la vista */
}

static void fire(float x, float z, float a, int enemy) {
    int i;
    for (i = 0; i < MAX_SHELLS; i++)
        if (!shells[i].life) {
            shells[i].x = place(x + dir_x(a) * 22.0f);
            shells[i].z = place(z + dir_z(a) * 22.0f);
            shells[i].dx = dir_x(a) * (enemy ? 5.0f : 10.0f);
            shells[i].dz = dir_z(a) * (enemy ? 5.0f : 10.0f);
            shells[i].life = enemy ? 200 : 100;
            shells[i].enemy = enemy;
            return;
        }
}

static void burst(float x, float y, float z, int n, mgl_color_t c0, mgl_color_t c1, float power) {
    int i;
    for (i = 0; i < MAX_DEBRIS && n > 0; i++)
        if (!debris[i].life) {
            debris[i].x = x;
            debris[i].y = y;
            debris[i].z = z;
            debris[i].dx = (rnd() - 0.5f) * power;
            debris[i].dz = (rnd() - 0.5f) * power;
            debris[i].dy = -rnd() * power;
            debris[i].life = 40 + (int)(rnd() * 40.0f);
            debris[i].color = n & 1 ? c0 : c1;
            n--;
        }
}

/* ---- Actualización ---- */

static void update_player(void) {
    int turn = (keyIsDown(LEFT) || keyIsDown('a')) - (keyIsDown(RIGHT) || keyIsDown('d'));
    int move = (keyIsDown(UP) || keyIsDown('w')) - (keyIsDown(DOWN) || keyIsDown('s'));
    float speed = move > 0 ? 2.4f : 1.5f, nx, nz;
    int i, has_shell = 0;
    pa = wrap_angle(pa + 0.03f * turn);
    if (move) {
        nx = place(px + dir_x(pa) * speed * move);
        nz = place(pz + dir_z(pa) * speed * move);
        if (!blocked(nx, nz, 24.0f, -1)) {
            px = nx;
            pz = nz;
        }
    }
    for (i = 0; i < MAX_SHELLS; i++)
        if (shells[i].life && !shells[i].enemy) has_shell = 1;
    if (reload) reload--;
    if (keyIsDown(' ') && !reload && !has_shell) {
        fire(px, pz, pa, 0);
        reload = 30;
    }
}

static void update_enemies(void) {
    float dx, dz, dist, side, along, nx, nz;
    Enemy *e;
    int i;
    for (i = 0; i < MAX_ENEMIES; i++) {
        e = &enemies[i];
        if (!e->alive) {
            if (i < wanted_enemies() && --e->timer <= 0)
                spawn_enemy(e, (rnd() - 0.5f) * TWO_PI, 700.0f + rnd() * 300.0f);
            continue;
        }
        if (state != PLAY) continue;
        dx = wrap(px - e->x);
        dz = wrap(pz - e->z);
        dist = mgl_sqrt(dx * dx + dz * dz);
        along = dir_x(e->a) * dx + dir_z(e->a) * dz;
        side = -mgl_cos(e->a) * dx + mgl_sin(e->a) * dz; /* > 0: el jugador queda girando a la izquierda */
        if (e->timer > 0) { /* rodeando lo que estorbaba: se aparta sin mirar al jugador */
            e->timer--;
            e->a += 0.025f * e->turn;
        } else if (side > dist * 0.03f)
            e->a += 0.012f;
        else if (side < -dist * 0.03f)
            e->a -= 0.012f;
        e->a = wrap_angle(e->a);
        if (e->timer > 0 || (dist > 240.0f && along > dist * 0.5f)) {
            nx = place(e->x + dir_x(e->a) * e->speed);
            nz = place(e->z + dir_z(e->a) * e->speed);
            if (blocked(nx, nz, 22.0f, i)) {
                if (!e->timer) e->timer = 60;
            } else {
                e->x = nx;
                e->z = nz;
            }
        }
        if (e->cooldown) e->cooldown--;
        if (!e->cooldown && along > dist * 0.995f && dist < 900.0f) {
            fire(e->x, e->z, e->a, 1);
            e->cooldown = 150 - 8 * (score < 10 ? score : 10);
        }
    }
}

static void hit_player(void) {
    int i;
    lives--;
    state = HIT;
    timer = 120;
    for (i = 0; i < MAX_SHELLS; i++) shells[i].life = 0;
}

static void update_shells(void) {
    float dx, dz;
    Shell *s;
    int i, j;
    for (i = 0; i < MAX_SHELLS; i++) {
        s = &shells[i];
        if (!s->life) continue;
        s->life--;
        s->x = place(s->x + s->dx);
        s->z = place(s->z + s->dz);
        for (j = 0; j < MAX_OBSTACLES && s->life; j++) {
            dx = wrap(obstacles[j].x - s->x);
            dz = wrap(obstacles[j].z - s->z);
            if (dx * dx + dz * dz < obstacles[j].r * obstacles[j].r) {
                burst(s->x, SHELL_Y, s->z, 4, color565(200, 200, 200), color565(255, 210, 120), 2.0f);
                s->life = 0;
            }
        }
        if (!s->life) continue;
        if (s->enemy) {
            dx = wrap(px - s->x);
            dz = wrap(pz - s->z);
            if (state == PLAY && dx * dx + dz * dz < 18.0f * 18.0f) hit_player();
            continue;
        }
        for (j = 0; j < MAX_ENEMIES; j++) {
            if (!enemies[j].alive) continue;
            dx = wrap(enemies[j].x - s->x);
            dz = wrap(enemies[j].z - s->z);
            if (dx * dx + dz * dz < 20.0f * 20.0f) {
                burst(enemies[j].x, -10.0f, enemies[j].z, 14, color565(255, 180, 40), color565(190, 50, 36), 4.0f);
                enemies[j].alive = 0;
                enemies[j].timer = 150;
                s->life = 0;
                score++;
                break;
            }
        }
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
        d->y += d->dy;
        d->dy += 0.15f;
        if (d->y > -2.0f) { /* rebota en el suelo, cada vez menos */
            d->y = -2.0f;
            d->dy *= -0.4f;
            d->dx *= 0.6f;
            d->dz *= 0.6f;
        }
    }
}

/* Tras un impacto, los enemigos se apartan antes de seguir. */
static void respawn_player(void) {
    int i;
    for (i = 0; i < MAX_ENEMIES; i++)
        if (enemies[i].alive) spawn_enemy(&enemies[i], (rnd() - 0.5f) * TWO_PI, 700.0f + rnd() * 300.0f);
    state = PLAY;
}

static void update(void) {
    int space = keyIsDown(' ');
    if (state == PLAY) update_player();
    else if (state == HIT && --timer <= 0) {
        if (lives > 0) respawn_player();
        else state = OVER;
    } else if (state == OVER && space && !space_was_down)
        reset_game();
    space_was_down = space;
    update_enemies();
    update_shells();
    update_debris();
}

/* ---- Dibujo ---- */

/* Pantalla de lo que está a dirección a (por encima del horizonte). */
static int sky_x(float a) {
    return width / 2 - (int)(wrap_angle(a - pa) * FOCAL);
}

static void draw_sky(void) {
    int i, x, h = height / 2;
    background(6, 8, 24);
    noStroke();
    fill(14, 16, 40);
    rect(0, h - 30, width, 15);
    fill(26, 24, 58);
    rect(0, h - 15, width, 15);
    stroke(200, 200, 230);
    for (i = 0; i < STARS; i++) {
        x = sky_x(star_a[i]);
        if (x >= 0 && x < width) point(x, star_y[i]);
    }
    noStroke();
    x = sky_x(0.9f);
    if (x > -20 && x < width + 20) { /* una luna creciente */
        fill(235, 228, 190);
        circle(x, 46, 22);
        fill(6, 8, 24);
        circle(x + 6, 43, 20);
    }
    for (i = 0; i < PEAKS; i++) {
        x = sky_x(peak_a[i]);
        if (x < -peak_w[i] || x > width + peak_w[i]) continue;
        fill(44, 36, 70);
        triangle(x - peak_w[i], h, x, h - peak_h[i], x + peak_w[i], h);
        fill(84, 72, 112);
        triangle(x - peak_w[i] / 6, h - peak_h[i] * 5 / 6, x, h - peak_h[i], x + peak_w[i] / 6,
            h - peak_h[i] * 5 / 6);
    }
    fill(22, 26, 16);
    rect(0, h, width, 8);
    fill(34, 40, 24);
    rect(0, h + 8, width, height - h - 8);
}

/* Coloca la matriz en (x, y, z) del mundo, si se ve: la de la cámara ya está
   puesta (draw_world) y aquí solo se añade la posición relativa, envuelta en
   el toro. r: radio del objeto, para no descartar lo que asoma por un borde. */
static int place_object(float x, float y, float z, float r) {
    float dx = wrap(x - px), dz = wrap(z - pz);
    float ahead = dx * dir_x(pa) + dz * dir_z(pa), side = dx * mgl_cos(pa) - dz * mgl_sin(pa);
    if (ahead < -r || ahead > VIEW) return 0;
    if (side > ahead * 0.8f + r || -side > ahead * 0.8f + r) return 0;
    pushMatrix();
    translate(dx, y + EYE, dz);
    return 1;
}

static void draw_things(const Thing *t, int n) {
    int i;
    for (i = 0; i < n; i++)
        if (place_object(t[i].x, 0.0f, t[i].z, 60.0f)) {
            rotateY(t[i].a);
            shape(t[i].shape);
            popMatrix();
        }
}

static void draw_world(void) {
    int i;
    translate(width / 2, height / 2, FOCAL); /* el ojo, en el origen */
    rotateY(-pa);
    draw_things(rocks, MAX_ROCKS);
    draw_things(obstacles, MAX_OBSTACLES);
    for (i = 0; i < MAX_ENEMIES; i++)
        if (enemies[i].alive && place_object(enemies[i].x, 0.0f, enemies[i].z, 30.0f)) {
            rotateY(enemies[i].a);
            shape(&tank);
            popMatrix();
        }
    for (i = 0; i < MAX_SHELLS; i++)
        if (shells[i].life && place_object(shells[i].x, SHELL_Y, shells[i].z, 4.0f)) {
            if (shells[i].enemy) fill(255, 90, 50);
            else fill(255, 240, 140);
            box(4);
            popMatrix();
        }
    for (i = 0; i < MAX_DEBRIS; i++)
        if (debris[i].life && place_object(debris[i].x, debris[i].y, debris[i].z, 4.0f)) {
            rotateY(debris[i].life * 0.3f);
            rotateX(debris[i].life * 0.2f);
            fill565(debris[i].color);
            box(3);
            popMatrix();
        }
}

/* Letras de 3 x 5 píxeles, una fila de 3 bits por cada 3 bits, de arriba abajo. */
static int glyph(int c) {
    static const int digits[10] = {075557, 026227, 071747, 071717, 055711, 074717, 074757, 071111, 075757,
        075717};
    if (c >= '0' && c <= '9') return digits[c - '0'];
    switch (c) {
    case 'A': return 025755;
    case 'C': return 074447;
    case 'E': return 074647;
    case 'G': return 074557;
    case 'M': return 057755;
    case 'O': return 075557;
    case 'P': return 075744;
    case 'R': return 065655;
    case 'S': return 074717;
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

static void draw_radar(void) {
    int cx = width / 2, cy = 27, r = 22, i, x, y;
    float dx, dz, sweep = frameCount * 0.07f;
    fill(0, 30, 10);
    stroke(50, 150, 70);
    circle(cx, cy, 2 * r);
    stroke(30, 90, 45);
    line(cx, cy, cx - 13, cy - 18); /* el campo de visión */
    line(cx, cy, cx + 13, cy - 18);
    stroke(90, 230, 120);
    line(cx, cy, cx + (int)(mgl_cos(sweep) * r), cy + (int)(mgl_sin(sweep) * r));
    noStroke();
    fill(255, 70, 50);
    for (i = 0; i < MAX_ENEMIES; i++) {
        if (!enemies[i].alive) continue;
        dx = wrap(enemies[i].x - px);
        dz = wrap(enemies[i].z - pz);
        if (dx * dx + dz * dz > RADAR_RANGE * RADAR_RANGE) continue;
        x = cx + (int)((dx * mgl_cos(pa) - dz * mgl_sin(pa)) * r / RADAR_RANGE);
        y = cy - (int)((dx * dir_x(pa) + dz * dir_z(pa)) * r / RADAR_RANGE);
        rect(x - 1, y - 1, 3, 3);
    }
}

static void draw_hud(void) {
    static const int cracks[][4] = {{150, 110, 96, 70}, {150, 110, 120, 170}, {150, 110, 210, 92},
        {96, 70, 40, 52}, {120, 170, 84, 230}, {210, 92, 260, 30}, {210, 92, 300, 150}, {120, 170, 190, 210}};
    int cx = width / 2, cy = height / 2, i;
    draw_radar();
    noStroke();
    fill(90, 230, 120);
    number(score, 8, 8, 2);
    fill(200, 60, 40);
    for (i = 0; i < lives; i++) rect(width - 16 - 12 * i, 8, 9, 6);
    if (state == PLAY) {
        stroke(reload ? 60 : 120, reload ? 120 : 255, reload ? 60 : 120);
        line(cx - 12, cy, cx - 4, cy);
        line(cx + 4, cy, cx + 12, cy);
        line(cx, cy - 10, cx, cy - 4);
        line(cx, cy + 4, cx, cy + 10);
    } else {
        stroke(230, 230, 240);
        for (i = 0; i < (int)(sizeof cracks / sizeof cracks[0]); i++)
            line(cracks[i][0], cracks[i][1], cracks[i][2], cracks[i][3]);
        noStroke();
        if (state == OVER) {
            fill(255, 70, 50);
            draw_text("GAME OVER", cx - 72, cy - 30, 4);
            if (frameCount / 30 % 2) {
                fill(230, 230, 240);
                draw_text("PRESS SPACE", cx - 44, cy + 4, 2);
            }
        }
    }
    noStroke();
}

void setup(void) {
    size(320, 240, P3D);
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

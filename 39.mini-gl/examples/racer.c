/* Carreras en islas: circuitos con saltos, puentes y faro. Cada nivel es un
   fichero en racer/ (coast.h, sierra.h, zigzag.h...) con su nombre y tres mapas de
   texto de GW x GH, una letra por casilla, como un editor de circuitos por
   casillas:
   - ground_map: el terreno. Una cifra por casilla, la altura en niveles de
     LEVEL unidades; '~' es fondo de agua. La altura de cada esquina es la
     media de las casillas que la tocan: laderas, no escalones.
   - track_map: el circuito. '-' y '|' rectas, 'r' '7' 'L' 'J' curvas (las
     esquinas de un dibujo en ASCII; un cuadrado de 2 x 2 o 3 x 3 con la misma
     letra es una curva grande, que se entra y se sale por las casillas de
     sus bordes que siguen a las rectas), '^' cuesta marcada (recta, en
     cualquier dirección), '=' puente (sigue a la altura a la que llega), '+' cruce (se pasa dos veces, en línea recta: a la misma
     altura es un cruce; a distinta, un paso elevado) y 'S' la salida, que
     mira a la primera casilla con carretera de N, E, S, O.
     La altura de la carretera sale de las cifras de ground_map bajo ella, con
     cuestas donde cambian; una racha de '^' hace el cambio entero dentro de
     ella, como una rampa (road_heights). Una casilla con carretera fija sus
     esquinas a la altura de la carretera y el terreno de alrededor se
     adapta; donde no puede (junto a un paso elevado), una pared tapa el
     desnivel.
   - scenery_map: el decorado. 'T' pino, 't' árbol, 'H' casa, 's' señal
     y 'E' gasolinera (miran a la carretera de al lado), 'V' vaca y 'F' el
     faro. Los ciervos no van en el mapa: salen solos a cruzar.
   El agua está a WATER_H: lo que queda por debajo es mar, río o lago. Solo se
   dibuja en las casillas con alguna esquina por debajo (sin el terreno que
   tapa), y fuera del mapa sigue el mar en 2D bajo el horizonte, del mismo color.

   El terreno y la carretera se construyen al cargar el nivel en trozos de CHUNK x
   CHUNK casillas, cada uno un PShape con las caras ya sombreadas y agrupadas
   por color (un dibujo por color), y por frame solo se dibujan los trozos que
   caen delante de la cámara. Una casilla con carretera no lleva terreno
   debajo: es un solo plano con arcén, bordillo y asfalto, sin dos caras
   superpuestas que se peleen en el Z-buffer de 16 bits.

   Controles: arriba/W acelerar, abajo/S frenar y marcha atrás, izquierda/A y
   derecha/D girar, C cambia de cámara (detrás, dentro, alta y TV), R vuelve a
   la carretera, espacio vuelve a empezar al acabar, N pasa al siguiente nivel,
   P pone o quita el piloto automático (que, al acabar, vuelve a empezar: modo
   demo) y G es el modo debug (ver draw_debug); - y + cambian el tamaño del
   coche, y < y > la velocidad del tráfico, para probar. Tres vueltas contra el
   reloj.
   Uso: racer [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
#include "processing3d.h"

#define PI 3.14159265f
#define FOCAL 207.846f /* (height / 2) / tan(30°): la distancia de la cámara de Processing */
#define GW 24          /* casillas del mapa */
#define GH 24
#define TILE 40.0f
#define LEVEL 10.0f    /* altura de un nivel del terreno */
#define ROAD_W 22.0f
#define KERB 2.5f
#define CAR_SCALE 0.33f /* el modelo mide 16.5 de ancho: así, 5.4, una cuarta parte de la carretera */
#define CAR_R (6.6f * car_scale) /* radio del coche para chocar */
#define CAM_BACK 46.0f  /* la cámara de detrás: distancia y altura sobre el coche */
#define CAM_UP 16.0f
#define EYE 3.0f        /* la de dentro: altura de los ojos, a la del techo del coche */
#define WATER_H -4.0f
#define WATER 40, 95, 150 /* el del mar 2D bajo el horizonte: sin costura en el borde del mapa */
#define CHUNK 4
#define CHUNKS_X (GW / CHUNK)
#define CHUNKS_Z (GH / CHUNK)
#define VIEW 1200.0f
#define LOD_FAR 300.0f /* más lejos, los árboles sin tronco y el pino de una pieza */
#define LAPS 3
#define OFFROAD_V 2.0f /* fuera del asfalto, la velocidad máxima (60 km/h en el marcador) */
#define MAX_TRAFFIC 3
#define LANE 6.5f      /* el tráfico va por la derecha, a esta distancia del centro */
#define LOOK 80.0f     /* hasta dónde mira el tráfico por delante */
#define BRAKE 0.18f    /* lo que frena por frame, con margen (frena hasta 0.2) */
#define MAX_PATH 128
#define MAX_PROPS 200

/* Un nivel: su nombre y sus tres mapas (ver arriba), cada uno en su fichero. */
typedef struct {
    const char *name;
    const char *ground[GH], *track[GH], *scenery[GH];
} Level;

#include "racer/coast.h"
#include "racer/sierra.h"
#include "racer/delta.h"
#include "racer/knot.h"
#include "racer/chequilla.h"
#include "racer/zigzag.h"

static const Level *const levels[] = {
    &level_coast, &level_sierra, &level_delta, &level_knot, &level_chequilla, &level_zigzag};
#define LEVELS (int)(sizeof levels / sizeof levels[0])
static int level;
static const char *const *ground_map, *const *track_map, *const *scenery_map;

enum { COUNTDOWN, RACE, FINISHED };
enum { STRAIGHT, CURVE, BRIDGE };
enum { PROP_TREE, PROP_HOUSE, PROP_SIGN, PROP_LIGHTHOUSE, PROP_STATION, PROP_COW };

/* Direcciones N, E, S, O: N es -z (hacia arriba en el mapa), E es +x. */
static const int step_x[4] = {0, 1, 0, -1}, step_z[4] = {-1, 0, 1, 0};
static const float dir_angle[4] = {0.0f, -PI / 2, PI, PI / 2};

typedef struct {
    float x, z, h, a, s, r; /* posición, giro, escala y radio para chocar */
    const PShape *shape;
    int kind, phase; /* phase: una vaca no pasta al compás de las demás */
} Prop;

static PShape chunks[CHUNKS_Z][CHUNKS_X];
static PShape car, pine, tree, house, sign, lighthouse;
static PShape pine_far, tree_far; /* los árboles de lejos, más sencillos (LOD) */
static PShape car_blue, car_yellow, truck;
static PShape station, cow_down, cow_up, deer_shape;

/* El ciervo: de vez en cuando cruza una recta por delante del coche, al trote. */
static struct {
    int on, wait;
    float x, z, h, a, left; /* left: lo que le queda por andar */
} deer;

/* El tráfico: sigue el circuito por su carril, cada uno a su velocidad. */
typedef struct {
    float x, z, h, a, v, top; /* top: la velocidad a la que va en recta */
    float lane;               /* distancia al centro: LANE por la derecha, -LANE adelantando */
    int k, off, passing;      /* k: su casilla; off: frames fuera del asfalto; passing: adelantando */
    int stuck;                /* frames parado contra algo */
    float pass_lane;          /* el carril por el que adelanta: el contrario al del que estorba */
    int truck;
    const PShape *shape;
} Vehicle;

static Vehicle traffic[MAX_TRAFFIC];
static Prop props[MAX_PROPS];
static int n_props;

/* El circuito en orden, desde la salida. */
static int path_i[MAX_PATH], path_j[MAX_PATH], path_din[MAX_PATH], path_dout[MAX_PATH], path_kind[MAX_PATH];
static float path_hin[MAX_PATH], path_hout[MAX_PATH];
static char path_cross[MAX_PATH], path_ramp[MAX_PATH]; /* un cruce ('+'), una cuesta marcada ('^') */
static int n_path;
static float path_px[MAX_PATH], path_pz[MAX_PATH], path_r[MAX_PATH]; /* curvas: la esquina de giro y el radio del eje */
static float path_s[MAX_PATH], road_length; /* dónde empieza cada pieza, a lo largo del circuito, y la vuelta */
static signed char tile_path[GH][GW]; /* índice en el circuito, o -1 */
static signed char tile_path2[GH][GW]; /* en un cruce, la otra pieza (la de arriba, si es un paso elevado); si no, -1 */
static unsigned char block_i[GH][GW], block_j[GH][GW], block_n[GH][GW]; /* el bloque de curva de cada casilla */
static float corner_h[(GH + 1) * (GW + 1)];
#define CORNER(i, j) corner_h[(j) * (GW + 1) + (i)]

static float car_x, car_z, car_h, car_a, car_v, car_vh, car_pitch, car_roll, ground_prev;
static int car_ground, on_road;
static float cam_x, cam_z, cam_h, cam_a, cam_p, steer_shown;
static int cam_mode, state, timer, race_time, lap, lap_start, best_lap, progress, sinking;
static int anim; /* frames de juego (no cuenta en pausa): el haz del faro */
static int c_was_down, r_was_down, space_was_down;
static float car_scale = CAR_SCALE; /* - y + lo cambian mientras se juega, para probar */
static int minus_was_down, plus_was_down, scale_shown;
static int n_was_down, level_shown;
enum { CAM_CHASE, CAM_COCKPIT, CAM_HIGH, CAM_TV, CAMS };
static const char *const cam_names[CAMS] = {"CHASE", "COCKPIT", "HIGH", "TV"};
static int cam_shown;
static int autopilot, p_was_down, auto_stuck, auto_back;
static int debug, g_was_down; /* 1: congelado; 2: congelado, con los datos en vez de la escena */
static float traffic_speed = 1.0f; /* < y > lo cambian, de 0.2 a 1.3 (más rápido se acaban tocando) */
static int less_was_down, more_was_down, speed_shown;

/* ---- Utilidades ---- */

static unsigned int seed = 1990;

static float rnd(void) { /* 0 <= rnd() < 1, igual en la host y en MiniGPU */
    seed = seed * 1103515245u + 12345u;
    return (float)((seed >> 8) & 0xFFFF) / 65536.0f;
}

static float absf(float v) { return v < 0.0f ? -v : v; }

static float clampf(float v, float lo, float hi) {
    return v < lo ? lo : v > hi ? hi : v;
}

/* atan2 sin la de la biblioteca (mgl_math no la tiene): la serie de atan en
   [0, 1] y los octantes; error < 0.0001. */
static float atan2_(float y, float x) {
    float ax = y < 0.0f ? -y : y, bx = x < 0.0f ? -x : x, t, t2, r;
    if (ax < 1e-6f && bx < 1e-6f) return 0.0f;
    t = bx > ax ? ax / bx : bx / ax;
    t2 = t * t;
    r = t * (0.9998660f + t2 * (-0.3302995f + t2 * (0.1801410f + t2 * (-0.0851330f + t2 * 0.0208351f))));
    if (ax > bx) r = PI * 0.5f - r;
    if (x < 0.0f) r = PI - r;
    return y < 0.0f ? -r : r;
}

static float wrap_angle(float a) {
    while (a >= PI) a -= 2.0f * PI;
    while (a < -PI) a += 2.0f * PI;
    return a;
}

/* El rumbo a apunta a (-sin a, -cos a): con a = 0, hacia -z (el norte). */
static float dir_x(float a) { return -mgl_sin(a); }
static float dir_z(float a) { return -mgl_cos(a); }
/* El rumbo que apunta de un punto a otro separado (dx, dz). */
static float heading_to(float dx, float dz) { return atan2_(-dx, -dz); }

static int level_at(int i, int j) {
    char c = ground_map[j][i];
    return c == '~' ? -1 : c - '0';
}

/* ---- Modelos: caras sombreadas, agrupadas por color en un PShape ---- */

#define POOL_V 8000
#define POOL_I 12000
#define POOL_G 1200
#define MAX_FACES 420

static float pool_xyz[POOL_V * 3];
static unsigned short pool_idx[POOL_I];
static PShapeGroup pool_groups[POOL_G];
static int pool_v, pool_i, pool_g;
static int models_v, models_i, models_g; /* lo que ocupan los modelos: el nivel va detrás */

/* Las caras del modelo que se construye, hasta end_model(). */
static float face_p[MAX_FACES][12];
static unsigned char face_n[MAX_FACES], face_rgb[MAX_FACES][3], face_done[MAX_FACES];
static int n_faces;
static PShape *building;
static float center_x, center_y, center_z; /* las normales se orientan hacia fuera de aquí */
static int clip; /* con clip, solo las caras con el centro en [clip_x0, clip_x1) x [clip_z0, clip_z1) */
static float clip_x0, clip_z0, clip_x1, clip_z1;
static int flat; /* sin sombrear: el color tal cual (el agua) */

static void begin_model(PShape *s) {
    building = s;
    n_faces = 0;
}

/* Una cara plana y convexa de 3 o 4 vértices (x, y, z, con y hacia abajo),
   con la luz de arriba, a la izquierda y por delante, en 9 tonos. */
static void face(int n, const float *p, int r, int g, int b) {
    float ux = p[3] - p[0], uy = p[4] - p[1], uz = p[5] - p[2];
    float vx = p[6] - p[0], vy = p[7] - p[1], vz = p[8] - p[2];
    float nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    float cx = 0.0f, cy = 0.0f, cz = 0.0f, len, k;
    int i, flip;
    if (n_faces == MAX_FACES) return;
    for (i = 0; i < n; i++) {
        cx += p[3 * i];
        cy += p[3 * i + 1];
        cz += p[3 * i + 2];
    }
    if (clip && (cx / n < clip_x0 || cx / n >= clip_x1 || cz / n < clip_z0 || cz / n >= clip_z1)) return;
    flip = nx * (cx / n - center_x) + ny * (cy / n - center_y) + nz * (cz / n - center_z) < 0.0f;
    if (flip) {
        nx = -nx;
        ny = -ny;
        nz = -nz;
    }
    /* Los vértices, en el sentido en que la normal sale hacia fuera: así todas
       las caras tienen el mismo sentido de giro y se puede descartar las de
       detrás (PShape.cull). */
    for (i = 0; i < n; i++) {
        face_p[n_faces][3 * i] = p[3 * (flip ? n - 1 - i : i)];
        face_p[n_faces][3 * i + 1] = p[3 * (flip ? n - 1 - i : i) + 1];
        face_p[n_faces][3 * i + 2] = p[3 * (flip ? n - 1 - i : i) + 2];
    }
    len = mgl_sqrt(nx * nx + ny * ny + nz * nz);
    k = len > 0.0f ? (-0.4f * nx - 0.82f * ny + 0.41f * nz) / len : 0.0f;
    k = flat ? 1.0f : 0.35f + 0.65f * (k < 0.0f ? 0.0f : k);
    k = (float)(int)(k * 8.0f + 0.5f) / 8.0f;
    face_n[n_faces] = (unsigned char)n;
    face_rgb[n_faces][0] = (unsigned char)clampf(r * k, 0.0f, 255.0f);
    face_rgb[n_faces][1] = (unsigned char)clampf(g * k, 0.0f, 255.0f);
    face_rgb[n_faces][2] = (unsigned char)clampf(b * k, 0.0f, 255.0f);
    n_faces++;
}

/* El índice de (x, y, z) entre los vértices del grupo, desde first; si no
   está, lo añade. Las caras vecinas calculan sus esquinas comunes con las
   mismas operaciones, así que coinciden bit a bit, y compartirlas deja que el
   renderer transforme cada vértice una vez (su caché de vértices, draw.c). */
static unsigned short vertex_index(const PShape *s, int first, const float *p) {
    float *v = pool_xyz + 3 * first;
    int i, n = pool_v - first;
    for (i = 0; i < n; i++, v += 3)
        if (v[0] == p[0] && v[1] == p[1] && v[2] == p[2]) break;
    if (i == n) {
        v[0] = p[0];
        v[1] = p[1];
        v[2] = p[2];
        pool_v++;
    }
    return (unsigned short)(first - (s->positions - pool_xyz) / 3 + i);
}

/* Copia las caras al pool, las de un mismo color seguidas: un grupo por color,
   con los vértices compartidos dentro del grupo. */
static void end_model(void) {
    PShape *s = building;
    PShapeGroup *group;
    unsigned short idx[4];
    int f, g, i, first;
    s->positions = pool_xyz + 3 * pool_v;
    s->indices = pool_idx + pool_i;
    s->groups = pool_groups + pool_g;
    s->vertex_count = s->index_count = s->group_count = 0;
    s->cull = 1; /* las caras de detrás no se rasterizan: la mitad de un objeto cerrado */
    for (f = 0; f < n_faces; f++) face_done[f] = 0;
    for (f = 0; f < n_faces; f++) {
        if (face_done[f]) continue;
        first = pool_v;
        for (g = f; g < n_faces; g++) {
            if (face_done[g] || face_rgb[g][0] != face_rgb[f][0] || face_rgb[g][1] != face_rgb[f][1] ||
                face_rgb[g][2] != face_rgb[f][2])
                continue;
            if (pool_v + 4 > POOL_V || pool_i + 6 > POOL_I) break;
            face_done[g] = 1;
            for (i = 0; i < face_n[g]; i++) idx[i] = vertex_index(s, first, face_p[g] + 3 * i);
            for (i = 1; i + 1 < face_n[g]; i++) {
                pool_idx[pool_i++] = idx[0];
                pool_idx[pool_i++] = idx[i];
                pool_idx[pool_i++] = idx[i + 1];
                s->index_count += 3;
            }
        }
        s->vertex_count = (unsigned int)(pool_v - (s->positions - pool_xyz) / 3);
        if (pool_g == POOL_G) break;
        group = &pool_groups[pool_g++];
        group->r = face_rgb[f][0];
        group->g = face_rgb[f][1];
        group->b = face_rgb[f][2];
        group->end = (unsigned short)s->index_count;
        s->group_count++;
    }
}

/* Un tronco de pirámide: base de bw x bl en y0 centrada en (cx, cz) y tapa de
   tw x tl en y1 (más arriba: y menor) desplazada tz en z; con tw = 0, una
   pirámide. Con cara de abajo solo con with_bottom: lo que está en el aire y
   se ve desde abajo (sin ella, con cull, se vería el hueco). */
static int with_bottom;

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
    if (with_bottom) face(4, bot, r, g, b);
}

/* Un octaedro centrado en (0, cy, 0) con semiejes rx, ry, rz. */
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

static void set_point(float *p, int n, float x, float h, float z) {
    p[3 * n] = x;
    p[3 * n + 1] = -h;
    p[3 * n + 2] = z;
}

/* Un coche del color (r, g, b), de frente hacia -z: 13 de ancho y 26 de largo. */
static void build_car(PShape *s, int r, int g, int b) {
    int i;
    begin_model(s);
    with_bottom = 1;
    frustum(0.0f, 0.0f, 13.0f, 26.0f, 12.0f, 22.0f, 1.0f, -1.5f, -6.0f, r, g, b);
    with_bottom = 0;
    frustum(0.0f, 2.5f, 11.0f, 12.0f, 8.0f, 7.0f, 1.0f, -6.0f, -9.5f, 50, 60, 85);
    with_bottom = 1;
    frustum(0.0f, 11.5f, 13.0f, 2.0f, 13.0f, 2.0f, 0.0f, -7.0f, -8.5f, r * 7 / 10, g * 7 / 10, b * 7 / 10);
    with_bottom = 0;
    for (i = 0; i < 4; i++)
        frustum(i & 1 ? 7.0f : -7.0f, i & 2 ? 8.0f : -8.0f, 2.5f, 6.0f, 2.5f, 6.0f, 0.0f, 0.0f, -4.0f, 25, 25, 25);
    frustum(-4.0f, -12.9f, 3.0f, 0.6f, 3.0f, 0.6f, 0.0f, -3.0f, -4.5f, 255, 240, 180);
    frustum(4.0f, -12.9f, 3.0f, 0.6f, 3.0f, 0.6f, 0.0f, -3.0f, -4.5f, 255, 240, 180);
    end_model();
}

/* El camión: cabina, caja de carga y seis ruedas; 16 de ancho y 52 de largo. */
static void build_truck(PShape *s) {
    int i;
    begin_model(s);
    frustum(0.0f, -18.0f, 15.0f, 14.0f, 14.0f, 10.0f, 1.5f, -2.0f, -15.0f, 230, 230, 235);
    frustum(0.0f, -25.0f, 13.0f, 1.2f, 12.0f, 1.2f, 0.0f, -9.0f, -13.5f, 40, 50, 70);
    with_bottom = 1;
    frustum(0.0f, 8.0f, 16.0f, 36.0f, 16.0f, 36.0f, 0.0f, -3.0f, -22.0f, 215, 120, 40);
    frustum(0.0f, 0.0f, 12.0f, 50.0f, 12.0f, 50.0f, 0.0f, -1.5f, -3.0f, 45, 45, 50);
    with_bottom = 0;
    for (i = 0; i < 6; i++)
        frustum(i & 1 ? 7.5f : -7.5f, i < 2 ? -17.0f : i < 4 ? 6.0f : 16.0f, 2.5f, 6.0f, 2.5f, 6.0f, 0.0f, 0.0f,
            -4.5f, 25, 25, 25);
    end_model();
}

static void build_models(void) {
    float p[12];
    int i, j;
    build_car(&car, 215, 30, 30);
    build_car(&car_blue, 40, 90, 215);
    build_car(&car_yellow, 240, 195, 30);
    build_truck(&truck);

    begin_model(&pine);
    frustum(0.0f, 0.0f, 2.5f, 2.5f, 2.0f, 2.0f, 0.0f, 0.0f, -5.0f, 110, 80, 50);
    with_bottom = 1;
    frustum(0.0f, 0.0f, 13.0f, 13.0f, 0.0f, 0.0f, 0.0f, -4.0f, -18.0f, 40, 95, 50);
    frustum(0.0f, 0.0f, 9.0f, 9.0f, 0.0f, 0.0f, 0.0f, -13.0f, -26.0f, 50, 115, 60);
    with_bottom = 0;
    end_model();

    begin_model(&tree);
    frustum(0.0f, 0.0f, 2.5f, 2.5f, 2.0f, 2.0f, 0.0f, 0.0f, -8.0f, 110, 80, 50);
    octahedron(-14.0f, 8.0f, 8.0f, 8.0f, 85, 150, 55);
    end_model();

    begin_model(&pine_far); /* de lejos: 4 caras en vez de 13, y 2 en vez de 4 grupos de color */
    with_bottom = 1;
    frustum(0.0f, 0.0f, 12.0f, 12.0f, 0.0f, 0.0f, 0.0f, -2.0f, -26.0f, 45, 105, 55);
    with_bottom = 0;
    end_model();

    begin_model(&tree_far);
    octahedron(-13.0f, 8.0f, 9.0f, 8.0f, 85, 150, 55);
    end_model();

    begin_model(&house); /* paredes y tejado a dos aguas, con la cumbrera en x */
    frustum(0.0f, 0.0f, 20.0f, 16.0f, 20.0f, 16.0f, 0.0f, 0.0f, -12.0f, 235, 225, 200);
    frustum(-5.0f, -2.0f, 3.0f, 3.0f, 3.0f, 3.0f, 0.0f, -14.0f, -23.0f, 150, 70, 55);
    center_x = center_z = 0.0f;
    center_y = -12.0f;
    for (i = -1; i <= 1; i += 2) {
        set_point(p, 0, -11.5f, 11.5f, 9.5f * i);
        set_point(p, 1, 11.5f, 11.5f, 9.5f * i);
        set_point(p, 2, 11.5f, 20.0f, 0.0f);
        set_point(p, 3, -11.5f, 20.0f, 0.0f);
        face(4, p, 180, 65, 45);
        set_point(p, 0, 10.0f * i, 12.0f, -8.0f);
        set_point(p, 1, 10.0f * i, 12.0f, 8.0f);
        set_point(p, 2, 10.0f * i, 20.0f, 0.0f);
        face(3, p, 235, 225, 200);
    }
    end_model();

    begin_model(&sign); /* la placa mira a -z */
    frustum(0.0f, 0.0f, 1.2f, 1.2f, 1.2f, 1.2f, 0.0f, 0.0f, -9.0f, 150, 150, 150);
    with_bottom = 1;
    frustum(0.0f, 0.0f, 11.0f, 1.2f, 11.0f, 1.2f, 0.0f, -9.0f, -16.0f, 245, 200, 40);
    with_bottom = 0;
    end_model();

    begin_model(&station); /* de cara a -z: marquesina con dos surtidores, la tienda detrás y el cartel */
    for (i = 0; i < 4; i++)
        frustum(i & 1 ? 12.0f : -12.0f, i & 2 ? -2.0f : -13.0f, 1.5f, 1.5f, 1.5f, 1.5f, 0.0f, 0.0f, -14.0f, 200, 200,
            205);
    frustum(0.0f, -7.5f, 18.0f, 4.0f, 18.0f, 4.0f, 0.0f, 0.0f, -0.8f, 170, 170, 170);
    for (i = -1; i <= 1; i += 2) {
        frustum(6.0f * i, -7.5f, 3.0f, 2.0f, 3.0f, 2.0f, 0.0f, -0.8f, -7.0f, 215, 40, 35);
        frustum(6.0f * i, -7.5f, 3.4f, 2.4f, 3.4f, 2.4f, 0.0f, -7.0f, -8.0f, 240, 240, 240);
    }
    with_bottom = 1;
    frustum(0.0f, -7.5f, 32.0f, 19.0f, 32.0f, 19.0f, 0.0f, -14.0f, -16.0f, 215, 40, 35);
    with_bottom = 0;
    frustum(0.0f, -7.5f, 31.0f, 18.0f, 31.0f, 18.0f, 0.0f, -16.0f, -17.0f, 245, 245, 245);
    frustum(0.0f, 12.0f, 26.0f, 12.0f, 26.0f, 12.0f, 0.0f, 0.0f, -11.0f, 235, 225, 200);
    frustum(0.0f, 5.9f, 18.0f, 0.4f, 18.0f, 0.4f, 0.0f, -3.0f, -8.0f, 70, 110, 150);
    with_bottom = 1;
    frustum(0.0f, 12.0f, 28.0f, 14.0f, 28.0f, 14.0f, 0.0f, -11.0f, -12.5f, 215, 40, 35);
    with_bottom = 0;
    frustum(16.0f, -14.0f, 1.0f, 1.0f, 1.0f, 1.0f, 0.0f, 0.0f, -22.0f, 150, 150, 150);
    with_bottom = 1;
    frustum(16.0f, -14.0f, 7.0f, 1.2f, 7.0f, 1.2f, 0.0f, -22.0f, -30.0f, 245, 200, 40);
    with_bottom = 0;
    end_model();

    for (i = 0; i < 2; i++) { /* la vaca, de cara a -z: pastando (cabeza abajo) o mirando */
        begin_model(i ? &cow_up : &cow_down);
        for (j = 0; j < 4; j++)
            frustum(j & 1 ? 2.0f : -2.0f, j & 2 ? 4.0f : -4.0f, 1.3f, 1.3f, 1.2f, 1.2f, 0.0f, 0.0f, -4.5f, 70, 60,
                55);
        with_bottom = 1;
        frustum(0.0f, 0.0f, 6.0f, 12.0f, 6.0f, 12.0f, 0.0f, -4.0f, -9.5f, 255, 255, 250);
        with_bottom = 0;
        frustum(0.0f, 2.0f, 6.3f, 4.0f, 6.3f, 4.0f, 0.0f, -5.0f, -8.8f, 35, 35, 35); /* las manchas */
        frustum(0.0f, -3.0f, 6.3f, 2.5f, 6.3f, 2.5f, 0.0f, -6.5f, -9.2f, 35, 35, 35);
        with_bottom = 1;
        frustum(0.0f, -7.0f, 3.6f, 4.0f, 3.2f, 3.6f, 0.0f, i ? -8.0f : -1.5f, i ? -12.0f : -5.5f, 255, 255, 250);
        with_bottom = 0;
        frustum(0.0f, -9.3f, 3.0f, 1.0f, 3.0f, 1.0f, 0.0f, i ? -8.0f : -1.5f, i ? -10.0f : -3.5f, 230, 165, 155);
        frustum(-1.6f, -6.0f, 1.2f, 0.8f, 0.6f, 0.5f, 0.0f, i ? -11.5f : -5.0f, i ? -13.0f : -6.5f, 225, 215, 190);
        frustum(1.6f, -6.0f, 1.2f, 0.8f, 0.6f, 0.5f, 0.0f, i ? -11.5f : -5.0f, i ? -13.0f : -6.5f, 225, 215, 190);
        end_model();
    }

    begin_model(&deer_shape); /* de cara a -z: patas largas, cuello, cuernas y la cola blanca */
    for (j = 0; j < 4; j++)
        frustum(j & 1 ? 1.5f : -1.5f, j & 2 ? 4.0f : -4.0f, 0.9f, 0.9f, 0.8f, 0.8f, 0.0f, 0.0f, -6.5f, 105, 70, 45);
    with_bottom = 1;
    frustum(0.0f, 0.0f, 4.0f, 11.0f, 4.0f, 10.0f, 0.0f, -6.0f, -10.5f, 155, 105, 60);
    with_bottom = 0;
    frustum(0.0f, 5.4f, 3.0f, 0.6f, 3.0f, 0.6f, 0.0f, -8.0f, -10.0f, 245, 240, 230);
    frustum(0.0f, -4.5f, 2.2f, 2.6f, 1.6f, 2.0f, -2.0f, -9.0f, -14.5f, 155, 105, 60);
    with_bottom = 1;
    frustum(0.0f, -7.8f, 2.2f, 4.2f, 2.0f, 4.0f, 0.0f, -13.5f, -16.0f, 140, 92, 55);
    with_bottom = 0;
    frustum(0.0f, -10.0f, 1.4f, 0.4f, 1.4f, 0.4f, 0.0f, -13.8f, -15.0f, 40, 30, 25);
    for (i = -1; i <= 1; i += 2) { /* las cuernas, con una punta hacia delante; las orejas */
        frustum(1.0f * i, -6.6f, 0.5f, 0.5f, 0.3f, 0.3f, 2.5f, -16.0f, -22.0f, 215, 195, 155);
        frustum(1.0f * i, -6.0f, 0.4f, 0.4f, 0.25f, 0.25f, -2.0f, -18.5f, -21.5f, 215, 195, 155);
        frustum(1.9f * i, -5.8f, 1.4f, 0.4f, 0.4f, 0.3f, 0.0f, -15.0f, -17.0f, 140, 92, 55);
    }
    end_model();

    begin_model(&lighthouse); /* franjas blancas y rojas, galería, linterna y techo */
    for (i = 0; i < 4; i++)
        frustum(0.0f, 0.0f, 14.0f - 1.25f * i, 14.0f - 1.25f * i, 12.75f - 1.25f * i, 12.75f - 1.25f * i, 0.0f,
            -14.0f * i, -14.0f * (i + 1), i & 1 ? 200 : 245, i & 1 ? 40 : 245, i & 1 ? 40 : 240);
    with_bottom = 1; /* la galería y el techo sobresalen: se ven desde abajo */
    frustum(0.0f, 0.0f, 14.0f, 14.0f, 14.0f, 14.0f, 0.0f, -56.0f, -58.0f, 70, 70, 75);
    with_bottom = 0;
    frustum(0.0f, 0.0f, 7.0f, 7.0f, 7.0f, 7.0f, 0.0f, -58.0f, -65.0f, 255, 235, 130);
    with_bottom = 1;
    frustum(0.0f, 0.0f, 9.0f, 9.0f, 0.0f, 0.0f, 0.0f, -65.0f, -72.0f, 150, 30, 30);
    with_bottom = 0;
    end_model();
}

/* ---- El circuito ---- */

static int curve_mask(char c) { /* lados que une una curva */
    return c == 'r' ? 2 | 4 : c == '7' ? 8 | 4 : c == 'L' ? 1 | 2 : c == 'J' ? 1 | 8 : 0;
}


static int is_road(int i, int j) {
    return i >= 0 && i < GW && j >= 0 && j < GH && track_map[j][i] != '.';
}

/* Las curvas grandes: un cuadrado de n x n casillas con la misma letra de
   curva (n de 1 a 3) es una curva de radio (n - 0.5) * TILE. Recorriendo el
   mapa por filas, la primera casilla de cada bloque es la de arriba a la
   izquierda. */
static void find_blocks(void) {
    int i, j, n, a, b, ok;
    char c;
    for (j = 0; j < GH; j++)
        for (i = 0; i < GW; i++) block_n[j][i] = 0;
    for (j = 0; j < GH; j++)
        for (i = 0; i < GW; i++) {
            c = track_map[j][i];
            if (!curve_mask(c) || block_n[j][i]) continue;
            for (n = 3; n > 1; n--) { /* el cuadrado más grande que empiece aquí */
                ok = i + n <= GW && j + n <= GH;
                for (b = j; ok && b < j + n; b++)
                    for (a = i; ok && a < i + n; a++) ok = track_map[b][a] == c && !block_n[b][a];
                if (ok) break;
            }
            for (b = j; b < j + n; b++)
                for (a = i; a < i + n; a++) {
                    block_i[b][a] = (unsigned char)i;
                    block_j[b][a] = (unsigned char)j;
                    block_n[b][a] = (unsigned char)n;
                }
        }
}

/* La curva de la casilla (i, j) entrando hacia d: su esquina de giro (px, pz),
   el radio de su eje y la casilla por la que sale. 0 si por ahí no se entra:
   en un bloque, solo por la casilla del borde que queda a un radio de la
   esquina. */
static int curve_geometry(int i, int j, int d, float *px, float *pz, float *r, int *oi, int *oj) {
    int m = curve_mask(track_map[j][i]), from = (d + 2) & 3, out = -1, k, n = block_n[j][i];
    if (!(m >> from & 1)) return 0;
    for (k = 0; k < 4; k++)
        if ((m >> k & 1) && k != from) out = k;
    *r = (n - 0.5f) * TILE;
    *px = (block_i[j][i] + 0.5f * n * (1 + step_x[from] + step_x[out])) * TILE;
    *pz = (block_j[j][i] + 0.5f * n * (1 + step_z[from] + step_z[out])) * TILE;
    if ((int)((*px - step_x[out] * *r - step_x[from] * TILE * 0.5f) / TILE) != i ||
        (int)((*pz - step_z[out] * *r - step_z[from] * TILE * 0.5f) / TILE) != j)
        return 0;
    *oi = (int)((*px - step_x[from] * *r - step_x[out] * TILE * 0.5f) / TILE);
    *oj = (int)((*pz - step_z[from] * *r - step_z[out] * TILE * 0.5f) / TILE);
    return 1;
}

/* ¿Se puede entrar en (i, j) yendo hacia d? */
static int accepts(int i, int j, int d) {
    float px, pz, r;
    int oi, oj;
    if (!is_road(i, j)) return 0;
    return !curve_mask(track_map[j][i]) || curve_geometry(i, j, d, &px, &pz, &r, &oi, &oj);
}

/* La altura de la carretera sale de ground_map, la cifra de cada casilla:
   las rectas y las curvas, a la de la suya (una curva, la de la casilla por
   la que se entra); los puentes y los cruces siguen a la de antes. Donde
   cambia, una cuesta centrada en el cambio, que ocupa por cada lado la mitad
   de lo que dura esa altura, como mucho SLOPE_HALF, y nunca entra en un
   puente o un cruce (planos); en una curva, sí: sube con el ángulo. La pendiente es, así, el cambio de
   altura entre lo que dura la cuesta: 1 2 3, 0.25; 1 1 2 2, 0.125; 1 1 1 2 2 2,
   0.083... La salida también es plana. Sin sitio a ningún lado (entre dos
   puentes), queda un escalón. Una racha de '^' es la excepción: el cambio
   entre lo de antes y lo de después se hace entero en ella, en línea recta,
   sin mirar sus cifras; las cuestas automáticas no entran en ella.
   Las alturas de cada pieza se miden en sus extremos. */
#define SLOPE_HALF (3.0f * TILE)
static float target_h[MAX_PATH];

/* Lo que mide la pieza k por su eje. */
static float piece_len(int k) { return path_kind[k] == CURVE ? path_r[k] * PI * 0.5f : TILE; }

static int fixed_piece(int k) {
    return !k || path_kind[k] == BRIDGE || path_cross[k] || path_ramp[k];
}

/* La cuesta del cambio de altura al empezar la pieza k: cuánto entra hacia
   atrás (*back) y hacia delante (*ahead). */
static void slope_span(int k, float *back, float *ahead) {
    float run, free;
    int q, n, stop;
    for (n = 0; n < 2; n++) {
        run = free = 0.0f;
        stop = 0;
        for (q = n ? k : (k - 1 + n_path) % n_path; target_h[q] == target_h[n ? k : (k - 1 + n_path) % n_path];
             q = n ? (q + 1) % n_path : (q - 1 + n_path) % n_path) {
            run += piece_len(q);
            if (fixed_piece(q)) stop = 1;
            if (!stop) free += piece_len(q);
            if (run > 4.0f * SLOPE_HALF) break; /* basta: ya no limita */
        }
        run *= 0.5f;
        if (run > SLOPE_HALF) run = SLOPE_HALF;
        if (free > run) free = run;
        if (n) *ahead = free;
        else *back = free;
    }
}

/* La altura en s (a lo largo del circuito) de la pieza k, que la contiene. */
static float road_h_at(int k, float s) {
    float back, ahead, u;
    int q;
    for (q = 0; q < n_path; q++) {
        if (target_h[q] == target_h[(q - 1 + n_path) % n_path] || path_ramp[q] ||
            path_ramp[(q - 1 + n_path) % n_path])
            continue; /* junto a una '^', la cuesta es la suya */
        slope_span(q, &back, &ahead);
        if (back + ahead <= 0.0f) continue;
        u = s - path_s[q];
        if (u > road_length * 0.5f) u -= road_length;
        if (u < -road_length * 0.5f) u += road_length;
        if (u >= -back && u <= ahead) {
            q = (q - 1 + n_path) % n_path;
            return target_h[q] + (target_h[(q + 1) % n_path] - target_h[q]) * (u + back) / (back + ahead);
        }
    }
    return target_h[k];
}

/* La altura con la que acaba la racha de '^' que empieza en k: la de la
   siguiente pieza con cifra propia (saltando puentes y cruces). */
static float ramp_end(int k) {
    while (path_ramp[k % n_path] || path_kind[k % n_path] == BRIDGE || path_cross[k % n_path]) k++;
    return level_at(path_i[k % n_path], path_j[k % n_path]) * LEVEL;
}

static void road_heights(void) {
    int k, q, n;
    float a, b;
    for (k = 0; k < n_path; k++)
        if (path_ramp[k]) /* una racha de '^': distinta de todo, para que corte las demás */
            target_h[k] = -1000.0f - k;
        else if (k && (path_kind[k] == BRIDGE || path_cross[k]))
            target_h[k] = path_ramp[k - 1] ? ramp_end(k) : target_h[k - 1];
        else
            target_h[k] = level_at(path_i[k], path_j[k]) * LEVEL;
    for (k = 0; k < n_path; k++) {
        path_hin[k] = road_h_at(k, path_s[k] + 0.01f);
        path_hout[k] = road_h_at(k, path_s[k] + piece_len(k) - 0.01f);
    }
    for (k = 1; k < n_path; k = q) { /* cada racha de '^', en línea recta de lo de antes a lo de después */
        for (q = k; q < n_path && path_ramp[q]; q++) {
        }
        if (q == k) {
            q++;
            continue;
        }
        a = path_hout[k - 1];
        b = path_hin[q % n_path];
        for (n = k; n < q; n++) {
            path_hin[n] = a + (b - a) * (n - k) / (q - k);
            path_hout[n] = a + (b - a) * (n - k + 1) / (q - k);
        }
    }
}

/* El circuito desde la salida. Una curva ocupa su bloque entero; un cruce
   ('+') se pasa dos veces, en línea recta: si las dos a la misma altura, es un
   cruce; si no, la de arriba es un puente (paso elevado). */
static void trace_track(void) {
    int i, j, si = 0, sj = 0, d, from, m, k, oi, oj, a, b, t;
    char c;
    find_blocks();
    for (j = 0; j < GH; j++)
        for (i = 0; i < GW; i++) {
            tile_path[j][i] = tile_path2[j][i] = -1;
            if (track_map[j][i] == 'S') {
                si = i;
                sj = j;
            }
        }
    for (d = 0; d < 4 && !accepts(si + step_x[d], sj + step_z[d], d); d++) {
    }
    i = si;
    j = sj;
    n_path = 0;
    do {
        c = track_map[j][i];
        m = curve_mask(c);
        path_i[n_path] = i;
        path_j[n_path] = j;
        path_din[n_path] = d;
        path_cross[n_path] = c == '+';
        path_ramp[n_path] = c == '^';
        if (m) { /* sale por el otro lado de la curva, por la casilla que toca */
            curve_geometry(i, j, d, &path_px[n_path], &path_pz[n_path], &path_r[n_path], &oi, &oj);
            from = (d + 2) & 3;
            for (k = 0; k < 4; k++)
                if ((m >> k & 1) && k != from) d = k;
            path_kind[n_path] = CURVE;
            for (b = block_j[j][i]; b < block_j[j][i] + block_n[j][i]; b++)
                for (a = block_i[j][i]; a < block_i[j][i] + block_n[j][i]; a++) tile_path[b][a] = (signed char)n_path;
            i = oi;
            j = oj;
        } else {
            path_kind[n_path] = c == '=' ? BRIDGE : STRAIGHT;
            if (tile_path[j][i] < 0) tile_path[j][i] = (signed char)n_path;
            else
                tile_path2[j][i] = (signed char)n_path;
        }
        path_dout[n_path++] = d;
        i += step_x[d];
        j += step_z[d];
    } while ((i != si || j != sj) && accepts(i, j, d) &&
             (tile_path[j][i] < 0 || (track_map[j][i] == '+' && tile_path2[j][i] < 0)) && n_path < MAX_PATH);
    for (road_length = 0.0f, k = 0; k < n_path; k++) {
        path_s[k] = road_length;
        road_length += piece_len(k);
    }
    road_heights();
    for (j = 0; j < GH; j++) /* pasos elevados: arriba, un puente, y en tile_path2 */
        for (i = 0; i < GW; i++)
            if ((k = tile_path2[j][i]) >= 0 && path_hin[k] != path_hin[tile_path[j][i]]) {
                if (path_hin[k] < path_hin[tile_path[j][i]]) {
                    t = tile_path[j][i];
                    tile_path[j][i] = (signed char)k;
                    tile_path2[j][i] = (signed char)t;
                    k = t;
                }
                path_kind[k] = BRIDGE;
            }
}

/* Las dos esquinas del lado d de la casilla (i, j). */
static void side_corners(int i, int j, int d, float h) {
    if (d == 0) CORNER(i, j) = CORNER(i + 1, j) = h;
    else if (d == 1) CORNER(i + 1, j) = CORNER(i + 1, j + 1) = h;
    else if (d == 2) CORNER(i, j + 1) = CORNER(i + 1, j + 1) = h;
    else CORNER(i, j) = CORNER(i, j + 1) = h;
}

/* Lo recorrido de la curva k en (x, z): su ángulo desde la entrada, de 0 a 1. */
static float curve_t(int k, float x, float z) {
    int from = (path_din[k] + 2) & 3, dout = path_dout[k];
    float ox = x - path_px[k], oz = z - path_pz[k];
    return clampf(
        atan2_(-(ox * step_x[from] + oz * step_z[from]), -(ox * step_x[dout] + oz * step_z[dout])) /
            (PI * 0.5f),
        0.0f, 1.0f);
}

/* La altura de la curva k a ángulo t: en una cuesta, sube o baja con el ángulo. */
static float arc_h(int k, float t) {
    return path_hin[k] + (path_hout[k] - path_hin[k]) * t;
}

/* La de (x, z), en el bloque de la curva k; en la esquina de giro, la del medio. */
/* El centro de la curva, a media cuesta; en una horquilla de dos curvas con el mismo
   centro, el mismo para las dos. */
static float center_h(int k) {
    float h = arc_h(k, 0.5f);
    int n = 1, d, q;
    for (d = -1; d <= 1; d += 2) {
        q = (k + d + n_path) % n_path;
        if (path_kind[q] == CURVE && absf(path_px[q] - path_px[k]) < 0.5f && absf(path_pz[q] - path_pz[k]) < 0.5f) {
            h += arc_h(q, 0.5f);
            n++;
        }
    }
    return h / n;
}
static void arc_point(int k, float t, float radius, float *x, float *z);

/* En una escalera de curvas de 1 x 1, la punta de la curva k por su lado end (0 o 1)
   es el centro de la de al lado: cuánto más alto está ese centro que su asfalto. */
static float end_rise(int k, int end) {
    int q = (k + (end ? 1 : -1) + n_path) % n_path;
    float x, z;
    if (path_kind[q] != CURVE || path_r[q] >= TILE) return 0.0f;
    arc_point(k, (float)end, TILE, &x, &z);
    if (absf(x - path_px[q]) > 0.5f || absf(z - path_pz[q]) > 0.5f) return 0.0f;
    return center_h(q) - arc_h(k, (float)end);
}

/* La altura del bloque de la curva a radio r en t: la del ángulo, y la hierba de
   dentro va en línea recta desde el centro: en las grandes, hasta una casilla menos
   que el bloque, como el terreno de al lado entre sus esquinas; en las de 1 x 1, hasta
   el bordillo, como la hierba de las rectas de los lados (strip_corner), y la de fuera,
   hacia el centro de la curva de al lado si es una escalera. Así casan sin rendijas. */
/* La altura de la esquina (ci, cj) del borde del bloque de la curva k. */
static float edge_corner(int k, int ci, int cj) {
    float t = curve_t(k, ci * (float)TILE, cj * (float)TILE);
    if (block_n[path_j[k]][path_i[k]] > 1) return arc_h(k, t);
    return arc_h(k, t) + end_rise(k, 0) * (1.0f - t) + end_rise(k, 1) * t;
}

static float arc_surface(int k, float t, float r) {
    int n = block_n[path_j[k]][path_i[k]], g;
    float rho = n > 1 ? (n - 1) * (float)TILE : path_r[k] - ROAD_W * 0.5f - KERB, c, e, rout, co, si, x, z, u, edge;
    if (r < rho) {
        c = center_h(k);
        return c + (arc_h(k, t) - c) * r / rho;
    }
    rout = path_r[k] + ROAD_W * 0.5f + KERB;
    if (r <= rout) return arc_h(k, t);
    /* fuera: hacia el borde del bloque, en línea recta entre sus esquinas, como el terreno */
    co = mgl_cos(t * PI * 0.5f);
    si = mgl_sin(t * PI * 0.5f);
    e = n * TILE / (co > si ? co : si);
    arc_point(k, t, e, &x, &z);
    x /= TILE;
    z /= TILE;
    if (absf(x - (int)(x + 0.5f)) < absf(z - (int)(z + 0.5f))) { /* en una línea x = cte */
        g = (int)(z + 0.001f);
        u = z - g;
        edge = edge_corner(k, (int)(x + 0.5f), g) * (1.0f - u) + edge_corner(k, (int)(x + 0.5f), g + 1) * u;
    } else {
        g = (int)(x + 0.001f);
        u = x - g;
        edge = edge_corner(k, g, (int)(z + 0.5f)) * (1.0f - u) + edge_corner(k, g + 1, (int)(z + 0.5f)) * u;
    }
    return arc_h(k, t) + (edge - arc_h(k, t)) * clampf((r - rout) / (e - rout), 0.0f, 1.0f);
}
static float curve_h(int k, float x, float z) {
    float ox = x - path_px[k], oz = z - path_pz[k], r2 = ox * ox + oz * oz;
    return r2 < 0.01f ? center_h(k) : arc_surface(k, curve_t(k, x, z), mgl_sqrt(r2));
}

static void build_corners(void) {
    int ci, cj, i, j, n, k;
    float sum;
    for (cj = 0; cj <= GH; cj++)
        for (ci = 0; ci <= GW; ci++) {
            sum = 0.0f;
            n = 0;
            for (j = cj - 1; j <= cj; j++)
                for (i = ci - 1; i <= ci; i++)
                    if (i >= 0 && i < GW && j >= 0 && j < GH) {
                        sum += level_at(i, j) * LEVEL;
                        n++;
                    }
            CORNER(ci, cj) = sum / n;
        }
    for (k = 0; k < n_path; k++)
        if (path_kind[k] != BRIDGE && path_kind[k] != CURVE) {
            side_corners(path_i[k], path_j[k], (path_din[k] + 2) & 3, path_hin[k]);
            side_corners(path_i[k], path_j[k], path_dout[k], path_hout[k]);
        }
    for (k = 0; k < n_path; k++) /* las curvas después: el centro de una de 1 x 1 es suyo */
        if (path_kind[k] == CURVE) { /* el bloque, a la altura de la curva en cada esquina */
            i = block_i[path_j[k]][path_i[k]];
            j = block_j[path_j[k]][path_i[k]];
            for (cj = j; cj <= j + block_n[path_j[k]][path_i[k]]; cj++)
                for (ci = i; ci <= i + block_n[path_j[k]][path_i[k]]; ci++)
                    CORNER(ci, cj) = curve_h(k, ci * TILE, cj * TILE);
        }
}

/* La altura del terreno en (x, z): dos triángulos por casilla, con la
   diagonal de la esquina (i, j) a la (i + 1, j + 1), igual que se dibujan. */
static float terrain_h(float x, float z) {
    int i = (int)(x / TILE), j = (int)(z / TILE);
    float fx, fz, a, b, c, d;
    if (x < 0.0f || z < 0.0f || i >= GW || j >= GH) return -LEVEL;
    fx = x / TILE - i;
    fz = z / TILE - j;
    a = CORNER(i, j);
    b = CORNER(i + 1, j);
    c = CORNER(i + 1, j + 1);
    d = CORNER(i, j + 1);
    return fx > fz ? a + (b - a) * fx + (c - b) * fz : a + (d - a) * fz + (c - d) * fx;
}

/* Dónde está (x, z) en la pieza k: along de 0 (entrada) a 1 (salida) en las
   rectas, y lat, la distancia al eje de la carretera. */
static void piece_local(int k, float x, float z, float *along, float *lat) {
    float cx = (path_i[k] + 0.5f) * TILE, cz = (path_j[k] + 0.5f) * TILE, ox, oz;
    int din = path_din[k];
    if (path_kind[k] == CURVE) { /* alrededor de la esquina de giro; lat, hacia fuera */
        ox = x - path_px[k];
        oz = z - path_pz[k];
        *along = curve_t(k, x, z);
        *lat = mgl_sqrt(ox * ox + oz * oz) - path_r[k];
        return;
    }
    *along = ((x - cx) * step_x[din] + (z - cz) * step_z[din]) / TILE + 0.5f;
    *lat = (x - cx) * -step_z[din] + (z - cz) * step_x[din];
}

static float straight_h(int k, float along, float lat);

/* La altura de la pieza k (no un puente) en (x, z). */
static float road_h(int k, float x, float z) {
    float along, lat;
    if (path_kind[k] == CURVE) return curve_h(k, x, z);
    piece_local(k, x, z, &along, &lat);
    return straight_h(k, along, lat);
}

/* La altura del suelo bajo (x, z) para algo que está a altura h: en un
   puente, el tablero si se está encima. road: si es asfalto. */
static float surface(float x, float z, float h, int *road) {
    int i = (int)(x / TILE), j = (int)(z / TILE), k, k2;
    float along, lat;
    *road = 0;
    if (x < 0.0f || z < 0.0f || i >= GW || j >= GH) return -LEVEL;
    k = tile_path[j][i];
    if ((k2 = tile_path2[j][i]) >= 0) { /* un cruce */
        piece_local(k2, x, z, &along, &lat);
        if (path_kind[k2] == BRIDGE) { /* paso elevado: el tablero, o la de abajo */
            if (absf(lat) < ROAD_W * 0.5f + 1.0f && h > path_hin[k2] - 4.0f) {
                *road = 1;
                return path_hin[k2];
            }
        } else
            *road = absf(lat) < ROAD_W * 0.5f;
    }
    if (k >= 0) {
        piece_local(k, x, z, &along, &lat);
        if (path_kind[k] != BRIDGE) {
            *road |= absf(lat) < ROAD_W * 0.5f;
            return road_h(k, x, z);
        }
        if (absf(lat) < ROAD_W * 0.5f + 1.0f && h > path_hin[k] - 4.0f) {
            *road = 1;
            return path_hin[k];
        }
    }
    return terrain_h(x, z);
}

/* La pieza de la casilla (i, j) para algo a altura h que va por la pieza hint
   (o -1): en un cruce hay dos; en un paso elevado, la de su altura; al mismo
   nivel, la que antes le toca. -1 si no hay carretera. */
static int tile_piece(int i, int j, float h, int hint) {
    int k, k2;
    if (i < 0 || j < 0 || i >= GW || j >= GH || (k = tile_path[j][i]) < 0) return -1;
    if ((k2 = tile_path2[j][i]) < 0) return k;
    if (path_kind[k2] == BRIDGE) return h > path_hin[k2] - 4.0f ? k2 : k;
    if (hint < 0) return k;
    return (k - hint + n_path) % n_path <= (k2 - hint + n_path) % n_path ? k : k2;
}

/* ¿Es (i, j) un cruce al mismo nivel? */
static int flat_cross(int i, int j) {
    return i >= 0 && j >= 0 && i < GW && j < GH && tile_path2[j][i] >= 0 && path_kind[tile_path2[j][i]] != BRIDGE;
}

/* ---- El terreno y la carretera, en trozos ---- */

#define GRASS 80, 140, 58
#define ASPHALT 78, 78, 84

static void terrain_tile(int i, int j) {
    static const int tri[2][3] = {{0, 1, 2}, {0, 2, 3}}; /* esquinas: (i,j) (i+1,j) (i+1,j+1) (i,j+1) */
    static const int ox[4] = {0, 1, 1, 0}, oz[4] = {0, 0, 1, 1};
    float p[9], avg, ux, uy, uz, vx, vy, vz, nx, ny, nz, up;
    int t, v, r, g, b, dry;
    for (t = 0; t < 2; t++) {
        avg = 0.0f;
        dry = 0;
        for (v = 0; v < 3; v++) {
            set_point(p, v, (i + ox[tri[t][v]]) * TILE, CORNER(i + ox[tri[t][v]], j + oz[tri[t][v]]),
                (j + oz[tri[t][v]]) * TILE);
            avg -= p[3 * v + 1] / 3.0f;
            dry |= -p[3 * v + 1] > WATER_H;
        }
        if (!dry) continue; /* entero bajo el agua: no se ve */
        ux = p[3] - p[0];
        uy = p[4] - p[1];
        uz = p[5] - p[2];
        vx = p[6] - p[0];
        vy = p[7] - p[1];
        vz = p[8] - p[2];
        nx = uy * vz - uz * vy;
        ny = uz * vx - ux * vz;
        nz = ux * vy - uy * vx;
        up = absf(ny) / mgl_sqrt(nx * nx + ny * ny + nz * nz);
        if (avg < WATER_H + 3.0f) { /* arena */
            r = 205;
            g = 190;
            b = 135;
        } else if (avg > 58.0f) { /* nieve */
            r = g = 240;
            b = 245;
        } else if (up < 0.84f) { /* roca */
            r = 135;
            g = 122;
            b = 108;
        } else {
            r = 80;
            g = (i * 7 + j * 13) % 3 ? 140 : 150;
            b = 58;
        }
        face(3, p, r, g, b);
    }
}

/* Un punto de la curva k a ángulo t * 90° y a radius de su esquina de giro. */
static void arc_point(int k, float t, float radius, float *x, float *z) {
    int from = (path_din[k] + 2) & 3, dout = path_dout[k];
    float c = mgl_cos(t * PI * 0.5f), s = mgl_sin(t * PI * 0.5f);
    *x = path_px[k] - radius * (step_x[dout] * c + step_x[from] * s);
    *z = path_pz[k] - radius * (step_z[dout] * c + step_z[from] * s);
}

/* ¿Gira a la izquierda la curva k? */
static int turns_left(int k) { return path_dout[k] == ((path_din[k] + 3) & 3); }

/* Un punto de la pieza: a lo largo (t, de 0 a 1) y a lat a la derecha del eje. */
static void piece_point(int k, float t, float lat, float *x, float *z) {
    float cx = (path_i[k] + 0.5f) * TILE, cz = (path_j[k] + 0.5f) * TILE;
    int din = path_din[k];
    if (path_kind[k] == CURVE) {
        arc_point(k, t, path_r[k] + (turns_left(k) ? lat : -lat), x, z);
        return;
    }
    *x = cx + (t - 0.5f) * TILE * step_x[din] - lat * step_z[din];
    *z = cz + (t - 0.5f) * TILE * step_z[din] + lat * step_x[din];
}

/* Un cuadrilátero de la pieza k entre t0..t1 y lat0..lat1. */
static void piece_quad(int k, float t0, float t1, float lat0, float lat1, float h0, float h1, int r, int g, int b) {
    float p[12], x, z;
    piece_point(k, t0, lat0, &x, &z);
    set_point(p, 0, x, h0, z);
    piece_point(k, t0, lat1, &x, &z);
    set_point(p, 1, x, h0, z);
    piece_point(k, t1, lat1, &x, &z);
    set_point(p, 2, x, h1, z);
    piece_point(k, t1, lat0, &x, &z);
    set_point(p, 3, x, h1, z);
    face(4, p, r, g, b);
}

/* La esquina de fuera de la hierba de la recta k, en la punta end (0 o 1) del lado
   side (-1 izquierda, 1 derecha). Si es el centro de una curva de 1 x 1 en cuesta,
   a la altura de ese centro: las rectas de antes y de después llegan ahí a alturas
   distintas, y el terreno de dentro de la curva solo tiene una esquina. */
static float strip_corner(int k, int end, int side) {
    int q = (k + (end ? 1 : -1) + n_path) % n_path;
    float x, z;
    if (path_kind[q] == CURVE && path_r[q] < TILE) {
        piece_point(k, (float)end, side * TILE * 0.5f, &x, &z);
        if (absf(x - path_px[q]) < 0.5f && absf(z - path_pz[q]) < 0.5f) return center_h(q);
    }
    return end ? path_hout[k] : path_hin[k];
}

/* La altura de la recta k a lo largo y a lat: la del eje, y en la hierba, hacia
   las esquinas de fuera. */
static float straight_h(int k, float along, float lat) {
    float a = clampf(along, 0.0f, 1.0f), h = path_hin[k] + (path_hout[k] - path_hin[k]) * a;
    float u = (absf(lat) - ROAD_W * 0.5f - KERB) / (TILE * 0.5f - ROAD_W * 0.5f - KERB);
    int side = lat < 0.0f ? -1 : 1;
    if (u <= 0.0f) return h;
    return h + clampf(u, 0.0f, 1.0f) * ((strip_corner(k, 0, side) - path_hin[k]) * (1.0f - a) +
                                           (strip_corner(k, 1, side) - path_hout[k]) * a);
}

/* La hierba de un lado de la recta k: si va hacia el centro de una curva en cuesta,
   llana hasta el ancho del bordillo de la curva y luego inclinada, como ella. */
static void grass_strip(int k, int side) {
    float p[12], x, z, w = ROAD_W * 0.5f, half = TILE * 0.5f, lat0, lat1;
    if (strip_corner(k, 0, side) != path_hin[k] || strip_corner(k, 1, side) != path_hout[k]) {
        piece_quad(k, 0.0f, 1.0f, side < 0 ? -w - KERB : w, side < 0 ? -w : w + KERB, path_hin[k], path_hout[k], GRASS);
        w += KERB;
    }
    lat0 = side < 0 ? -half : w;
    lat1 = side < 0 ? -w : half;
    piece_point(k, 0.0f, lat0, &x, &z);
    set_point(p, 0, x, straight_h(k, 0.0f, lat0), z);
    piece_point(k, 0.0f, lat1, &x, &z);
    set_point(p, 1, x, straight_h(k, 0.0f, lat1), z);
    piece_point(k, 1.0f, lat1, &x, &z);
    set_point(p, 2, x, straight_h(k, 1.0f, lat1), z);
    piece_point(k, 1.0f, lat0, &x, &z);
    set_point(p, 3, x, straight_h(k, 1.0f, lat0), z);
    face(4, p, GRASS);
}

#define CURVE_SEGMENTS 4 /* por cada casilla de lado del bloque */

/* Un trozo de la curva k: de t0 a t1 y de radio r0 a r1 (r0 = 0: un triángulo). */
static void arc_quad(int k, float t0, float t1, float r0, float r1, int r, int g, int b) {
    float p[12], x, z;
    int fan = r0 <= 0.0f; /* el centro, un punto: un triángulo */
    arc_point(k, t0, r0, &x, &z);
    set_point(p, 0, x, fan ? center_h(k) : arc_surface(k, t0, r0), z);
    arc_point(k, t0, r1, &x, &z);
    set_point(p, 1, x, arc_surface(k, t0, r1), z);
    arc_point(k, t1, r1, &x, &z);
    set_point(p, 2, x, arc_surface(k, t1, r1), z);
    arc_point(k, t1, r0, &x, &z);
    set_point(p, 3, x, arc_surface(k, t1, r0), z);
    face(fan ? 3 : 4, p, r, g, b);
}

/* Una casilla de carretera, entera: arcenes de hierba y asfalto; en una
   curva, todo su bloque, con bordillos; en un cruce, las dos. */
static void road_tile(int k) {
    float h0 = path_hin[k], h1 = path_hout[k], w = ROAD_W * 0.5f, half = TILE * 0.5f, t0, t1, c, s, rin, rout, e0, e1;
    float p[12], x, z;
    int seg, n, red, shade = k & 1 ? 6 : 0, segs, band, bands;
    center_x = center_z = 0.0f;
    center_y = 1e6f; /* todo mira hacia arriba */
    if (flat_cross(path_i[k], path_j[k])) { /* el cruce: la cruz de asfalto y cuatro esquinas de hierba */
        t0 = 0.5f - w / TILE;
        t1 = 0.5f + w / TILE;
        piece_quad(k, 0.0f, 1.0f, -w, w, h0, h0, ASPHALT);
        for (n = 0; n < 2; n++) {
            piece_quad(k, n ? t1 : 0.0f, n ? 1.0f : t0, -half, -w, h0, h0, GRASS);
            piece_quad(k, n ? t1 : 0.0f, n ? 1.0f : t0, w, half, h0, h0, GRASS);
            piece_quad(k, t0, t1, n ? w : -half, n ? half : -w, h0, h0, ASPHALT);
        }
        return;
    }
    if (path_kind[k] != CURVE) {
        grass_strip(k, -1);
        grass_strip(k, 1);
        if (k == 0) { /* la línea de salida, a cuadros */
            for (n = 0; n < 12; n++)
                piece_quad(k, 0.08f * (n / 6), 0.08f * (n / 6 + 1), -w + ROAD_W * (n % 6) / 6.0f,
                    -w + ROAD_W * (n % 6 + 1) / 6.0f, h0, h0, (n + n / 6) & 1 ? 20 : 240, (n + n / 6) & 1 ? 20 : 240,
                    (n + n / 6) & 1 ? 20 : 240);
            piece_quad(k, 0.16f, 1.0f, -w, w, h0, h1, ASPHALT);
        } else
            piece_quad(k, 0.0f, 1.0f, -w, w, h0, h1, 78 + shade, 78 + shade, 84 + shade);
        return;
    }
    bands = block_n[path_j[k]][path_i[k]]; /* las caras de hierba, en tantas bandas: ninguna muy grande */
    segs = CURVE_SEGMENTS * bands;
    rin = path_r[k] - w - KERB;
    rout = path_r[k] + w + KERB;
    for (seg = 0; seg < segs; seg++) {
        t0 = (float)seg / segs;
        t1 = (float)(seg + 1) / segs;
        red = seg & 1;
        for (band = 0; band < bands; band++) /* la hierba de dentro, desde la esquina */
            arc_quad(k, t0, t1, rin * band / bands, rin * (band + 1) / bands, GRASS);
        arc_quad(k, t0, t1, rin, path_r[k] - w, 230, red ? 40 : 230, red ? 40 : 230);
        arc_quad(k, t0, t1, path_r[k] - w, path_r[k] + w, 78 + shade, 78 + shade, 84 + shade);
        arc_quad(k, t0, t1, path_r[k] + w, rout, 230, red ? 230 : 40, red ? 230 : 40);
        /* la de fuera llega al borde del bloque: radio lado / max(cos, sin) */
        c = mgl_cos(t0 * PI * 0.5f);
        s = mgl_sin(t0 * PI * 0.5f);
        e0 = bands * TILE / (c > s ? c : s);
        c = mgl_cos(t1 * PI * 0.5f);
        s = mgl_sin(t1 * PI * 0.5f);
        e1 = bands * TILE / (c > s ? c : s);
        for (band = 0; band < bands; band++) {
            arc_point(k, t0, rout + (e0 - rout) * band / bands, &x, &z);
            set_point(p, 0, x, arc_surface(k, t0, rout + (e0 - rout) * band / bands), z);
            arc_point(k, t0, rout + (e0 - rout) * (band + 1) / bands, &x, &z);
            set_point(p, 1, x, arc_surface(k, t0, rout + (e0 - rout) * (band + 1) / bands), z);
            arc_point(k, t1, rout + (e1 - rout) * (band + 1) / bands, &x, &z);
            set_point(p, 2, x, arc_surface(k, t1, rout + (e1 - rout) * (band + 1) / bands), z);
            arc_point(k, t1, rout + (e1 - rout) * band / bands, &x, &z);
            set_point(p, 3, x, arc_surface(k, t1, rout + (e1 - rout) * band / bands), z);
            face(4, p, GRASS);
        }
    }
}

/* El puente: tablero, la cara de abajo, dos barandillas y un pilar hasta el fondo
   (en un paso elevado, sin pilar). */
static void bridge_tile(int k) {
    float h = path_hin[k], w = ROAD_W * 0.5f + 1.0f, cx = (path_i[k] + 0.5f) * TILE, cz = (path_j[k] + 0.5f) * TILE;
    float p[12], x0, z0, x1, z1;
    int side;
    center_x = center_z = 0.0f;
    center_y = 1e6f;
    piece_quad(k, 0.0f, 1.0f, -w + 1.0f, w - 1.0f, h, h, ASPHALT);
    center_y = -1e6f; /* la cara de abajo mira abajo */
    piece_quad(k, 0.0f, 1.0f, -w, w, h - 2.5f, h - 2.5f, 120, 115, 110);
    center_y = -h; /* las barandillas, por las dos caras: se ven desde el tablero y desde fuera */
    for (side = -1; side <= 1; side += 2) {
        piece_point(k, 0.0f, side * w, &x0, &z0);
        piece_point(k, 1.0f, side * w, &x1, &z1);
        set_point(p, 0, x0, h - 2.5f, z0);
        set_point(p, 1, x1, h - 2.5f, z1);
        set_point(p, 2, x1, h + 3.0f, z1);
        set_point(p, 3, x0, h + 3.0f, z0);
        center_x = cx;
        center_z = cz;
        face(4, p, 215, 215, 220);
        piece_point(k, 0.5f, side * 2.0f * w, &center_x, &center_z); /* un centro más allá: la otra cara */
        face(4, p, 215, 215, 220);
    }
    if (tile_path[path_j[k]][path_i[k]] == k) /* sobre otra carretera no: la sujetan los estribos */
        frustum(cx, cz, 7.0f, 7.0f, 6.0f, 6.0f, 0.0f, -terrain_h(cx, cz), -(h - 2.5f), 150, 145, 140);
}

/* ¿Tiene (i, j) alguna esquina bajo el agua? */
static int wet(int i, int j) {
    return CORNER(i, j) < WATER_H || CORNER(i + 1, j) < WATER_H || CORNER(i, j + 1) < WATER_H ||
           CORNER(i + 1, j + 1) < WATER_H;
}

/* El agua de las casillas i0..i1-1 de la fila j: un cuadrilátero sin sombrear. */
static void water_run(int i0, int i1, int j) {
    float p[12];
    set_point(p, 0, i0 * TILE, WATER_H, j * TILE);
    set_point(p, 1, i1 * TILE, WATER_H, j * TILE);
    set_point(p, 2, i1 * TILE, WATER_H, (j + 1) * TILE);
    set_point(p, 3, i0 * TILE, WATER_H, (j + 1) * TILE);
    center_x = center_z = 0.0f;
    center_y = 1e6f;
    flat = 1;
    face(4, p, WATER);
    flat = 0;
}

/* La altura de lo que hay en la casilla (i, j) en (x, z), un punto de su
   borde: su carretera o su terreno (leído un poco hacia dentro). */
static float tile_top(int i, int j, float x, float z) {
    int k = tile_path[j][i];
    x += ((i + 0.5f) * TILE - x) * 0.001f;
    z += ((j + 0.5f) * TILE - z) * 0.001f;
    if (k >= 0 && path_kind[k] != BRIDGE) return road_h(k, x, z);
    return terrain_h(x, z);
}

/* Una pared vertical en el borde de (xa, za) a (xb, zb), entre las alturas lo
   y hi de cada punta, mirando hacia fuera de (cx, cz). */
static void wall_face(float xa, float za, float loa, float hia, float xb, float zb, float lob, float hib, float cx,
    float cz, int r, int g, int b) {
    float p[12];
    int n = 0;
    set_point(p, n++, xa, hia, za);
    set_point(p, n++, xb, hib, zb);
    if (hib - lob > 0.01f) set_point(p, n++, xb, lob, zb);
    if (hia - loa > 0.01f) set_point(p, n++, xa, loa, za);
    if (n < 3) return;
    center_x = cx;
    center_z = cz;
    center_y = -(hia + loa) * 0.5f;
    face(n, p, r, g, b);
}

/* Las paredes de la casilla de carretera (i, j) donde lo de al lado no está a
   su altura (un paso elevado, un terraplén): de la casilla alta hacia la baja,
   y si al lado hay terreno, también hacia arriba (el terreno no tiene). Sin
   ellas, por la rendija se vería el cielo. */
static void skirts(int i, int j) {
    static const int ex0[4] = {0, 1, 0, 0}, ez0[4] = {0, 0, 1, 0}, ex1[4] = {1, 1, 1, 0}, ez1[4] = {0, 1, 1, 1};
    float x0, z0, x1, z1, a0, a1, b0, b1, u, xm, zm, bm, cx = (i + 0.5f) * TILE, cz = (j + 0.5f) * TILE, ox, oz;
    int d, ni, nj, road_side, r, g, b, part, parts;
    for (d = 0; d < 4; d++) {
        ni = i + step_x[d];
        nj = j + step_z[d];
        if (ni < 0 || nj < 0 || ni >= GW || nj >= GH || tile_path[nj][ni] == tile_path[j][i]) continue;
        road_side = tile_path[nj][ni] >= 0 && path_kind[tile_path[nj][ni]] != BRIDGE;
        r = road_side ? 165 : 135;
        g = road_side ? 160 : 122;
        b = road_side ? 150 : 108;
        ox = (ni + 0.5f) * TILE;
        oz = (nj + 0.5f) * TILE;
        x0 = (i + ex0[d]) * TILE;
        z0 = (j + ez0[d]) * TILE;
        x1 = (i + ex1[d]) * TILE;
        z1 = (j + ez1[d]) * TILE;
        a0 = tile_top(i, j, x0, z0) - tile_top(ni, nj, x0, z0); /* cuánto más alta está esta */
        a1 = tile_top(i, j, x1, z1) - tile_top(ni, nj, x1, z1);
        b0 = tile_top(ni, nj, x0, z0);
        b1 = tile_top(ni, nj, x1, z1);
        if (absf(a0) < 0.05f) a0 = 0.0f;
        if (absf(a1) < 0.05f) a1 = 0.0f;
        if (!a0 && !a1) continue;
        /* si una punta está más alta y la otra más baja, dos trozos que se cruzan en u */
        parts = a0 * a1 < 0.0f ? 2 : 1;
        u = parts == 2 ? a0 / (a0 - a1) : 1.0f;
        xm = x0 + (x1 - x0) * u;
        zm = z0 + (z1 - z0) * u;
        bm = b0 + (b1 - b0) * u;
        for (part = 0; part < parts; part++) {
            float xa = part ? xm : x0, za = part ? zm : z0, ba = part ? bm : b0, da = part ? 0.0f : a0;
            float xb = part || parts == 1 ? x1 : xm, zb = part || parts == 1 ? z1 : zm;
            float bb = part || parts == 1 ? b1 : bm, db = part || parts == 1 ? a1 : 0.0f;
            if (da + db > 0.0f) /* esta, más alta: hacia fuera */
                wall_face(xa, za, ba, ba + da, xb, zb, bb, bb + db, cx, cz, r, g, b);
            else if (!road_side) /* el terreno, más alto: hacia dentro */
                wall_face(xa, za, ba + da, ba, xb, zb, bb + db, bb, ox, oz, r, g, b);
        }
    }
}

/* ¿Es (i, j) la primera casilla (por filas) de su bloque de curva dentro del
   trozo (ci, cj)? La curva se construye una vez por trozo, con solo sus caras. */
static int first_in_chunk(int i, int j, int ci, int cj) {
    int a, b, n = block_n[j][i];
    for (b = block_j[j][i]; b < block_j[j][i] + n; b++)
        for (a = block_i[j][i]; a < block_i[j][i] + n; a++)
            if (a / CHUNK == ci && b / CHUNK == cj) return a == i && b == j;
    return 0;
}

static void build_chunks(void) {
    int ci, cj, i, j, k, run;
    for (cj = 0; cj < CHUNKS_Z; cj++)
        for (ci = 0; ci < CHUNKS_X; ci++) {
            begin_model(&chunks[cj][ci]);
            for (j = cj * CHUNK; j < (cj + 1) * CHUNK; j++) { /* el agua: un trozo por tramo mojado de la fila */
                run = -1;
                for (i = ci * CHUNK; i <= (ci + 1) * CHUNK; i++) {
                    k = i < (ci + 1) * CHUNK && wet(i, j) &&
                        (tile_path[j][i] < 0 || path_kind[tile_path[j][i]] == BRIDGE);
                    if (k && run < 0) run = i;
                    if (!k && run >= 0) {
                        water_run(run, i, j);
                        run = -1;
                    }
                }
            }
            clip_x0 = ci * CHUNK * TILE; /* las caras de una curva grande, cada una en el trozo de su centro */
            clip_z0 = cj * CHUNK * TILE;
            clip_x1 = clip_x0 + CHUNK * TILE;
            clip_z1 = clip_z0 + CHUNK * TILE;
            for (j = cj * CHUNK; j < (cj + 1) * CHUNK; j++)
                for (i = ci * CHUNK; i < (ci + 1) * CHUNK; i++) {
                    k = tile_path[j][i];
                    if (k >= 0 && path_kind[k] != BRIDGE) {
                        clip = path_kind[k] == CURVE;
                        if (!clip || first_in_chunk(i, j, ci, cj)) road_tile(k);
                        clip = 0;
                        skirts(i, j);
                        if (tile_path2[j][i] >= 0 && path_kind[tile_path2[j][i]] == BRIDGE) bridge_tile(tile_path2[j][i]);
                        continue;
                    }
                    center_x = center_z = 0.0f;
                    center_y = 1e6f;
                    terrain_tile(i, j);
                    if (k >= 0) bridge_tile(k);
                }
            end_model();
        }
}

/* ---- El decorado ---- */

static void add_prop(float x, float z, float a, float s, float r, const PShape *shape, int kind) {
    Prop *p;
    int road;
    if (n_props == MAX_PROPS) return;
    p = &props[n_props++];
    p->x = x;
    p->z = z;
    p->h = surface(x, z, 0.0f, &road);
    p->a = a;
    p->s = s;
    p->r = r;
    p->shape = shape;
    p->kind = kind;
    p->phase = (int)(rnd() * 1000.0f);
}

static void build_props(void) {
    float x, z;
    int i, j, d;
    char c;
    for (j = 0; j < GH; j++)
        for (i = 0; i < GW; i++) {
            c = scenery_map[j][i];
            x = (i + 0.5f) * TILE;
            z = (j + 0.5f) * TILE;
            if (c == 'T' || c == 't')
                add_prop(x + (rnd() - 0.5f) * 16.0f, z + (rnd() - 0.5f) * 16.0f, rnd() * 2.0f * PI,
                    0.8f + 0.5f * rnd(), 4.0f, c == 'T' ? &pine : &tree, PROP_TREE);
            else if (c == 'H')
                add_prop(x, z, (float)(int)(rnd() * 4.0f) * PI * 0.5f, 1.0f, 13.0f, &house, PROP_HOUSE);
            else if (c == 'F')
                add_prop(x, z, 0.0f, 1.0f, 9.0f, &lighthouse, PROP_LIGHTHOUSE);
            else if (c == 'V')
                add_prop(x + (rnd() - 0.5f) * 16.0f, z + (rnd() - 0.5f) * 16.0f, rnd() * 2.0f * PI, 1.0f, 7.0f,
                    &cow_down, PROP_COW);
            else if (c == 's' || c == 'E') /* junto a la carretera, de cara a ella */
                for (d = 0; d < 4; d++)
                    if (is_road(i + step_x[d], j + step_z[d])) {
                        if (c == 's')
                            add_prop(x + step_x[d] * 10.0f, z + step_z[d] * 10.0f, dir_angle[d], 1.0f, 2.0f, &sign,
                                PROP_SIGN);
                        else
                            add_prop(x, z, dir_angle[d], 1.0f, 15.0f, &station, PROP_STATION);
                        break;
                    }
        }
}

/* ---- El coche ---- */

/* Al principio de la pieza k (una recta, en medio), mirando hacia donde va. */
static void place_car(int k) {
    int road;
    piece_point(k, path_kind[k] == CURVE ? 0.0f : 0.5f, 0.0f, &car_x, &car_z);
    car_a = dir_angle[path_din[k]];
    car_h = ground_prev = surface(car_x, car_z, path_hin[k] + 2.0f, &road);
    car_v = car_vh = car_pitch = car_roll = 0.0f;
    car_ground = 1;
    sinking = 0;
    cam_a = car_a;
    cam_h = car_h + CAM_UP;
}

/* Un vehículo en la casilla k del circuito, en su carril y parado. */
static void place_vehicle(Vehicle *t, int k) {
    int d = path_din[k], road;
    t->k = k;
    piece_point(k, path_kind[k] == CURVE ? 0.0f : 0.5f, LANE, &t->x, &t->z); /* a la derecha */
    t->a = dir_angle[d];
    t->h = surface(t->x, t->z, path_hin[k] + 2.0f, &road);
    t->v = 0.0f;
    t->off = 0;
    t->lane = LANE;
    t->passing = 0;
    t->stuck = 0;
}

static void add_vehicle(int n, int k, float top, const PShape *shape, int is_truck) {
    traffic[n].top = top;
    traffic[n].shape = shape;
    traffic[n].truck = is_truck;
    place_vehicle(&traffic[n], k);
}

static void reset_race(void) {
    add_vehicle(0, n_path / 10, 4.4f, &car_blue, 0); /* por delante de la salida, escalonados */
    add_vehicle(1, n_path * 13 / 50, 4.0f, &car_yellow, 0);
    add_vehicle(2, n_path * 22 / 50, 3.0f, &truck, 1);
    place_car(0);
    deer.on = 0;
    deer.wait = 600;
    state = COUNTDOWN;
    timer = 180;
    race_time = lap_start = best_lap = 0;
    lap = 1;
    progress = 0;
}

/* ¿Toca un círculo de radio r en (x, z) al vehículo t? El coche es un círculo; el
   camión, largo, dos: uno por delante y otro por detrás. */
static int hits_vehicle(const Vehicle *t, float x, float z, float r) {
    float dx, dz, off, d;
    int n;
    for (n = 0; n < (t->truck ? 2 : 1); n++) {
        off = t->truck ? (n ? 13.0f : -14.0f) * car_scale : 0.0f;
        dx = t->x + dir_x(t->a) * off - x;
        dz = t->z + dir_z(t->a) * off - z;
        d = (t->truck ? 9.0f : 6.6f) * car_scale + r;
        if (dx * dx + dz * dz < d * d) return 1;
    }
    return 0;
}

/* ¿Se tocan dos vehículos? Los círculos de b contra los de a. */
static int vehicles_touch(const Vehicle *a, const Vehicle *b) {
    float off;
    int n;
    for (n = 0; n < (b->truck ? 2 : 1); n++) {
        off = b->truck ? (n ? 13.0f : -14.0f) * car_scale : 0.0f;
        if (hits_vehicle(a, b->x + dir_x(b->a) * off, b->z + dir_z(b->a) * off, (b->truck ? 9.0f : 6.6f) * car_scale))
            return 1;
    }
    return 0;
}

/* ¿Tocaría t algo (el jugador u otro vehículo) si estuviera en (x, z)? */
static int traffic_hits(const Vehicle *t, int n, float x, float z) {
    Vehicle moved = *t;
    int m;
    moved.x = x;
    moved.z = z;
    if (hits_vehicle(&moved, car_x, car_z, CAR_R) && absf(car_h - t->h) < 8.0f) return 1;
    for (m = 0; m < MAX_TRAFFIC; m++)
        if (m != n && vehicles_touch(&moved, &traffic[m])) return 1;
    return 0;
}

static int blocked(float x, float z) {
    float dx, dz, d, along, lat;
    int i, k;
    if (x < TILE * 0.6f || z < TILE * 0.6f || x > (GW - 0.6f) * TILE || z > (GH - 0.6f) * TILE) return 1;
    k = tile_path2[(int)(z / TILE)][(int)(x / TILE)]; /* el puente es la segunda en un paso elevado */
    if (k < 0) k = tile_path[(int)(z / TILE)][(int)(x / TILE)];
    if (k >= 0 && path_kind[k] == BRIDGE && car_h > path_hin[k] - 4.0f) { /* las barandillas */
        piece_local(k, x, z, &along, &lat);
        if (absf(lat) > ROAD_W * 0.5f + 1.0f - CAR_R) return 1;
    }
    for (i = 0; i < n_props; i++) {
        dx = props[i].x - x;
        dz = props[i].z - z;
        d = props[i].r * props[i].s + CAR_R;
        if (dx * dx + dz * dz < d * d && car_h < props[i].h + 20.0f) return 1;
    }
    for (i = 0; i < MAX_TRAFFIC; i++)
        if (hits_vehicle(&traffic[i], x, z, CAR_R) && absf(car_h - traffic[i].h) < 8.0f) return 1;
    dx = deer.x - x;
    dz = deer.z - z;
    if (deer.on && dx * dx + dz * dz < (5.0f + CAR_R) * (5.0f + CAR_R) && absf(car_h - deer.h) < 8.0f) return 1;
    return 0;
}

/* ¿No se puede ir a (x, z)? Algo en medio, un cortado o una cuesta de roca
   (la que se pinta gris, más de 0.65 de pendiente); por la carretera, sí. */
static int wall(float x, float z) {
    int road, here;
    float to, dx = x - car_x, dz = z - car_z;
    if (blocked(x, z)) return 1;
    to = surface(x, z, car_h + 2.0f, &road);
    if (to - car_h > 7.0f) return 1;
    /* la pendiente del suelo, no la del coche: dando saltitos tampoco se sube */
    return !road && to > car_h - 2.0f &&
        to - surface(car_x, car_z, car_h + 2.0f, &here) > 0.65f * mgl_sqrt(dx * dx + dz * dz) + 0.05f;
}

/* ¿No puede ir el coche a (x, z)? Mira también dónde quedaría el morro (o la
   trasera, marcha atrás) y si hay roca empinada hasta 8 por delante: la
   cámara de dentro va 2 por delante del centro y el plano cercano está a 5;
   más cerca de una pared de roca, la atravesaría y se vería el cielo. */
static int car_wall(float x, float z) {
    float sign = car_v < 0.0f ? -1.0f : 1.0f, fx = dir_x(car_a) * sign, fz = dir_z(car_a) * sign;
    float nose = 13.0f * car_scale, d, prev, s;
    int road;
    if (wall(x, z) || blocked(x + fx * nose, z + fz * nose)) return 1;
    prev = surface(x, z, car_h + 2.0f, &road);
    for (d = 2.0f; d <= 8.0f; d += 2.0f) {
        s = surface(x + fx * d, z + fz * d, car_h + 2.0f, &road);
        if (!road && s > car_h - 2.0f && s - prev > 0.65f * 2.0f) return 1;
        prev = s;
    }
    return 0;
}

/* La altura del suelo junto al coche, para inclinarlo; la de un muro o una
   cuesta de roca no cuenta: el coche no tiene las ruedas ahí. */
static float ground_near(float x, float z) {
    int road;
    float s = surface(x, z, car_h + 2.0f, &road);
    if (s > car_h && wall(x, z)) return car_h;
    return s < car_h - 7.0f ? car_h - 7.0f : s;
}

static int road_position(float x, float z, float h, int hint, float *pos, float *right);

/* La distancia a lo largo del circuito hasta pos (pieza + lo recorrido de ella). */
static float road_s(float pos) {
    int k = (int)pos % n_path;
    return path_s[k] + (pos - (int)pos) * piece_len(k);
}

/* pos, dist más adelante por la carretera. */
static float pos_ahead(float pos, float dist) {
    float len, f;
    for (;;) {
        len = piece_len((int)pos % n_path);
        f = pos - (int)pos;
        if (f * len + dist < len) return pos + dist / len;
        dist -= (1.0f - f) * len;
        pos = (float)((int)pos + 1);
    }
}

/* Lo más deprisa que se toma la curva k sin salirse del asfalto, con la
   dirección del coche (update_car): el radio de giro a velocidad v es
   v (1 + 0.08 v) / 0.065; con 8 de margen hacia fuera del eje. En una
   horquilla (dos curvas seguidas al mismo lado) el margen se sumaría: sin él. */
static int same_turn(int k, int q) {
    q = (q + n_path) % n_path;
    return path_kind[q] == CURVE && turns_left(q) == turns_left(k);
}
static float curve_speed(int k) {
    float margin = same_turn(k, k - 1) || same_turn(k, k + 1) ? 0.0f : 8.0f;
    return (mgl_sqrt(1.0f + 4.0f * 0.08f * 0.065f * (path_r[k] + margin)) - 1.0f) / (2.0f * 0.08f);
}

/* El punto del centro de la carretera en pos (pieza + lo recorrido de ella). */
static void road_point(float pos, float *x, float *z) {
    int k = (int)pos;
    piece_point(k % n_path, pos - k, 0.0f, x, z);
}

/* El piloto automático: sigue el centro de la carretera mirando un poco por
   delante, frena a tiempo para tomar cada curva a su curve_speed y detrás de
   un vehículo que le estorbe, al que adelanta por el otro lado; si se queda
   clavado contra algo, da marcha atrás un rato. */
static void drive_auto(int *up, int *down, int *steer) {
    float fx = dir_x(car_a), fz = dir_z(car_a), pos, right, tx, tz, dx, dz, lat, ahead, d, want = 6.5f;
    float shift = 0.0f, gap;
    int k = road_position(car_x, car_z, car_h, progress, &pos, &right), n, m, q;
    if (k < 0 || (k - progress + n_path) % n_path > 3) pos = progress + 1.0f; /* fuera: a la siguiente */
    for (m = 0; m < 8; m++) { /* las curvas de delante; frenando con margen, que al final de una cuesta vuela */
        q = ((int)pos + m) % n_path;
        gap = m ? road_s((float)q) - road_s(pos) : 0.0f;
        if (gap < 0.0f) gap += road_length;
        if (gap > 250.0f) break;
        if (path_kind[q] != CURVE) continue;
        gap = gap > 4.0f ? gap - 4.0f : 0.0f;
        d = mgl_sqrt(curve_speed(q) * curve_speed(q) + 2.0f * 0.07f * gap);
        if (d < want) want = d;
    }
    for (n = 0; n < MAX_TRAFFIC; n++) {
        dx = traffic[n].x - car_x;
        dz = traffic[n].z - car_z;
        ahead = dx * fx + dz * fz;
        lat = -dx * fz + dz * fx; /* a la derecha, positivo */
        if (ahead > 0.0f && ahead < 40.0f && absf(lat) < 6.5f) {
            shift = lat > 0.0f ? -7.0f : 7.0f;
            if (ahead < 18.0f && traffic[n].v < want) want = traffic[n].v;
        }
    }
    if (deer.on) { /* un ciervo en la carretera por delante: para hasta que pase */
        dx = deer.x - car_x;
        dz = deer.z - car_z;
        ahead = dx * fx + dz * fz;
        lat = -dx * fz + dz * fx;
        if (ahead > 0.0f && ahead < 90.0f && absf(lat) < ROAD_W) {
            d = ahead > 22.0f ? mgl_sqrt(2.0f * 0.12f * (ahead - 22.0f)) : 0.0f;
            if (d < want) want = d;
        }
    }
    road_point(pos_ahead(pos, 24.0f), &tx, &tz);
    dx = tx - fz * shift - car_x;
    dz = tz + fx * shift - car_z;
    lat = -dx * fz + dz * fx;
    d = mgl_sqrt(dx * dx + dz * dz);
    *steer = lat < -d * 0.03f ? 1 : lat > d * 0.03f ? -1 : 0;
    *up = car_v < want;
    *down = car_v > want + 0.15f;
    auto_stuck = state == RACE && absf(car_v) < 0.2f && !auto_back ? auto_stuck + 1 : 0;
    if (auto_stuck > 60) auto_back = 50;
    if (auto_back) { /* marcha atrás, con el volante al revés: el morro gira hacia donde quiere ir */
        auto_back--;
        *up = 0;
        *down = 1;
        *steer = -*steer;
    }
}

static void update_car(void) {
    int up = keyIsDown(UP) || keyIsDown('w'), down = keyIsDown(DOWN) || keyIsDown('s');
    int steer = (keyIsDown(LEFT) || keyIsDown('a')) - (keyIsDown(RIGHT) || keyIsDown('d'));
    float fx = dir_x(car_a), fz = dir_z(car_a), nx, nz, s, hf, hb, hl, hr, prev;
    if (autopilot) drive_auto(&up, &down, &steer);
    if (sinking) { /* en el agua: se hunde y luego vuelve a la carretera */
        car_v = car_vh = 0.0f;
        car_h -= 0.15f;
        return;
    }
    if (state != RACE) up = down = steer = 0;
    steer_shown += (steer - steer_shown) * 0.25f;
    if (car_ground) {
        if (up) car_v += on_road ? 0.07f : 0.035f; /* en la hierba acelera la mitad */
        if (down) car_v -= car_v > 0.2f ? 0.16f : 0.05f;
        if (!up && !down) car_v *= on_road ? 0.985f : 0.96f;
        if (!on_road && car_v > OFFROAD_V) /* y pierde enseguida lo que traía de más */
            car_v = OFFROAD_V + (car_v - OFFROAD_V) * 0.88f;
        car_v = clampf(car_v, -2.0f, 6.5f);
        hf = ground_near(car_x + fx * 8.0f, car_z + fz * 8.0f);
        hb = ground_near(car_x - fx * 8.0f, car_z - fz * 8.0f);
        car_v -= 0.1f * (hf - hb) / 16.0f; /* cuesta arriba frena, abajo empuja */
        /* despacio gira cerrado (radio ~25); deprisa, abierto: en las curvas hay que frenar */
        car_a = wrap_angle(car_a + steer * 0.065f * clampf(car_v / 1.5f, -1.0f, 1.0f) / (1.0f + 0.08f * absf(car_v)));
        hl = ground_near(car_x + fz * 6.0f, car_z - fx * 6.0f);
        hr = ground_near(car_x - fz * 6.0f, car_z + fx * 6.0f);
        car_pitch += (clampf((hf - hb) / 16.0f, -0.45f, 0.45f) - car_pitch) * 0.3f;
        car_roll += (clampf((hl - hr) / 12.0f, -0.35f, 0.35f) - car_roll) * 0.3f;
    }
    nx = car_x + dir_x(car_a) * car_v;
    nz = car_z + dir_z(car_a) * car_v;
    if (car_wall(nx, nz)) { /* contra algo: resbala por el lado que se pueda, o rebota */
        if (!car_wall(nx, car_z)) nz = car_z;
        else if (!car_wall(car_x, nz))
            nx = car_x;
        else {
            nx = car_x;
            nz = car_z;
        }
        if (nx == car_x && nz == car_z)
            car_v *= -0.3f;
        else /* resbalando, la velocidad es lo que avanza de frente */
            car_v = 0.9f * ((nx - car_x) * dir_x(car_a) + (nz - car_z) * dir_z(car_a));
    }
    car_x = nx;
    car_z = nz;
    /* Lo vertical: la gravedad y, en el suelo, la velocidad vertical del suelo,
       para que al acabar una cuesta el coche siga subiendo y vuele. */
    prev = car_h;
    car_h += car_vh;
    car_vh -= 0.2f;
    s = surface(car_x, car_z, prev + 2.0f, &on_road);
    if (car_h <= s) {
        car_vh = absf(s - ground_prev) < 3.0f ? s - ground_prev : 0.0f; /* un escalón (el puente) no lanza */
        car_h = s;
        car_ground = 1;
    } else
        car_ground = car_h - s < 0.5f;
    ground_prev = s;
    if (car_h < WATER_H - 2.0f && !sinking) sinking = 50;
}

/* La vuelta: hay que pasar por las casillas en orden (o saltar dos). */
static void update_progress(void) {
    int i = (int)(car_x / TILE), j = (int)(car_z / TILE), k, n;
    if (i < 0 || j < 0 || i >= GW || j >= GH) return;
    k = tile_piece(i, j, car_h, progress);
    if (k < 0 || car_h < path_hin[k] - 3.0f) return; /* por debajo del puente no cuenta */
    for (n = 1; n <= 3; n++)
        if (k == (progress + n) % n_path) {
            if (k < progress) { /* por la salida: vuelta */
                if (!best_lap || race_time - lap_start < best_lap) best_lap = race_time - lap_start;
                lap_start = race_time;
                if (++lap > LAPS) {
                    lap = LAPS;
                    state = FINISHED;
                }
            }
            progress = k;
            return;
        }
}

/* El rumbo de la carretera en (x, z) sobre la pieza k; en *right, cuánto se
   aparta de su centro hacia la derecha, y en *along, cuánto ha recorrido de la
   pieza (0 a la entrada, 1 a la salida). En las curvas, el rumbo y el
   recorrido salen del ángulo alrededor de la esquina, como sin / (sin + cos)
   (sin arcotangente: a lo más 4° de error). */
static float road_heading(int k, float x, float z, float *right, float *along) {
    int din = path_din[k], from = (din + 2) & 3, dout = path_dout[k];
    float cx = (path_i[k] + 0.5f) * TILE, cz = (path_j[k] + 0.5f) * TILE, ox, oz, c, s, f;
    if (path_kind[k] != CURVE) {
        *right = (x - cx) * -step_z[din] + (z - cz) * step_x[din];
        *along = ((x - cx) * step_x[din] + (z - cz) * step_z[din]) / TILE + 0.5f;
        return dir_angle[din];
    }
    ox = x - path_px[k]; /* desde la esquina de giro */
    oz = z - path_pz[k];
    c = -(ox * step_x[dout] + oz * step_z[dout]);
    s = -(ox * step_x[from] + oz * step_z[from]);
    f = c + s > 0.0f ? clampf(s / (c + s), 0.0f, 1.0f) : 0.5f;
    *along = f;
    /* por fuera de la curva: la derecha si gira a la izquierda */
    *right = (mgl_sqrt(ox * ox + oz * oz) - path_r[k]) * (turns_left(k) ? 1.0f : -1.0f);
    return dir_angle[din] + wrap_angle(dir_angle[dout] - dir_angle[din]) * f;
}

/* Dónde queda (x, z) respecto a t: por delante (ahead) y a la derecha (side). */
static void relative(const Vehicle *t, float x, float z, float *ahead, float *side) {
    float dx = x - t->x, dz = z - t->z;
    *ahead = dx * dir_x(t->a) + dz * dir_z(t->a);
    *side = dx * mgl_cos(t->a) - dz * mgl_sin(t->a);
}

/* Medio ancho y medio largo: los modelos miden 16.5 x 26 (el coche) y
   16 x 52 (el camión), escalados con car_scale. */
static float half_width(int is_truck) { return (is_truck ? 8.0f : 8.25f) * car_scale; }
static float half_length(int is_truck) { return (is_truck ? 26.0f : 13.0f) * car_scale; }

/* Dónde está (x, z) en la carretera: la pieza (o -1 si no está en ella) y, en
   *pos, lo recorrido desde la salida en casillas; en *right, cuánto se aparta
   del centro hacia la derecha. */
static int road_position(float x, float z, float h, int hint, float *pos, float *right) {
    int k;
    float along;
    if (x < 0.0f || z < 0.0f || (k = tile_piece((int)(x / TILE), (int)(z / TILE), h, hint)) < 0) return -1;
    road_heading(k, x, z, right, &along);
    *pos = k + clampf(along, 0.0f, 1.0f);
    return k;
}

/* Lo de delante de t (en la carretera a pos): algo de ancho en (x, z)
   a velocidad v. Las distancias van a lo largo de la carretera, así que ve lo
   que hay pasada una curva. Devuelve lo que puede correr t para pararse a
   tiempo detrás (o ir a su ritmo), y apunta en *slow si le estorba en su
   carril yendo despacio: entonces adelanta, por el lado contrario al que
   ocupa (*slow_right). Lo que esté en su carril le hace frenar; lo que solo
   esté donde está ahora (a right del centro), mientras se aparta, que vaya
   despacio, sin pararse: parado no podría apartarse. */
static float obstacle(const Vehicle *t, float pos, float right, float x, float z, float h, float v, int is_truck,
    float want, int *slow, float *slow_right) {
    float opos, oright, ahead, gap, allowed, width = half_width(t->truck) + half_width(is_truck) + 0.8f;
    int in_lane, in_way;
    if (road_position(x, z, h, t->k, &opos, &oright) < 0) return want; /* fuera de la carretera no estorba */
    ahead = road_s(opos) - road_s(pos);
    if (ahead < 0.0f) ahead += road_length;
    if (ahead <= 0.0f || ahead > LOOK) return want;
    in_lane = absf(oright - t->lane) < width;
    in_way = absf(oright - right) < width;
    if (!in_lane && !in_way) return want;
    gap = ahead - half_length(t->truck) - half_length(is_truck) - 2.0f; /* entre parachoques */
    allowed = gap > 0.0f ? mgl_sqrt(2.0f * BRAKE * gap) : 0.0f;
    if (gap > 0.0f && v > allowed) allowed = v;
    if (!in_lane && allowed < 0.6f) allowed = 0.6f;
    if (in_lane && v < t->top * traffic_speed * 0.7f) {
        *slow = 1;
        *slow_right = oright;
    }
    return allowed < want ? allowed : want;
}

/* ¿Tiene algo al lado por la derecha? Entonces aún no puede volver a su carril. */
static int alongside(const Vehicle *t, float x, float z, int is_truck) {
    float ahead, side, len = half_length(t->truck) + half_length(is_truck) + 4.0f;
    relative(t, x, z, &ahead, &side);
    return ahead > -len && ahead < len && side > 0.0f;
}

/* Un cruce al mismo nivel por delante: espera fuera a que pase lo que haya
   dentro o llegue por su derecha por la otra carretera (así, de dos que
   llegan a la vez, uno pasa). Devuelve lo que puede correr. */
static float give_way(const Vehicle *t, float want) {
    float cx, cz, dx, dz, d, ahead, side, gap, allowed, oa, ox, oz, cross;
    int m, q, n;
    for (m = 0; m <= 2; m++) {
        q = (t->k + m) % n_path;
        if (path_kind[q] == CURVE || !flat_cross(path_i[q], path_j[q])) continue;
        cx = (path_i[q] + 0.5f) * TILE;
        cz = (path_j[q] + 0.5f) * TILE;
        dx = cx - t->x;
        dz = cz - t->z;
        d = mgl_sqrt(dx * dx + dz * dz);
        if (d < TILE * 0.5f) return want; /* ya dentro: que salga */
        gap = d - TILE * 0.5f - half_length(t->truck) - 2.0f;
        if (gap > LOOK) return want;
        for (n = -1; n < MAX_TRAFFIC; n++) { /* -1: el jugador */
            if (n >= 0 && &traffic[n] == t) continue;
            ox = n < 0 ? car_x : traffic[n].x;
            oz = n < 0 ? car_z : traffic[n].z;
            oa = n < 0 ? car_a : traffic[n].a;
            cross = mgl_cos(oa - t->a); /* por la otra carretera: de lado */
            if (cross > 0.7f || cross < -0.7f) continue;
            dx = ox - cx;
            dz = oz - cz;
            if (dx * dx + dz * dz > 50.0f * 50.0f) continue;
            relative(t, ox, oz, &ahead, &side);
            if (dx * dx + dz * dz < TILE * TILE * 0.36f || side > 0.0f) {
                allowed = gap > 0.0f ? mgl_sqrt(2.0f * BRAKE * gap) : 0.0f;
                if (allowed < want) want = allowed;
            }
        }
        return want;
    }
    return want;
}

static void update_traffic(void) {
    float road_a, right, along, pos, heading, want, nx, nz, slow_right = 0.0f, deer_right;
    Vehicle *t;
    int n, m, i, j, k, road, slow, busy;
    if (state == COUNTDOWN) return;
    for (n = 0; n < MAX_TRAFFIC; n++) {
        t = &traffic[n];
        i = (int)(t->x / TILE);
        j = (int)(t->z / TILE);
        k = tile_piece(i, j, t->h, t->k);
        if (k == (t->k + 1) % n_path || k == (t->k + 2) % n_path) t->k = k;
        /* El rumbo de la carretera, corregido hacia su carril: apartado a la
           derecha (right > lane), gira a la izquierda, y al revés. */
        road_a = road_heading(k >= 0 ? k : t->k, t->x, t->z, &right, &along);
        pos = (k >= 0 ? k : t->k) + clampf(along, 0.0f, 1.0f);
        heading = road_a + clampf((right - t->lane) * 0.07f, -0.5f, 0.5f);
        if (t->stuck > 10) /* atascado contra algo: apunta del todo hacia su carril y lo rodea despacio */
            heading = road_a + (right > t->lane ? 1.2f : -1.2f);
        /* sin física: gira lo que haga falta para seguir su carril, también por
           dentro de una curva cerrada */
        t->a = wrap_angle(t->a + clampf(wrap_angle(heading - t->a), -0.2f, 0.2f));
        /* despacio en las curvas, y detrás de lo que tenga delante */
        want = t->top * traffic_speed;
        for (m = 1; m <= 2; m++) { /* más despacio cuanto más cerrada la curva: 0.6 en las de una casilla */
            road = (t->k + m) % n_path;
            if (path_kind[road] == CURVE && want > t->top * traffic_speed * (0.4f + path_r[road] / 100.0f))
                want = t->top * traffic_speed * clampf(0.4f + path_r[road] / 100.0f, 0.0f, 1.0f);
        }
        want = give_way(t, want);
        /* Frena a tiempo por lo que lleva delante (el jugador y el resto); si le
           estorba algo lento, adelanta por la izquierda, y vuelve a la derecha
           cuando no tiene a nadie al lado. */
        slow = 0;
        want = obstacle(t, pos, right, car_x, car_z, car_h, car_v, 0, want, &slow, &slow_right);
        for (m = 0; m < MAX_TRAFFIC; m++)
            if (m != n)
                want = obstacle(t, pos, right, traffic[m].x, traffic[m].z, traffic[m].h, traffic[m].v, traffic[m].truck, want,
                    &slow, &slow_right);
        if (deer.on) /* espera a que cruce: no adelanta */
            want = obstacle(t, pos, right, deer.x, deer.z, deer.h, 0.0f, 0, want, &busy, &deer_right);
        if (slow) { /* por el otro lado del que estorba; si ya iba por ahí, sigue */
            t->pass_lane = slow_right > 0.0f ? -LANE : LANE;
            if (!t->passing) t->passing = 120;
        }
        if (t->passing == 1) {
            busy = alongside(t, car_x, car_z, 0);
            for (m = 0; m < MAX_TRAFFIC; m++)
                if (m != n) busy |= alongside(t, traffic[m].x, traffic[m].z, traffic[m].truck);
            if (busy) t->passing = 30;
        }
        if (t->passing) t->passing--;
        t->lane = t->passing ? t->pass_lane : LANE;
        t->v += clampf(want - t->v, -0.2f, 0.05f);
        nx = t->x + dir_x(t->a) * t->v;
        nz = t->z + dir_z(t->a) * t->v;
        /* Si así tocaría algo (y ahora no lo toca), espera: el giro de este frame
           ya está hecho. Si lleva mucho esperando, se echa atrás para tener
           sitio y rodearlo. */
        if (traffic_hits(t, n, nx, nz) && !traffic_hits(t, n, t->x, t->z)) {
            t->v = 0.0f;
            if (++t->stuck > 40) {
                nx = t->x - dir_x(t->a) * 0.4f;
                nz = t->z - dir_z(t->a) * 0.4f;
                if (!traffic_hits(t, n, nx, nz)) {
                    t->x = nx;
                    t->z = nz;
                }
                if (t->stuck > 70) t->stuck = 0;
            }
            continue;
        }
        t->stuck = 0;
        t->x = nx;
        t->z = nz;
        t->h = surface(t->x, t->z, t->h + 2.0f, &road);
        t->off = road ? 0 : t->off + 1;
        if (t->off > 90 || t->h < WATER_H) place_vehicle(t, t->k); /* perdido: de vuelta a su casilla */
    }
}

/* La cámara de TV de la pieza k: cada 4 piezas, a un lado de la carretera
   (por fuera, si por ahí no hay un monte que tape) y por encima del suelo. */
static void tv_spot(int k, float *x, float *z, float *h) {
    float side = 30.0f, g;
    int road, n;
    k = k / 4 * 4 % n_path;
    for (n = 0; n < 2; n++, side = -side) {
        piece_point(k, 0.5f, side, x, z);
        g = surface(*x, *z, 1e4f, &road);
        *h = (g > path_hin[k] ? g : path_hin[k]) + 14.0f;
        if (g < path_hin[k] + 12.0f) return;
    }
}

static void update_camera(void) {
    float tx, tz, th, g, back = CAM_BACK, up = CAM_UP, dx, dz;
    int road;
    if (cam_mode == CAM_COCKPIT) {
        cam_a = car_a;
        cam_x = car_x + dir_x(car_a) * 2.0f;
        cam_z = car_z + dir_z(car_a) * 2.0f;
        cam_h = car_h + EYE;
        cam_p = car_pitch;
        return;
    }
    if (cam_mode == CAM_TV) { /* fija junto a la pista, girando para seguir al coche */
        tv_spot(progress + 2, &cam_x, &cam_z, &cam_h);
        dx = car_x - cam_x;
        dz = car_z - cam_z;
        cam_a = heading_to(dx, dz);
        cam_p = atan2_(car_h + 2.0f - cam_h, mgl_sqrt(dx * dx + dz * dz));
        return;
    }
    if (cam_mode == CAM_HIGH) { /* más lejos y más alta: se ve el circuito por delante */
        back = CAM_BACK * 2.0f;
        up = CAM_UP * 4.0f;
    }
    cam_a = wrap_angle(cam_a + wrap_angle(car_a - cam_a) * 0.12f);
    tx = car_x - dir_x(cam_a) * back;
    tz = car_z - dir_z(cam_a) * back;
    th = car_h + up;
    g = surface(tx, tz, th, &road);
    if (th < g + 8.0f) th = g + 8.0f;
    cam_x = tx;
    cam_z = tz;
    cam_h += (th - cam_h) * 0.2f;
    cam_p = -(cam_h - car_h - 4.0f) / back;
}

static void build_minimap(void);

/* Construye el nivel n: el circuito, el terreno en trozos (detrás de los
   modelos, que se quedan) y el decorado, y prepara la carrera. */
static void load_level(int n) {
    level = n;
    ground_map = levels[n]->ground;
    track_map = levels[n]->track;
    scenery_map = levels[n]->scenery;
    pool_v = models_v;
    pool_i = models_i;
    pool_g = models_g;
    seed = 1990;
    n_props = 0;
    trace_track();
    build_corners();
    build_chunks();
    build_props();
    build_minimap();
    reset_race();
    update_camera();
    level_shown = 180;
}

static void update_deer(void);

static void update(void) {
    int c = keyIsDown('c'), r = keyIsDown('r'), space = keyIsDown(' '), less, more;
    if (keyIsDown('g') && !g_was_down) debug = (debug + 1) % 3;
    g_was_down = keyIsDown('g');
    if (debug) return; /* congelado: no se mueve nada, ni la cámara */
    anim++;
    if (c && !c_was_down) {
        cam_mode = (cam_mode + 1) % CAMS;
        cam_shown = 90;
    }
    if (cam_shown) cam_shown--;
    if (r && !r_was_down && state == RACE) place_car(progress);
    if (space && !space_was_down && state == FINISHED) reset_race();
    if (keyIsDown('p') && !p_was_down) autopilot = !autopilot;
    p_was_down = keyIsDown('p');
    if (autopilot && state == FINISHED && ++timer > 300) reset_race(); /* en bucle, como demo */
    if (keyIsDown('n') && !n_was_down) { /* el siguiente nivel: sus mallas, en vez de las de este */
        resetShapes();
        load_level((level + 1) % LEVELS);
    }
    n_was_down = keyIsDown('n');
    if (level_shown) level_shown--;
    if (keyIsDown('-') && !minus_was_down && car_scale > 0.31f) {
        car_scale -= 0.05f;
        scale_shown = 120;
    }
    if (keyIsDown('+') && !plus_was_down && car_scale < 1.49f) {
        car_scale += 0.05f;
        scale_shown = 120;
    }
    minus_was_down = keyIsDown('-');
    plus_was_down = keyIsDown('+');
    if (scale_shown) scale_shown--;
    /* En la española > es Shift+<: en SDL llega como < con Shift, en el
       simulador como el > US. */
    less = keyIsDown('<') && !keyIsDown(SHIFT);
    more = keyIsDown('>') || (keyIsDown('<') && keyIsDown(SHIFT));
    if (less && !less_was_down && traffic_speed > 0.25f) {
        traffic_speed -= 0.1f;
        speed_shown = 120;
    }
    if (more && !more_was_down && traffic_speed < 1.25f) {
        traffic_speed += 0.1f;
        speed_shown = 120;
    }
    less_was_down = less;
    more_was_down = more;
    if (speed_shown) speed_shown--;
    c_was_down = c;
    r_was_down = r;
    space_was_down = space;
    if (state == COUNTDOWN && --timer <= 0) {
        state = RACE;
        timer = 0;
    }
    if (state == RACE) race_time++;
    update_car();
    update_traffic();
    update_deer();
    if (sinking && --sinking == 0) place_car(progress);
    if (state == RACE) update_progress();
    update_camera();
}

static int visible(float x, float z, float r);

/* El ciervo: cada 15 a 35 s, si hay una recta por delante con tierra a los dos lados,
   la cruza de lado a lado al trote y se va por donde no se le vea. */
static void update_deer(void) {
    float x0, z0, x1, z1;
    int k, side, road;
    if (!deer.on) {
        if (state != RACE || --deer.wait > 0) return;
        deer.wait = 30; /* si no hay sitio, otra vez dentro de poco */
        k = (progress + 4 + (int)(rnd() * 4.0f)) % n_path;
        if (!k || path_kind[k] != STRAIGHT || path_cross[k] || path_ramp[k] || path_hin[k] != path_hout[k]) return;
        side = rnd() < 0.5f ? -1 : 1;
        piece_point(k, 0.5f, side * 34.0f, &x0, &z0);
        piece_point(k, 0.5f, -side * 34.0f, &x1, &z1);
        if (surface(x0, z0, 1000.0f, &road) < WATER_H + 2.0f || surface(x1, z1, 1000.0f, &road) < WATER_H + 2.0f ||
            absf(surface(x0, z0, 1000.0f, &road) - path_hin[k]) > 6.0f ||
            absf(surface(x1, z1, 1000.0f, &road) - path_hin[k]) > 6.0f)
            return;
        deer.on = 1;
        deer.x = x0;
        deer.z = z0;
        deer.a = atan2_(-(x1 - x0), -(z1 - z0)); /* de cara a donde va */
        deer.left = 68.0f + 60.0f;
    }
    deer.x += dir_x(deer.a) * 0.9f;
    deer.z += dir_z(deer.a) * 0.9f;
    deer.left -= 0.9f;
    deer.h = surface(deer.x, deer.z, deer.h + 4.0f, &road);
    if ((deer.left < 60.0f && !visible(deer.x, deer.z, 15.0f)) || deer.left < -400.0f ||
        deer.h < WATER_H) { /* ya cruzó y no se le ve: se ha ido */
        deer.on = 0;
        deer.wait = 900 + (int)(rnd() * 1200.0f);
    }
}

/* ---- Dibujo ---- */

static void draw_sky(int hy) {
    static const float isle_a[5] = {0.7f, 1.9f, 2.6f, 4.1f, 5.3f};
    static const int isle_w[5] = {40, 22, 60, 30, 48}, isle_h[5] = {7, 4, 10, 5, 8};
    int i, x;
    background(95, 145, 210);
    noStroke();
    fill(140, 175, 220);
    rect(0, hy - 50, width, 20);
    fill(190, 200, 215);
    rect(0, hy - 30, width, 15);
    fill(235, 215, 185);
    rect(0, hy - 15, width, 15);
    fill(120, 140, 165);
    for (i = 0; i < 5; i++) { /* islas lejanas */
        x = width / 2 - (int)(wrap_angle(isle_a[i] - cam_a) * FOCAL);
        if (x > -isle_w[i] && x < width + isle_w[i])
            triangle(x - isle_w[i], hy, x - isle_w[i] / 3, hy - isle_h[i], x + isle_w[i], hy);
    }
    if (hy < height) {
        fill(WATER);
        rect(0, hy, width, height - hy);
    }
}

/* ¿Puede verse algo en (x, z) de radio r? En planta, con margen por el cabeceo. */
static int visible(float x, float z, float r) {
    float dx = x - cam_x, dz = z - cam_z;
    float ahead = dx * dir_x(cam_a) + dz * dir_z(cam_a), side = dx * mgl_cos(cam_a) - dz * mgl_sin(cam_a);
    if (ahead < -r || ahead > VIEW + r) return 0;
    return absf(side) < ahead * 0.85f + r;
}

static void draw_world(void) {
    int ci, cj, i, far;
    Prop *p;
    translate(width / 2, height / 2, FOCAL);
    rotateX(cam_p);
    rotateY(-cam_a);
    translate(-cam_x, cam_h, -cam_z); /* desde aquí, coordenadas del mundo con y = -altura */
    for (cj = 0; cj < CHUNKS_Z; cj++)
        for (ci = 0; ci < CHUNKS_X; ci++)
            if (visible((ci + 0.5f) * CHUNK * TILE, (cj + 0.5f) * CHUNK * TILE, CHUNK * TILE * 0.75f + 20.0f))
                shape(&chunks[cj][ci]);
    for (i = 0; i < n_props; i++) {
        p = &props[i];
        if (!visible(p->x, p->z, 30.0f)) continue;
        far = p->kind == PROP_TREE &&
              (p->x - cam_x) * (p->x - cam_x) + (p->z - cam_z) * (p->z - cam_z) > LOD_FAR * LOD_FAR;
        pushMatrix();
        translate(p->x, -p->h, p->z);
        if (p->kind == PROP_COW) { /* pasta y de vez en cuando levanta la cabeza; se va girando */
            rotateY(p->a + 0.6f * mgl_sin((anim + p->phase) * 0.004f));
            shape((anim + p->phase) % 500 < 380 ? &cow_down : &cow_up);
            popMatrix();
            continue;
        }
        rotateY(p->a);
        scale(p->s);
        shape(!far ? p->shape : p->shape == &pine ? &pine_far : &tree_far);
        if (p->kind == PROP_LIGHTHOUSE) { /* el haz que gira: dos cuñas de luz */
            rotateY(anim * 0.03f);
            fill(255, 245, 185);
            beginShape(TRIANGLES);
            vertex(0.0f, -61.0f, 0.0f);
            vertex(-14.0f, -52.0f, -160.0f);
            vertex(14.0f, -52.0f, -160.0f);
            vertex(0.0f, -61.0f, 0.0f);
            vertex(14.0f, -52.0f, 160.0f);
            vertex(-14.0f, -52.0f, 160.0f);
            endShape();
        }
        popMatrix();
    }
    if (deer.on && visible(deer.x, deer.z, 15.0f)) { /* al trote: da saltitos */
        pushMatrix();
        translate(deer.x, -deer.h - 1.5f * absf(mgl_sin(anim * 0.25f)), deer.z);
        rotateY(deer.a);
        shape(&deer_shape);
        popMatrix();
    }
    for (i = 0; i < MAX_TRAFFIC; i++) {
        if (!visible(traffic[i].x, traffic[i].z, 20.0f)) continue;
        pushMatrix();
        translate(traffic[i].x, -traffic[i].h, traffic[i].z);
        rotateY(traffic[i].a);
        scale(car_scale);
        shape(traffic[i].shape);
        popMatrix();
    }
    if (cam_mode != CAM_COCKPIT) {
        pushMatrix();
        translate(car_x, -car_h, car_z);
        rotateY(car_a);
        rotateX(-car_pitch);
        rotateZ(car_roll);
        scale(car_scale);
        shape(&car);
        popMatrix();
    }
}

/* Letras de 3 x 5 píxeles: una cifra octal por fila, de arriba abajo. */
static int glyph(int c) {
    static const int letters[26] = {025755, 065656, 074447, 065556, 074647, 074644, 074557, 055755, 072227,
        011157, 055655, 044447, 057755, 065555, 075557, 075744, 075571, 065655, 074717, 072222, 055557,
        055552, 055775, 055255, 055222, 071247};
    static const int digits[10] = {075557, 026227, 071747, 071717, 055711, 074717, 074757, 071111, 075757,
        075717};
    if (c >= 'A' && c <= 'Z') return letters[c - 'A'];
    if (c >= '0' && c <= '9') return digits[c - '0'];
    return c == ':' ? 002020 : c == '.' ? 000002 : c == '/' ? 011244 : c == '-' ? 000700 : 0;
}

/* Cada letra con pocos rectángulos (cada uno es un comando de 40 bytes): de
   cada píxel encendido y sin pintar, lo más ancho que se pueda y luego lo
   más alto. Una cifra sale en 3 o 4. */
static void draw_text(const char *s, int x, int y, int px_size) {
    int bits, row, col, w, h, r, c, ok;
    for (; *s; s++, x += 4 * px_size) {
        bits = glyph(*s);
        for (row = 0; row < 5; row++)
            for (col = 0; col < 3; col++) {
                if (!(bits >> (3 * (4 - row) + 2 - col) & 1)) continue;
                for (w = 1; col + w < 3 && bits >> (3 * (4 - row) + 2 - col - w) & 1; w++) {
                }
                for (h = 1, ok = 1; ok && row + h < 5; h += ok)
                    for (c = col; c < col + w; c++)
                        ok &= bits >> (3 * (4 - row - h) + 2 - c) & 1;
                for (r = row; r < row + h; r++) /* pintado: fuera del glifo */
                    for (c = col; c < col + w; c++)
                        bits &= ~(1 << (3 * (4 - r) + 2 - c));
                rect(x + col * px_size, y + row * px_size, w * px_size, h * px_size);
            }
    }
}

/* v con dec decimales, redondeado y con su signo; devuelve el final. */
static char *put_num(char *s, float v, int dec) {
    long scale = 1, n, q;
    int i;
    char tmp[12];
    for (i = 0; i < dec; i++) scale *= 10;
    n = (long)((v < 0.0f ? -v : v) * (float)scale + 0.5f);
    if (v < 0.0f && n) *s++ = '-'; /* sin -0.0000 */
    q = n / scale;
    i = 0;
    do {
        tmp[i++] = (char)('0' + q % 10);
        q /= 10;
    } while (q);
    while (i) *s++ = tmp[--i];
    if (dec) {
        *s++ = '.';
        for (q = scale / 10; q; q /= 10) *s++ = (char)('0' + n / q % 10);
    }
    *s = 0;
    return s;
}

static char *put_str(char *s, const char *t) {
    while (*t) *s++ = *t++;
    *s = 0;
    return s;
}

/* El modo debug (G): con la primera pulsación el juego se congela tal cual;
   con la segunda, en lugar de la escena, todo lo que hace falta para volver a
   dibujarla en el host (racer/scene.c, make racer-scene): nivel, cámara,
   coche, tráfico y el reloj de las animaciones; con la tercera, sigue. Sin
   la escena detrás, porque el texto ya llena el buffer de comandos. */
static void draw_debug(void) {
    char line[64], *s;
    int i, y = 4;
    background(0, 0, 0);
    noStroke();
    fill(255, 220, 60);
    draw_text("RACER DEBUG - G GOES ON", 4, y, 2);
    fill(120, 255, 120);
    s = put_num(put_str(line, "LV "), (float)level, 0);
    s = put_num(put_str(s, " CAM "), (float)cam_mode, 0);
    s = put_num(put_str(s, " F "), (float)anim, 0);
    put_num(put_str(s, " SC "), car_scale, 2);
    draw_text(line, 4, y += 16, 2);
    s = put_num(put_str(line, "EYE X "), cam_x, 2);
    put_num(put_str(s, " Z "), cam_z, 2);
    draw_text(line, 4, y += 14, 2);
    s = put_num(put_str(line, "    H "), cam_h, 2);
    s = put_num(put_str(s, " A "), cam_a, 4);
    put_num(put_str(s, " P "), cam_p, 4);
    draw_text(line, 4, y += 12, 2);
    s = put_num(put_str(line, "CAR X "), car_x, 2);
    put_num(put_str(s, " Z "), car_z, 2);
    draw_text(line, 4, y += 14, 2);
    s = put_num(put_str(line, "    H "), car_h, 2);
    put_num(put_str(s, " A "), car_a, 4);
    draw_text(line, 4, y += 12, 2);
    s = put_num(put_str(line, "    P "), car_pitch, 4);
    put_num(put_str(s, " R "), car_roll, 4);
    draw_text(line, 4, y += 12, 2);
    for (i = 0; i < MAX_TRAFFIC; i++) {
        s = put_num(put_str(line, "T"), (float)i, 0);
        s = put_num(put_str(s, " X "), traffic[i].x, 2);
        put_num(put_str(s, " Z "), traffic[i].z, 2);
        draw_text(line, 4, y += 14, 2);
        s = put_num(put_str(line, "   H "), traffic[i].h, 2);
        put_num(put_str(s, " A "), traffic[i].a, 4);
        draw_text(line, 4, y += 12, 2);
    }
    fill(160, 160, 160); /* el resto, para entender qué pasaba */
    s = put_num(put_str(line, "V "), car_v, 2);
    s = put_num(put_str(s, " VH "), car_vh, 2);
    s = put_num(put_str(s, " GROUND "), (float)car_ground, 0);
    s = put_num(put_str(s, " ROAD "), (float)on_road, 0);
    put_num(put_str(s, " K "), (float)progress, 0);
    draw_text(line, 4, y += 14, 2);
}

/* Centrado en horizontal. */
static void draw_centered(const char *s, int y, int px_size) {
    int n = 0;
    while (s[n]) n++;
    draw_text(s, (width - (4 * n - 1) * px_size) / 2, y, px_size);
}

/* Frames (60 por segundo) como M:SS.D. */
static void format_time(char *s, int frames) {
    int tenths = frames / 6;
    s[0] = (char)('0' + tenths / 600 % 10);
    s[1] = ':';
    s[2] = (char)('0' + tenths / 100 % 6);
    s[3] = (char)('0' + tenths / 10 % 10);
    s[4] = '.';
    s[5] = (char)('0' + tenths % 10);
    s[6] = 0;
}

/* El minimapa, preparado al cargar el nivel: 2 píxeles por casilla (uno
   por cada 20 unidades), la tierra y el eje de la carretera, en tramos
   horizontales del mismo color (cada uno, un rect: pocos comandos). */
#define MAP_RUNS 400
static unsigned char map_run_x[MAP_RUNS], map_run_y[MAP_RUNS], map_run_w[MAP_RUNS], map_run_road[MAP_RUNS];
static int map_runs;

static void build_minimap(void) {
    static unsigned char px[2 * GH][2 * GW]; /* 0 agua, 1 tierra, 2 carretera */
    int i, j, k, n, steps, x, y;
    float t, fx, fz;
    for (j = 0; j < 2 * GH; j++)
        for (i = 0; i < 2 * GW; i++) px[j][i] = level_at(i / 2, j / 2) >= 0;
    for (k = 0; k < n_path; k++) { /* el eje, cada 5 unidades */
        steps = (int)(piece_len(k) / 5.0f) + 1;
        for (n = 0; n <= steps; n++) {
            t = (float)n / steps;
            piece_point(k, t, 0.0f, &fx, &fz);
            x = (int)(fx / 20.0f);
            y = (int)(fz / 20.0f);
            if (x >= 0 && y >= 0 && x < 2 * GW && y < 2 * GH) px[y][x] = 2;
        }
    }
    /* la tierra (con la carretera encima: menos tramos) y luego la carretera; dos fill() */
    map_runs = 0;
    for (k = 1; k <= 2; k++)
        for (y = 0; y < 2 * GH; y++)
            for (x = 0; x < 2 * GW; x = i + 1) {
                for (i = x; i < 2 * GW && px[y][i] >= k; i++) {
                }
                if (i > x && map_runs < MAP_RUNS) {
                    map_run_x[map_runs] = (unsigned char)x;
                    map_run_y[map_runs] = (unsigned char)y;
                    map_run_w[map_runs] = (unsigned char)(i - x);
                    map_run_road[map_runs++] = (unsigned char)(k == 2);
                }
            }
}

/* Un punto del mapa, de size x size, centrado en (x, z). */
static void map_dot(int x0, int y0, float x, float z, int size) {
    rect(x0 + (int)(x / 20.0f + 0.5f) - size / 2, y0 + (int)(z / 20.0f + 0.5f) - size / 2, size, size);
}

static void draw_minimap(int x0, int y0) {
    int k;
    fill(20, 40, 60);
    rect(x0 - 2, y0 - 2, 2 * GW + 4, 2 * GH + 4);
    for (k = 0; k < map_runs; k++) {
        if (k == 0 || map_run_road[k] != map_run_road[k - 1]) {
            if (map_run_road[k]) fill(210, 210, 215);
            else fill(45, 85, 50);
        }
        rect(x0 + map_run_x[k], y0 + map_run_y[k], map_run_w[k], 1);
    }
    fill(255, 255, 255); /* la salida */
    map_dot(x0, y0, (path_i[0] + 0.5f) * TILE, (path_j[0] + 0.5f) * TILE, 2);
    for (k = 0; k < MAX_TRAFFIC; k++) {
        if (traffic[k].truck) fill(240, 140, 40);
        else fill(240, 230, 120);
        map_dot(x0, y0, traffic[k].x, traffic[k].z, 2);
    }
    fill(255, 40, 40);
    map_dot(x0, y0, car_x, car_z, 3);
}

/* Dentro del coche: el salpicadero, con el volante girando con la dirección. */
static void draw_dashboard(void) {
    int cx = width / 2, top = height - 52, i;
    float a = -steer_shown * 0.8f, t; /* a la izquierda, el volante gira al revés del reloj */
    noStroke();
    fill(36, 34, 38);
    rect(0, top, width, height - top);
    fill(52, 50, 56);
    rect(0, top, width, 3);
    noFill();
    stroke(20, 20, 22);
    strokeWeight(7);
    circle(cx, height + 20, 120); /* el volante, y sus radios girando con la dirección */
    for (i = 0; i < 3; i++) { /* arriba a izquierda y derecha y abajo, girados con el volante */
        t = a + (i == 0 ? -1.1f : i == 1 ? 1.1f : PI);
        line(cx, height + 20, cx + (int)(mgl_sin(t) * 58.0f), height + 20 - (int)(mgl_cos(t) * 58.0f));
    }
    strokeWeight(1);
    noStroke();
}

static void draw_hud(void) {
    char s[16];
    int speed = (int)(absf(car_v) * 30.0f), cx = width / 2;
    if (cam_mode == CAM_COCKPIT) draw_dashboard();
    noStroke();
    fill(255, 255, 255);
    draw_text("LAP", 6, 6, 2);
    s[0] = (char)('0' + lap);
    s[1] = '/';
    s[2] = (char)('0' + LAPS);
    s[3] = 0;
    draw_text(s, 38, 6, 2);
    format_time(s, race_time);
    draw_text(s, width - 62, 6, 2);
    if (best_lap) {
        fill(255, 230, 120);
        draw_text("BEST", width - 62, 20, 1);
        format_time(s, best_lap);
        draw_text(s, width - 42, 20, 1);
    }
    draw_minimap(6, height - 2 * GH - 6);
    fill(255, 255, 255);
    s[0] = (char)('0' + speed / 100 % 10);
    s[1] = (char)('0' + speed / 10 % 10);
    s[2] = (char)('0' + speed % 10);
    s[3] = 0;
    draw_text(speed >= 100 ? s : speed >= 10 ? s + 1 : s + 2, width - 62, height - 22, 4);
    draw_text("KMH", width - 18, height - 10, 1);
    if (sinking) {
        fill(255, 255, 255);
        draw_text("SPLASH", cx - 46, 70, 4);
    }
    if (scale_shown) { /* el tamaño del coche, en centésimas: CAR 0.68 */
        speed = (int)(car_scale * 100.0f + 0.5f);
        s[0] = (char)('0' + speed / 100);
        s[1] = '.';
        s[2] = (char)('0' + speed / 10 % 10);
        s[3] = (char)('0' + speed % 10);
        s[4] = 0;
        fill(255, 220, 60);
        draw_text("CAR", cx - 34, 36, 2);
        draw_text(s, cx - 2, 36, 2);
    }
    if (speed_shown) { /* la velocidad del tráfico, en décimas: TRAFFIC 0.7 */
        speed = (int)(traffic_speed * 10.0f + 0.5f);
        s[0] = (char)('0' + speed / 10);
        s[1] = '.';
        s[2] = (char)('0' + speed % 10);
        s[3] = 0;
        fill(255, 220, 60);
        draw_text("TRAFFIC", cx - 52, 50, 2);
        draw_text(s, cx + 12, 50, 2);
    }
    if (cam_shown) {
        fill(255, 220, 60);
        draw_centered(cam_names[cam_mode], 150, 2);
    }
    if (autopilot) {
        fill(120, 255, 120);
        draw_text("AUTO", cx - 15, 6, 2);
    }
    if (level_shown) { /* el nombre del nivel, al cargarlo */
        fill(255, 255, 255);
        draw_centered(levels[level]->name, 100, 3);
    }
    if (state == COUNTDOWN) {
        s[0] = (char)('1' + (timer - 1) / 60);
        s[1] = 0;
        fill(255, 220, 60);
        draw_text(s, cx - 9, 60, 6);
    } else if (state == RACE && race_time < 50) {
        fill(80, 255, 80);
        draw_text("GO", cx - 22, 60, 6);
    } else if (state == FINISHED) {
        fill(255, 220, 60);
        draw_text("FINISH", cx - 70, 50, 6);
        fill(255, 255, 255);
        format_time(s, race_time);
        draw_text(s, cx - 40, 90, 3);
        if (frameCount / 30 % 2) draw_text("PRESS SPACE", cx - 44, 120, 2);
    }
}

void setup(void) {
    size(320, 240, P3D);
    perspective(PI / 3.0f, (float)width / height, 5.0f, 2000.0f); /* plano cercano a 5: se ve el suelo junto al coche */
    build_models();
    models_v = pool_v;
    models_i = pool_i;
    models_g = pool_g;
    load_level(0);
}

void draw(void) {
    update();
    if (debug == 2) {
        draw_debug();
        return;
    }
    draw_sky(height / 2 + (int)(mgl_sin(cam_p) / mgl_cos(cam_p) * FOCAL));
    draw_world();
    draw_hud();
}

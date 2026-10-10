/* cube_body.h - el cuerpo del cubo, UNA vez, para la CPU y los dos repartos de GPU
 *
 * Se incluye tres veces desde cube.c con otras definiciones de NAME, ROW_FIRST, ROW_STEP,
 * COL_FIRST y COL_STEP (la misma tabla que rotate_body.h). Cada celda prueba las tres caras en
 * orden con la tabla `cube_faces` (la deja `cube_prepare`, ver cube.inc): si (u, v) cae
 * dentro, lee el texel; si no cae en ninguna, es fondo. Los saltos dependen de la lane, asi
 * que en la GPU divergen: los SSY los pone mini-opt.
 *
 * Los 14 registros preservados son las seis coordenadas, el puntero, la columna y los seis
 * pasos: justo los que usa el bucle de celdas, declarados primero para que lcc se los dé.
 * Lo demas (fila, paso de fila, columna de partida) va a la pila, pero solo se toca una vez
 * por fila. Los limites y el fondo son constantes, y la textura se lee de la tabla al acertar.
 */
#define CUBE_TEXEL(n, u, v) \
    (*(int *)((char *)cube_faces[n].tex + ((((v) - 256) << 1) & 0x3F00) \
              + (((unsigned)((u) - 256) >> 5) & 0xFC)))

void NAME(int *fb) {
    int u0, v0, u1, v1, u2, v2;                     /* la celda: (u, v) de cada cara */
    int *p, x;
    int a0, b0, a1, b1, a2, b2;                     /* cuanto avanza cada una por vuelta */
    int y, rstep, cstart;                           /* por fila */

    cstart = COL_FIRST;
    rstep = ROW_STEP;
    a0 = COL_STEP * cube_faces[0].ux;
    b0 = COL_STEP * cube_faces[0].vx;
    a1 = COL_STEP * cube_faces[1].ux;
    b1 = COL_STEP * cube_faces[1].vx;
    a2 = COL_STEP * cube_faces[2].ux;
    b2 = COL_STEP * cube_faces[2].vx;

    for (y = ROW_FIRST; y < CUBE_ROWS; y += rstep) {
        u0 = cube_faces[0].u00 + y * cube_faces[0].uy + cstart * cube_faces[0].ux;
        v0 = cube_faces[0].v00 + y * cube_faces[0].vy + cstart * cube_faces[0].vx;
        u1 = cube_faces[1].u00 + y * cube_faces[1].uy + cstart * cube_faces[1].ux;
        v1 = cube_faces[1].v00 + y * cube_faces[1].vy + cstart * cube_faces[1].vx;
        u2 = cube_faces[2].u00 + y * cube_faces[2].uy + cstart * cube_faces[2].ux;
        v2 = cube_faces[2].v00 + y * cube_faces[2].vy + cstart * cube_faces[2].vx;
        p = fb + y * (2 * CUBE_COLS) + cstart;      /* dos lineas de pixeles por celda */

        for (x = cstart; x < CUBE_COLS; x += COL_STEP) {
            if ((unsigned)u0 < CUBE_LIM && (unsigned)v0 < CUBE_LIM)
                p[0] = p[CUBE_COLS] = CUBE_TEXEL(0, u0, v0);
            else if ((unsigned)u1 < CUBE_LIM && (unsigned)v1 < CUBE_LIM)
                p[0] = p[CUBE_COLS] = CUBE_TEXEL(1, u1, v1);
            else if ((unsigned)u2 < CUBE_LIM && (unsigned)v2 < CUBE_LIM)
                p[0] = p[CUBE_COLS] = CUBE_TEXEL(2, u2, v2);
            else
                p[0] = p[CUBE_COLS] = CUBE_BG;
            u0 += a0; v0 += b0;
            u1 += a1; v1 += b1;
            u2 += a2; v2 += b2;
            p += COL_STEP;
        }
    }
}

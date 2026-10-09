/* plane_body.h - el cuerpo del plano giratorio, UNA vez, para la CPU y los dos repartos de GPU
 *
 * Se incluye tres veces desde plane.c con otras definiciones de NAME, ROW_FIRST, ROW_STEP,
 * COL_FIRST y COL_STEP (la misma tabla que rotate_body.h y cube_body.h).
 *
 * El plano gira sobre el eje vertical, asi que v no depende de la columna: cada fila lee una sola
 * fila de la textura (`row`) y solo u avanza. El plano esta fuera de la fila si v se sale (toda la fila
 * es fondo) y, dentro, fuera de la columna si u se sale (solo esa celda es fondo).
 *
 * El texel lleva su alfa (plane_tex.py): `t & PLANE_MASK` es el RGB565 "abierto" (rojo y azul abajo,
 * verde arriba, con huecos) y `(t >> 5) & 63` es el alfa de 0 a 32. La mezcla con el fondo de la fila,
 * tambien abierto (`bgx`), es de una multiplicacion para los tres canales:
 *
 *     r = ((texel - fondo) * alfa >> 5) + fondo        (sin signo, y se enmascara al final)
 *
 * Los huecos de 5 y 6 bits absorben el acarreo y el prestamo entre canales. El pixel se cierra
 * (`r | r >> 16`) y se repite en las dos mitades de la palabra: una celda son 2 x 2 pixeles.
 */
#define PLANE_MASK 0x07E0F81Fu

void NAME(int *fb) {
    int u, du, x, y, v, rstep, cstart;
    int *p;
    unsigned *row;
    unsigned t, a, r, bgx, bgw;

    cstart = COL_FIRST;
    rstep = ROW_STEP;
    du = COL_STEP * plane_cfg.ux;

    for (y = ROW_FIRST; y < PLANE_ROWS; y += rstep) {
        v = plane_cfg.v00 + y * plane_cfg.vy;
        bgx = plane_bg[y];
        bgw = ((bgx | (bgx >> 16)) & 0xFFFF) * 65537;
        p = fb + y * (2 * PLANE_COLS) + cstart;     /* dos lineas de pixeles por celda */

        if ((unsigned)v < PLANE_LIM) {
            row = plane_cfg.tex + (v & 0x3F80);     /* (v >> 7) * 128 palabras */
            u = plane_cfg.u00 + cstart * plane_cfg.ux;
            for (x = cstart; x < PLANE_COLS; x += COL_STEP) {
                if ((unsigned)u < PLANE_LIM) {
                    t = row[u >> 7];
                    a = (t >> 5) & 63;
                    r = (((((t & PLANE_MASK) - bgx) * a) >> 5) + bgx) & PLANE_MASK;
                    r = (r | (r >> 16)) & 0xFFFF;
                    p[0] = p[PLANE_COLS] = r * 65537;
                } else
                    p[0] = p[PLANE_COLS] = bgw;
                u += du;
                p += COL_STEP;
            }
        } else {
            for (x = cstart; x < PLANE_COLS; x += COL_STEP) {
                p[0] = p[PLANE_COLS] = bgw;
                p += COL_STEP;
            }
        }
    }
}

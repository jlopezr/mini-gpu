/* rotate_body.h - el cuerpo de la rotacion de textura, UNA vez, para la CPU y los dos repartos de GPU
 *
 * Se incluye tres veces desde rotate_c.c, cada una con otras definiciones de:
 *
 *   NAME, DECLARE_ARGS, BLOCK          como se llama la funcion y de donde sale el bloque de argumentos
 *   ROW_FIRST, ROW_STEP                que filas hace este hilo: la primera y de cuanto en cuanto
 *   COL_FIRST, COL_STEP                que columnas, dentro de cada fila
 *
 * Eso es todo lo que distingue a los tres metodos. El calculo de cada celda es el mismo.
 *
 *                 filas (primera, paso)            columnas (primera, paso)
 *   CPU           0, 1                             0, 1
 *   GPU inocente  mi id de hilo, todos los hilos   0, 1
 *   GPU buena     mi warp, todos los warps         mi lane, las lanes de un warp
 *
 * En la inocente, cada hilo hace una fila entera: las ocho lanes de un warp escriben ocho
 * filas distintas, a 1280 bytes unas de otras. En la buena, un warp hace una fila y sus ocho
 * lanes escriben ocho palabras seguidas.
 *
 * (u, v) en punto fijo Q7. Cada columna suma (dux, dvx); una lane de la buena salta COL_STEP
 * columnas por vuelta, asi que suma COL_STEP veces eso (`du`, `dv`) y empieza ya desplazada.
 *
 * Las variables se declaran de la mas caliente a la mas fria: lcc reparte los 14 registros
 * preservados por orden de declaracion, y lo que no cabe va a la pila (en la GPU, una carga o un
 * almacenamiento por lane, ~20 ciclos). Las del bucle de celdas van primero.
 */
void NAME DECLARE_ARGS {
    int x, u, v, texel, du, dv, cstep;              /* por celda */
    int *p;
    unsigned *tex;
    int y, rstep, cstart;                           /* por fila */
    Block *blk;                                     /* una vez */
    int *fb;
    int u00, v00, dux, dvx;

    blk = BLOCK;
    fb = (int *)blk->p[0];
    u00 = blk->p[1];
    v00 = blk->p[2];
    dux = blk->p[3];
    dvx = blk->p[4];
    tex = (unsigned *)ROT_TEX;
    cstart = COL_FIRST;
    cstep = COL_STEP;
    rstep = ROW_STEP;
    du = cstep * dux;
    dv = cstep * dvx;

    for (y = ROW_FIRST; y < ROT_ROWS; y += rstep) {
        u = u00 - y * dvx + cstart * dux;
        v = v00 + y * dux + cstart * dvx;
        p = fb + y * (2 * ROT_COLS) + cstart;       /* dos lineas de pixeles por celda */

        for (x = cstart; x < ROT_COLS; x += cstep) {
            texel = tex[((u >> 7) & 127) + (v & 0x3F80)];
            p[0] = texel;
            p[ROT_COLS] = texel;
            u += du;
            v += dv;
            p += cstep;
        }
    }
}

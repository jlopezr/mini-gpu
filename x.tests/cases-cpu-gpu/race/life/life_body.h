/* life_body.h - el juego de la vida en C "natural": una vez, para la CPU y los dos repartos de GPU
 *
 * Se incluye tres veces desde life.c con otras definiciones de NAME, DECLARE_ARGS, BLOCK, ROW_FIRST,
 * ROW_STEP, COL_FIRST y COL_STEP (la misma tabla que rotate_body.h). Es una medida, no un port: se
 * escribe como lo escribiria quien no piensa en el compilador (indices de la rejilla con
 * (y + 1) * STRIDE + 8 + x, la regla con un if, un bucle por eje), para ver cuanto se aleja de life.inc
 * sin trucos. Las variables se declaran en el orden en que se usan, sin repartir registros a mano.
 */
#define CELL(grid, x, y) ((grid)[((y) + 1) * LIFE_STRIDE + 8 + (x)])

void NAME DECLARE_ARGS {
    Block *blk = BLOCK;
    int *cur = (int *)blk->p[0], *next = (int *)blk->p[1], *fb = (int *)blk->p[2];
    int color = blk->p[3];
    int x, y, n, alive;

    for (y = ROW_FIRST; y < LIFE_ROWS; y += ROW_STEP) {
        for (x = COL_FIRST; x < LIFE_COLS; x += COL_STEP) {
            n = CELL(cur, x - 1, y - 1) + CELL(cur, x, y - 1) + CELL(cur, x + 1, y - 1)
              + CELL(cur, x - 1, y)                            + CELL(cur, x + 1, y)
              + CELL(cur, x - 1, y + 1) + CELL(cur, x, y + 1) + CELL(cur, x + 1, y + 1);
            if (CELL(cur, x, y))
                alive = n == 2 || n == 3;
            else
                alive = n == 3;
            CELL(next, x, y) = alive;
            fb[y * 2 * LIFE_COLS + x] = alive ? color : 0;
            fb[y * 2 * LIFE_COLS + LIFE_COLS + x] = alive ? color : 0;
        }
    }
}

/* blur_body.h - la difusion de calor en C "natural": una vez, para la CPU y los dos repartos de GPU
 *
 * Como life_body.h: se incluye tres veces desde blur.c, y es una medida, no un port. Cada celda pasa a ser
 * (4c + 2 (N + S + E + W) + (NO + NE + SO + SE)) * 15 >> 8 y se pinta con una paleta del negro al
 * amarillo (rojo = (v << 8) & 0xF800, verde = (v << 3) & 0x07E0), dos pixeles por palabra.
 */
#define CELL(grid, x, y) ((grid)[((y) + 1) * BLUR_STRIDE + 8 + (x)])

void NAME DECLARE_ARGS {
    Block *blk = BLOCK;
    int *cur = (int *)blk->p[0], *next = (int *)blk->p[1], *fb = (int *)blk->p[2];
    int x, y, sum, heat, pixel;

    for (y = ROW_FIRST; y < BLUR_ROWS; y += ROW_STEP) {
        for (x = COL_FIRST; x < BLUR_COLS; x += COL_STEP) {
            sum = 4 * CELL(cur, x, y)
                + 2 * (CELL(cur, x, y - 1) + CELL(cur, x, y + 1) + CELL(cur, x - 1, y) + CELL(cur, x + 1, y))
                + CELL(cur, x - 1, y - 1) + CELL(cur, x + 1, y - 1)
                + CELL(cur, x - 1, y + 1) + CELL(cur, x + 1, y + 1);
            heat = (sum * 15) >> 8;
            CELL(next, x, y) = heat;
            pixel = ((heat << 8) & 0xF800) | ((heat << 3) & 0x07E0);
            pixel |= pixel << 16;
            fb[y * 2 * BLUR_COLS + x] = pixel;
            fb[y * 2 * BLUR_COLS + BLUR_COLS + x] = pixel;
        }
    }
}

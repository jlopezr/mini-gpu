/* Park 10 as extracted from NEWS.FLB: MiniFont v2 metrics checked against
   NewsMaster screenshots (spacing 2, space 5, 11 px line pitch, 120 x 72 dpi). */
#include "minifont.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    assert(argc == 2);
    FILE *f = fopen(argv[1], "rb");
    assert(f);
    assert(fseek(f, 0, SEEK_END) == 0);
    long n = ftell(f);
    assert(n > MF_HEADER_SIZE);
    rewind(f);
    unsigned char *p = malloc((size_t)n);
    assert(p);
    assert(fread(p, 1, (size_t)n, f) == (size_t)n);
    fclose(f);
    MfFont mf;
    assert(mf_open(&mf, p, (size_t)n) == 0);
    assert(mf.font_spacing == 2);
    assert(mf.res_x == 120 && mf.res_y == 72);
    assert(mf.ascent == 8 && mf.descent == 2 && mf.line_gap == 1 && mf.pixel_size == 10);
    MfGlyph g;
    assert(mf_find_glyph(&mf, ' ', &g) == 0 && g.advance_x == 5 && g.width == 0 && g.height == 0);
    assert(mf_find_glyph(&mf, 'O', &g) == 0 && g.advance_x == 12);
    free(p);
    puts("Park 10 metrics OK");
    return 0;
}

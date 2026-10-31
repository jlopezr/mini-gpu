#include "minifont.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    assert(argc == 2);
    FILE *f = fopen(argv[1], "rb");
    assert(f);
    assert(!fseek(f, 0, SEEK_END));
    long n = ftell(f);
    rewind(f);
    unsigned char *mem = malloc((size_t)n);
    assert(mem);
    assert(fread(mem, 1, (size_t)n, f) == (size_t)n);
    fclose(f);
    MfFont font;
    assert(mf_open(&font, mem, (size_t)n) == 0);
    assert(font.glyph_count == 4);
    assert(font.font_spacing == 0);
    assert(font.res_x == 75 && font.res_y == 75); /* SIZE 8 75 75 in test.bdf */
    MfGlyph g;
    assert(mf_find_glyph(&font, 'A', &g) == 0);
    assert(g.width == 5 && g.height == 7 && g.advance_x == 6);
    assert(mf_glyph_pixel(&font, &g, 2, 0) == 1);
    assert(mf_glyph_pixel(&font, &g, 0, 0) == 0);
    assert(mf_find_glyph(&font, 'Z', &g) != 0);
    assert(mf_open(&font, mem, (size_t)n - 1) != 0);
    /* Only v2 headers: other versions, flags, zero resolution or reserved bytes are rejected. */
    static const int bad[][2] = {{4, 1}, {6, 1}, {30, 0}, {32, 0}, {34, 1}, {39, 1}};
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        unsigned char *b = mem + bad[i][0], old0 = b[0], old1 = b[1];
        b[0] = (unsigned char)bad[i][1], b[1] = 0;
        assert(mf_open(&font, mem, (size_t)n) != 0);
        b[0] = old0, b[1] = old1;
    }
    assert(mf_open(&font, mem, (size_t)n) == 0);
    free(mem);
    puts("MiniFont tests passed");
    return 0;
}

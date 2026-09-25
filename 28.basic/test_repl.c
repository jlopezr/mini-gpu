#include "basic.h"

#include <stdio.h>
#include <string.h>

struct ReplHarness {
    const char *input;
    int input_pos;
    char output[2048];
};

static int fake_get_char(void *ctx)
{
    struct ReplHarness *h;
    char c;

    h = (struct ReplHarness *)ctx;
    c = h->input[h->input_pos];
    if (c == 0) {
        return -1;
    }
    ++h->input_pos;
    return (unsigned char)c;
}

static void fake_put_char(char c, void *ctx)
{
    struct ReplHarness *h;
    size_t n;

    h = (struct ReplHarness *)ctx;
    n = strlen(h->output);
    if (n + 1 < sizeof(h->output)) {
        h->output[n] = c;
        h->output[n + 1] = 0;
    }
}

static int contains(const char *text, const char *part)
{
    return strstr(text, part) != 0;
}

int main(void)
{
    mb_u8 memory[1024];
    char line[80];
    MBProgram program;
    MBRuntime runtime;
    MBReplIO io;
    struct ReplHarness h;
    int r;

    h.input =
        "10 A = 1\n"
        "20 PRINT A\n"
        "30 A = A + 1\n"
        "40 IF A <= 3 THEN GOTO 20\n"
        "LISS\bT\n"
        "RUN\n";
    h.input_pos = 0;
    h.output[0] = 0;

    mb_program_init(&program, memory, sizeof(memory));
    mb_runtime_init(&runtime);

    io.get_char = fake_get_char;
    io.put_char = fake_put_char;
    io.ctx = &h;

    r = mb_repl(&program, &runtime, &io, line, sizeof(line), 64);
    if (r != MB_OK) {
        printf("repl failed: %d\n", r);
        return 1;
    }

    if (!contains(h.output, "READY\r\n> ")) {
        printf("missing ready/prompt:\n%s\n", h.output);
        return 1;
    }
    if (!contains(h.output, "10 A = 1\n20 PRINT A\n30 A = A + 1\n40 IF A <= 3 THEN GOTO 20\n")) {
        printf("missing list output:\n%s\n", h.output);
        return 1;
    }
    if (!contains(h.output, "1\r\n2\r\n3\r\n")) {
        printf("missing run output:\n%s\n", h.output);
        return 1;
    }

    printf("ok: repl\n");
    return 0;
}

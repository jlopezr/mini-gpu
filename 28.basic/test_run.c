#include "basic.h"

#include <stdio.h>
#include <string.h>

struct Output {
    char text[128];
};

static void append_char(struct Output *out, char c)
{
    size_t n;

    n = strlen(out->text);
    if (n + 1 < sizeof(out->text)) {
        out->text[n] = c;
        out->text[n + 1] = 0;
    }
}

static void print_int(mb_i32 value, void *ctx)
{
    struct Output *out;
    char buf[32];
    char *p;

    out = (struct Output *)ctx;
    sprintf(buf, "%ld", value);
    p = buf;
    while (*p != 0) {
        append_char(out, *p);
        ++p;
    }
}

static void newline(void *ctx)
{
    append_char((struct Output *)ctx, '\n');
}

static int expect(const char *got, const char *want)
{
    if (strcmp(got, want) != 0) {
        printf("got:\n%s\nwant:\n%s\n", got, want);
        return 1;
    }
    return 0;
}

int main(void)
{
    mb_u8 memory[512];
    MBProgram program;
    MBRuntime runtime;
    struct Output output;
    MBIO io;
    int r;

    mb_program_init(&program, memory, sizeof(memory));
    mb_runtime_init(&runtime);

    if (mb_program_store_statement(&program, 10, "LET A = 1") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 15, "REM count to three") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 20, "PRINT A") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 30, "A = A + 1") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 40, "IF A <= 3 THEN GOTO 20") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 45, "END") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 50, "GOTO 999") != MB_OK) return 1;

    output.text[0] = 0;
    io.print_int = print_int;
    io.newline = newline;
    io.ctx = &output;

    r = mb_program_run(&program, &runtime, &io, 32);
    if (r != MB_OK) {
        printf("run failed: %d\n", r);
        return 1;
    }

    if (expect(output.text, "1\n2\n3\n") != 0) return 1;

    mb_program_clear(&program);
    if (mb_program_store_statement(&program, 10, "PRINT 1") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 20, "STOP") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 30, "GOTO 999") != MB_OK) return 1;
    r = mb_program_run(&program, &runtime, &io, 64);
    if (r != MB_OK) {
        printf("stop run failed: %d\n", r);
        return 1;
    }

    mb_program_clear(&program);
    mb_runtime_init(&runtime);
    output.text[0] = 0;
    if (mb_program_store_statement(&program, 10, "A = 7") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 20, "GOSUB 100") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 30, "PRINT A") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 40, "END") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 100, "A = A + 1") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 110, "RETURN") != MB_OK) return 1;
    r = mb_program_run(&program, &runtime, &io, 64);
    if (r != MB_OK) {
        printf("gosub run failed: %d\n", r);
        return 1;
    }
    if (expect(output.text, "8\n") != 0) return 1;

    mb_program_clear(&program);
    mb_runtime_init(&runtime);
    if (mb_program_store_statement(&program, 10, "RETURN") != MB_OK) return 1;
    r = mb_program_run(&program, &runtime, &io, 64);
    if (r != MB_ERR_RETURN_WITHOUT_GOSUB) {
        printf("expected return without gosub, got %d\n", r);
        return 1;
    }

    mb_program_clear(&program);
    mb_runtime_init(&runtime);
    output.text[0] = 0;
    if (mb_program_store_statement(&program, 10, "A = 0") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 20, "IF A = 0 THEN PRINT 10 ELSE PRINT 20") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 30, "IF A <> 0 THEN PRINT 30 ELSE A = 5") != MB_OK) return 1;
    if (mb_program_store_statement(&program, 40, "PRINT A") != MB_OK) return 1;
    r = mb_program_run(&program, &runtime, &io, 64);
    if (r != MB_OK) {
        printf("if stmt run failed: %d\n", r);
        return 1;
    }
    if (expect(output.text, "10\n5\n") != 0) return 1;

    mb_program_clear(&program);
    if (mb_program_store_statement(&program, 10, "GOTO 999") != MB_OK) return 1;
    r = mb_program_run(&program, &runtime, &io, 64);
    if (r != MB_ERR_NO_SUCH_LINE) {
        printf("expected missing line, got %d\n", r);
        return 1;
    }

    printf("ok: statement compile/run\n");
    return 0;
}

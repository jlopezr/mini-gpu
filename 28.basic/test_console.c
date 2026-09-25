#include "basic.h"

#include <stdio.h>
#include <string.h>

struct Output {
    char text[512];
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

static void put_char(char c, void *ctx)
{
    append_char((struct Output *)ctx, c);
}

static void print_int(mb_i32 value, void *ctx)
{
    char buf[32];
    char *p;

    sprintf(buf, "%ld", value);
    p = buf;
    while (*p != 0) {
        append_char((struct Output *)ctx, *p);
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

static int process(MBProgram *program,
                   MBRuntime *runtime,
                   const char *line,
                   const MBIO *run_io,
                   const MBConsoleIO *console_io)
{
    int r;

    r = mb_console_process_line(program, runtime, line, run_io, console_io, 64);
    if (r != MB_OK) {
        printf("line '%s' failed: %d\n", line, r);
        return 1;
    }
    return 0;
}

int main(void)
{
    mb_u8 memory[1024];
    MBProgram program;
    MBRuntime runtime;
    struct Output output;
    MBIO run_io;
    MBConsoleIO console_io;

    mb_program_init(&program, memory, sizeof(memory));
    mb_runtime_init(&runtime);
    output.text[0] = 0;

    run_io.print_int = print_int;
    run_io.newline = newline;
    run_io.ctx = &output;
    console_io.put_char = put_char;
    console_io.ctx = &output;

    if (process(&program, &runtime, "20 PRINT A", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "10 A = 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "15 REM count to three", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 A = A + 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "40 IF A <= 3 THEN GOTO 20", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "50 END", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "60 PRINT 999", &run_io, &console_io)) return 1;

    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 A = 1\n"
               "15 REM count to three\n"
               "20 PRINT A\n"
               "30 A = A + 1\n"
               "40 IF A <= 3 THEN GOTO 20\n"
               "50 END\n"
               "60 PRINT 999\n") != 0) return 1;

    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "1\n2\n3\n") != 0) return 1;

    output.text[0] = 0;
    if (process(&program, &runtime, "20", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 A = 1\n"
               "15 REM count to three\n"
               "30 A = A + 1\n"
               "40 IF A <= 3 THEN GOTO 20\n"
               "50 END\n"
               "60 PRINT 999\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text, "") != 0) return 1;

    output.text[0] = 0;
    if (process(&program, &runtime, "PRINT 2 + 3 * 4", &run_io, &console_io)) return 1;
    if (expect(output.text, "14\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "10 counter = 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "20 LIMIT = 3", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 PRINT counter", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "40 counter = counter + 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "50 IF counter <= LIMIT THEN GOTO 30", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "60 END", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 COUNTER = 1\n"
               "20 LIMIT = 3\n"
               "30 PRINT COUNTER\n"
               "40 COUNTER = COUNTER + 1\n"
               "50 IF COUNTER <= LIMIT THEN GOTO 30\n"
               "60 END\n") != 0) return 1;

    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "1\n2\n3\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "10 A = 7", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "20 GOSUB 100", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 PRINT A", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "40 END", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "100 A = A + 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "110 RETURN", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 A = 7\n"
               "20 GOSUB 100\n"
               "30 PRINT A\n"
               "40 END\n"
               "100 A = A + 1\n"
               "110 RETURN\n") != 0) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "8\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "10 A = 0", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "20 IF A = 0 THEN PRINT 10 ELSE PRINT 20", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 IF A <> 0 THEN PRINT 30 ELSE A = 5", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "40 PRINT A", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 A = 0\n"
               "20 IF A = 0 THEN PRINT 10 ELSE PRINT 20\n"
               "30 IF A <> 0 THEN PRINT 30 ELSE A = 5\n"
               "40 PRINT A\n") != 0) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "10\n5\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "10 A = ABS(-5)", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "20 PRINT MIN(A, 3)", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 PRINT MAX(A, 8)", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 A = ABS(-5)\n"
               "20 PRINT MIN(A, 3)\n"
               "30 PRINT MAX(A, 8)\n") != 0) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "3\n8\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "10 A = 0", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "20 IF A = 0 THEN", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 PRINT 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "40 A = 2", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "50 ELSE", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "60 PRINT 9", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "70 END IF", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "80 PRINT A", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 A = 0\n"
               "20 IF A = 0 THEN\n"
               "30 PRINT 1\n"
               "40 A = 2\n"
               "50 ELSE\n"
               "60 PRINT 9\n"
               "70 END IF\n"
               "80 PRINT A\n") != 0) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "1\n2\n") != 0) return 1;

    output.text[0] = 0;
    if (process(&program, &runtime, "10 A = 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "9\n1\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "10 A = 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "20 WHILE A <= 3", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 PRINT A", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "40 A = A + 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "50 WEND", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "60 END", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 A = 1\n"
               "20 WHILE A <= 3\n"
               "30 PRINT A\n"
               "40 A = A + 1\n"
               "50 WEND\n"
               "60 END\n") != 0) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "1\n2\n3\n") != 0) return 1;

    if (process(&program, &runtime, "NEW", &run_io, &console_io)) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "10 FOR I = 1 TO 3", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "20 PRINT I", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "30 NEXT I", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "40 FOR J = 6 TO 2 STEP -2", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "50 PRINT J", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "60 NEXT", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "70 FOR K = 5 TO 1", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "80 PRINT 99", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "90 NEXT K", &run_io, &console_io)) return 1;
    if (process(&program, &runtime, "LIST", &run_io, &console_io)) return 1;
    if (expect(output.text,
               "10 FOR I = 1 TO 3\n"
               "20 PRINT I\n"
               "30 NEXT I\n"
               "40 FOR J = 6 TO 2 STEP -2\n"
               "50 PRINT J\n"
               "60 NEXT\n"
               "70 FOR K = 5 TO 1\n"
               "80 PRINT 99\n"
               "90 NEXT K\n") != 0) return 1;
    output.text[0] = 0;
    if (process(&program, &runtime, "RUN", &run_io, &console_io)) return 1;
    if (expect(output.text, "1\n2\n3\n6\n4\n2\n") != 0) return 1;

    printf("ok: console line processing\n");
    return 0;
}

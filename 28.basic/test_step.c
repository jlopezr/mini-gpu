#include "basic.h"

#include <stdio.h>
#include <string.h>

static MBProgram program;
static MBRuntime runtime;
static MBIO io;
static mb_u8 memory[4096];
static char output[1024];
static const char *pending_line; /* what read_line delivers next; 0 = not yet */
static int failures;

static void append(const char *s, mb_u16 len)
{
    size_t n;

    n = strlen(output);
    if (n + len + 1 < sizeof(output)) {
        memcpy(output + n, s, len);
        output[n + len] = 0;
    }
}

static void print_int(mb_i32 value, void *ctx)
{
    char buf[32];

    (void)ctx;
    sprintf(buf, "%ld", (long)value);
    append(buf, (mb_u16)strlen(buf));
}

static void print_str(const char *text, mb_u16 len, void *ctx)
{
    (void)ctx;
    append(text, len);
}

static void newline(void *ctx)
{
    (void)ctx;
    append("\n", 1);
}

static int read_line(char *buf, mb_u16 cap, void *ctx)
{
    size_t n;

    (void)ctx;
    if (pending_line == 0) {
        return MB_READ_WAIT;
    }
    n = strlen(pending_line);
    if (n + 1 > cap) {
        return -1;
    }
    memcpy(buf, pending_line, n + 1);
    pending_line = 0;
    return (int)n;
}

static void check(int cond, const char *what)
{
    if (!cond) {
        printf("FAIL: %s\n", what);
        ++failures;
    }
}

static void reset(void)
{
    mb_program_init(&program, memory, sizeof(memory));
    mb_runtime_init(&runtime);
    output[0] = 0;
    pending_line = 0;
}

static void test_slices(void)
{
    MBRun run;
    int r;
    int calls;

    reset();
    check(mb_program_load_text(&program,
                               "10 FOR I = 1 TO 50\n20 S = S + I\n30 NEXT I\n40 PRINT S\n",
                               (mb_u16)strlen("10 FOR I = 1 TO 50\n20 S = S + I\n30 NEXT I\n40 PRINT S\n"),
                               0) == MB_OK, "load loop");
    check(mb_run_begin(&program, &runtime, &run) == MB_OK, "begin");
    calls = 0;
    do {
        r = mb_run_step(&program, &runtime, &run, &io, 10);
        ++calls;
    } while (r == MB_RUNNING && calls < 1000);
    check(r == MB_OK, "slices finish with MB_OK");
    check(calls > 5, "the run was cut in several slices");
    check(strcmp(output, "1275\n") == 0, "slices give the same result");
    check(mb_run_step(&program, &runtime, &run, &io, 10) == MB_OK, "step after the end stays OK");
}

static void test_infinite_can_be_abandoned(void)
{
    MBRun run;
    int i;
    int r;

    reset();
    mb_program_load_text(&program, "10 A = A + 1\n20 GOTO 10\n", 24, 0);
    mb_run_begin(&program, &runtime, &run);
    r = MB_RUNNING;
    for (i = 0; i < 20 && r == MB_RUNNING; ++i) {
        r = mb_run_step(&program, &runtime, &run, &io, 100);
    }
    check(r == MB_RUNNING, "infinite loop keeps returning MB_RUNNING");
    check(runtime.vars[0] > 0, "and makes progress");
}

static void test_input_wait(void)
{
    MBRun run;
    int r;

    reset();
    {
        const char *src = "10 INPUT \"Name: \"; N$\n20 PRINT \"Hi \" + N$\n";
        check(mb_program_load_text(&program, src, (mb_u16)strlen(src), 0) == MB_OK, "load input");
    }
    mb_run_begin(&program, &runtime, &run);
    r = mb_run_step(&program, &runtime, &run, &io, 100);
    check(r == MB_WAITING_INPUT, "INPUT without a line waits");
    check(strcmp(output, "Name: ") == 0, "the prompt is printed once");
    r = mb_run_step(&program, &runtime, &run, &io, 100);
    check(r == MB_WAITING_INPUT, "still waiting");
    check(strcmp(output, "Name: ") == 0, "the prompt is not repeated");
    pending_line = "Ana";
    r = mb_run_step(&program, &runtime, &run, &io, 100);
    check(r == MB_OK, "the line arrives and the run ends");
    check(strcmp(output, "Name: Hi Ana\n") == 0, "INPUT value is used");
}

static void test_input_redo(void)
{
    MBRun run;
    int r;

    reset();
    {
        const char *src = "10 INPUT A\n20 PRINT A\n";
        mb_program_load_text(&program, src, (mb_u16)strlen(src), 0);
    }
    mb_run_begin(&program, &runtime, &run);
    mb_run_step(&program, &runtime, &run, &io, 100);
    pending_line = "xx";
    r = mb_run_step(&program, &runtime, &run, &io, 100);
    check(r == MB_WAITING_INPUT, "a bad number asks again");
    check(strstr(output, "?REDO") != 0, "?REDO is printed");
    pending_line = "42";
    r = mb_run_step(&program, &runtime, &run, &io, 100);
    check(r == MB_OK && strstr(output, "42\n") != 0, "the second try is accepted");
}

static void test_blocking_run_with_wait(void)
{
    reset();
    {
        const char *src = "10 INPUT A\n";
        mb_program_load_text(&program, src, (mb_u16)strlen(src), 0);
    }
    check(mb_program_run(&program, &runtime, &io, 0) == MB_ERR_NO_INPUT,
          "mb_program_run turns a wait into NO INPUT");
}

static void test_error_in_step(void)
{
    MBRun run;
    const char *src = "10 PRINT 1\n20 PRINT 1 / 0\n";

    reset();
    mb_program_load_text(&program, src, (mb_u16)strlen(src), 0);
    mb_run_begin(&program, &runtime, &run);
    check(mb_run_step(&program, &runtime, &run, &io, 100) == MB_ERR_DIV_ZERO, "error is returned by the step");
}

static void test_load_text(void)
{
    mb_u16 err;
    const char *src;
    int r;

    reset();
    src = "10 A = 1\r\n\r\n   20 PRINT A\n30 END";
    check(mb_program_load_text(&program, src, (mb_u16)strlen(src), &err) == MB_OK, "CRLF, blank lines, no final newline");
    check(mb_program_run(&program, &runtime, &io, 0) == MB_OK && strcmp(output, "1\n") == 0, "loaded program runs");

    reset();
    src = "10 A = 1\nPRINT A\n";
    err = 0;
    r = mb_program_load_text(&program, src, (mb_u16)strlen(src), &err);
    check(r == MB_ERR_BAD_LINE && err == 2, "a line without a number is reported with its position");

    reset();
    src = "10 A = 1\n\n20 PRINT (\n";
    err = 0;
    r = mb_program_load_text(&program, src, (mb_u16)strlen(src), &err);
    check(r < 0 && err == 3, "a syntax error is reported with its text line");

    reset();
    src = "10 A = 1\n10\n20 PRINT 7\n";
    mb_program_load_text(&program, src, (mb_u16)strlen(src), 0);
    mb_program_run(&program, &runtime, &io, 0);
    check(strcmp(output, "7\n") == 0, "a bare number deletes the line");
}

int main(void)
{
    io.print_int = print_int;
    io.print_str = print_str;
    io.newline = newline;
    io.read_line = read_line;
    io.ctx = 0;

    test_slices();
    test_infinite_can_be_abandoned();
    test_input_wait();
    test_input_redo();
    test_blocking_run_with_wait();
    test_error_in_step();
    test_load_text();

    if (failures == 0) {
        printf("test_step: OK\n");
        return 0;
    }
    printf("test_step: %d failure(s)\n", failures);
    return 1;
}

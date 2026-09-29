#include "basic.h"

#include <stdio.h>
#include <string.h>

static MBProgram program;
static MBRuntime runtime;
static MBIO run_io;
static MBConsoleIO console_io;
static char output[4096];
static const char *script[512];
static int script_count;
static int script_pos;
static int failures;

static void append_char(char c)
{
    size_t n;

    n = strlen(output);
    if (n + 1 < sizeof(output)) {
        output[n] = c;
        output[n + 1] = 0;
    }
}

static void put_char(char c, void *ctx)
{
    (void)ctx;
    append_char(c);
}

static void print_int(mb_i32 value, void *ctx)
{
    char buf[32];
    char *p;

    (void)ctx;
    sprintf(buf, "%ld", (long)value);
    for (p = buf; *p != 0; ++p) {
        append_char(*p);
    }
}

static void print_str(const char *text, mb_u16 len, void *ctx)
{
    mb_u16 i;

    (void)ctx;
    for (i = 0; i < len; ++i) {
        append_char(text[i]);
    }
}

static void newline(void *ctx)
{
    (void)ctx;
    append_char('\n');
}

static int read_line(char *buf, mb_u16 cap, void *ctx)
{
    size_t n;

    (void)ctx;
    if (script_pos >= script_count) {
        return -1;
    }
    n = strlen(script[script_pos]);
    if (n + 1 > cap) {
        n = cap - 1u;
    }
    memcpy(buf, script[script_pos], n);
    buf[n] = 0;
    ++script_pos;
    return (int)n;
}

static void reset(void)
{
    static mb_u8 memory[2048];

    mb_program_init(&program, memory, sizeof(memory));
    mb_runtime_init(&runtime);
    output[0] = 0;
    script_count = 0;
    script_pos = 0;
}

static void feed(const char *text)
{
    script[script_count] = text;
    ++script_count;
}

static int line(const char *text)
{
    return mb_console_process_line(&program, &runtime, text, &run_io, &console_io, 5000);
}

static void want_rc(const char *text, int want)
{
    int got;

    got = line(text);
    if (got != want) {
        printf("line '%s': got rc %d, want %d\n", text, got, want);
        ++failures;
    }
}

static void ok(const char *text)
{
    want_rc(text, MB_OK);
}

static void want_out(const char *what, const char *want)
{
    if (strcmp(output, want) != 0) {
        printf("%s\ngot:\n%s\nwant:\n%s\n", what, output, want);
        ++failures;
    }
    output[0] = 0;
}

static void test_immediate(void)
{
    reset();
    feed("hello world");
    ok("INPUT A$");
    ok("PRINT A$");
    want_out("string input, default prompt", "? hello world\n");

    feed("Ada");
    ok("INPUT \"Name: \"; N$");
    ok("PRINT \"Hi \" + N$ + \"!\"");
    want_out("string input with prompt", "Name: Hi Ada!\n");

    feed("");
    ok("INPUT E$");
    ok("PRINT LEN(E$)");
    want_out("empty line", "? 0\n");

    feed("42");
    ok("INPUT N");
    ok("PRINT N + 1");
    want_out("integer input", "? 43\n");

    feed("  -7  ");
    ok("INPUT \"n? \"; M");
    ok("PRINT M");
    want_out("integer input with spaces and sign", "n? -7\n");

    feed("abc");
    feed("");
    feed("12x");
    feed("1 2");
    feed("-");
    feed("9");
    ok("INPUT K");
    ok("PRINT K");
    want_out("integer input retries",
             "? ?REDO\n? ?REDO\n? ?REDO\n? ?REDO\n? ?REDO\n? 9\n");
}

static void test_errors(void)
{
    reset();
    want_rc("INPUT", MB_ERR_SYNTAX);
    want_rc("INPUT 5", MB_ERR_SYNTAX);
    want_rc("INPUT A, B", MB_ERR_SYNTAX);
    want_rc("INPUT \"x\" A", MB_ERR_SYNTAX);
    want_rc("INPUT \"x\"; ", MB_ERR_SYNTAX);
    want_rc("INPUT \"unterminated; A", MB_ERR_SYNTAX);
    want_rc("INPUT \"x\"; A B", MB_ERR_SYNTAX);

    want_rc("INPUT A", MB_ERR_NO_INPUT);
    want_rc("INPUT B$", MB_ERR_NO_INPUT);
    want_out("prompts printed before the failure", "? ? ");

    feed("1");
    run_io.read_line = 0;
    want_rc("INPUT A", MB_ERR_NO_INPUT);
    run_io.read_line = read_line;
    want_out("no reader", "");
}

static void test_program(void)
{
    reset();
    ok("10 INPUT \"X? \"; A");
    ok("20 INPUT NAME$");
    ok("30 PRINT NAME$ + \" \" + STR$(A * 2)");
    ok("LIST");
    want_out("list", "10 INPUT \"X? \"; A\n20 INPUT NAME$\n30 PRINT NAME$ + \" \" + STR$(A * 2)\n");
    feed("21");
    feed("Bob");
    ok("RUN");
    want_out("run", "X? ? Bob 42\n");

    ok("NEW");
    ok("10 WHILE 1");
    ok("20 INPUT \"> \"; L$");
    ok("30 IF L$ = \"quit\" THEN END");
    ok("40 PRINT UCASE$(L$)");
    ok("50 WEND");
    feed("one");
    feed("two");
    feed("quit");
    ok("RUN");
    want_out("loop until quit", "> ONE\n> TWO\n> ");

    ok("NEW");
    ok("10 INPUT A$");
    ok("20 PRINT A$");
    feed("x");
    ok("RUN");
    want_out("consumed", "? x\n");
    want_rc("RUN", MB_ERR_NO_INPUT);
}

static void test_heap(void)
{
    int i;

    reset();
    ok("B$ = \"keep\"");
    for (i = 0; i < 300; ++i) {
        feed("0123456789012345678901234567890123456789");
    }
    for (i = 0; i < 300; ++i) {
        ok("INPUT A$");
    }
    output[0] = 0;
    ok("PRINT A$ + B$");
    want_out("300 inputs reuse the heap", "0123456789012345678901234567890123456789keep\n");
}

int main(void)
{
    run_io.print_int = print_int;
    run_io.print_str = print_str;
    run_io.newline = newline;
    run_io.read_line = read_line;
    run_io.ctx = 0;
    console_io.put_char = put_char;
    console_io.ctx = 0;

    test_immediate();
    test_errors();
    test_program();
    test_heap();

    if (failures != 0) {
        printf("FAILED: %d checks\n", failures);
        return 1;
    }
    printf("ok: input\n");
    return 0;
}

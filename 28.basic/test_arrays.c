#include "basic.h"

#include <stdio.h>
#include <string.h>

static MBProgram program;
static MBRuntime runtime;
static MBIO run_io;
static MBConsoleIO console_io;
static char output[4096];
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

static void reset(void)
{
    static mb_u8 memory[2048];

    mb_program_init(&program, memory, sizeof(memory));
    mb_runtime_init(&runtime);
    output[0] = 0;
}

static int line(const char *text)
{
    return mb_console_process_line(&program, &runtime, text, &run_io, &console_io, 20000);
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

/* FRE() must report exactly this many bytes free. */
static void want_free(const char *what, long want)
{
    char expected[32];

    sprintf(expected, "%ld\n", want);
    output[0] = 0;
    ok("PRINT FRE()");
    want_out(what, expected);
}

static void test_integer_arrays(void)
{
    reset();
    ok("DIM A(10)");
    ok("PRINT A(0); \",\"; A(10); \",\"; A(5)");
    ok("A(0) = 5");
    ok("A(10) = 7");
    ok("I = 2");
    ok("A(I + 1) = A(0) * 2");
    ok("PRINT A(0); \",\"; A(10); \",\"; A(3); \",\"; A(2)");
    want_out("basic elements", "0,0,0\n5,7,10,0\n");

    ok("A(1) = 3");
    ok("A(2) = 1");
    ok("PRINT A(A(2))");
    ok("PRINT A(LEN(\"ab\")) + A(MAX(1, 2))");
    ok("IF A(1) = 3 THEN PRINT \"three\" ELSE PRINT \"no\"");
    ok("PRINT A(1) + A(2) * A(3)");
    want_out("index expressions", "3\n2\nthree\n13\n");

    ok("DIM B(0)");
    ok("B(0) = -4");
    ok("PRINT B(0)");
    want_out("one element array", "-4\n");

    ok("A(10) = -2147483647");
    ok("PRINT A(10)");
    want_out("wide values", "-2147483647\n");
}

static void test_string_arrays(void)
{
    reset();
    ok("DIM N$(3)");
    ok("N$(1) = \"uno\"");
    ok("N$(2) = N$(1) + \"!\"");
    ok("N$(3) = LEFT$(N$(2), 2) + \"X\"");
    ok("PRINT N$(1); \" \"; N$(2); \" \"; N$(3); \"|\"; N$(0); \"|\"; LEN(N$(0))");
    want_out("string elements", "uno uno! unX||0\n");

    ok("N$(0) = N$(1)");
    ok("N$(1) = \"\"");
    ok("PRINT N$(0); \"/\"; N$(1); \"/\"");
    want_out("copies and empties", "uno//\n");

    ok("IF N$(0) = \"uno\" THEN PRINT \"same\" ELSE PRINT \"diff\"");
    ok("PRINT N$(3) = \"unX\"");
    want_out("comparison of elements", "same\n-1\n");

    ok("I = 2");
    ok("N$(I) = STR$(I) + N$(I)");
    ok("PRINT N$(2)");
    want_out("index variable", "2uno!\n");
}

static void test_errors(void)
{
    reset();
    ok("DIM A(3)");
    ok("DIM N$(2)");
    want_rc("PRINT A(4)", MB_ERR_SUBSCRIPT);
    want_rc("PRINT A(-1)", MB_ERR_SUBSCRIPT);
    want_rc("A(4) = 1", MB_ERR_SUBSCRIPT);
    want_rc("A(-1) = 1", MB_ERR_SUBSCRIPT);
    want_rc("N$(3) = \"x\"", MB_ERR_SUBSCRIPT);
    want_rc("PRINT N$(3)", MB_ERR_SUBSCRIPT);
    want_rc("PRINT B(1)", MB_ERR_NO_ARRAY);
    want_rc("B(1) = 1", MB_ERR_NO_ARRAY);
    want_rc("PRINT FOO(1)", MB_ERR_NO_ARRAY);
    want_rc("ERASE B", MB_ERR_NO_ARRAY);
    want_rc("DIM A(5)", MB_ERR_ARRAY_EXISTS);
    want_rc("DIM A(2)", MB_ERR_ARRAY_EXISTS);
    want_rc("DIM C(-1)", MB_ERR_BAD_ARG);
    want_rc("DIM C(100000)", MB_ERR_FULL);

    want_rc("N$(1) = 5", MB_ERR_TYPE_MISMATCH);
    want_rc("A(1) = \"x\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT A(\"x\")", MB_ERR_TYPE_MISMATCH);
    want_rc("A(\"x\") = 1", MB_ERR_TYPE_MISMATCH);
    want_rc("DIM C(\"x\")", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT A(1) + N$(1)", MB_ERR_TYPE_MISMATCH);

    want_rc("DIM", MB_ERR_SYNTAX);
    want_rc("DIM C", MB_ERR_SYNTAX);
    want_rc("DIM C()", MB_ERR_SYNTAX);
    want_rc("DIM C(3) x", MB_ERR_SYNTAX);
    want_rc("DIM C(1, 2)", MB_ERR_SYNTAX);
    want_rc("DIM 5(3)", MB_ERR_SYNTAX);
    want_rc("DIM C(3", MB_ERR_SYNTAX);
    want_rc("ERASE", MB_ERR_SYNTAX);
    want_rc("ERASE A B", MB_ERR_SYNTAX);
    want_rc("A(1) =", MB_ERR_SYNTAX);
    want_rc("A(1 = 2", MB_ERR_SYNTAX);
    want_rc("A() = 1", MB_ERR_SYNTAX);
    want_rc("PRINT A(1", MB_ERR_SYNTAX);
    want_rc("INPUT A(1)", MB_ERR_SYNTAX);
    want_rc("FOR A(1) = 1 TO 2", MB_ERR_SYNTAX);
    want_out("no output on errors", "");
}

static void test_memory(void)
{
    long free0;

    reset();
    free0 = MB_HEAP_SIZE;
    want_free("empty heap", free0);

    ok("DIM A(99)");
    want_free("after DIM A(99)", free0 - 400);
    ok("ERASE A");
    want_free("after ERASE", free0);

    ok("DIM A(2)");
    ok("DIM B(3)");
    ok("DIM C(4)");
    want_free("three arrays", free0 - 12 - 16 - 20);
    ok("A(0) = 10");
    ok("A(1) = 11");
    ok("A(2) = 12");
    ok("B(0) = 20");
    ok("B(3) = 23");
    ok("C(0) = 30");
    ok("C(4) = 34");

    ok("ERASE B");
    want_free("after erasing the middle one", free0 - 12 - 20);
    ok("PRINT A(0); A(1); A(2); \",\"; C(0); \",\"; C(4)");
    want_out("the others survive the compaction", "101112,30,34\n");
    want_rc("PRINT B(0)", MB_ERR_NO_ARRAY);

    ok("DIM D(3)");
    want_free("the freed room is reused", free0 - 12 - 20 - 16);
    ok("PRINT D(0); D(3)");
    want_out("a new array is zeroed", "00\n");
    ok("D(0) = 40");
    ok("D(3) = 43");
    ok("PRINT A(2); \",\"; C(4); \",\"; D(0); D(3)");
    want_out("all three", "12,34,4043\n");

    ok("ERASE A");
    ok("ERASE C");
    want_free("two erased", free0 - 16);
    ok("PRINT D(0); D(3)");
    want_out("the last one moved", "4043\n");
    ok("ERASE D");
    want_free("everything back", free0);

    ok("DIM X(400)");
    want_free("big array", free0 - 1604);
    want_rc("DIM Z(200)", MB_ERR_FULL);
    want_rc("DIM Y(1000)", MB_ERR_FULL);
    want_free("failed DIMs change nothing", free0 - 1604);
    want_rc("PRINT SPACE$(500)", MB_ERR_STRING_TOO_LONG);
    ok("ERASE X");
    ok("DIM Z(200)");
    want_free("room again after ERASE", free0 - 804);
    ok("PRINT LEN(SPACE$(500))");
    want_out("strings fit again", "500\n");
}

static void test_dim_again(void)
{
    reset();
    ok("DIM A(3)");
    ok("A(1) = 5");
    ok("DIM A(3)");
    ok("PRINT A(1)");
    want_out("DIM with the same size clears", "0\n");

    ok("A(1) = 5");
    ok("REDIM A(3)");
    ok("PRINT A(1)");
    want_out("REDIM with the same size clears", "0\n");

    ok("A(1) = 5");
    ok("REDIM PRESERVE A(3)");
    ok("PRINT A(1)");
    want_out("PRESERVE with the same size keeps", "5\n");

    ok("10 DIM P(2)");
    ok("20 P(1) = P(1) + 1");
    ok("30 PRINT P(1)");
    ok("RUN");
    ok("RUN");
    want_out("a program can be run again", "1\n1\n");
}

static void test_redim(void)
{
    long free0;

    reset();
    free0 = MB_HEAP_SIZE;
    ok("DIM A(2)");
    ok("A(0) = 1");
    ok("A(1) = 2");
    ok("A(2) = 3");

    ok("REDIM PRESERVE A(4)");
    ok("PRINT A(0); A(1); A(2); A(3); A(4)");
    want_out("grow keeping", "12300\n");
    want_free("grown", free0 - 20);

    ok("REDIM PRESERVE A(1)");
    ok("PRINT A(0); A(1)");
    want_out("shrink keeping", "12\n");
    want_rc("PRINT A(2)", MB_ERR_SUBSCRIPT);
    want_free("shrunk", free0 - 8);

    ok("REDIM A(3)");
    ok("PRINT A(0); A(1); A(3)");
    want_out("REDIM without PRESERVE clears", "000\n");
    want_free("resized", free0 - 16);

    ok("REDIM B(2)");
    ok("B(2) = 9");
    ok("PRINT B(2)");
    want_out("REDIM of an array that does not exist", "9\n");
    want_free("created", free0 - 16 - 12);

    ok("DIM C(1)");
    ok("C(0) = 77");
    ok("REDIM PRESERVE A(30)");
    ok("PRINT C(0); \",\"; B(2); \",\"; A(30)");
    want_out("growing with other arrays around", "77,9,0\n");
    ok("ERASE A");
    ok("PRINT C(0); \",\"; B(2)");
    want_out("and erasing it afterwards", "77,9\n");
    want_free("all back to the others", free0 - 12 - 8);

    ok("DIM X(300)");
    want_rc("REDIM PRESERVE X(400)", MB_ERR_FULL);
    ok("REDIM PRESERVE X(200)");
    ok("REDIM X(400)");
    want_free("REDIM without PRESERVE reuses its own block", free0 - 12 - 8 - 1604);

    reset();
    ok("DIM S$(2)");
    ok("S$(0) = \"a\"");
    ok("S$(2) = \"ccc\"");
    ok("REDIM PRESERVE S$(5)");
    ok("PRINT S$(0); S$(2); \"|\"; S$(5); \"|\"");
    want_out("strings survive a REDIM PRESERVE", "accc||\n");
    ok("REDIM PRESERVE S$(1)");
    ok("PRINT S$(0); \"|\"; LEN(S$(1))");
    want_out("and a shrink", "a|0\n");
}

static void test_string_collection(void)
{
    reset();
    ok("DIM S$(2)");
    ok("S$(0) = \"keep-me\"");
    ok("10 K$ = \"abcdefghij\"");
    ok("20 FOR I = 1 TO 300");
    ok("30 S$(1) = K$ + K$ + K$ + K$ + K$ + K$ + K$ + K$");
    ok("40 S$(2) = K$ + STR$(I)");
    ok("50 NEXT I");
    ok("RUN");
    ok("PRINT S$(0); \"|\"; S$(2); \"|\"; LEN(S$(1))");
    want_out("elements are roots of the collection", "keep-me|abcdefghij300|80\n");

    ok("ERASE S$");
    ok("PRINT LEN(SPACE$(1000))");
    want_out("dead strings of an erased array are reclaimed", "1000\n");

    reset();
    ok("DIM S$(1)");
    ok("S$(0) = \"x\"");
    ok("PRINT FRE()");
    output[0] = 0;
    ok("S$(0) = \"yy\"");
    want_free("an overwritten element counts as free again", MB_HEAP_SIZE - 8 - 3 + 1);
}

static void test_fre(void)
{
    reset();
    want_free("FRE()", MB_HEAP_SIZE);
    ok("PRINT FRE(0); \",\"; FRE(99)");
    want_out("FRE(x)", "2048,2048\n");

    ok("A$ = \"0123456789\"");
    want_free("after a string", MB_HEAP_SIZE - 10);
    ok("A$ = \"y\"");
    want_free("dead strings count as free", MB_HEAP_SIZE - 11 + 10);
    ok("PRINT FRE() - FRE()");
    want_out("usable in expressions", "0\n");
    ok("PRINT LEN(SPACE$(100)) + FRE()");
    want_out("temporaries in flight are not free", "2047\n");

    want_rc("PRINT FRE(\"x\")", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT FRE(1, 2)", MB_ERR_BAD_BUILTIN);
}

static void test_list(void)
{
    reset();
    ok("10 DIM A(N + 1)");
    ok("20 A(I) = A(I - 1) * 2");
    ok("30 REDIM PRESERVE A(20)");
    ok("40 REDIM A(5)");
    ok("50 ERASE A");
    ok("60 N$(1) = \"x\"");
    ok("70 PRINT A(1); N$(2); A(A(2) + 1)");
    ok("80 DIM N$(3)");
    ok("LIST");
    want_out("list",
             "10 DIM A(N + 1)\n"
             "20 A(I) = A(I - 1) * 2\n"
             "30 REDIM PRESERVE A(20)\n"
             "40 REDIM A(5)\n"
             "50 ERASE A\n"
             "60 N$(1) = \"x\"\n"
             "70 PRINT A(1); N$(2); A(A(2) + 1)\n"
             "80 DIM N$(3)\n");

    ok("NEW");
    ok("10 DIM A(4)");
    ok("20 FOR I = 0 TO 4");
    ok("30 A(I) = I * I");
    ok("40 NEXT I");
    ok("50 S = 0");
    ok("60 FOR I = 0 TO 4");
    ok("70 S = S + A(I)");
    ok("80 NEXT I");
    ok("90 PRINT \"sum=\"; S; \" last=\"; A(4)");
    ok("RUN");
    want_out("a program with arrays", "sum=30 last=16\n");
}

int main(void)
{
    run_io.print_int = print_int;
    run_io.print_str = print_str;
    run_io.newline = newline;
    run_io.read_line = 0;
    run_io.ctx = 0;
    console_io.put_char = put_char;
    console_io.ctx = 0;

    test_integer_arrays();
    test_string_arrays();
    test_errors();
    test_memory();
    test_dim_again();
    test_redim();
    test_string_collection();
    test_fre();
    test_list();

    if (failures != 0) {
        printf("FAILED: %d checks\n", failures);
        return 1;
    }
    printf("ok: arrays\n");
    return 0;
}

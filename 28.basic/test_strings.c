#include "basic.h"

#include <stdio.h>
#include <string.h>

struct Output {
    char text[2048];
};

static MBProgram program;
static MBRuntime runtime;
static MBIO run_io;
static MBConsoleIO console_io;
static struct Output output;
static int failures;

static void append_char(char c)
{
    size_t n;

    n = strlen(output.text);
    if (n + 1 < sizeof(output.text)) {
        output.text[n] = c;
        output.text[n + 1] = 0;
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
    output.text[0] = 0;
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

static void want_out(const char *what, const char *want)
{
    if (strcmp(output.text, want) != 0) {
        printf("%s\ngot:\n%s\nwant:\n%s\n", what, output.text, want);
        ++failures;
    }
    output.text[0] = 0;
}

static void ok(const char *text)
{
    want_rc(text, MB_OK);
}

static void test_immediate(void)
{
    reset();
    ok("PRINT \"HELLO\"");
    want_out("literal", "HELLO\n");

    ok("A$ = \"HI\"");
    ok("B$ = A$ + \" THERE\" + \"!\"");
    ok("PRINT B$");
    ok("PRINT A$");
    want_out("concat", "HI THERE!\nHI\n");

    ok("E$ = \"\"");
    ok("PRINT E$");
    ok("PRINT E$ + \"x\"");
    ok("PRINT F$");
    want_out("empty", "\nx\n\n");

    ok("LET C$ = \"lower Case\"");
    ok("PRINT C$");
    want_out("case kept in literal", "lower Case\n");

    ok("PRINT \"a, b: (c) + d = e\"");
    want_out("punctuation in literal", "a, b: (c) + d = e\n");
}

static void test_compare(void)
{
    reset();
    ok("A$ = \"HI\"");
    ok("PRINT A$ = \"HI\"");
    ok("PRINT A$ = \"HO\"");
    ok("PRINT A$ <> \"HO\"");
    ok("PRINT A$ <> \"HI\"");
    ok("PRINT \"\" = E$");
    ok("PRINT A$ + \"!\" = \"HI!\"");
    want_out("comparison", "-1\n0\n-1\n0\n-1\n-1\n");

    ok("IF A$ = \"HI\" THEN PRINT \"yes\" ELSE PRINT \"no\"");
    ok("IF A$ = \"XX\" THEN PRINT \"yes\" ELSE PRINT \"no\"");
    want_out("if/else with strings", "yes\nno\n");

    ok("PRINT \"IF X THEN Y ELSE Z TO STEP\"");
    ok("IF A$ = \"THEN\" THEN PRINT \"a\" ELSE PRINT \"ELSE\"");
    ok("IF A$ = \"HI\" THEN PRINT \"THEN ELSE\"");
    want_out("keywords inside literals", "IF X THEN Y ELSE Z TO STEP\nELSE\nTHEN ELSE\n");
}

static void test_errors(void)
{
    reset();
    want_rc("A$ = 5", MB_ERR_TYPE_MISMATCH);
    want_rc("A = \"x\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" + 1", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 1 + \"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" - \"b\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" * 2", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT -\"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" = 1", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT ABS(\"a\")", MB_ERR_TYPE_MISMATCH);
    want_rc("IF \"a\" THEN PRINT 1", MB_ERR_TYPE_MISMATCH);
    want_rc("FOR A$ = 1 TO 2", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"unterminated", MB_ERR_SYNTAX);
    want_rc("A$ = ", MB_ERR_SYNTAX);
    want_out("no output on errors", "");
}

static void test_list_and_run(void)
{
    reset();
    ok("10 A$ = \"count\"");
    ok("20 I = 1");
    ok("30 WHILE I <= 3");
    ok("40 PRINT A$ + \" \" + \"#\"");
    ok("50 I = I + 1");
    ok("60 WEND");
    ok("70 IF A$ = \"count\" THEN PRINT \"done\" ELSE PRINT \"?\"");
    ok("LIST");
    want_out("list",
             "10 A$ = \"count\"\n"
             "20 I = 1\n"
             "30 WHILE I <= 3\n"
             "40 PRINT A$ + \" \" + \"#\"\n"
             "50 I = I + 1\n"
             "60 WEND\n"
             "70 IF A$ = \"count\" THEN PRINT \"done\" ELSE PRINT \"?\"\n");
    ok("RUN");
    want_out("run", "count #\ncount #\ncount #\ndone\n");

    ok("NEW");
    ok("10 S$ = \"\"");
    ok("20 WHILE S$ <> \"xxxx\"");
    ok("30 S$ = S$ + \"x\"");
    ok("40 WEND");
    ok("50 PRINT S$");
    ok("RUN");
    want_out("while on string condition", "xxxx\n");
}

static void test_heap_reuse(void)
{
    int i;

    reset();
    ok("A$ = \"alpha\"");
    ok("B$ = \"beta\"");
    ok("10 K$ = \"abcdefghij\"");
    ok("20 FOR I = 1 TO 200");
    ok("30 C$ = K$ + K$ + K$ + K$ + K$ + K$ + K$ + K$");
    ok("40 NEXT I");
    ok("50 PRINT C$");
    ok("RUN");
    want_out("churn keeps the last value",
             "abcdefghijabcdefghijabcdefghijabcdefghijabcdefghijabcdefghijabcdefghijabcdefghij\n");
    ok("PRINT A$ + B$");
    want_out("other variables survive the churn", "alphabeta\n");

    for (i = 0; i < 300; ++i) {
        ok("A$ = \"0123456789\" + \"0123456789\"");
    }
    ok("PRINT A$ + B$");
    want_out("repeated immediate assignment", "01234567890123456789beta\n");

    ok("A$ = A$");
    ok("PRINT A$");
    want_out("self assignment", "01234567890123456789\n");
}

static void test_too_long(void)
{
    reset();
    ok("10 D$ = \"0123456789\"");
    ok("20 FOR I = 1 TO 20");
    ok("30 D$ = D$ + D$");
    ok("40 NEXT I");
    want_rc("RUN", MB_ERR_STRING_TOO_LONG);
    want_out("no output", "");

    ok("PRINT D$ = D$");
    want_out("heap still usable after the error", "-1\n");
}

static void test_builtins(void)
{
    reset();
    ok("A$ = \"HELLO WORLD\"");
    ok("PRINT LEN(A$)");
    ok("PRINT LEN(\"\")");
    ok("PRINT LEN(A$ + \"!!\")");
    want_out("len", "11\n0\n13\n");

    ok("PRINT LEFT$(A$, 5)");
    ok("PRINT RIGHT$(A$, 5)");
    ok("PRINT LEFT$(A$, 99)");
    ok("PRINT RIGHT$(A$, 99)");
    ok("PRINT LEFT$(A$, 0) + \"|\"");
    ok("PRINT RIGHT$(A$, 0) + \"|\"");
    want_out("left/right",
             "HELLO\nWORLD\nHELLO WORLD\nHELLO WORLD\n|\n|\n");

    ok("PRINT MID$(A$, 7)");
    ok("PRINT MID$(A$, 1, 4)");
    ok("PRINT MID$(A$, 5, 3)");
    ok("PRINT MID$(A$, 7, 99)");
    ok("PRINT MID$(A$, 12) + \"|\"");
    ok("PRINT MID$(A$, 3, 0) + \"|\"");
    ok("PRINT MID$(LEFT$(A$, 8), 3, 4)");
    want_out("mid", "WORLD\nHELL\nO W\nWORLD\n|\n|\nLLO \n");

    ok("PRINT ASC(\"A\")");
    ok("PRINT ASC(A$)");
    ok("PRINT CHR$(72) + CHR$(105)");
    ok("PRINT ASC(CHR$(200))");
    want_out("asc/chr", "65\n72\nHi\n200\n");

    ok("PRINT STR$(0)");
    ok("PRINT STR$(123)");
    ok("PRINT STR$(-45) + \"!\"");
    ok("PRINT STR$(2 * 21) + \"?\"");
    want_out("str$", "0\n123\n-45!\n42?\n");

    ok("PRINT VAL(\"123\")");
    ok("PRINT VAL(\"  -7abc\")");
    ok("PRINT VAL(\"+9\") + 1");
    ok("PRINT VAL(\"abc\")");
    ok("PRINT VAL(\"\")");
    ok("PRINT VAL(STR$(-321)) + 1");
    want_out("val", "123\n-7\n10\n0\n0\n-320\n");

    ok("B$ = MID$(A$, 7) + \" / \" + LEFT$(A$, 5)");
    ok("PRINT B$");
    ok("B$ = RIGHT$(B$, 5)");
    ok("PRINT B$");
    ok("PRINT LEFT$(A$, 5) = \"HELLO\"");
    ok("IF MID$(A$, 7, 1) = \"W\" THEN PRINT \"w\" ELSE PRINT \"-\"");
    want_out("builtins in expressions and assignments",
             "WORLD / HELLO\nHELLO\n-1\nw\n");

    ok("PRINT INSTR(A$, \"WORLD\")");
    ok("PRINT INSTR(A$, \"O\")");
    ok("PRINT INSTR(A$, \"XYZ\")");
    ok("PRINT INSTR(A$, \"\")");
    ok("PRINT INSTR(A$, \"HELLO WORLD!\")");
    ok("PRINT INSTR(6, A$, \"O\")");
    ok("PRINT INSTR(9, A$, \"O\")");
    ok("PRINT INSTR(12, A$, \"\")");
    ok("PRINT INSTR(13, A$, \"\")");
    ok("PRINT INSTR(\"\", \"a\")");
    ok("PRINT INSTR(LEFT$(A$, 5), \"L\") + INSTR(RIGHT$(A$, 5), \"L\")");
    want_out("instr", "7\n5\n0\n1\n0\n8\n0\n12\n0\n0\n7\n");

    ok("PRINT UCASE$(\"Hello, World 1\")");
    ok("PRINT LCASE$(\"Hello, World 1\")");
    ok("PRINT UCASE$(\"\") + LCASE$(\"\") + \"|\"");
    ok("PRINT LCASE$(A$) + \"!\"");
    ok("PRINT A$");
    want_out("case", "HELLO, WORLD 1\nhello, world 1\n|\nhello world!\nHELLO WORLD\n");

    ok("PRINT \"[\" + SPACE$(3) + \"]\"");
    ok("PRINT \"[\" + SPACE$(0) + \"]\"");
    ok("PRINT LEN(SPACE$(500))");
    want_out("space", "[   ]\n[]\n500\n");

    want_rc("PRINT INSTR(1, 2)", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT INSTR(\"a\", 1)", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT INSTR(\"a\", \"b\", \"c\")", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT INSTR(\"a\")", MB_ERR_BAD_BUILTIN);
    want_rc("PRINT INSTR(0, \"a\", \"b\")", MB_ERR_BAD_ARG);
    want_rc("PRINT UCASE$(1)", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT SPACE$(\"a\")", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT SPACE$(-1)", MB_ERR_BAD_ARG);
    want_rc("PRINT SPACE$(5000)", MB_ERR_STRING_TOO_LONG);
    want_out("no output on instr/case/space errors", "");

    want_rc("PRINT LEN(5)", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT LEFT$(\"a\", \"b\")", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT LEFT$(1, 1)", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT CHR$(\"a\")", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT VAL(1)", MB_ERR_TYPE_MISMATCH);
    want_rc("A = LEFT$(\"a\", 1)", MB_ERR_TYPE_MISMATCH);
    want_rc("C$ = LEN(\"a\")", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT LEN(\"a\") + \"b\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT LEFT$(\"a\")", MB_ERR_BAD_BUILTIN);
    want_rc("PRINT MID$(\"a\", 1, 1, 1)", MB_ERR_BAD_BUILTIN);
    want_rc("PRINT CHR$(300)", MB_ERR_BAD_ARG);
    want_rc("PRINT CHR$(-1)", MB_ERR_BAD_ARG);
    want_rc("PRINT ASC(\"\")", MB_ERR_BAD_ARG);
    want_rc("PRINT LEFT$(\"abc\", -1)", MB_ERR_BAD_ARG);
    want_rc("PRINT MID$(\"abc\", 0)", MB_ERR_BAD_ARG);
    want_rc("PRINT MID$(\"abc\", 1, -1)", MB_ERR_BAD_ARG);
    want_out("no output on errors", "");

    ok("NEW");
    ok("10 A$ = \"abc\"");
    ok("20 PRINT MID$(A$, 2, 1) + STR$(LEN(A$)) + CHR$(33)");
    ok("LIST");
    want_out("list", "10 A$ = \"abc\"\n20 PRINT MID$(A$, 2, 1) + STR$(LEN(A$)) + CHR$(33)\n");
    ok("RUN");
    want_out("run", "b3!\n");
}

static void test_print_lists(void)
{
    reset();
    ok("PRINT \"Edad: \"; 5");
    ok("A = 3");
    ok("PRINT A; \"x\"; A + 1; \"!\"");
    ok("PRINT");
    ok("PRINT \"a\";");
    ok("PRINT \"b\"");
    ok("PRINT \"c\"; \"d\";");
    ok("PRINT");
    ok("PRINT 1; 2; 3");
    want_out("print lists", "Edad: 5\n3x4!\n\nab\ncd\n123\n");

    ok("PRINT MID$(\"abc\", 2, 1); LEN(\"xy\"); MAX(4, 9)");
    ok("PRINT \"a;b, c\"; \";\"");
    ok("PRINT (1 + 2); (\"x\" + \"y\")");
    want_out("separators inside parentheses and literals", "b29\na;b, c;\n3xy\n");

    ok("IF A = 3 THEN PRINT \"yes\"; A ELSE PRINT \"no\"");
    ok("IF A = 4 THEN PRINT \"yes\"; A ELSE PRINT \"no\"; \"!\"");
    want_out("in if/else", "yes3\nno!\n");

    want_rc("PRINT ;", MB_ERR_SYNTAX);
    want_rc("PRINT \"a\", \"b\"", MB_ERR_SYNTAX);
    want_rc("PRINT \"a\";; \"b\"", MB_ERR_SYNTAX);
    want_rc("PRINT \"a\" \"b\"", MB_ERR_SYNTAX);
    want_rc("PRINT \"a\"; 1 +", MB_ERR_SYNTAX);
    want_rc("PRINT 1; \"a\" + 1", MB_ERR_TYPE_MISMATCH);
    want_out("no output on errors", "");

    ok("NEW");
    ok("10 A = 7");
    ok("20 B$ = \"q\"");
    ok("30 PRINT \"a=\"; A; \" b=\"; B$;");
    ok("40 PRINT");
    ok("50 PRINT A");
    ok("LIST");
    want_out("list",
             "10 A = 7\n"
             "20 B$ = \"q\"\n"
             "30 PRINT \"a=\"; A; \" b=\"; B$;\n"
             "40 PRINT\n"
             "50 PRINT A\n");
    ok("RUN");
    want_out("run", "a=7 b=q\n7\n");
}

static void test_long_lines_list(void)
{
    char text[MB_LINE_TEXT_MAX + 32];
    char want[MB_LINE_TEXT_MAX + 32];
    char literal[MB_EXPR_TEXT_MAX + 8];
    int n;

    /* Whatever the compiler accepts, LIST has to show again. */
    for (n = 10; n <= MB_EXPR_TEXT_MAX - 3; n += 17) {
        reset();
        memset(literal, 'x', (size_t)n);
        literal[n] = 0;
        sprintf(text, "10 PRINT \"%s\"", literal);
        ok(text);
        sprintf(text, "20 A$ = \"%s\"", literal);
        ok(text);
        ok("LIST");
        sprintf(want, "10 PRINT \"%s\"\n20 A$ = \"%s\"\n", literal, literal);
        want_out("long literal in LIST", want);
    }

    reset();
    memset(literal, 'x', MB_EXPR_TEXT_MAX);
    literal[MB_EXPR_TEXT_MAX - 1] = 0;
    sprintf(text, "PRINT \"%s\"", literal);
    want_rc(text, MB_ERR_FULL);

    /* The same limit applies to every place an expression is compiled. */
    reset();
    memset(literal, ' ', MB_EXPR_TEXT_MAX);
    literal[0] = '1';
    literal[MB_EXPR_TEXT_MAX - 3] = '+';
    literal[MB_EXPR_TEXT_MAX - 2] = '1';
    literal[MB_EXPR_TEXT_MAX - 1] = 0;
    sprintf(text, "A = %s", literal);
    ok(text);
    sprintf(text, "10 WHILE %s", literal);
    ok(text);
    sprintf(text, "PRINT %s", literal);
    ok(text);
    literal[MB_EXPR_TEXT_MAX - 2] = ' ';
    literal[MB_EXPR_TEXT_MAX - 1] = '1';
    literal[MB_EXPR_TEXT_MAX] = 0;
    literal[MB_EXPR_TEXT_MAX - 3] = ' ';
    literal[MB_EXPR_TEXT_MAX - 2] = '+';
    sprintf(text, "A = %s", literal);
    want_rc(text, MB_ERR_FULL);
    sprintf(text, "A =   %s   ", literal);
    want_rc(text, MB_ERR_FULL);
    sprintf(text, "10 WHILE %s", literal);
    want_rc(text, MB_ERR_FULL);
    sprintf(text, "PRINT %s", literal);
    want_rc(text, MB_ERR_FULL);
    sprintf(text, "IF %s THEN PRINT 1", literal);
    want_rc(text, MB_ERR_FULL);
}

int main(void)
{
    run_io.print_int = print_int;
    run_io.print_str = print_str;
    run_io.newline = newline;
    run_io.ctx = 0;
    console_io.put_char = put_char;
    console_io.ctx = 0;

    test_immediate();
    test_compare();
    test_errors();
    test_list_and_run();
    test_heap_reuse();
    test_too_long();
    test_builtins();
    test_print_lists();
    test_long_lines_list();

    if (failures != 0) {
        printf("FAILED: %d checks\n", failures);
        return 1;
    }
    printf("ok: strings\n");
    return 0;
}

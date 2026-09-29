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

/* PRINT expr must print value. */
static void want_value(const char *expr, long value)
{
    char text[160];
    char expected[32];

    sprintf(text, "PRINT %s", expr);
    sprintf(expected, "%ld\n", value);
    output[0] = 0;
    want_rc(text, MB_OK);
    if (strcmp(output, expected) != 0) {
        printf("%s: got %s want %s", expr, output, expected);
        ++failures;
    }
    output[0] = 0;
}

static void test_truth(void)
{
    reset();
    want_value("5 > 3", -1);
    want_value("5 < 3", 0);
    want_value("4 = 4", -1);
    want_value("4 <> 4", 0);
    want_value("3 <= 3", -1);
    want_value("3 >= 4", 0);
    want_value("-(5 > 3)", 1);
    want_value("(5 > 3) + (2 > 1)", -2);
    want_value("(1 = 2) + 7", 7);

    ok("A = 3");
    ok("B = 3");
    ok("N = 0");
    ok("N = N - (A = B)");
    ok("N = N - (A = B)");
    ok("N = N - (A <> B)");
    want_value("N", 2);
}

static void test_bit_operators(void)
{
    reset();
    want_value("12 AND 10", 8);
    want_value("12 OR 3", 15);
    want_value("6 XOR 3", 5);
    want_value("NOT 0", -1);
    want_value("NOT -1", 0);
    want_value("NOT 5", -6);
    want_value("NOT NOT 5", 5);
    want_value("1000 AND 255", 232);
    want_value("NOT 0 AND 255", 255);
    want_value("-3 AND 255", 253);
    want_value("5 XOR 5", 0);
    want_value("5 XOR 0", 5);
    want_value("0 OR 0", 0);

    want_value("-1 AND -1", -1);
    want_value("-1 AND 0", 0);
    want_value("-1 OR 0", -1);
    want_value("-1 XOR -1", 0);
}

static void test_precedence(void)
{
    reset();
    /* AND binds tighter than OR, which binds tighter than XOR */
    want_value("1 OR 0 AND 0", 1);
    want_value("(1 OR 0) AND 0", 0);
    want_value("1 XOR 1 OR 1", 0);
    want_value("(1 XOR 1) OR 1", 1);
    want_value("6 OR 1 AND 3", 7);
    want_value("6 XOR 3 AND 1", 7);
    /* arithmetic binds tighter than the comparisons, which bind tighter than NOT */
    want_value("2 + 3 AND 6", 4);
    want_value("1 < 2 AND 2 < 3", -1);
    want_value("1 < 2 AND 3 < 2", 0);
    want_value("1 < 2 OR 3 < 2", -1);
    want_value("NOT 1 < 2", 0);
    want_value("NOT 2 < 1", -1);
    want_value("NOT 1 = 1 OR 1", 1);
    want_value("NOT 1 = 2 OR 0", -1);
    want_value("NOT 0 AND 5", 5);
    want_value("(NOT 0) + 1", 0);
    want_value("-(NOT 0)", 1);
    want_value("NOT -1 + 1", -1);
    want_value("1 + 2 * 3 AND 7", 7);
    /* associativity */
    want_value("7 AND 6 AND 3", 2);
    want_value("1 OR 2 OR 4", 7);
    want_value("15 XOR 5 XOR 1", 11);
}

static void test_mod(void)
{
    reset();
    want_value("7 MOD 3", 1);
    want_value("9 MOD 3", 0);
    want_value("2 MOD 5", 2);
    want_value("-7 MOD 3", -1);
    want_value("7 MOD -3", 1);
    /* MOD is looser than * and /, like in classic BASIC */
    want_value("10 MOD 3 * 2", 4);
    want_value("(10 MOD 3) * 2", 2);
    want_value("10 * 3 MOD 4", 2);
    want_value("1 + 7 MOD 4", 4);
    want_value("7 MOD 3 * 2 + 1", 2);
    want_value("10 MOD 4 + 1", 3);
    want_value("10 MOD (3 + 1)", 2);
    want_value("7 MOD 3 = 1", -1);
    want_rc("PRINT 7 MOD 0", MB_ERR_DIV_ZERO);
    want_rc("PRINT 7 MOD (3 - 3)", MB_ERR_DIV_ZERO);
    want_out("no output on the errors", "");
}

static void test_power(void)
{
    reset();
    want_value("2 ^ 3", 8);
    want_value("2 ^ 0", 1);
    want_value("0 ^ 0", 1);
    want_value("0 ^ 5", 0);
    want_value("5 ^ 1", 5);
    want_value("3 ^ 4", 81);
    want_value("2 ^ 10", 1024);
    want_value("10 ^ 9", 1000000000L);
    want_value("(-2) ^ 3", -8);
    want_value("(-2) ^ 2", 4);
    want_value("-2 ^ 2", -4);
    want_value("-3 ^ 2", -9);
    want_value("2 ^ 3 ^ 2", 64);
    want_value("2 ^ (3 ^ 2)", 512);
    want_value("2 ^ -1", 0);
    want_value("1 ^ -5", 1);
    want_value("(-1) ^ -3", -1);
    want_value("(-1) ^ -2", 1);
    want_value("2 ^ - -2", 4);
    want_rc("PRINT 0 ^ -1", MB_ERR_DIV_ZERO);
    /* ^ binds tighter than the unary minus and everything else */
    want_value("2 * 3 ^ 2", 18);
    want_value("2 ^ 2 * 3", 12);
    want_value("1 + 2 ^ 3", 9);
    want_value("(2 + 1) ^ 2", 9);
    want_value("2 ^ (1 + 1)", 4);
    want_value("10 MOD 3 ^ 2", 1);
    want_value("2 ^ 3 = 8", -1);
    want_value("2 ^3", 8);
    want_value("2^3", 8);
    ok("A = 3");
    ok("B = 2");
    want_value("A ^ B", 9);
    want_value("A ^ B ^ B", 81);

    want_rc("PRINT \"a\" ^ 2", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 2 ^ \"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 2 ^", MB_ERR_SYNTAX);
    want_rc("PRINT ^ 2", MB_ERR_SYNTAX);
    want_rc("PRINT 2 ^ ^ 2", MB_ERR_SYNTAX);
    want_out("no output on errors", "");
}

static void test_integer_division(void)
{
    reset();
    want_value("7 \\ 2", 3);
    want_value("-7 \\ 2", -3);
    want_value("7 \\ -2", -3);
    want_value("6 \\ 3", 2);
    want_value("7\\2", 3);
    want_value("12 \\ 3 \\ 2", 2);
    want_value("12 \\ (3 \\ 2)", 12);
    /* \ is looser than * and /, tighter than MOD and + */
    want_value("7 \\ 2 * 2", 1);
    want_value("7 * 2 \\ 4", 3);
    want_value("7 / 2 \\ 3", 1);
    want_value("10 MOD 4 \\ 2", 0);
    want_value("100 \\ 10 MOD 7", 3);
    want_value("10 \\ 3 MOD 2", 1);
    want_value("1 + 7 \\ 2", 4);
    want_value("(1 + 7) \\ 2", 4);
    want_value("7 \\ 2 = 3", -1);
    want_rc("PRINT 7 \\ 0", MB_ERR_DIV_ZERO);
    want_rc("PRINT 7 \\ (2 - 2)", MB_ERR_DIV_ZERO);
    want_rc("PRINT \"a\" \\ 2", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 7 \\", MB_ERR_SYNTAX);
    want_rc("PRINT \\ 2", MB_ERR_SYNTAX);
    want_out("no output on errors", "");
}

static void test_shifts(void)
{
    reset();
    want_value("1 << 4", 16);
    want_value("256 >> 4", 16);
    want_value("1 << 0", 1);
    want_value("5 >> 1", 2);
    want_value("5 >> 0", 5);
    want_value("-1 << 1", -2);
    want_value("-8 >> 1", -4);
    want_value("-16 >> 2", -4);
    want_value("-1 >> 5", -1);
    want_value("-5 >> 1", -3);
    want_value("1 << 32", 0);
    want_value("1 << 100", 0);
    want_value("5 >> 40", 0);
    want_value("-5 >> 40", -1);
    want_value("8 >> 1 >> 1", 2);
    want_value("1 << 2 << 1", 8);
    want_value("1<<3", 8);
    want_value("64>>2", 16);
    ok("A = 3");
    ok("B = 4");
    want_value("A << B", 48);
    want_value("48 >> B", 3);
    want_value("(1 << A) - 1", 7);
    /* looser than +, tighter than the comparisons and AND */
    want_value("1 << 2 + 1", 8);
    want_value("1 + 1 << 2", 8);
    want_value("6 >> 1 = 3", -1);
    want_value("1 << 1 < 3", -1);
    want_value("1 << 1 AND 3", 2);
    want_value("12 >> 2 AND 1", 1);
    want_value("4 >> 1 > 1", -1);
    want_value("(1 < 2) << 1", -2);
    want_value("(1 << 4) OR (1 << 1)", 18);
    want_value("255 AND NOT (1 << 3)", 247);
    /* the comparisons are still what they were */
    want_value("1 < 2", -1);
    want_value("2 < 1", 0);
    want_value("1 <= 1", -1);
    want_value("2 > 1", -1);
    want_value("2 >= 3", 0);
    want_value("1 <> 2", -1);
    want_value("3 < 4 AND 5 > 4", -1);

    want_rc("PRINT 2 << -1", MB_ERR_BAD_ARG);
    want_rc("PRINT 5 >> -2", MB_ERR_BAD_ARG);
    want_rc("PRINT \"a\" << 1", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 1 >> \"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 1 <<", MB_ERR_SYNTAX);
    want_rc("PRINT << 1", MB_ERR_SYNTAX);
    want_rc("PRINT 1 < < 2", MB_ERR_SYNTAX);
    want_rc("PRINT 1 >> >> 2", MB_ERR_SYNTAX);
    want_out("no output on errors", "");
}

static void test_list_new_operators(void)
{
    reset();
    ok("10 A = 2 ^ 3 ^ 2");
    ok("20 A = 2 ^ (3 ^ 2)");
    ok("30 A = -2 ^ 2");
    ok("40 A = (-2) ^ 2");
    ok("50 A = 2 ^ -1");
    ok("60 A = 7 \\ 2 \\ 3");
    ok("70 A = 7 \\ (2 \\ 3)");
    ok("80 A = 1 << 2 + 3");
    ok("90 A = (1 << 2) + 3");
    ok("100 A = 1 << 2 < 5");
    ok("110 A = 10 MOD 3 * 2");
    ok("120 A = (10 MOD 3) * 2");
    ok("130 A = 10 \\ 3 MOD 2");
    ok("140 A = 10 \\ (3 MOD 2)");
    ok("150 A = B >> 1 << 1");
    ok("160 A = B >> (1 << 1)");
    ok("170 IF A >> 1 > 2 THEN PRINT A ^ 2");
    ok("LIST");
    want_out("list",
             "10 A = 2 ^ 3 ^ 2\n"
             "20 A = 2 ^ (3 ^ 2)\n"
             "30 A = -2 ^ 2\n"
             "40 A = (-2) ^ 2\n"
             "50 A = 2 ^ (-1)\n"
             "60 A = 7 \\ 2 \\ 3\n"
             "70 A = 7 \\ (2 \\ 3)\n"
             "80 A = 1 << 2 + 3\n"
             "90 A = (1 << 2) + 3\n"
             "100 A = 1 << 2 < 5\n"
             "110 A = 10 MOD 3 * 2\n"
             "120 A = (10 MOD 3) * 2\n"
             "130 A = 10 \\ 3 MOD 2\n"
             "140 A = 10 \\ (3 MOD 2)\n"
             "150 A = B >> 1 << 1\n"
             "160 A = B >> (1 << 1)\n"
             "170 IF A >> 1 > 2 THEN PRINT A ^ 2\n");

    ok("NEW");
    ok("10 FOR I = 0 TO 5");
    ok("20 PRINT 2 ^ I; \" \";");
    ok("30 NEXT I");
    ok("40 PRINT");
    ok("50 X = 200");
    ok("60 PRINT (X >> 4) AND 15; \" \"; X AND 15; \" \"; X \\ 16");
    ok("RUN");
    want_out("a program", "1 2 4 8 16 32 \n12 8 12\n");
}

static void test_words(void)
{
    reset();
    ok("ANDY = 5");
    ok("ORANGE = 2");
    ok("NOTE = 3");
    ok("MODE = 9");
    ok("XORB = 1");
    want_value("ANDY OR ORANGE", 7);
    want_value("ANDY AND ORANGE", 0);
    want_value("NOT NOTE", -4);
    want_value("MODE MOD 4", 1);
    want_value("XORB XOR 3", 2);
    want_value("ANDY", 5);
    want_value("ORANGE", 2);

    want_value("12 and 10", 8);
    want_value("12 Or 3", 15);
    want_value("not 0", -1);
    want_value("7 mod 3", 1);
    want_value("6 xor 3", 5);

    want_value("12AND 10", 8);
    want_value("(1)OR(2)", 3);
    want_value("NOT(0)", -1);
    want_value("7MOD 3", 1);
}

static void test_conditions(void)
{
    reset();
    ok("A = 5");
    ok("B = 2");
    ok("IF A > 1 AND B < 5 THEN PRINT \"both\" ELSE PRINT \"no\"");
    ok("IF A > 9 AND B < 5 THEN PRINT \"both\" ELSE PRINT \"no\"");
    ok("IF A > 9 OR B < 5 THEN PRINT \"either\" ELSE PRINT \"no\"");
    ok("IF A > 9 OR B > 5 THEN PRINT \"either\" ELSE PRINT \"no\"");
    ok("IF NOT (A = B) THEN PRINT \"differ\" ELSE PRINT \"equal\"");
    ok("IF NOT A = B THEN PRINT \"differ\" ELSE PRINT \"equal\"");
    ok("IF A > 1 XOR B > 1 THEN PRINT \"one\" ELSE PRINT \"none or both\"");
    ok("IF A MOD 2 = 1 THEN PRINT \"odd\" ELSE PRINT \"even\"");
    ok("IF (A > 1) AND (B > 1) AND NOT (A = B) THEN PRINT \"chain\"");
    want_out("conditions",
             "both\nno\neither\nno\ndiffer\ndiffer\nnone or both\nodd\nchain\n");

    ok("NEW");
    ok("10 FOR I = 1 TO 15");
    ok("20 IF I MOD 3 = 0 AND I MOD 5 = 0 THEN PRINT \"FizzBuzz\"");
    ok("30 IF I MOD 3 = 0 AND I MOD 5 <> 0 THEN PRINT \"Fizz\"");
    ok("40 IF I MOD 3 <> 0 AND I MOD 5 = 0 THEN PRINT \"Buzz\"");
    ok("50 IF I MOD 3 <> 0 AND I MOD 5 <> 0 THEN PRINT I");
    ok("60 NEXT I");
    ok("RUN");
    want_out("fizzbuzz",
             "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz\n");
}

static void test_program(void)
{
    reset();
    ok("10 I = 0");
    ok("20 S = 0");
    ok("30 WHILE I < 10 AND S < 20");
    ok("40 I = I + 1");
    ok("50 S = S + I");
    ok("60 WEND");
    ok("70 PRINT I; \" \"; S");
    ok("RUN");
    want_out("while with AND", "6 21\n");

    ok("NEW");
    ok("10 FOR I = 1 TO 10");
    ok("20 IF I MOD 2 = 0 THEN PRINT I;");
    ok("30 NEXT I");
    ok("40 PRINT");
    ok("RUN");
    want_out("even numbers", "246810\n");

    ok("NEW");
    ok("10 F = 0");
    ok("20 F = F OR 4");
    ok("30 F = F OR 1");
    ok("40 PRINT F; \" \"; F AND 4; \" \"; NOT (F AND 2)");
    ok("50 F = F AND NOT 4");
    ok("60 PRINT F");
    ok("RUN");
    want_out("flags", "5 4 -1\n1\n");
}

static void test_string_order(void)
{
    reset();
    want_value("\"a\" < \"b\"", -1);
    want_value("\"b\" < \"a\"", 0);
    want_value("\"a\" < \"a\"", 0);
    want_value("\"a\" <= \"a\"", -1);
    want_value("\"b\" > \"a\"", -1);
    want_value("\"a\" > \"b\"", 0);
    want_value("\"a\" >= \"a\"", -1);
    want_value("\"a\" >= \"b\"", 0);
    want_value("\"a\" < \"aa\"", -1);
    want_value("\"aa\" < \"a\"", 0);
    want_value("\"ab\" < \"b\"", -1);
    want_value("\"abc\" < \"abd\"", -1);
    want_value("\"abd\" > \"abc\"", -1);
    want_value("\"\" < \"a\"", -1);
    want_value("\"\" < \"\"", 0);
    want_value("\"\" <= \"\"", -1);
    want_value("\"\" >= \"\"", -1);
    want_value("\"a\" > \"\"", -1);
    want_value("\"Z\" < \"a\"", -1);
    want_value("\"B\" >= \"a\"", 0);
    want_value("CHR$(200) > \"a\"", -1);
    want_value("\"a\" < CHR$(200)", -1);

    ok("A$ = \"apple\"");
    ok("B$ = \"banana\"");
    want_value("A$ < B$", -1);
    want_value("A$ + \"z\" > B$", 0);
    want_value("LEFT$(B$, 1) > LEFT$(A$, 1)", -1);
    want_value("A$ < B$ AND B$ <> \"\"", -1);
    ok("IF A$ >= \"apple\" AND A$ <= \"apricot\" THEN PRINT \"in range\"");
    want_out("range check", "in range\n");
    want_value("(\"a\" < \"b\") + (\"b\" < \"c\")", -2);

    ok("DIM W$(2)");
    ok("W$(0) = \"pear\"");
    ok("W$(1) = \"fig\"");
    want_value("W$(1) < W$(0)", -1);
}

static void test_type_errors(void)
{
    reset();
    want_rc("PRINT 1 AND \"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" AND 1", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" AND \"b\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" OR 1", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 1 XOR \"x\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT NOT \"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" MOD 2", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 2 MOD \"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT \"a\" < 1", MB_ERR_TYPE_MISMATCH);
    want_rc("PRINT 1 >= \"a\"", MB_ERR_TYPE_MISMATCH);
    want_rc("A$ = \"a\" < \"b\"", MB_ERR_TYPE_MISMATCH);
    want_rc("A = \"a\" < \"b\" AND \"c\"", MB_ERR_TYPE_MISMATCH);

    want_rc("PRINT 1 AND", MB_ERR_SYNTAX);
    want_rc("PRINT AND 1", MB_ERR_SYNTAX);
    want_rc("PRINT NOT", MB_ERR_SYNTAX);
    want_rc("PRINT 1 AND AND 2", MB_ERR_SYNTAX);
    want_rc("PRINT 1 OR OR 2", MB_ERR_SYNTAX);
    want_rc("PRINT 1 MOD", MB_ERR_SYNTAX);
    want_rc("PRINT 1 MOD MOD 2", MB_ERR_SYNTAX);
    want_rc("PRINT (1 AND 2", MB_ERR_SYNTAX);
    want_rc("PRINT 1 NOT 2", MB_ERR_SYNTAX);
    want_out("no output on errors", "");
}

static void test_list(void)
{
    reset();
    ok("10 IF A > 1 AND NOT (B = 2) OR C MOD 2 = 0 THEN PRINT \"x\"");
    ok("20 A = (1 OR 2) AND 3");
    ok("30 A = 1 OR 2 AND 3");
    ok("40 A = NOT (B AND C)");
    ok("50 A = NOT B AND C");
    ok("60 A = -(NOT B)");
    ok("70 A = (NOT B) = C");
    ok("80 A = 10 MOD (3 + 1)");
    ok("90 A = 10 MOD 3 * 2");
    ok("100 A = 10 MOD (3 * 2)");
    ok("105 A = (10 MOD 3) * 2");
    ok("110 A = (1 XOR 2) XOR 3");
    ok("120 A = 1 XOR (2 XOR 3)");
    ok("130 A = 1 AND (2 OR 3) XOR 4");
    ok("140 IF A$ < B$ AND B$ <= C$ THEN PRINT A$ > B$");
    ok("150 X = (\"a\" < \"b\") AND (\"c\" >= \"d\")");
    ok("160 A = NOT NOT B");
    ok("170 A = -B MOD 3");
    ok("LIST");
    want_out("list",
             "10 IF A > 1 AND NOT B = 2 OR C MOD 2 = 0 THEN PRINT \"x\"\n"
             "20 A = (1 OR 2) AND 3\n"
             "30 A = 1 OR 2 AND 3\n"
             "40 A = NOT (B AND C)\n"
             "50 A = NOT B AND C\n"
             "60 A = -(NOT B)\n"
             "70 A = (NOT B) = C\n"
             "80 A = 10 MOD (3 + 1)\n"
             "90 A = 10 MOD 3 * 2\n"
             "100 A = 10 MOD 3 * 2\n"
             "105 A = (10 MOD 3) * 2\n"
             "110 A = 1 XOR 2 XOR 3\n"
             "120 A = 1 XOR (2 XOR 3)\n"
             "130 A = 1 AND (2 OR 3) XOR 4\n"
             "140 IF A$ < B$ AND B$ <= C$ THEN PRINT A$ > B$\n"
             "150 X = \"a\" < \"b\" AND \"c\" >= \"d\"\n"
             "160 A = NOT NOT B\n"
             "170 A = -B MOD 3\n");
}

static void test_list_reparses(void)
{
    /* What LIST prints must mean the same thing when it is typed in again. */
    static const char *exprs[] = {
        "1 OR 2 AND 3 XOR 4",
        "(1 OR 2) AND (3 XOR 4)",
        "NOT 1 AND 2 OR NOT 3",
        "NOT (1 AND 2) OR 3",
        "1 < 2 AND NOT 3 > 4",
        "10 MOD 4 * 3 + 2 MOD 5",
        "-7 MOD 3 AND 255",
        "NOT (1 = 1) OR (2 <> 3)",
        "(5 > 3) + (2 > 1) * 4",
        "1 + 2 AND 3 OR 4 XOR 5",
        "2 ^ 3 ^ 2 + 1",
        "-2 ^ 2 * 3",
        "(-2) ^ 2 \\ 3 MOD 5",
        "1 << 2 + 3 >> 1 AND 7",
        "7 \\ 2 * 2 MOD 3",
        "2 ^ -1 + 3",
        "1 < 2 << 1",
        "100 \\ 3 \\ 2 + 10 MOD 3 ^ 2",
        "NOT 1 << 2 AND 255",
        0
    };
    int i;
    char text[200];
    char first[64];
    char second[64];

    for (i = 0; exprs[i] != 0; ++i) {
        reset();
        sprintf(text, "10 PRINT %s", exprs[i]);
        ok(text);
        ok("RUN");
        strcpy(first, output);
        output[0] = 0;
        ok("LIST");
        /* the listing is "10 PRINT <canonical>\n" */
        sprintf(text, "%s", output + 3);
        text[strlen(text) - 1] = 0;
        output[0] = 0;
        ok("NEW");
        ok(text);
        ok("RUN");
        strcpy(second, output);
        output[0] = 0;
        if (strcmp(first, second) != 0) {
            printf("'%s' listed as '%s' changes its value: %s vs %s\n", exprs[i], text, first, second);
            ++failures;
        }
    }
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

    test_truth();
    test_bit_operators();
    test_precedence();
    test_mod();
    test_power();
    test_integer_division();
    test_shifts();
    test_list_new_operators();
    test_words();
    test_conditions();
    test_program();
    test_string_order();
    test_type_errors();
    test_list();
    test_list_reparses();

    if (failures != 0) {
        printf("FAILED: %d checks\n", failures);
        return 1;
    }
    printf("ok: logic\n");
    return 0;
}

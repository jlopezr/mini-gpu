#include "basic.h"
#include "basic_builtins.h"

#define MB_NONE 0u
#define MB_NO_JUMP 0xFFFFu
#define MB_FIRST_OFFSET 1u
#define MB_HEADER_SIZE 6u
/* Room for one record holding the largest statement, as the immediate mode needs. */
#define MB_IMMEDIATE_MEM (MB_FIRST_OFFSET + MB_HEADER_SIZE + MB_STMT_CODE_MAX)
#define MB_PAYLOAD_SOURCE_STMT 0x7eu
#define MB_KW_PRESERVE 249u
#define MB_KW_THEN 250u
#define MB_KW_ELSE 251u
#define MB_KW_TO 252u
#define MB_KW_STEP 253u
#define MB_NEXT_ANY 255u

/* C89 has no static_assert: a negative array size fails the build. */
typedef char mb_check_line_holds_expr[(MB_LINE_TEXT_MAX >= MB_EXPR_TEXT_MAX) ? 1 : -1];
typedef char mb_check_line_holds_branch[(MB_LINE_TEXT_MAX >= MB_STMT_TEXT_MAX) ? 1 : -1];
typedef char mb_check_literal_is_a_byte[(MB_STRING_LITERAL_MAX <= 255) ? 1 : -1];
typedef char mb_check_heap_fits_handle[(MB_HEAP_SIZE <= 65535) ? 1 : -1];
typedef char mb_check_input_fits_line[(MB_INPUT_LINE_MAX <= 255) ? 1 : -1];

typedef struct MBKeywordInfo MBKeywordInfo;
typedef struct MBOperatorInfo MBOperatorInfo;
typedef struct MBExecResult MBExecResult;
typedef struct MBJumpEntry MBJumpEntry;
typedef struct MBRunPlan MBRunPlan;
typedef struct MBBlockPrep MBBlockPrep;

struct MBKeywordInfo {
    const char *text;
    mb_u8 opcode;
};

struct MBOperatorInfo {
    const char *text;
    mb_u8 opcode;
    mb_u8 prec;
};

struct MBExecResult {
    mb_u8 jumped;
    mb_u16 next;
};

struct MBJumpEntry {
    mb_u16 from;
    mb_u16 to;
};

struct MBRunPlan {
    MBJumpEntry jumps[MB_RUN_JUMP_MAX];
    mb_u8 jump_count;
};

struct MBBlockPrep {
    mb_u8 kind;
    mb_u16 start_offset;
    mb_u16 else_offset;
    mb_u8 has_else;
};

static const MBKeywordInfo mb_keywords[] = {
    { "LET", MB_ST_LET },
    { "PRINT", MB_ST_PRINT },
    { "INPUT", MB_ST_INPUT },
    { "DIM", MB_ST_DIM },
    { "REDIM", MB_ST_REDIM },
    { "ERASE", MB_ST_ERASE },
    { "PRESERVE", MB_KW_PRESERVE },
    { "GOTO", MB_ST_GOTO },
    { "IF", MB_ST_IF },
    { "END", MB_ST_END },
    { "STOP", MB_ST_STOP },
    { "REM", MB_ST_REM },
    { "GOSUB", MB_ST_GOSUB },
    { "RETURN", MB_ST_RETURN },
    { "ELSE", MB_ST_ELSE },
    { "ELSE", MB_KW_ELSE },
    { "THEN", MB_KW_THEN },
    { "END IF", MB_ST_END_IF },
    { "WHILE", MB_ST_WHILE },
    { "WEND", MB_ST_WEND },
    { "FOR", MB_ST_FOR },
    { "NEXT", MB_ST_NEXT },
    { "TO", MB_KW_TO },
    { "STEP", MB_KW_STEP },
    { 0, 0 }
};

/* Binding strength, weakest first. As in classic BASIC, NOT sits between the
   comparisons and AND, MOD is looser than \ and both are looser than * and /,
   and ^ binds tighter than the unary minus (-2 ^ 2 is -4). The last level is
   not an operator: what an operand is made of (a number, a name, a call...). */
enum {
    MB_PREC_XOR = 1,
    MB_PREC_OR = 2,
    MB_PREC_AND = 3,
    MB_PREC_NOT = 4,
    MB_PREC_COMPARE = 5,
    MB_PREC_SHIFT = 6,
    MB_PREC_ADD = 7,
    MB_PREC_MODULO = 8,
    MB_PREC_IDIV = 9,
    MB_PREC_MUL = 10,
    MB_PREC_NEG = 11,
    MB_PREC_POW = 12,
    MB_PREC_ATOM = 13
};

static const MBOperatorInfo mb_operators[] = {
    { "<>", MB_BC_NE, MB_PREC_COMPARE },
    { "<=", MB_BC_LE, MB_PREC_COMPARE },
    { ">=", MB_BC_GE, MB_PREC_COMPARE },
    { "=", MB_BC_EQ, MB_PREC_COMPARE },
    { "<", MB_BC_LT, MB_PREC_COMPARE },
    { ">", MB_BC_GT, MB_PREC_COMPARE },
    { "<<", MB_BC_SHL, MB_PREC_SHIFT },
    { ">>", MB_BC_SHR, MB_PREC_SHIFT },
    { "+", MB_BC_ADD, MB_PREC_ADD },
    { "-", MB_BC_SUB, MB_PREC_ADD },
    { "MOD", MB_BC_MOD, MB_PREC_MODULO },
    { "\\", MB_BC_IDIV, MB_PREC_IDIV },
    { "*", MB_BC_MUL, MB_PREC_MUL },
    { "/", MB_BC_DIV, MB_PREC_MUL },
    { "^", MB_BC_POW, MB_PREC_POW },
    { "AND", MB_BC_AND, MB_PREC_AND },
    { "OR", MB_BC_OR, MB_PREC_OR },
    { "XOR", MB_BC_XOR, MB_PREC_XOR },
    { 0, 0, 0 }
};

static int bc_is_binary(mb_u8 op)
{
    return (op >= MB_BC_ADD && op <= MB_BC_DIV) ||
           (op >= MB_BC_MOD && op <= MB_BC_POW) ||
           (op >= MB_BC_AND && op <= MB_BC_XOR) ||
           op == MB_BC_SHL || op == MB_BC_SHR ||
           (op >= MB_BC_EQ && op <= MB_BC_GE) ||
           (op >= MB_BC_CONCAT && op <= MB_BC_SGE);
}
static int bc_is_unary(mb_u8 op)
{
    return op == MB_BC_NEG || op == MB_BC_NOT;
}

static int append_i32_buf(char *out, mb_u16 cap, mb_u16 *len, mb_i32 value);
static void skip_cstr_spaces(const char **s);
static int compile_statement_for_program(MBProgram *program, const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len);
static int decompile_statement_for_program(const MBProgram *program, const mb_u8 *code, mb_u16 len, char *out, mb_u16 cap);
static int eval_expr_for_program(const MBProgram *program, const mb_u8 *code, mb_u16 len, MBRuntime *runtime, mb_i32 *result);

static mb_u16 rd16(const mb_u8 *p)
{
    return (mb_u16)(p[0] | ((mb_u16)p[1] << 8));
}

static void wr16(mb_u8 *p, mb_u16 v)
{
    p[0] = (mb_u8)(v & 0xffu);
    p[1] = (mb_u8)((v >> 8) & 0xffu);
}

static mb_u16 rec_next(const MBProgram *program, mb_u16 off)
{
    return rd16(program->mem + off);
}

static void rec_set_next(MBProgram *program, mb_u16 off, mb_u16 next)
{
    wr16(program->mem + off, next);
}

static mb_u16 rec_line(const MBProgram *program, mb_u16 off)
{
    return rd16(program->mem + off + 2u);
}

static mb_u16 rec_len(const MBProgram *program, mb_u16 off)
{
    return rd16(program->mem + off + 4u);
}

static mb_u16 rec_size(const MBProgram *program, mb_u16 off)
{
    return (mb_u16)(MB_HEADER_SIZE + rec_len(program, off));
}

static const mb_u8 *rec_payload(const MBProgram *program, mb_u16 off)
{
    return program->mem + off + MB_HEADER_SIZE;
}

static mb_u16 payload_stmt_offset(const mb_u8 *payload, mb_u16 len)
{
    mb_u16 source_len;

    if (len >= 3u && payload[0] == MB_PAYLOAD_SOURCE_STMT) {
        source_len = rd16(payload + 1u);
        if ((mb_u16)(3u + source_len) <= len) {
            return (mb_u16)(3u + source_len);
        }
    }
    return 0;
}

static const mb_u8 *payload_stmt_code(const mb_u8 *payload, mb_u16 len, mb_u16 *code_len)
{
    mb_u16 off;

    off = payload_stmt_offset(payload, len);
    *code_len = (mb_u16)(len - off);
    return payload + off;
}

static int payload_source(const mb_u8 *payload, mb_u16 len, const char **source, mb_u16 *source_len)
{
    mb_u16 n;

    if (len < 3u || payload[0] != MB_PAYLOAD_SOURCE_STMT) {
        return 0;
    }
    n = rd16(payload + 1u);
    if ((mb_u16)(3u + n) > len) {
        return 0;
    }
    *source = (const char *)(payload + 3u);
    *source_len = n;
    return 1;
}

static mb_u16 cstr_len(const char *s)
{
    mb_u16 n;

    n = 0;
    while (s[n] != 0) {
        ++n;
    }
    return n;
}

static void copy_bytes(mb_u8 *dst, const mb_u8 *src, mb_u16 len)
{
    mb_u16 i;

    for (i = 0; i < len; ++i) {
        dst[i] = src[i];
    }
}

static int is_space(char c)
{
    return c == ' ' || c == '\t';
}

static int is_digit(char c)
{
    return c >= '0' && c <= '9';
}

static int is_alpha(char c)
{
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}

static int is_ident_tail(char c)
{
    return is_alpha(c) || is_digit(c) || c == '_';
}

static char upper_char(char c)
{
    if (c >= 'a' && c <= 'z') {
        return (char)(c - 'a' + 'A');
    }
    return c;
}

static int str_ieq_n(const char *a, const char *b, mb_u16 n)
{
    mb_u16 i;

    for (i = 0; i < n; ++i) {
        if (upper_char(a[i]) != upper_char(b[i])) {
            return 0;
        }
    }
    return 1;
}

static int str_eq(const char *a, const char *b)
{
    while (*a != 0 && *b != 0) {
        if (*a != *b) {
            return 0;
        }
        ++a;
        ++b;
    }
    return *a == 0 && *b == 0;
}

/* end == 0 means the text is NUL-terminated; otherwise it stops at end. */
static char char_at(const char *s, const char *end)
{
    return (end != 0 && s >= end) ? 0 : *s;
}

static int parse_ident_text(const char **s, const char *end, char *name, mb_u16 cap)
{
    mb_u16 len;

    skip_cstr_spaces(s);
    if (!is_alpha(**s)) {
        return MB_ERR_SYNTAX;
    }

    len = 0;
    while (is_ident_tail(char_at(*s, end))) {
        if (len + 1u >= cap) {
            return MB_ERR_FULL;
        }
        name[len] = upper_char(**s);
        ++len;
        ++*s;
    }
    if (char_at(*s, end) == '$') {
        if (len + 1u >= cap) {
            return MB_ERR_FULL;
        }
        name[len] = '$';
        ++len;
        ++*s;
    }
    name[len] = 0;
    return MB_OK;
}

static int name_is_string(const char *name)
{
    mb_u16 n;

    n = cstr_len(name);
    return n != 0 && name[n - 1u] == '$';
}

static int var_is_string(const MBProgram *program, mb_u8 var)
{
    return program != 0 && var < program->symbol_count &&
           name_is_string(program->symbols[var].name);
}

static void symbol_set_name(MBSymbol *symbol, const char *name)
{
    mb_u16 i;

    i = 0;
    while (name[i] != 0 && i + 1u < MB_SYMBOL_NAME_MAX) {
        symbol->name[i] = name[i];
        ++i;
    }
    symbol->name[i] = 0;
}

static void symbols_init(MBProgram *program)
{
    mb_u8 i;
    char name[2];

    program->symbol_count = 0;
    name[1] = 0;
    for (i = 0; i < 26u; ++i) {
        name[0] = (char)('A' + i);
        symbol_set_name(&program->symbols[i], name);
        ++program->symbol_count;
    }
}

static int symbol_find(const MBProgram *program, const char *name, mb_u8 *id)
{
    mb_u8 i;

    for (i = 0; i < program->symbol_count; ++i) {
        if (str_eq(program->symbols[i].name, name)) {
            *id = i;
            return 1;
        }
    }
    return 0;
}

static int symbol_get_or_create(MBProgram *program, const char *name, mb_u8 *id)
{
    if (symbol_find(program, name, id)) {
        return MB_OK;
    }
    if (program->symbol_count >= MB_VAR_COUNT) {
        return MB_ERR_FULL;
    }
    *id = program->symbol_count;
    symbol_set_name(&program->symbols[*id], name);
    ++program->symbol_count;
    return MB_OK;
}

static void symbols_copy(MBProgram *dst, const MBProgram *src)
{
    mb_u8 i;

    dst->symbol_count = src->symbol_count;
    for (i = 0; i < src->symbol_count; ++i) {
        symbol_set_name(&dst->symbols[i], src->symbols[i].name);
    }
    dst->builtins = src->builtins;
    dst->builtin_count = src->builtin_count;
}

static const char *symbol_name(const MBProgram *program, mb_u8 id)
{
    static char short_name[2];
    static const char bad[] = "?";

    if (program != 0 && id < program->symbol_count) {
        return program->symbols[id].name;
    }
    if (id < 26u) {
        short_name[0] = (char)('A' + id);
        short_name[1] = 0;
        return short_name;
    }
    return bad;
}

/* The same name may appear more than once with different argument counts
   (INSTR has a two- and a three-argument form). */
static int builtin_find(const MBProgram *program, const char *name, mb_u8 argc, mb_u8 *id)
{
    mb_u8 i;

    if (program == 0 || program->builtins == 0) {
        return 0;
    }
    for (i = 0; i < program->builtin_count; ++i) {
        if (str_eq(program->builtins[i].name, name) &&
            argc >= program->builtins[i].min_args && argc <= program->builtins[i].max_args) {
            *id = i;
            return 1;
        }
    }
    return 0;
}

static int builtin_name_exists(const MBProgram *program, const char *name)
{
    mb_u8 i;

    if (program == 0 || program->builtins == 0) {
        return 0;
    }
    for (i = 0; i < program->builtin_count; ++i) {
        if (str_eq(program->builtins[i].name, name)) {
            return 1;
        }
    }
    return 0;
}

static const char *builtin_name(const MBProgram *program, mb_u8 id)
{
    static const char bad[] = "?";

    if (program != 0 && program->builtins != 0 && id < program->builtin_count) {
        return program->builtins[id].name;
    }
    return bad;
}

static const MBKeywordInfo *keyword_by_opcode(mb_u8 opcode)
{
    mb_u16 i;

    for (i = 0; mb_keywords[i].text != 0; ++i) {
        if (mb_keywords[i].opcode == opcode) {
            return &mb_keywords[i];
        }
    }
    return 0;
}

static const MBOperatorInfo *operator_by_opcode(mb_u8 opcode)
{
    mb_u16 i;

    for (i = 0; mb_operators[i].text != 0; ++i) {
        if (mb_operators[i].opcode == opcode) {
            return &mb_operators[i];
        }
    }
    return 0;
}

static const MBOperatorInfo *operator_by_text(const char *s, const char *end, mb_u8 min_prec, mb_u8 max_prec)
{
    mb_u16 i;
    mb_u16 n;

    for (i = 0; mb_operators[i].text != 0; ++i) {
        if (mb_operators[i].prec < min_prec || mb_operators[i].prec > max_prec) {
            continue;
        }
        n = cstr_len(mb_operators[i].text);
        if (end != 0 && (end - s) < (long)n) {
            continue;
        }
        if (str_ieq_n(s, mb_operators[i].text, n)) {
            /* A word operator is not the start of a longer name: ORANGE. */
            if (is_alpha(mb_operators[i].text[0]) && is_ident_tail(char_at(s + n, end))) {
                continue;
            }
            return &mb_operators[i];
        }
    }
    return 0;
}

static void skip_cstr_spaces(const char **s)
{
    while (is_space(**s)) {
        ++*s;
    }
}

static int take_word(const char **s, const char *word)
{
    mb_u16 n;

    skip_cstr_spaces(s);
    n = cstr_len(word);
    if (!str_ieq_n(*s, word, n)) {
        return 0;
    }
    if (is_alpha((*s)[n])) {
        return 0;
    }
    *s += n;
    return 1;
}

static int take_keyword(const char **s, mb_u8 opcode)
{
    const MBKeywordInfo *keyword;

    keyword = keyword_by_opcode(opcode);
    if (keyword == 0) {
        return 0;
    }
    return take_word(s, keyword->text);
}

static int take_char(const char **s, char c)
{
    skip_cstr_spaces(s);
    if (**s != c) {
        return 0;
    }
    ++*s;
    return 1;
}

static int parse_var_name(MBProgram *program, const char **s, mb_u8 *var)
{
    char name[MB_SYMBOL_NAME_MAX];
    int r;

    r = parse_ident_text(s, 0, name, sizeof(name));
    if (r != MB_OK) {
        return r;
    }

    if (program == 0) {
        if (name[0] == 0 || name[1] != 0) {
            return MB_ERR_SYNTAX;
        }
        *var = (mb_u8)(name[0] - 'A');
        return MB_OK;
    }

    return symbol_get_or_create(program, name, var);
}

static int parse_u16_line_ref(const char **s, mb_u16 *line)
{
    mb_u16 value;

    skip_cstr_spaces(s);
    if (!is_digit(**s)) {
        return MB_ERR_SYNTAX;
    }

    value = 0;
    while (is_digit(**s)) {
        value = (mb_u16)(value * 10u + (mb_u16)(**s - '0'));
        ++*s;
    }
    if (value == 0) {
        return MB_ERR_BAD_LINE;
    }
    *line = value;
    return MB_OK;
}

static int parse_leading_line_number(const char **s, mb_u16 *line)
{
    mb_u16 value;

    skip_cstr_spaces(s);
    if (!is_digit(**s)) {
        return 0;
    }
    value = 0;
    while (is_digit(**s)) {
        value = (mb_u16)(value * 10u + (mb_u16)(**s - '0'));
        ++*s;
    }
    *line = value;
    return 1;
}

static int cstr_is_empty_after_spaces(const char *s)
{
    skip_cstr_spaces(&s);
    return *s == 0;
}

static void console_put_char(const MBConsoleIO *io, char c)
{
    if (io != 0 && io->put_char != 0) {
        io->put_char(c, io->ctx);
    }
}

static void console_put_text_n(const MBConsoleIO *io, const char *s, mb_u16 len)
{
    mb_u16 i;

    for (i = 0; i < len; ++i) {
        console_put_char(io, s[i]);
    }
}

static void console_put_u16(const MBConsoleIO *io, mb_u16 value)
{
    char buf[6];
    mb_u16 n;

    n = 0;
    if (value == 0) {
        console_put_char(io, '0');
        return;
    }
    while (value != 0 && n < sizeof(buf)) {
        buf[n] = (char)('0' + (value % 10u));
        value = (mb_u16)(value / 10u);
        ++n;
    }
    while (n != 0) {
        --n;
        console_put_char(io, buf[n]);
    }
}

static void repl_put_char(const MBReplIO *io, char c)
{
    if (io != 0 && io->put_char != 0) {
        io->put_char(c, io->ctx);
    }
}

static void repl_put_text(const MBReplIO *io, const char *s)
{
    while (*s != 0) {
        repl_put_char(io, *s);
        ++s;
    }
}

static void repl_newline(const MBReplIO *io)
{
    repl_put_char(io, '\r');
    repl_put_char(io, '\n');
}

static void repl_print_int(mb_i32 value, void *ctx)
{
    MBReplIO *io;
    char buf[16];
    mb_u16 len;

    io = (MBReplIO *)ctx;
    len = 0;
    buf[0] = 0;
    if (append_i32_buf(buf, sizeof(buf), &len, value) == MB_OK) {
        repl_put_text(io, buf);
    }
}

static void repl_print_str(const char *text, mb_u16 len, void *ctx)
{
    mb_u16 i;

    for (i = 0; i < len; ++i) {
        repl_put_char((const MBReplIO *)ctx, text[i]);
    }
}

/* Line editor for INPUT while a program runs: echo, Enter and backspace. */
static int repl_read_line(char *buf, mb_u16 cap, void *ctx)
{
    const MBReplIO *io;
    mb_u16 len;
    int ch;

    io = (const MBReplIO *)ctx;
    len = 0;
    for (;;) {
        ch = io->get_char(io->ctx);
        if (ch < 0) {
            return -1;
        }
        if (ch == '\r' || ch == '\n') {
            repl_newline(io);
            buf[len] = 0;
            return (int)len;
        }
        if (ch == 8 || ch == 127) {
            if (len != 0) {
                --len;
                repl_put_char(io, 8);
                repl_put_char(io, ' ');
                repl_put_char(io, 8);
            }
            continue;
        }
        if (ch >= 32 && ch < 127 && len + 1u < cap) {
            buf[len] = (char)ch;
            ++len;
            repl_put_char(io, (char)ch);
        }
    }
}

static void repl_print_newline(void *ctx)
{
    repl_newline((const MBReplIO *)ctx);
}

static void repl_console_put_char(char c, void *ctx)
{
    repl_put_char((const MBReplIO *)ctx, c);
}

static const char *error_text(int err)
{
    if (err == MB_ERR_FULL) return "FULL";
    if (err == MB_ERR_BAD_LINE) return "BAD LINE";
    if (err == MB_ERR_BAD_ARG) return "BAD ARG";
    if (err == MB_ERR_SYNTAX) return "SYNTAX";
    if (err == MB_ERR_STACK) return "STACK";
    if (err == MB_ERR_DIV_ZERO) return "DIV ZERO";
    if (err == MB_ERR_NO_SUCH_LINE) return "NO SUCH LINE";
    if (err == MB_ERR_TOO_MANY_STEPS) return "TOO MANY STEPS";
    if (err == MB_ERR_CONTROL_STACK) return "CONTROL STACK";
    if (err == MB_ERR_RETURN_WITHOUT_GOSUB) return "RETURN WITHOUT GOSUB";
    if (err == MB_ERR_BAD_BUILTIN) return "BAD BUILTIN";
    if (err == MB_ERR_STRING_TOO_LONG) return "STRING TOO LONG";
    if (err == MB_ERR_TYPE_MISMATCH) return "TYPE MISMATCH";
    if (err == MB_ERR_NO_INPUT) return "NO INPUT";
    if (err == MB_ERR_SUBSCRIPT) return "SUBSCRIPT OUT OF RANGE";
    if (err == MB_ERR_NO_ARRAY) return "NO SUCH ARRAY";
    if (err == MB_ERR_ARRAY_EXISTS) return "ARRAY EXISTS";
    return "ERROR";
}

static void print_error(const MBReplIO *io, int err)
{
    if (err == MB_OK) {
        return;
    }
    repl_put_char(io, '?');
    repl_put_text(io, error_text(err));
    repl_newline(io);
}

static void move_left(mb_u8 *mem, mb_u16 dst, mb_u16 src, mb_u16 len)
{
    mb_u16 i;

    for (i = 0; i < len; ++i) {
        mem[(mb_u16)(dst + i)] = mem[(mb_u16)(src + i)];
    }
}

static void move_right(mb_u8 *mem, mb_u16 dst, mb_u16 src, mb_u16 len)
{
    mb_u16 i;

    i = len;
    while (i != 0) {
        --i;
        mem[(mb_u16)(dst + i)] = mem[(mb_u16)(src + i)];
    }
}

static void adjust_links_after_insert(MBProgram *program, mb_u16 at, mb_u16 size)
{
    mb_u16 off;
    mb_u16 next;

    if (program->first >= at && program->first != MB_NONE) {
        program->first = (mb_u16)(program->first + size);
    }

    off = program->first;
    while (off != MB_NONE) {
        next = rec_next(program, off);
        if (next >= at && next != MB_NONE) {
            rec_set_next(program, off, (mb_u16)(next + size));
        }
        off = rec_next(program, off);
    }
}

static void adjust_links_after_delete(MBProgram *program, mb_u16 at, mb_u16 size)
{
    mb_u16 off;
    mb_u16 next;

    if (program->first > at) {
        program->first = (mb_u16)(program->first - size);
    }

    off = program->first;
    while (off != MB_NONE) {
        next = rec_next(program, off);
        if (next > at) {
            rec_set_next(program, off, (mb_u16)(next - size));
        }
        off = rec_next(program, off);
    }
}

static void find_line(const MBProgram *program, mb_u16 line, mb_u16 *prev, mb_u16 *cur)
{
    mb_u16 p;
    mb_u16 c;

    p = MB_NONE;
    c = program->first;
    while (c != MB_NONE && rec_line(program, c) < line) {
        p = c;
        c = rec_next(program, c);
    }

    *prev = p;
    *cur = c;
}

static mb_u16 find_line_offset(const MBProgram *program, mb_u16 line)
{
    mb_u16 prev;
    mb_u16 cur;

    find_line(program, line, &prev, &cur);
    if (cur != MB_NONE && rec_line(program, cur) == line) {
        return cur;
    }
    return MB_NONE;
}

void mb_program_init(MBProgram *program, mb_u8 *memory, mb_u16 capacity)
{
    program->mem = memory;
    program->capacity = capacity;
    program->builtins = mb_default_builtins;
    program->builtin_count = mb_default_builtin_count;
    mb_program_clear(program);
}

void mb_program_set_builtins(MBProgram *program, const MBBuiltin *builtins, mb_u8 count)
{
    program->builtins = builtins;
    program->builtin_count = count;
}

void mb_program_clear(MBProgram *program)
{
    program->used = MB_FIRST_OFFSET;
    program->first = MB_NONE;
    symbols_init(program);
}

int mb_program_delete_line(MBProgram *program, mb_u16 line)
{
    mb_u16 prev;
    mb_u16 cur;
    mb_u16 next;
    mb_u16 size;
    mb_u16 tail_src;
    mb_u16 tail_len;

    if (line == 0) {
        return MB_ERR_BAD_LINE;
    }

    find_line(program, line, &prev, &cur);
    if (cur == MB_NONE || rec_line(program, cur) != line) {
        return MB_OK;
    }

    next = rec_next(program, cur);
    if (prev == MB_NONE) {
        program->first = next;
    } else {
        rec_set_next(program, prev, next);
    }

    size = rec_size(program, cur);
    tail_src = (mb_u16)(cur + size);
    tail_len = (mb_u16)(program->used - tail_src);
    move_left(program->mem, cur, tail_src, tail_len);
    program->used = (mb_u16)(program->used - size);
    adjust_links_after_delete(program, cur, size);

    return MB_OK;
}

int mb_program_store_line(MBProgram *program, mb_u16 line, const char *text)
{
    mb_u16 len;

    if (program == 0 || text == 0) {
        return MB_ERR_BAD_ARG;
    }
    if (line == 0) {
        return MB_ERR_BAD_LINE;
    }

    len = cstr_len(text);
    if (len == 0) {
        return mb_program_delete_line(program, line);
    }

    return mb_program_store_payload(program, line, (const mb_u8 *)text, len);
}

int mb_program_store_payload(MBProgram *program, mb_u16 line, const mb_u8 *payload, mb_u16 len)
{
    mb_u16 prev;
    mb_u16 cur;
    mb_u16 size;
    mb_u16 insert_at;

    if (program == 0 || payload == 0) {
        return MB_ERR_BAD_ARG;
    }
    if (line == 0) {
        return MB_ERR_BAD_LINE;
    }
    if (len == 0) {
        return mb_program_delete_line(program, line);
    }

    mb_program_delete_line(program, line);

    size = (mb_u16)(MB_HEADER_SIZE + len);
    if ((mb_u16)(program->capacity - program->used) < size) {
        return MB_ERR_FULL;
    }

    find_line(program, line, &prev, &cur);
    insert_at = program->used;
    move_right(program->mem, (mb_u16)(insert_at + size), insert_at, 0);

    wr16(program->mem + insert_at, cur);
    wr16(program->mem + insert_at + 2u, line);
    wr16(program->mem + insert_at + 4u, len);
    copy_bytes(program->mem + insert_at + MB_HEADER_SIZE, payload, len);

    program->used = (mb_u16)(program->used + size);
    adjust_links_after_insert(program, insert_at, size);

    if (prev == MB_NONE) {
        program->first = insert_at;
    } else {
        rec_set_next(program, prev, insert_at);
    }

    return MB_OK;
}

int mb_program_store_statement(MBProgram *program, mb_u16 line, const char *text)
{
    mb_u8 code[MB_STMT_CODE_MAX];
    mb_u16 code_len;
    int r;

    if (text == 0) {
        return MB_ERR_BAD_ARG;
    }
    if (cstr_len(text) == 0) {
        return mb_program_delete_line(program, line);
    }

    r = compile_statement_for_program(program, text, code, sizeof(code), &code_len);
    if (r != MB_OK) {
        return r;
    }
    return mb_program_store_payload(program, line, code, code_len);
}

void mb_program_each(const MBProgram *program, MBListFn fn, void *ctx)
{
    mb_u16 off;

    off = program->first;
    while (off != MB_NONE) {
        fn(rec_line(program, off),
           program->mem + off + MB_HEADER_SIZE,
           rec_len(program, off),
           ctx);
        off = rec_next(program, off);
    }
}

void mb_program_each_source(const MBProgram *program, MBSourceListFn fn, void *ctx)
{
    mb_u16 off;
    const mb_u8 *payload;
    mb_u16 len;
    const char *source;
    mb_u16 source_len;
    char line[MB_LINE_TEXT_MAX];
    int r;

    off = program->first;
    while (off != MB_NONE) {
        payload = rec_payload(program, off);
        len = rec_len(program, off);
        if (payload_source(payload, len, &source, &source_len)) {
            fn(rec_line(program, off), source, source_len, ctx);
        } else {
            r = decompile_statement_for_program(program, payload, len, line, sizeof(line));
            if (r == MB_OK) {
                fn(rec_line(program, off), line, cstr_len(line), ctx);
            }
        }
        off = rec_next(program, off);
    }
}

mb_u16 mb_program_bytes_used(const MBProgram *program)
{
    if (program->used == 0) {
        return 0;
    }
    return (mb_u16)(program->used - MB_FIRST_OFFSET);
}

void mb_runtime_init(MBRuntime *runtime)
{
    mb_u16 i;

    for (i = 0; i < MB_VAR_COUNT; ++i) {
        runtime->vars[i] = 0;
        runtime->str_var[i] = 0;
        runtime->arrays[i].off = 0;
        runtime->arrays[i].count = 0;
        runtime->arrays[i].is_str = 0;
    }
    runtime->frame_sp = 0;
    runtime->str_used = 0;
    runtime->str_top = 0;
    runtime->str_garbage = 0;
    runtime->arr_base = MB_HEAP_SIZE;
}

typedef struct ExprParser ExprParser;

struct ExprParser {
    MBProgram *program;
    const char *s;
    const char *end; /* 0: NUL-terminated */
    mb_u8 *out;
    mb_u16 cap;
    mb_u16 len;
    mb_u8 type;
};

enum {
    MB_T_INT = 0,
    MB_T_STR = 1
};

static char peek(const ExprParser *parser)
{
    return char_at(parser->s, parser->end);
}

static void skip_spaces(ExprParser *parser)
{
    while (is_space(peek(parser))) {
        ++parser->s;
    }
}

static int emit_u8(ExprParser *parser, mb_u8 v)
{
    if (parser->len >= parser->cap) {
        return MB_ERR_FULL;
    }
    parser->out[parser->len] = v;
    ++parser->len;
    return MB_OK;
}

static int emit_i32(ExprParser *parser, mb_i32 v)
{
    int r;

    r = emit_u8(parser, (mb_u8)(v & 0xff));
    if (r != MB_OK) return r;
    r = emit_u8(parser, (mb_u8)((v >> 8) & 0xff));
    if (r != MB_OK) return r;
    r = emit_u8(parser, (mb_u8)((v >> 16) & 0xff));
    if (r != MB_OK) return r;
    return emit_u8(parser, (mb_u8)((v >> 24) & 0xff));
}

static int emit_op(ExprParser *parser, mb_u8 op)
{
    return emit_u8(parser, op);
}

static int parse_compare(ExprParser *parser);
static int parse_expr(ExprParser *parser);

static int parse_builtin_call(ExprParser *parser, const char *name)
{
    mb_u8 builtin_id;
    mb_u8 argc;
    mb_u8 arg_strings;
    int r;

    if (!builtin_name_exists(parser->program, name)) {
        return MB_ERR_BAD_BUILTIN;
    }

    ++parser->s;
    argc = 0;
    arg_strings = 0;
    skip_spaces(parser);
    if (peek(parser) != ')') {
        for (;;) {
            if (argc >= MB_BUILTIN_ARG_MAX) {
                return MB_ERR_BAD_BUILTIN;
            }
            r = parse_expr(parser);
            if (r != MB_OK) return r;
            if (parser->type == MB_T_STR) {
                arg_strings = (mb_u8)(arg_strings | (1u << argc));
            }
            ++argc;
            skip_spaces(parser);
            if (peek(parser) == ',') {
                ++parser->s;
                continue;
            }
            break;
        }
    }

    skip_spaces(parser);
    if (peek(parser) != ')') {
        return MB_ERR_SYNTAX;
    }
    ++parser->s;

    if (!builtin_find(parser->program, name, argc, &builtin_id)) {
        return MB_ERR_BAD_BUILTIN;
    }
    if (((arg_strings ^ parser->program->builtins[builtin_id].string_args) & ((1u << argc) - 1u)) != 0u) {
        return MB_ERR_TYPE_MISMATCH;
    }

    parser->type = parser->program->builtins[builtin_id].string_result ? MB_T_STR : MB_T_INT;
    r = emit_op(parser, MB_BC_CALL_BUILTIN);
    if (r != MB_OK) return r;
    r = emit_u8(parser, builtin_id);
    if (r != MB_OK) return r;
    return emit_u8(parser, argc);
}

/* name(index): an element of an array. The array itself is only checked when
   the expression runs, since the lines of a program can be entered in any
   order. */
static int parse_array_element(ExprParser *parser, const char *name)
{
    mb_u8 var;
    int r;

    if (parser->program == 0) {
        if (name[0] == 0 || name[1] != 0) return MB_ERR_SYNTAX;
        var = (mb_u8)(name[0] - 'A');
    } else {
        r = symbol_get_or_create(parser->program, name, &var);
        if (r != MB_OK) return r;
    }
    ++parser->s;
    r = parse_expr(parser);
    if (r != MB_OK) return r;
    if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
    skip_spaces(parser);
    if (peek(parser) != ')') {
        return MB_ERR_SYNTAX;
    }
    ++parser->s;
    parser->type = name_is_string(name) ? MB_T_STR : MB_T_INT;
    r = emit_op(parser, MB_BC_PUSH_ELEM);
    if (r != MB_OK) return r;
    return emit_u8(parser, var);
}

static int parse_primary(ExprParser *parser)
{
    mb_i32 value;
    int r;
    mb_u8 var;
    char name[MB_SYMBOL_NAME_MAX];
    const char *start;
    mb_u16 text_len;
    mb_u16 i;

    skip_spaces(parser);

    if (peek(parser) == '(') {
        ++parser->s;
        r = parse_expr(parser);
        if (r != MB_OK) return r;
        skip_spaces(parser);
        if (peek(parser) != ')') {
            return MB_ERR_SYNTAX;
        }
        ++parser->s;
        return MB_OK;
    }

    if (peek(parser) == '"') {
        ++parser->s;
        start = parser->s;
        while (peek(parser) != 0 && peek(parser) != '"') {
            ++parser->s;
        }
        if (peek(parser) == 0) {
            return MB_ERR_SYNTAX;
        }
        text_len = (mb_u16)(parser->s - start);
        ++parser->s;
        if (text_len > MB_STRING_LITERAL_MAX) {
            return MB_ERR_STRING_TOO_LONG;
        }
        r = emit_op(parser, MB_BC_PUSH_STR);
        if (r != MB_OK) return r;
        r = emit_u8(parser, (mb_u8)text_len);
        if (r != MB_OK) return r;
        for (i = 0; i < text_len; ++i) {
            r = emit_u8(parser, (mb_u8)start[i]);
            if (r != MB_OK) return r;
        }
        parser->type = MB_T_STR;
        return MB_OK;
    }

    if (is_digit(peek(parser))) {
        value = 0;
        while (is_digit(peek(parser))) {
            value = (mb_i32)(value * 10 + (peek(parser) - '0'));
            ++parser->s;
        }
        parser->type = MB_T_INT;
        r = emit_op(parser, MB_BC_PUSH_I32);
        if (r != MB_OK) return r;
        return emit_i32(parser, value);
    }

    if (is_alpha(peek(parser))) {
        r = parse_ident_text(&parser->s, parser->end, name, sizeof(name));
        if (r != MB_OK) return r;
        skip_spaces(parser);
        if (peek(parser) == '(') {
            if (builtin_name_exists(parser->program, name)) {
                return parse_builtin_call(parser, name);
            }
            return parse_array_element(parser, name);
        }
        if (parser->program == 0) {
            if (name[0] == 0 || name[1] != 0) return MB_ERR_SYNTAX;
            var = (mb_u8)(name[0] - 'A');
        } else {
            r = symbol_get_or_create(parser->program, name, &var);
            if (r != MB_OK) return r;
        }
        parser->type = name_is_string(name) ? MB_T_STR : MB_T_INT;
        r = emit_op(parser, MB_BC_PUSH_VAR);
        if (r != MB_OK) return r;
        return emit_u8(parser, var);
    }

    return MB_ERR_SYNTAX;
}

/* One left-associative level of integer-only operators: [text, next] chains
   such as "a * b * c" where every operand comes from next. */
static int parse_int_level(ExprParser *parser, mb_u8 prec, int (*next)(ExprParser *))
{
    const MBOperatorInfo *op;
    int r;

    r = next(parser);
    if (r != MB_OK) return r;
    for (;;) {
        skip_spaces(parser);
        op = operator_by_text(parser->s, parser->end, prec, prec);
        if (op == 0) {
            return MB_OK;
        }
        if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
        parser->s += cstr_len(op->text);
        r = next(parser);
        if (r != MB_OK) return r;
        if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
        r = emit_op(parser, op->opcode);
        if (r != MB_OK) return r;
    }
}

/* The right side of ^ may carry a sign: 2 ^ -1. */
static int parse_pow_operand(ExprParser *parser)
{
    int r;

    skip_spaces(parser);
    if (peek(parser) == '-') {
        ++parser->s;
        r = parse_pow_operand(parser);
        if (r != MB_OK) return r;
        if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
        return emit_op(parser, MB_BC_NEG);
    }
    return parse_primary(parser);
}

/* ^ is left-associative (2 ^ 3 ^ 2 is 64) and binds tighter than the unary
   minus: -2 ^ 2 is -4. */
static int parse_pow(ExprParser *parser)
{
    const MBOperatorInfo *op;
    int r;

    r = parse_primary(parser);
    if (r != MB_OK) return r;
    for (;;) {
        skip_spaces(parser);
        op = operator_by_text(parser->s, parser->end, MB_PREC_POW, MB_PREC_POW);
        if (op == 0) {
            return MB_OK;
        }
        if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
        parser->s += cstr_len(op->text);
        r = parse_pow_operand(parser);
        if (r != MB_OK) return r;
        if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
        r = emit_op(parser, op->opcode);
        if (r != MB_OK) return r;
    }
}

static int parse_unary(ExprParser *parser)
{
    int r;

    skip_spaces(parser);
    if (peek(parser) == '-') {
        ++parser->s;
        r = parse_unary(parser);
        if (r != MB_OK) return r;
        if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
        return emit_op(parser, MB_BC_NEG);
    }
    return parse_pow(parser);
}

static int parse_mul(ExprParser *parser)
{
    return parse_int_level(parser, MB_PREC_MUL, parse_unary);
}

static int parse_idiv(ExprParser *parser)
{
    return parse_int_level(parser, MB_PREC_IDIV, parse_mul);
}

static int parse_mod(ExprParser *parser)
{
    return parse_int_level(parser, MB_PREC_MODULO, parse_idiv);
}

static int parse_add(ExprParser *parser)
{
    int r;
    mb_u8 left_type;
    const MBOperatorInfo *op;

    r = parse_mod(parser);
    if (r != MB_OK) return r;

    for (;;) {
        skip_spaces(parser);
        op = operator_by_text(parser->s, parser->end, MB_PREC_ADD, MB_PREC_ADD);
        if (op == 0) {
            return MB_OK;
        }
        left_type = parser->type;
        parser->s += cstr_len(op->text);
        r = parse_mod(parser);
        if (r != MB_OK) return r;
        if (left_type == MB_T_STR || parser->type == MB_T_STR) {
            if (op->opcode != MB_BC_ADD || left_type != parser->type) {
                return MB_ERR_TYPE_MISMATCH;
            }
            r = emit_op(parser, MB_BC_CONCAT);
        } else {
            r = emit_op(parser, op->opcode);
        }
        if (r != MB_OK) return r;
    }
}

static int parse_shift(ExprParser *parser)
{
    return parse_int_level(parser, MB_PREC_SHIFT, parse_add);
}
static int parse_compare(ExprParser *parser)
{
    int r;
    mb_u8 left_type;
    mb_u8 opcode;
    const MBOperatorInfo *op;

    r = parse_shift(parser);
    if (r != MB_OK) return r;

    skip_spaces(parser);
    op = operator_by_text(parser->s, parser->end, MB_PREC_COMPARE, MB_PREC_COMPARE);
    if (op == 0) {
        return MB_OK;
    }
    left_type = parser->type;
    parser->s += cstr_len(op->text);

    r = parse_shift(parser);
    if (r != MB_OK) return r;
    if (left_type != parser->type) return MB_ERR_TYPE_MISMATCH;
    opcode = op->opcode;
    if (left_type == MB_T_STR) {
        if (opcode == MB_BC_EQ) {
            opcode = MB_BC_SEQ;
        } else if (opcode == MB_BC_NE) {
            opcode = MB_BC_SNE;
        } else if (opcode == MB_BC_LT) {
            opcode = MB_BC_SLT;
        } else if (opcode == MB_BC_LE) {
            opcode = MB_BC_SLE;
        } else if (opcode == MB_BC_GT) {
            opcode = MB_BC_SGT;
        } else {
            opcode = MB_BC_SGE;
        }
    }
    parser->type = MB_T_INT;
    return emit_op(parser, opcode);
}

/* NOT binds looser than the comparisons: NOT A = B is NOT (A = B). */
static int parse_not(ExprParser *parser)
{
    const char *word;
    int r;

    skip_spaces(parser);
    word = parser->s;
    if (peek(parser) != 0 && str_ieq_n(word, "NOT", 3) &&
        (parser->end == 0 || parser->end - word >= 3) &&
        !is_ident_tail(char_at(word + 3, parser->end))) {
        parser->s += 3;
        r = parse_not(parser);
        if (r != MB_OK) return r;
        if (parser->type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
        return emit_op(parser, MB_BC_NOT);
    }
    return parse_compare(parser);
}

static int parse_and(ExprParser *parser)
{
    return parse_int_level(parser, MB_PREC_AND, parse_not);
}

static int parse_or(ExprParser *parser)
{
    return parse_int_level(parser, MB_PREC_OR, parse_and);
}

static int parse_expr(ExprParser *parser)
{
    return parse_int_level(parser, MB_PREC_XOR, parse_or);
}

/* Compiles the expression in [text, end), or in the NUL-terminated text when end
   is 0. Its source may not reach MB_EXPR_TEXT_MAX characters: that is what LIST
   is able to decompile again. */
static int compile_expr_typed(MBProgram *program,
                              const char *text,
                              const char *end,
                              mb_u8 *out,
                              mb_u16 cap,
                              mb_u16 *out_len,
                              mb_u8 *type)
{
    ExprParser parser;
    mb_u16 text_len;
    int r;

    if (text == 0 || out == 0 || out_len == 0) {
        return MB_ERR_BAD_ARG;
    }
    if (end != 0 && end < text) {
        return MB_ERR_SYNTAX;
    }
    /* Only the significant text counts, not the blanks around it. */
    while (is_space(char_at(text, end))) {
        ++text;
    }
    text_len = end != 0 ? (mb_u16)(end - text) : cstr_len(text);
    while (text_len != 0 && is_space(text[text_len - 1u])) {
        --text_len;
    }
    if (text_len >= MB_EXPR_TEXT_MAX) {
        return MB_ERR_FULL;
    }

    parser.program = program;
    parser.s = text;
    parser.end = end;
    parser.out = out;
    parser.cap = cap;
    parser.len = 0;
    parser.type = MB_T_INT;

    r = parse_expr(&parser);
    if (r != MB_OK) return r;
    skip_spaces(&parser);
    if (peek(&parser) != 0) {
        return MB_ERR_SYNTAX;
    }
    r = emit_op(&parser, MB_BC_END);
    if (r != MB_OK) return r;

    *out_len = parser.len;
    *type = parser.type;
    return MB_OK;
}

static int compile_expr_for_program(MBProgram *program, const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    mb_u8 type;
    int r;

    r = compile_expr_typed(program, text, 0, out, cap, out_len, &type);
    if (r != MB_OK) return r;
    if (type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
    return MB_OK;
}

int mb_compile_expr(const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    return compile_expr_for_program(0, text, out, cap, out_len);
}

static int compile_expr_until_typed(MBProgram *program,
                                    const char *start,
                                    const char *end,
                                    mb_u8 *out,
                                    mb_u16 cap,
                                    mb_u16 *out_len,
                                    mb_u8 *type)
{
    return compile_expr_typed(program, start, end, out, cap, out_len, type);
}

/* s points at a '('; returns its matching ')' (outside quotes) or 0. */
static const char *find_matching_paren(const char *s)
{
    mb_u16 depth;

    depth = 0;
    while (*s != 0) {
        if (*s == '"') {
            ++s;
            while (*s != 0 && *s != '"') {
                ++s;
            }
            if (*s == 0) {
                return 0;
            }
        } else if (*s == '(') {
            ++depth;
        } else if (*s == ')') {
            --depth;
            if (depth == 0) {
                return s;
            }
        }
        ++s;
    }
    return 0;
}

static int compile_expr_until(MBProgram *program, const char *start, const char *end, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    mb_u8 type;
    int r;

    r = compile_expr_until_typed(program, start, end, out, cap, out_len, &type);
    if (r != MB_OK) return r;
    if (type != MB_T_INT) return MB_ERR_TYPE_MISMATCH;
    return MB_OK;
}

/* First ';' or ',' of a PRINT item list that is outside quotes and
   parentheses, or the terminating NUL. */
static const char *find_print_separator(const char *s)
{
    mb_u16 depth;

    depth = 0;
    while (*s != 0) {
        if (*s == '"') {
            ++s;
            while (*s != 0 && *s != '"') {
                ++s;
            }
            if (*s == 0) {
                return s;
            }
        } else if (*s == '(') {
            ++depth;
        } else if (*s == ')') {
            if (depth != 0) {
                --depth;
            }
        } else if ((*s == ';' || *s == ',') && depth == 0) {
            return s;
        }
        ++s;
    }
    return s;
}

static int emit_stmt_u8(mb_u8 *out, mb_u16 cap, mb_u16 *len, mb_u8 v)
{
    if (*len >= cap) {
        return MB_ERR_FULL;
    }
    out[*len] = v;
    ++*len;
    return MB_OK;
}

static int emit_stmt_u16(mb_u8 *out, mb_u16 cap, mb_u16 *len, mb_u16 v)
{
    int r;

    r = emit_stmt_u8(out, cap, len, (mb_u8)(v & 0xffu));
    if (r != MB_OK) return r;
    return emit_stmt_u8(out, cap, len, (mb_u8)((v >> 8) & 0xffu));
}

static const char *find_keyword_text(const char *s, mb_u8 opcode)
{
    const MBKeywordInfo *keyword;
    mb_u16 n;

    keyword = keyword_by_opcode(opcode);
    if (keyword == 0) {
        return 0;
    }
    n = cstr_len(keyword->text);
    while (*s != 0) {
        if (*s == '"') {
            ++s;
            while (*s != 0 && *s != '"') {
                ++s;
            }
            if (*s != 0) {
                ++s;
            }
            continue;
        }
        if (str_ieq_n(s, keyword->text, n) && !is_ident_tail(s[n])) {
            return s;
        }
        ++s;
    }
    return 0;
}

static int emit_statement_block(MBProgram *program,
                                const char *start,
                                const char *end,
                                mb_u8 *out,
                                mb_u16 cap,
                                mb_u16 *len)
{
    char tmp[MB_STMT_TEXT_MAX];
    mb_u8 stmt[MB_STMT_CODE_MAX];
    mb_u16 source_len;
    mb_u16 stmt_len;
    int r;

    if (end == 0) {
        source_len = cstr_len(start);
    } else {
        if (end < start) return MB_ERR_SYNTAX;
        source_len = (mb_u16)(end - start);
    }
    if (source_len >= sizeof(tmp)) {
        return MB_ERR_FULL;
    }
    copy_bytes((mb_u8 *)tmp, (const mb_u8 *)start, source_len);
    tmp[source_len] = 0;
    if (cstr_is_empty_after_spaces(tmp)) {
        return MB_ERR_SYNTAX;
    }

    r = compile_statement_for_program(program, tmp, stmt, sizeof(stmt), &stmt_len);
    if (r != MB_OK) return r;
    r = emit_stmt_u16(out, cap, len, stmt_len);
    if (r != MB_OK) return r;
    if ((mb_u16)(cap - *len) < stmt_len) {
        return MB_ERR_FULL;
    }
    copy_bytes(out + *len, stmt, stmt_len);
    *len = (mb_u16)(*len + stmt_len);
    return MB_OK;
}

static int compile_statement_for_program(MBProgram *program, const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    const char *s;
    const char *then_pos;
    const char *else_pos;
    const char *to_pos;
    const char *step_pos;
    mb_u16 len;
    mb_u16 expr_len;
    mb_u16 line;
    mb_u8 var;
    mb_u8 type;
    mb_u8 dim_op;
    mb_u8 flags;
    const char *close;
    int r;

    if (text == 0 || out == 0 || out_len == 0) {
        return MB_ERR_BAD_ARG;
    }

    s = text;
    len = 0;

    if (take_keyword(&s, MB_ST_REM)) {
        r = emit_stmt_u8(out, cap, &len, MB_ST_REM);
        if (r != MB_OK) return r;
        skip_cstr_spaces(&s);
        while (*s != 0) {
            r = emit_stmt_u8(out, cap, &len, (mb_u8)*s);
            if (r != MB_OK) return r;
            ++s;
        }
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_END)) {
        if (take_keyword(&s, MB_ST_IF)) {
            if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
            r = emit_stmt_u8(out, cap, &len, MB_ST_END_IF);
            if (r != MB_OK) return r;
            *out_len = len;
            return MB_OK;
        }
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_END);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_STOP)) {
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_STOP);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_PRINT)) {
        /* PRINT [item { ; item }] [;]  ->  PRINT flags { type expr }
           flags bit 0: no newline at the end */
        r = emit_stmt_u8(out, cap, &len, MB_ST_PRINT);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, 0);
        if (r != MB_OK) return r;
        for (;;) {
            skip_cstr_spaces(&s);
            if (*s == 0) {
                break;
            }
            then_pos = find_print_separator(s);
            r = emit_stmt_u8(out, cap, &len, MB_T_INT);
            if (r != MB_OK) return r;
            r = compile_expr_until_typed(program, s, then_pos, out + len, (mb_u16)(cap - len), &expr_len, &type);
            if (r != MB_OK) return r;
            out[len - 1u] = type;
            len = (mb_u16)(len + expr_len);
            if (*then_pos == ',') return MB_ERR_SYNTAX;
            if (*then_pos == 0) {
                break;
            }
            s = then_pos + 1;
            skip_cstr_spaces(&s);
            if (*s == 0) {
                out[1] = 1;
                break;
            }
        }
        *out_len = len;
        return MB_OK;
    }

    dim_op = 0;
    if (take_keyword(&s, MB_ST_DIM)) {
        dim_op = MB_ST_DIM;
    } else if (take_keyword(&s, MB_ST_REDIM)) {
        dim_op = MB_ST_REDIM;
    }
    if (dim_op != 0) {
        /* DIM name(n)   REDIM [PRESERVE] name(n)  ->  op var flags expr
           flags bit 0: PRESERVE, bit 1: string array */
        flags = 0;
        if (dim_op == MB_ST_REDIM && take_keyword(&s, MB_KW_PRESERVE)) {
            flags = (mb_u8)(flags | 1u);
        }
        r = parse_var_name(program, &s, &var);
        if (r != MB_OK) return r;
        if (var_is_string(program, var)) {
            flags = (mb_u8)(flags | 2u);
        }
        skip_cstr_spaces(&s);
        if (*s != '(') return MB_ERR_SYNTAX;
        close = find_matching_paren(s);
        if (close == 0) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, dim_op);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, var);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, flags);
        if (r != MB_OK) return r;
        r = compile_expr_until(program, s + 1, close, out + len, (mb_u16)(cap - len), &expr_len);
        if (r != MB_OK) return r;
        len = (mb_u16)(len + expr_len);
        s = close + 1;
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_ERASE)) {
        r = parse_var_name(program, &s, &var);
        if (r != MB_OK) return r;
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_ERASE);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, var);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_INPUT)) {
        /* INPUT [ "prompt" ; ] variable */
        const char *prompt;
        mb_u16 prompt_len;
        mb_u16 i;

        prompt = 0;
        prompt_len = 0;
        skip_cstr_spaces(&s);
        if (*s == '"') {
            ++s;
            prompt = s;
            while (*s != 0 && *s != '"') {
                ++s;
            }
            if (*s == 0) return MB_ERR_SYNTAX;
            prompt_len = (mb_u16)(s - prompt);
            ++s;
            if (prompt_len > MB_STRING_LITERAL_MAX) return MB_ERR_STRING_TOO_LONG;
            if (!take_char(&s, ';')) return MB_ERR_SYNTAX;
        }
        r = parse_var_name(program, &s, &var);
        if (r != MB_OK) return r;
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, var_is_string(program, var) ? MB_ST_INPUT_STR : MB_ST_INPUT);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, var);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, (mb_u8)prompt_len);
        if (r != MB_OK) return r;
        for (i = 0; i < prompt_len; ++i) {
            r = emit_stmt_u8(out, cap, &len, (mb_u8)prompt[i]);
            if (r != MB_OK) return r;
        }
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_GOTO)) {
        r = parse_u16_line_ref(&s, &line);
        if (r != MB_OK) return r;
        skip_cstr_spaces(&s);
        if (*s != 0) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_GOTO);
        if (r != MB_OK) return r;
        r = emit_stmt_u16(out, cap, &len, line);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_GOSUB)) {
        r = parse_u16_line_ref(&s, &line);
        if (r != MB_OK) return r;
        skip_cstr_spaces(&s);
        if (*s != 0) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_GOSUB);
        if (r != MB_OK) return r;
        r = emit_stmt_u16(out, cap, &len, line);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_ELSE)) {
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_ELSE);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_RETURN)) {
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_RETURN);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_WHILE)) {
        r = emit_stmt_u8(out, cap, &len, MB_ST_WHILE);
        if (r != MB_OK) return r;
        r = compile_expr_for_program(program, s, out + len, (mb_u16)(cap - len), &expr_len);
        if (r != MB_OK) return r;
        len = (mb_u16)(len + expr_len);
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_WEND)) {
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_WEND);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_FOR)) {
        r = parse_var_name(program, &s, &var);
        if (r != MB_OK) return r;
        if (var_is_string(program, var)) return MB_ERR_TYPE_MISMATCH;
        if (!take_char(&s, '=')) return MB_ERR_SYNTAX;
        to_pos = find_keyword_text(s, MB_KW_TO);
        if (to_pos == 0) return MB_ERR_SYNTAX;
        step_pos = find_keyword_text(to_pos, MB_KW_STEP);
        r = emit_stmt_u8(out, cap, &len, MB_ST_FOR);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, var);
        if (r != MB_OK) return r;
        r = compile_expr_until(program, s, to_pos, out + len, (mb_u16)(cap - len), &expr_len);
        if (r != MB_OK) return r;
        len = (mb_u16)(len + expr_len);
        s = to_pos;
        if (!take_keyword(&s, MB_KW_TO)) return MB_ERR_SYNTAX;
        if (step_pos != 0) {
            r = compile_expr_until(program, s, step_pos, out + len, (mb_u16)(cap - len), &expr_len);
        } else {
            r = compile_expr_for_program(program, s, out + len, (mb_u16)(cap - len), &expr_len);
        }
        if (r != MB_OK) return r;
        len = (mb_u16)(len + expr_len);
        if (step_pos != 0) {
            s = step_pos;
            if (!take_keyword(&s, MB_KW_STEP)) return MB_ERR_SYNTAX;
            r = compile_expr_for_program(program, s, out + len, (mb_u16)(cap - len), &expr_len);
            if (r != MB_OK) return r;
            len = (mb_u16)(len + expr_len);
        } else {
            r = emit_stmt_u8(out, cap, &len, MB_BC_PUSH_I32);
            if (r != MB_OK) return r;
            r = emit_stmt_u8(out, cap, &len, 1u);
            if (r != MB_OK) return r;
            r = emit_stmt_u8(out, cap, &len, 0u);
            if (r != MB_OK) return r;
            r = emit_stmt_u8(out, cap, &len, 0u);
            if (r != MB_OK) return r;
            r = emit_stmt_u8(out, cap, &len, 0u);
            if (r != MB_OK) return r;
            r = emit_stmt_u8(out, cap, &len, MB_BC_END);
            if (r != MB_OK) return r;
        }
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_NEXT)) {
        var = MB_NEXT_ANY;
        if (!cstr_is_empty_after_spaces(s)) {
            r = parse_var_name(program, &s, &var);
            if (r != MB_OK) return r;
            if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        }
        r = emit_stmt_u8(out, cap, &len, MB_ST_NEXT);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, var);
        if (r != MB_OK) return r;
        *out_len = len;
        return MB_OK;
    }

    if (take_keyword(&s, MB_ST_IF)) {
        then_pos = find_keyword_text(s, MB_KW_THEN);
        if (then_pos == 0) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_IF);
        if (r != MB_OK) return r;
        r = compile_expr_until(program, s, then_pos, out + len, (mb_u16)(cap - len), &expr_len);
        if (r != MB_OK) return r;
        len = (mb_u16)(len + expr_len);
        s = then_pos;
        if (!take_keyword(&s, MB_KW_THEN)) return MB_ERR_SYNTAX;
        if (cstr_is_empty_after_spaces(s)) {
            *out_len = len;
            out[0] = MB_ST_IF_BLOCK;
            return MB_OK;
        }
        else_pos = find_keyword_text(s, MB_KW_ELSE);
        r = emit_statement_block(program, s, else_pos, out, cap, &len);
        if (r != MB_OK) return r;
        if (else_pos != 0) {
            s = else_pos;
            if (!take_keyword(&s, MB_KW_ELSE)) return MB_ERR_SYNTAX;
            r = emit_statement_block(program, s, 0, out, cap, &len);
            if (r != MB_OK) return r;
        } else {
            r = emit_stmt_u16(out, cap, &len, 0);
            if (r != MB_OK) return r;
        }
        *out_len = len;
        return MB_OK;
    }

    take_keyword(&s, MB_ST_LET);
    r = parse_var_name(program, &s, &var);
    if (r != MB_OK) return r;
    skip_cstr_spaces(&s);
    if (*s == '(') {
        /* name(index) = value  ->  LET_ELEM var index value */
        close = find_matching_paren(s);
        if (close == 0) return MB_ERR_SYNTAX;
        r = emit_stmt_u8(out, cap, &len, MB_ST_LET_ELEM);
        if (r != MB_OK) return r;
        r = emit_stmt_u8(out, cap, &len, var);
        if (r != MB_OK) return r;
        r = compile_expr_until(program, s + 1, close, out + len, (mb_u16)(cap - len), &expr_len);
        if (r != MB_OK) return r;
        len = (mb_u16)(len + expr_len);
        s = close + 1;
        if (!take_char(&s, '=')) return MB_ERR_SYNTAX;
        r = compile_expr_typed(program, s, 0, out + len, (mb_u16)(cap - len), &expr_len, &type);
        if (r != MB_OK) return r;
        if (var_is_string(program, var)) {
            if (type != MB_T_STR) return MB_ERR_TYPE_MISMATCH;
            out[0] = MB_ST_LET_ELEM_STR;
        } else if (type != MB_T_INT) {
            return MB_ERR_TYPE_MISMATCH;
        }
        len = (mb_u16)(len + expr_len);
        *out_len = len;
        return MB_OK;
    }
    if (!take_char(&s, '=')) return MB_ERR_SYNTAX;
    r = emit_stmt_u8(out, cap, &len, MB_ST_LET);
    if (r != MB_OK) return r;
    r = emit_stmt_u8(out, cap, &len, var);
    if (r != MB_OK) return r;
    r = compile_expr_typed(program, s, 0, out + len, (mb_u16)(cap - len), &expr_len, &type);
    if (r != MB_OK) return r;
    if (var_is_string(program, var)) {
        if (type != MB_T_STR) return MB_ERR_TYPE_MISMATCH;
        out[0] = MB_ST_LET_STR;
    } else if (type != MB_T_INT) {
        return MB_ERR_TYPE_MISMATCH;
    }
    len = (mb_u16)(len + expr_len);
    *out_len = len;
    return MB_OK;
}

int mb_compile_statement(const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    return compile_statement_for_program(0, text, out, cap, out_len);
}

static mb_i32 read_i32(const mb_u8 *p)
{
    unsigned long v;

    v = (unsigned long)p[0]
      | ((unsigned long)p[1] << 8)
      | ((unsigned long)p[2] << 16)
      | ((unsigned long)p[3] << 24);
    return (mb_i32)v;
}

static int stack_push(mb_i32 *stack, mb_u16 *sp, mb_i32 v)
{
    if (*sp >= MB_EXPR_STACK_MAX) {
        return MB_ERR_STACK;
    }
    stack[*sp] = v;
    ++*sp;
    return MB_OK;
}

static int stack_pop(mb_i32 *stack, mb_u16 *sp, mb_i32 *v)
{
    if (*sp == 0) {
        return MB_ERR_STACK;
    }
    --*sp;
    *v = stack[*sp];
    return MB_OK;
}

static mb_i32 str_handle(mb_u16 off, mb_u16 len)
{
    if (len == 0) {
        return 0;
    }
    return (mb_i32)(((unsigned long)off << 16) | (unsigned long)len);
}

static mb_u16 str_handle_off(mb_i32 handle)
{
    return (mb_u16)(((unsigned long)handle >> 16) & 0xffffu);
}

static mb_u16 str_handle_len(mb_i32 handle)
{
    return (mb_u16)((unsigned long)handle & 0xffffu);
}

static int str_temp_alloc(MBRuntime *runtime, mb_u16 len, mb_u16 *off)
{
    if ((unsigned long)runtime->str_top + (unsigned long)len > (unsigned long)runtime->arr_base) {
        return MB_ERR_STRING_TOO_LONG;
    }
    *off = runtime->str_top;
    runtime->str_top = (mb_u16)(runtime->str_top + len);
    return MB_OK;
}

const char *mb_str_data(const MBRuntime *runtime, mb_i32 handle, mb_u16 *len)
{
    *len = str_handle_len(handle);
    return (const char *)(runtime->heap + str_handle_off(handle));
}

/* A view into an existing string: no copy, valid for as long as the string is. */
mb_i32 mb_str_slice(mb_i32 handle, mb_u16 start, mb_u16 len)
{
    if (len == 0 || (unsigned long)start + (unsigned long)len > (unsigned long)str_handle_len(handle)) {
        return 0;
    }
    return str_handle((mb_u16)(str_handle_off(handle) + start), len);
}

/* Reserves a temporary string of len bytes; the caller fills it in through
   the pointer that mb_str_data returns for the new handle. */
int mb_str_alloc(MBRuntime *runtime, mb_u16 len, mb_i32 *handle)
{
    mb_u16 off;
    int r;

    if (len == 0) {
        *handle = 0;
        return MB_OK;
    }
    r = str_temp_alloc(runtime, len, &off);
    if (r != MB_OK) return r;
    *handle = str_handle(off, len);
    return MB_OK;
}

int mb_str_make(MBRuntime *runtime, const char *text, mb_u16 len, mb_i32 *handle)
{
    int r;

    r = mb_str_alloc(runtime, len, handle);
    if (r != MB_OK || len == 0) return r;
    copy_bytes(runtime->heap + str_handle_off(*handle), (const mb_u8 *)text, len);
    return MB_OK;
}

static void write_i32(mb_u8 *p, mb_i32 v)
{
    unsigned long u;

    u = (unsigned long)v;
    p[0] = (mb_u8)(u & 0xffu);
    p[1] = (mb_u8)((u >> 8) & 0xffu);
    p[2] = (mb_u8)((u >> 16) & 0xffu);
    p[3] = (mb_u8)((u >> 24) & 0xffu);
}

static mb_i32 arr_get(const MBRuntime *runtime, mb_u16 off, mb_u16 index)
{
    return read_i32(runtime->heap + (mb_u16)(off + 4u * index));
}

static void arr_set(MBRuntime *runtime, mb_u16 off, mb_u16 index, mb_i32 value)
{
    write_i32(runtime->heap + (mb_u16)(off + 4u * index), value);
}

/* Slides the live strings down to the start of the heap, in ascending offset
   order so every copy moves towards lower addresses. The roots are the string
   variables and the elements of string arrays. Only valid between
   expressions: temporaries and handles in flight are lost. */
static void str_gc(MBRuntime *runtime)
{
    unsigned long next_min;
    unsigned long best_off;
    mb_u16 dst;
    mb_u16 off;
    mb_u16 len;
    mb_u16 i;
    mb_u16 j;
    mb_u16 best_index;
    mb_i32 handle;
    int best_var;
    int best_array;
    int found;

    dst = 0;
    next_min = 0;
    for (;;) {
        found = 0;
        best_var = -1;
        best_array = -1;
        best_off = 0;
        best_index = 0;
        for (i = 0; i < MB_VAR_COUNT; ++i) {
            if (runtime->str_var[i] && str_handle_len(runtime->vars[i]) != 0) {
                off = str_handle_off(runtime->vars[i]);
                if ((unsigned long)off >= next_min && (!found || (unsigned long)off < best_off)) {
                    found = 1;
                    best_var = (int)i;
                    best_array = -1;
                    best_off = off;
                }
            }
            if (runtime->arrays[i].count != 0 && runtime->arrays[i].is_str) {
                for (j = 0; j < runtime->arrays[i].count; ++j) {
                    handle = arr_get(runtime, runtime->arrays[i].off, j);
                    if (str_handle_len(handle) == 0) {
                        continue;
                    }
                    off = str_handle_off(handle);
                    if ((unsigned long)off >= next_min && (!found || (unsigned long)off < best_off)) {
                        found = 1;
                        best_var = -1;
                        best_array = (int)i;
                        best_index = j;
                        best_off = off;
                    }
                }
            }
        }
        if (!found) {
            break;
        }
        off = (mb_u16)best_off;
        if (best_var >= 0) {
            handle = runtime->vars[best_var];
        } else {
            handle = arr_get(runtime, runtime->arrays[best_array].off, best_index);
        }
        len = str_handle_len(handle);
        copy_bytes(runtime->heap + dst, runtime->heap + off, len);
        handle = str_handle(dst, len);
        if (best_var >= 0) {
            runtime->vars[best_var] = handle;
        } else {
            arr_set(runtime, runtime->arrays[best_array].off, best_index, handle);
        }
        dst = (mb_u16)(dst + len);
        next_min = (unsigned long)off + (unsigned long)len;
    }
    runtime->str_used = dst;
    runtime->str_top = dst;
    runtime->str_garbage = 0;
}

/* Copies a string value (a temporary or another variable's) into the
   persistent area and returns the handle of the copy. */
static int str_persist(MBRuntime *runtime, mb_i32 value, mb_i32 *out)
{
    mb_u16 off;
    mb_u16 len;

    len = str_handle_len(value);
    off = str_handle_off(value);
    if (len == 0) {
        *out = 0;
        return MB_OK;
    }
    if ((unsigned long)runtime->str_used + (unsigned long)len > (unsigned long)runtime->arr_base) {
        return MB_ERR_STRING_TOO_LONG;
    }
    copy_bytes(runtime->heap + runtime->str_used, runtime->heap + off, len);
    *out = str_handle(runtime->str_used, len);
    runtime->str_used = (mb_u16)(runtime->str_used + len);
    return MB_OK;
}

static int str_assign(MBRuntime *runtime, mb_u8 var, mb_i32 value)
{
    mb_i32 copy;
    int r;

    r = str_persist(runtime, value, &copy);
    if (r != MB_OK) return r;
    if (runtime->str_var[var]) {
        runtime->str_garbage = (mb_u16)(runtime->str_garbage + str_handle_len(runtime->vars[var]));
    }
    runtime->vars[var] = copy;
    runtime->str_var[var] = 1;
    return MB_OK;
}

/* Arrays live at the top of the heap, each block allocated below the previous
   one. Nothing holds a pointer to a block (every access goes through
   runtime->arrays), so freeing one just closes the gap by sliding the others
   up. */

static int arr_locate(const MBRuntime *runtime, mb_u8 var, mb_i32 index, mb_u16 *off)
{
    if (var >= MB_VAR_COUNT || runtime->arrays[var].count == 0) {
        return MB_ERR_NO_ARRAY;
    }
    if (index < 0 || index >= (mb_i32)runtime->arrays[var].count) {
        return MB_ERR_SUBSCRIPT;
    }
    *off = (mb_u16)(runtime->arrays[var].off + 4u * (mb_u16)index);
    return MB_OK;
}

/* The strings held by elements [from, count) of a are about to be dropped. */
static void arr_note_garbage(MBRuntime *runtime, const MBArray *a, mb_u16 from)
{
    mb_u16 i;

    if (!a->is_str) {
        return;
    }
    for (i = from; i < a->count; ++i) {
        runtime->str_garbage = (mb_u16)(runtime->str_garbage + str_handle_len(arr_get(runtime, a->off, i)));
    }
}

static void arr_compact(MBRuntime *runtime)
{
    unsigned long limit;
    unsigned long best_off;
    mb_u16 cursor;
    mb_u16 bytes;
    mb_u16 i;
    int best;

    cursor = MB_HEAP_SIZE;
    limit = (unsigned long)MB_HEAP_SIZE + 1ul;
    for (;;) {
        best = -1;
        best_off = 0;
        for (i = 0; i < MB_VAR_COUNT; ++i) {
            if (runtime->arrays[i].count != 0 && (unsigned long)runtime->arrays[i].off < limit &&
                (best < 0 || (unsigned long)runtime->arrays[i].off > best_off)) {
                best = (int)i;
                best_off = runtime->arrays[i].off;
            }
        }
        if (best < 0) {
            break;
        }
        bytes = (mb_u16)(4u * runtime->arrays[best].count);
        cursor = (mb_u16)(cursor - bytes);
        move_right(runtime->heap, cursor, runtime->arrays[best].off, bytes);
        limit = best_off;
        runtime->arrays[best].off = cursor;
    }
    runtime->arr_base = cursor;
}

/* Makes sure bytes more can be taken for arrays, counting reclaim bytes that
   are about to be freed; collects dead strings once if that is what it takes. */
static int arr_ensure_room(MBRuntime *runtime, unsigned long bytes, unsigned long reclaim)
{
    if (bytes <= (unsigned long)(runtime->arr_base - runtime->str_used) + reclaim) {
        return MB_OK;
    }
    if (runtime->str_garbage != 0) {
        str_gc(runtime);
        if (bytes <= (unsigned long)(runtime->arr_base - runtime->str_used) + reclaim) {
            return MB_OK;
        }
    }
    return MB_ERR_FULL;
}

static mb_u16 arr_carve(MBRuntime *runtime, mb_u16 count)
{
    mb_u16 bytes;
    mb_u16 i;

    bytes = (mb_u16)(4u * count);
    runtime->arr_base = (mb_u16)(runtime->arr_base - bytes);
    for (i = 0; i < bytes; ++i) {
        runtime->heap[(mb_u16)(runtime->arr_base + i)] = 0;
    }
    return runtime->arr_base;
}

static void arr_zero(MBRuntime *runtime, const MBArray *a)
{
    mb_u16 i;

    arr_note_garbage(runtime, a, 0);
    for (i = 0; i < a->count; ++i) {
        arr_set(runtime, a->off, i, 0);
    }
}

/* DIM and REDIM. n is the highest index, so the array has n + 1 elements.
   flags: bit 0 PRESERVE, bit 1 string array. */
static int arr_dim(MBRuntime *runtime, mb_u8 var, mb_u8 flags, mb_i32 n, int redim)
{
    MBArray old;
    mb_u16 count;
    mb_u16 off;
    mb_u16 keep;
    mb_u16 i;
    unsigned long bytes;
    int is_str;
    int r;

    if (var >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
    if (n < 0) return MB_ERR_BAD_ARG;
    if (n >= 0x3fff) return MB_ERR_FULL;
    count = (mb_u16)(n + 1);
    bytes = 4ul * (unsigned long)count;
    is_str = (flags & 2u) != 0;
    old = runtime->arrays[var];

    if (old.count == 0) {
        r = arr_ensure_room(runtime, bytes, 0);
        if (r != MB_OK) return r;
        off = arr_carve(runtime, count);
        runtime->arrays[var].off = off;
        runtime->arrays[var].count = count;
        runtime->arrays[var].is_str = (mb_u8)is_str;
        return MB_OK;
    }
    if (old.count == count) {
        if (!(redim && (flags & 1u) != 0)) {
            arr_zero(runtime, &old);
        }
        return MB_OK;
    }
    if (!redim) {
        return MB_ERR_ARRAY_EXISTS;
    }

    if ((flags & 1u) != 0) {
        /* Both blocks exist for a moment; the old one is closed up afterwards. */
        r = arr_ensure_room(runtime, bytes, 0);
        if (r != MB_OK) return r;
        off = arr_carve(runtime, count);
        keep = old.count < count ? old.count : count;
        for (i = 0; i < keep; ++i) {
            arr_set(runtime, off, i, arr_get(runtime, old.off, i));
        }
        arr_note_garbage(runtime, &old, keep);
        runtime->arrays[var].off = off;
        runtime->arrays[var].count = count;
        runtime->arrays[var].is_str = (mb_u8)is_str;
        arr_compact(runtime);
        return MB_OK;
    }

    r = arr_ensure_room(runtime, bytes, 4ul * (unsigned long)old.count);
    if (r != MB_OK) return r;
    arr_note_garbage(runtime, &old, 0);
    runtime->arrays[var].count = 0;
    arr_compact(runtime);
    off = arr_carve(runtime, count);
    runtime->arrays[var].off = off;
    runtime->arrays[var].count = count;
    runtime->arrays[var].is_str = (mb_u8)is_str;
    return MB_OK;
}

static int arr_erase(MBRuntime *runtime, mb_u8 var)
{
    if (var >= MB_VAR_COUNT || runtime->arrays[var].count == 0) {
        return MB_ERR_NO_ARRAY;
    }
    arr_note_garbage(runtime, &runtime->arrays[var], 0);
    runtime->arrays[var].count = 0;
    arr_compact(runtime);
    return MB_OK;
}
/* Classic BASIC: true is -1 (all bits set) so that AND, OR, XOR and NOT work
   both on conditions and on bits. */
static mb_i32 truth(int condition)
{
    return condition ? -1 : 0;
}

/* Integer power by repeated squaring, wrapping like the other operations. A
   negative exponent gives the integer part of the result: 0, except for 1 and
   -1, and 0 to a negative power is a division by zero. */
static int int_pow(mb_i32 base, mb_i32 exponent, mb_i32 *result)
{
    unsigned long acc;
    unsigned long b;
    unsigned long e;

    if (exponent < 0) {
        if (base == 0) return MB_ERR_DIV_ZERO;
        if (base == 1) *result = 1;
        else if (base == -1) *result = (exponent & 1) != 0 ? -1 : 1;
        else *result = 0;
        return MB_OK;
    }
    acc = 1ul;
    b = (unsigned long)base;
    e = (unsigned long)exponent;
    while (e != 0) {
        if ((e & 1ul) != 0) {
            acc *= b;
        }
        b *= b;
        e >>= 1;
    }
    *result = (mb_i32)acc;
    return MB_OK;
}

/* << and >>. The right shift keeps the sign; counts of 32 or more shift
   everything out and a negative count is an error. */
static int int_shift(mb_i32 value, mb_i32 count, int left, mb_i32 *result)
{
    if (count < 0) return MB_ERR_BAD_ARG;
    if (count > 31) {
        *result = (left || value >= 0) ? 0 : -1;
        return MB_OK;
    }
    if (left) {
        *result = (mb_i32)((unsigned long)value << count);
    } else if (value >= 0) {
        *result = (mb_i32)((unsigned long)value >> count);
    } else {
        *result = (mb_i32)(~(~(unsigned long)value >> count));
    }
    return MB_OK;
}

static int eval_expr_once(const MBProgram *program, const mb_u8 *code, mb_u16 len, MBRuntime *runtime, mb_i32 *result)
{
    mb_i32 stack[MB_EXPR_STACK_MAX];
    mb_i32 args[MB_BUILTIN_ARG_MAX];
    int cmp;
    mb_u8 ca;
    mb_u8 cb;
    mb_u16 sp;
    mb_u16 pc;
    mb_u16 n;
    mb_u16 off;
    mb_u16 la;
    mb_u16 lb;
    mb_u8 id;
    mb_u8 argc;
    mb_u8 i;
    mb_i32 a;
    mb_i32 b;
    mb_u8 op;
    int r;

    if (code == 0 || runtime == 0 || result == 0) {
        return MB_ERR_BAD_ARG;
    }

    runtime->str_top = runtime->str_used;
    sp = 0;
    pc = 0;
    while (pc < len) {
        op = code[pc];
        ++pc;
        switch (op) {
        case MB_BC_END:
            if (sp != 1) {
                return MB_ERR_STACK;
            }
            return stack_pop(stack, &sp, result);
        case MB_BC_PUSH_I32:
            if ((mb_u16)(len - pc) < 4u) return MB_ERR_SYNTAX;
            r = stack_push(stack, &sp, read_i32(code + pc));
            if (r != MB_OK) return r;
            pc = (mb_u16)(pc + 4u);
            break;
        case MB_BC_PUSH_VAR:
            if (pc >= len) return MB_ERR_SYNTAX;
            if (code[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
            r = stack_push(stack, &sp, runtime->vars[code[pc]]);
            if (r != MB_OK) return r;
            ++pc;
            break;
        case MB_BC_CALL_BUILTIN:
            if ((mb_u16)(len - pc) < 2u) return MB_ERR_SYNTAX;
            id = code[pc];
            ++pc;
            argc = code[pc];
            ++pc;
            if (program == 0 || program->builtins == 0 || id >= program->builtin_count) {
                return MB_ERR_BAD_BUILTIN;
            }
            if (argc < program->builtins[id].min_args || argc > program->builtins[id].max_args ||
                argc > MB_BUILTIN_ARG_MAX) {
                return MB_ERR_BAD_BUILTIN;
            }
            i = argc;
            while (i != 0) {
                --i;
                r = stack_pop(stack, &sp, &args[i]);
                if (r != MB_OK) return r;
            }
            r = program->builtins[id].fn(runtime, args, argc, &a);
            if (r != MB_OK) return r;
            r = stack_push(stack, &sp, a);
            if (r != MB_OK) return r;
            break;
        case MB_BC_PUSH_ELEM:
            if (pc >= len) return MB_ERR_SYNTAX;
            id = code[pc];
            ++pc;
            r = stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            r = arr_locate(runtime, id, a, &off);
            if (r != MB_OK) return r;
            r = stack_push(stack, &sp, read_i32(runtime->heap + off));
            if (r != MB_OK) return r;
            break;
        case MB_BC_PUSH_STR:
            if (pc >= len) return MB_ERR_SYNTAX;
            n = code[pc];
            ++pc;
            if ((mb_u16)(len - pc) < n) return MB_ERR_SYNTAX;
            off = 0;
            if (n != 0) {
                r = str_temp_alloc(runtime, n, &off);
                if (r != MB_OK) return r;
                copy_bytes(runtime->heap + off, code + pc, n);
            }
            r = stack_push(stack, &sp, str_handle(off, n));
            if (r != MB_OK) return r;
            pc = (mb_u16)(pc + n);
            break;
        case MB_BC_CONCAT:
            r = stack_pop(stack, &sp, &b);
            if (r != MB_OK) return r;
            r = stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            la = str_handle_len(a);
            lb = str_handle_len(b);
            off = 0;
            if (la != 0 || lb != 0) {
                r = str_temp_alloc(runtime, (mb_u16)(la + lb), &off);
                if (r != MB_OK) return r;
                copy_bytes(runtime->heap + off, runtime->heap + str_handle_off(a), la);
                copy_bytes(runtime->heap + off + la, runtime->heap + str_handle_off(b), lb);
            }
            r = stack_push(stack, &sp, str_handle(off, (mb_u16)(la + lb)));
            if (r != MB_OK) return r;
            break;
        case MB_BC_SEQ:
        case MB_BC_SNE:
        case MB_BC_SLT:
        case MB_BC_SLE:
        case MB_BC_SGT:
        case MB_BC_SGE:
            r = stack_pop(stack, &sp, &b);
            if (r != MB_OK) return r;
            r = stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            la = str_handle_len(a);
            lb = str_handle_len(b);
            cmp = 0;
            for (off = 0; off < la && off < lb; ++off) {
                ca = runtime->heap[(mb_u16)(str_handle_off(a) + off)];
                cb = runtime->heap[(mb_u16)(str_handle_off(b) + off)];
                if (ca != cb) {
                    cmp = ca < cb ? -1 : 1;
                    break;
                }
            }
            if (cmp == 0 && la != lb) {
                cmp = la < lb ? -1 : 1;
            }
            if (op == MB_BC_SEQ) r = stack_push(stack, &sp, truth(cmp == 0));
            else if (op == MB_BC_SNE) r = stack_push(stack, &sp, truth(cmp != 0));
            else if (op == MB_BC_SLT) r = stack_push(stack, &sp, truth(cmp < 0));
            else if (op == MB_BC_SLE) r = stack_push(stack, &sp, truth(cmp <= 0));
            else if (op == MB_BC_SGT) r = stack_push(stack, &sp, truth(cmp > 0));
            else r = stack_push(stack, &sp, truth(cmp >= 0));
            if (r != MB_OK) return r;
            break;
        case MB_BC_NEG:
        case MB_BC_NOT:
            r = stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            r = stack_push(stack, &sp, op == MB_BC_NEG ? -a : ~a);
            if (r != MB_OK) return r;
            break;
        case MB_BC_ADD:
        case MB_BC_SUB:
        case MB_BC_MUL:
        case MB_BC_DIV:
        case MB_BC_IDIV:
        case MB_BC_MOD:
        case MB_BC_POW:
        case MB_BC_SHL:
        case MB_BC_SHR:
        case MB_BC_AND:
        case MB_BC_OR:
        case MB_BC_XOR:
        case MB_BC_EQ:
        case MB_BC_NE:
        case MB_BC_LT:
        case MB_BC_LE:
        case MB_BC_GT:
        case MB_BC_GE:
            r = stack_pop(stack, &sp, &b);
            if (r != MB_OK) return r;
            r = stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            if (op == MB_BC_ADD) r = stack_push(stack, &sp, (mb_i32)(a + b));
            else if (op == MB_BC_SUB) r = stack_push(stack, &sp, (mb_i32)(a - b));
            else if (op == MB_BC_MUL) r = stack_push(stack, &sp, (mb_i32)(a * b));
            else if (op == MB_BC_DIV || op == MB_BC_IDIV) {
                if (b == 0) return MB_ERR_DIV_ZERO;
                r = stack_push(stack, &sp, (mb_i32)(a / b));
            } else if (op == MB_BC_POW) {
                r = int_pow(a, b, &a);
                if (r != MB_OK) return r;
                r = stack_push(stack, &sp, a);
            } else if (op == MB_BC_SHL || op == MB_BC_SHR) {
                r = int_shift(a, b, op == MB_BC_SHL, &a);
                if (r != MB_OK) return r;
                r = stack_push(stack, &sp, a);
            } else if (op == MB_BC_MOD) {
                if (b == 0) return MB_ERR_DIV_ZERO;
                r = stack_push(stack, &sp, (mb_i32)(a % b));
            } else if (op == MB_BC_AND) r = stack_push(stack, &sp, (mb_i32)(a & b));
            else if (op == MB_BC_OR) r = stack_push(stack, &sp, (mb_i32)(a | b));
            else if (op == MB_BC_XOR) r = stack_push(stack, &sp, (mb_i32)(a ^ b));
            else if (op == MB_BC_EQ) r = stack_push(stack, &sp, truth(a == b));
            else if (op == MB_BC_NE) r = stack_push(stack, &sp, truth(a != b));
            else if (op == MB_BC_LT) r = stack_push(stack, &sp, truth(a < b));
            else if (op == MB_BC_LE) r = stack_push(stack, &sp, truth(a <= b));
            else if (op == MB_BC_GT) r = stack_push(stack, &sp, truth(a > b));
            else r = stack_push(stack, &sp, truth(a >= b));
            if (r != MB_OK) return r;
            break;        default:
            return MB_ERR_SYNTAX;
        }
    }

    return MB_ERR_SYNTAX;
}

static int eval_expr_for_program(const MBProgram *program, const mb_u8 *code, mb_u16 len, MBRuntime *runtime, mb_i32 *result)
{
    int r;

    r = eval_expr_once(program, code, len, runtime, result);
    if (r == MB_ERR_STRING_TOO_LONG && runtime != 0 && runtime->str_garbage != 0) {
        /* Nothing is in flight between attempts: reclaim the dead strings
           and evaluate again from scratch. */
        str_gc(runtime);
        r = eval_expr_once(program, code, len, runtime, result);
    }
    return r;
}

int mb_eval_expr(const mb_u8 *code, mb_u16 len, MBRuntime *runtime, mb_i32 *result)
{
    return eval_expr_for_program(0, code, len, runtime, result);
}

static int expr_len(const mb_u8 *code, mb_u16 len, mb_u16 *used)
{
    mb_u16 pc;
    mb_u8 op;

    pc = 0;
    while (pc < len) {
        op = code[pc];
        ++pc;
        if (op == MB_BC_END) {
            *used = pc;
            return MB_OK;
        }
        if (op == MB_BC_PUSH_I32) {
            if ((mb_u16)(len - pc) < 4u) return MB_ERR_SYNTAX;
            pc = (mb_u16)(pc + 4u);
        } else if (op == MB_BC_PUSH_VAR || op == MB_BC_PUSH_ELEM) {
            if (pc >= len) return MB_ERR_SYNTAX;
            ++pc;
        } else if (op == MB_BC_CALL_BUILTIN) {
            if ((mb_u16)(len - pc) < 2u) return MB_ERR_SYNTAX;
            pc = (mb_u16)(pc + 2u);
        } else if (op == MB_BC_PUSH_STR) {
            if (pc >= len) return MB_ERR_SYNTAX;
            if ((mb_u16)(len - pc - 1u) < code[pc]) return MB_ERR_SYNTAX;
            pc = (mb_u16)(pc + 1u + code[pc]);
        } else if (bc_is_binary(op) || bc_is_unary(op)) {
        } else {
            return MB_ERR_SYNTAX;
        }
    }
    return MB_ERR_SYNTAX;
}

static mb_u16 read_u16(const mb_u8 *p);

typedef struct DecompExpr DecompExpr;

struct DecompExpr {
    char text[MB_EXPR_TEXT_MAX];
    mb_u8 prec;
};

static int append_char_buf(char *out, mb_u16 cap, mb_u16 *len, char c)
{
    if (*len + 1u >= cap) {
        return MB_ERR_FULL;
    }
    out[*len] = c;
    ++*len;
    out[*len] = 0;
    return MB_OK;
}

static int append_text_buf(char *out, mb_u16 cap, mb_u16 *len, const char *s)
{
    int r;

    while (*s != 0) {
        r = append_char_buf(out, cap, len, *s);
        if (r != MB_OK) return r;
        ++s;
    }
    return MB_OK;
}

static int append_bytes_buf(char *out, mb_u16 cap, mb_u16 *len, const mb_u8 *s, mb_u16 n)
{
    mb_u16 i;
    int r;

    for (i = 0; i < n; ++i) {
        r = append_char_buf(out, cap, len, (char)s[i]);
        if (r != MB_OK) return r;
    }
    return MB_OK;
}

static int append_u16_buf(char *out, mb_u16 cap, mb_u16 *len, mb_u16 value)
{
    char buf[6];
    mb_u16 n;
    int r;

    if (value == 0) {
        return append_char_buf(out, cap, len, '0');
    }

    n = 0;
    while (value != 0 && n < sizeof(buf)) {
        buf[n] = (char)('0' + (value % 10u));
        value = (mb_u16)(value / 10u);
        ++n;
    }
    while (n != 0) {
        --n;
        r = append_char_buf(out, cap, len, buf[n]);
        if (r != MB_OK) return r;
    }
    return MB_OK;
}

static int append_i32_buf(char *out, mb_u16 cap, mb_u16 *len, mb_i32 value)
{
    unsigned long v;
    char buf[16];
    mb_u16 n;
    int r;

    if (value < 0) {
        r = append_char_buf(out, cap, len, '-');
        if (r != MB_OK) return r;
        v = (unsigned long)(-value);
    } else {
        v = (unsigned long)value;
    }

    if (v == 0) {
        return append_char_buf(out, cap, len, '0');
    }

    n = 0;
    while (v != 0 && n < sizeof(buf)) {
        buf[n] = (char)('0' + (v % 10u));
        v = v / 10u;
        ++n;
    }
    while (n != 0) {
        --n;
        r = append_char_buf(out, cap, len, buf[n]);
        if (r != MB_OK) return r;
    }
    return MB_OK;
}

static int expr_stack_push(DecompExpr *stack, mb_u16 *sp, const char *text, mb_u8 prec)
{
    mb_u16 len;

    if (*sp >= MB_EXPR_STACK_MAX) {
        return MB_ERR_STACK;
    }
    len = 0;
    stack[*sp].text[0] = 0;
    if (append_text_buf(stack[*sp].text, sizeof(stack[*sp].text), &len, text) != MB_OK) {
        return MB_ERR_FULL;
    }
    stack[*sp].prec = prec;
    ++*sp;
    return MB_OK;
}

static int expr_stack_pop(DecompExpr *stack, mb_u16 *sp, DecompExpr *value)
{
    if (*sp == 0) {
        return MB_ERR_STACK;
    }
    --*sp;
    *value = stack[*sp];
    return MB_OK;
}

static mb_u8 decomp_canonical_op(mb_u8 op)
{
    if (op == MB_BC_CONCAT) return MB_BC_ADD;
    if (op == MB_BC_SEQ) return MB_BC_EQ;
    if (op == MB_BC_SNE) return MB_BC_NE;
    if (op == MB_BC_SLT) return MB_BC_LT;
    if (op == MB_BC_SLE) return MB_BC_LE;
    if (op == MB_BC_SGT) return MB_BC_GT;
    if (op == MB_BC_SGE) return MB_BC_GE;
    return op;
}

static mb_u8 decomp_prec(mb_u8 op)
{
    const MBOperatorInfo *info;

    op = decomp_canonical_op(op);
    info = operator_by_opcode(op);
    if (info != 0) return info->prec;
    if (op == MB_BC_NEG) {
        return MB_PREC_NEG;
    }
    if (op == MB_BC_NOT) {
        return MB_PREC_NOT;
    }
    return MB_PREC_ATOM;
}

static const char *decomp_op_text(mb_u8 op)
{
    const MBOperatorInfo *info;

    op = decomp_canonical_op(op);
    info = operator_by_opcode(op);
    if (info != 0) return info->text;
    return "?";
}

static int append_operator_buf(char *out, mb_u16 cap, mb_u16 *len, mb_u8 op)
{
    int r;

    r = append_char_buf(out, cap, len, ' ');
    if (r != MB_OK) return r;
    r = append_text_buf(out, cap, len, decomp_op_text(op));
    if (r != MB_OK) return r;
    return append_char_buf(out, cap, len, ' ');
}

static int append_operand(char *out, mb_u16 cap, mb_u16 *len, const DecompExpr *expr, mb_u8 parent_prec, int right)
{
    int paren;
    int r;

    paren = expr->prec < parent_prec || (right && expr->prec == parent_prec);
    if (paren) {
        r = append_char_buf(out, cap, len, '(');
        if (r != MB_OK) return r;
    }
    r = append_text_buf(out, cap, len, expr->text);
    if (r != MB_OK) return r;
    if (paren) {
        r = append_char_buf(out, cap, len, ')');
        if (r != MB_OK) return r;
    }
    return MB_OK;
}

static int decompile_expr(const MBProgram *program, const mb_u8 *code, mb_u16 len, mb_u16 *used, char *out, mb_u16 cap)
{
    DecompExpr stack[MB_EXPR_STACK_MAX];
    DecompExpr args[MB_BUILTIN_ARG_MAX];
    DecompExpr a;
    DecompExpr b;
    mb_u16 sp;
    mb_u16 pc;
    mb_u16 text_len;
    mb_i32 number;
    mb_u8 op;
    mb_u8 id;
    mb_u8 argc;
    mb_u8 i;
    mb_u8 prec;
    int r;

    sp = 0;
    pc = 0;
    out[0] = 0;
    while (pc < len) {
        op = code[pc];
        ++pc;
        if (op == MB_BC_END) {
            if (sp != 1) return MB_ERR_STACK;
            r = expr_stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            text_len = 0;
            out[0] = 0;
            r = append_text_buf(out, cap, &text_len, a.text);
            if (r != MB_OK) return r;
            *used = pc;
            return MB_OK;
        }
        if (op == MB_BC_PUSH_I32) {
            if ((mb_u16)(len - pc) < 4u) return MB_ERR_SYNTAX;
            number = read_i32(code + pc);
            pc = (mb_u16)(pc + 4u);
            text_len = 0;
            out[0] = 0;
            r = append_i32_buf(out, cap, &text_len, number);
            if (r != MB_OK) return r;
            r = expr_stack_push(stack, &sp, out, MB_PREC_ATOM);
            if (r != MB_OK) return r;
        } else if (op == MB_BC_PUSH_STR) {
            if (pc >= len) return MB_ERR_SYNTAX;
            argc = code[pc];
            ++pc;
            if ((mb_u16)(len - pc) < argc) return MB_ERR_SYNTAX;
            text_len = 0;
            out[0] = 0;
            r = append_char_buf(out, cap, &text_len, '"');
            if (r != MB_OK) return r;
            r = append_bytes_buf(out, cap, &text_len, code + pc, argc);
            if (r != MB_OK) return r;
            r = append_char_buf(out, cap, &text_len, '"');
            if (r != MB_OK) return r;
            pc = (mb_u16)(pc + argc);
            r = expr_stack_push(stack, &sp, out, MB_PREC_ATOM);
            if (r != MB_OK) return r;
        } else if (op == MB_BC_PUSH_ELEM) {
            if (pc >= len || code[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
            r = expr_stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            text_len = 0;
            out[0] = 0;
            r = append_text_buf(out, cap, &text_len, symbol_name(program, code[pc]));
            if (r != MB_OK) return r;
            r = append_char_buf(out, cap, &text_len, '(');
            if (r != MB_OK) return r;
            r = append_text_buf(out, cap, &text_len, a.text);
            if (r != MB_OK) return r;
            r = append_char_buf(out, cap, &text_len, ')');
            if (r != MB_OK) return r;
            ++pc;
            r = expr_stack_push(stack, &sp, out, MB_PREC_ATOM);
            if (r != MB_OK) return r;
        } else if (op == MB_BC_PUSH_VAR) {
            if (pc >= len || code[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
            r = expr_stack_push(stack, &sp, symbol_name(program, code[pc]), MB_PREC_ATOM);
            if (r != MB_OK) return r;
            ++pc;
        } else if (op == MB_BC_CALL_BUILTIN) {
            if ((mb_u16)(len - pc) < 2u) return MB_ERR_SYNTAX;
            id = code[pc];
            ++pc;
            argc = code[pc];
            ++pc;
            if (argc > MB_BUILTIN_ARG_MAX) return MB_ERR_BAD_BUILTIN;
            i = argc;
            while (i != 0) {
                --i;
                r = expr_stack_pop(stack, &sp, &args[i]);
                if (r != MB_OK) return r;
            }
            text_len = 0;
            out[0] = 0;
            r = append_text_buf(out, cap, &text_len, builtin_name(program, id));
            if (r != MB_OK) return r;
            r = append_char_buf(out, cap, &text_len, '(');
            if (r != MB_OK) return r;
            for (i = 0; i < argc; ++i) {
                if (i != 0) {
                    r = append_text_buf(out, cap, &text_len, ", ");
                    if (r != MB_OK) return r;
                }
                r = append_text_buf(out, cap, &text_len, args[i].text);
                if (r != MB_OK) return r;
            }
            r = append_char_buf(out, cap, &text_len, ')');
            if (r != MB_OK) return r;
            r = expr_stack_push(stack, &sp, out, MB_PREC_ATOM);
            if (r != MB_OK) return r;
        } else if (bc_is_unary(op)) {
            r = expr_stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            prec = decomp_prec(op);
            text_len = 0;
            out[0] = 0;
            r = append_text_buf(out, cap, &text_len, op == MB_BC_NEG ? "-" : "NOT ");
            if (r != MB_OK) return r;
            r = append_operand(out, cap, &text_len, &a, prec, 0);
            if (r != MB_OK) return r;
            r = expr_stack_push(stack, &sp, out, prec);
            if (r != MB_OK) return r;
        } else if (bc_is_binary(op)) {
            r = expr_stack_pop(stack, &sp, &b);
            if (r != MB_OK) return r;
            r = expr_stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            prec = decomp_prec(op);
            text_len = 0;
            out[0] = 0;
            r = append_operand(out, cap, &text_len, &a, prec, 0);
            if (r != MB_OK) return r;
            r = append_operator_buf(out, cap, &text_len, op);
            if (r != MB_OK) return r;
            r = append_operand(out, cap, &text_len, &b, prec, 1);
            if (r != MB_OK) return r;
            r = expr_stack_push(stack, &sp, out, prec);
            if (r != MB_OK) return r;
        } else {
            return MB_ERR_SYNTAX;
        }
    }

    return MB_ERR_SYNTAX;
}

static int decompile_statement_for_program(const MBProgram *program, const mb_u8 *code, mb_u16 len, char *out, mb_u16 cap)
{
    const mb_u8 *stmt;
    const MBKeywordInfo *keyword;
    const MBKeywordInfo *then_keyword;
    const MBKeywordInfo *else_keyword;
    mb_u16 stmt_len;
    mb_u16 pc;
    mb_u16 used;
    mb_u16 out_len;
    char expr[MB_LINE_TEXT_MAX];
    char expr2[MB_EXPR_TEXT_MAX];
    char expr3[MB_EXPR_TEXT_MAX];
    int r;

    if (code == 0 || out == 0) {
        return MB_ERR_BAD_ARG;
    }
    if (cap == 0) {
        return MB_ERR_FULL;
    }

    stmt = payload_stmt_code(code, len, &stmt_len);
    if (stmt_len == 0) {
        out[0] = 0;
        return MB_OK;
    }

    out[0] = 0;
    out_len = 0;
    pc = 1;

    if (stmt[0] == MB_ST_LET || stmt[0] == MB_ST_LET_STR) {
        keyword = keyword_by_opcode(MB_ST_LET);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if (pc >= stmt_len || stmt[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, symbol_name(program, stmt[pc]));
        if (r != MB_OK) return r;
        ++pc;
        r = append_text_buf(out, cap, &out_len, " = ");
        if (r != MB_OK) return r;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, expr);
    }

    if (stmt[0] == MB_ST_REM) {
        keyword = keyword_by_opcode(MB_ST_REM);
        if (keyword == 0) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        if (stmt_len > 1u) {
            r = append_char_buf(out, cap, &out_len, ' ');
            if (r != MB_OK) return r;
            return append_bytes_buf(out, cap, &out_len, stmt + 1u, (mb_u16)(stmt_len - 1u));
        }
        return MB_OK;
    }

    if (stmt[0] == MB_ST_END || stmt[0] == MB_ST_STOP) {
        keyword = keyword_by_opcode(stmt[0]);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if (stmt_len != 1u) return MB_ERR_SYNTAX;
        return append_text_buf(out, cap, &out_len, keyword->text);
    }

    if (stmt[0] == MB_ST_ELSE || stmt[0] == MB_ST_END_IF) {
        keyword = keyword_by_opcode(stmt[0]);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if (stmt_len != 1u) return MB_ERR_SYNTAX;
        return append_text_buf(out, cap, &out_len, keyword->text);
    }

    if (stmt[0] == MB_ST_PRINT) {
        keyword = keyword_by_opcode(MB_ST_PRINT);
        if (keyword == 0 || stmt_len < 2u) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        pc = 2;
        while (pc < stmt_len) {
            ++pc;
            r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
            if (r != MB_OK) return r;
            pc = (mb_u16)(pc + used);
            r = append_text_buf(out, cap, &out_len, out_len == cstr_len(keyword->text) ? " " : "; ");
            if (r != MB_OK) return r;
            r = append_text_buf(out, cap, &out_len, expr);
            if (r != MB_OK) return r;
        }
        if ((stmt[1] & 1u) != 0) {
            return append_char_buf(out, cap, &out_len, ';');
        }
        return MB_OK;
    }

    if (stmt[0] == MB_ST_INPUT || stmt[0] == MB_ST_INPUT_STR) {
        keyword = keyword_by_opcode(MB_ST_INPUT);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if ((mb_u16)(stmt_len - pc) < 2u || stmt[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        if ((mb_u16)(stmt_len - pc - 2u) < stmt[pc + 1u]) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        if (stmt[pc + 1u] != 0) {
            r = append_char_buf(out, cap, &out_len, '"');
            if (r != MB_OK) return r;
            r = append_bytes_buf(out, cap, &out_len, stmt + pc + 2u, stmt[pc + 1u]);
            if (r != MB_OK) return r;
            r = append_text_buf(out, cap, &out_len, "\"; ");
            if (r != MB_OK) return r;
        }
        return append_text_buf(out, cap, &out_len, symbol_name(program, stmt[pc]));
    }

    if (stmt[0] == MB_ST_DIM || stmt[0] == MB_ST_REDIM) {
        keyword = keyword_by_opcode(stmt[0]);
        then_keyword = keyword_by_opcode(MB_KW_PRESERVE);
        if (keyword == 0 || then_keyword == 0 || stmt_len < 4u || stmt[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        if ((stmt[2] & 1u) != 0) {
            r = append_text_buf(out, cap, &out_len, then_keyword->text);
            if (r != MB_OK) return r;
            r = append_char_buf(out, cap, &out_len, ' ');
            if (r != MB_OK) return r;
        }
        r = append_text_buf(out, cap, &out_len, symbol_name(program, stmt[1]));
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, '(');
        if (r != MB_OK) return r;
        r = decompile_expr(program, stmt + 3, (mb_u16)(stmt_len - 3u), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, expr);
        if (r != MB_OK) return r;
        return append_char_buf(out, cap, &out_len, ')');
    }

    if (stmt[0] == MB_ST_ERASE) {
        keyword = keyword_by_opcode(MB_ST_ERASE);
        if (keyword == 0 || stmt_len != 2u || stmt[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, symbol_name(program, stmt[1]));
    }

    if (stmt[0] == MB_ST_LET_ELEM || stmt[0] == MB_ST_LET_ELEM_STR) {
        if (stmt_len < 3u || stmt[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, symbol_name(program, stmt[1]));
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, '(');
        if (r != MB_OK) return r;
        pc = 2;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        r = append_text_buf(out, cap, &out_len, expr);
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, ") = ");
        if (r != MB_OK) return r;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr2, sizeof(expr2));
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, expr2);
    }

    if (stmt[0] == MB_ST_GOTO) {
        keyword = keyword_by_opcode(MB_ST_GOTO);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if ((mb_u16)(stmt_len - pc) < 2u) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        return append_u16_buf(out, cap, &out_len, read_u16(stmt + pc));
    }

    if (stmt[0] == MB_ST_GOSUB) {
        keyword = keyword_by_opcode(MB_ST_GOSUB);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if ((mb_u16)(stmt_len - pc) < 2u) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        return append_u16_buf(out, cap, &out_len, read_u16(stmt + pc));
    }

    if (stmt[0] == MB_ST_RETURN) {
        keyword = keyword_by_opcode(MB_ST_RETURN);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if (stmt_len != 1u) return MB_ERR_SYNTAX;
        return append_text_buf(out, cap, &out_len, keyword->text);
    }

    if (stmt[0] == MB_ST_WHILE) {
        keyword = keyword_by_opcode(MB_ST_WHILE);
        if (keyword == 0) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, expr);
    }

    if (stmt[0] == MB_ST_WEND) {
        keyword = keyword_by_opcode(MB_ST_WEND);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if (stmt_len != 1u) return MB_ERR_SYNTAX;
        return append_text_buf(out, cap, &out_len, keyword->text);
    }

    if (stmt[0] == MB_ST_FOR) {
        keyword = keyword_by_opcode(MB_ST_FOR);
        then_keyword = keyword_by_opcode(MB_KW_TO);
        else_keyword = keyword_by_opcode(MB_KW_STEP);
        if (keyword == 0 || then_keyword == 0 || else_keyword == 0) return MB_ERR_SYNTAX;
        if (pc >= stmt_len || stmt[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, symbol_name(program, stmt[pc]));
        if (r != MB_OK) return r;
        ++pc;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr2, sizeof(expr2));
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr3, sizeof(expr3));
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, " = ");
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, expr);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, then_keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, expr2);
        if (r != MB_OK) return r;
        if (str_eq(expr3, "1")) return MB_OK;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, else_keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, expr3);
    }

    if (stmt[0] == MB_ST_NEXT) {
        keyword = keyword_by_opcode(MB_ST_NEXT);
        if (keyword == 0) return MB_ERR_SYNTAX;
        if (stmt_len != 2u) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        if (stmt[1] == MB_NEXT_ANY) return MB_OK;
        if (stmt[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, symbol_name(program, stmt[1]));
    }

    if (stmt[0] == MB_ST_IF) {
        keyword = keyword_by_opcode(MB_ST_IF);
        then_keyword = keyword_by_opcode(MB_KW_THEN);
        else_keyword = keyword_by_opcode(MB_KW_ELSE);
        if (keyword == 0 || then_keyword == 0 || else_keyword == 0) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        if ((mb_u16)(stmt_len - pc) < 2u) return MB_ERR_SYNTAX;
        used = read_u16(stmt + pc);
        pc = (mb_u16)(pc + 2u);
        if ((mb_u16)(stmt_len - pc) < used) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, expr);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, then_keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = decompile_statement_for_program(program, stmt + pc, used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, expr);
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        if ((mb_u16)(stmt_len - pc) < 2u) return MB_ERR_SYNTAX;
        used = read_u16(stmt + pc);
        pc = (mb_u16)(pc + 2u);
        if (used == 0) return MB_OK;
        if ((mb_u16)(stmt_len - pc) < used) return MB_ERR_SYNTAX;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, else_keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = decompile_statement_for_program(program, stmt + pc, used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, expr);
    }

    if (stmt[0] == MB_ST_IF_BLOCK) {
        keyword = keyword_by_opcode(MB_ST_IF);
        then_keyword = keyword_by_opcode(MB_KW_THEN);
        if (keyword == 0 || then_keyword == 0) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        r = append_text_buf(out, cap, &out_len, expr);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, then_keyword->text);
    }

    return MB_ERR_SYNTAX;
}

int mb_decompile_statement(const mb_u8 *code, mb_u16 len, char *out, mb_u16 cap)
{
    return decompile_statement_for_program(0, code, len, out, cap);
}

static mb_u16 read_u16(const mb_u8 *p)
{
    return (mb_u16)(p[0] | ((mb_u16)p[1] << 8));
}

static int control_push(MBRuntime *runtime, mb_u8 kind, mb_u16 return_offset)
{
    if (runtime->frame_sp >= MB_CONTROL_STACK_MAX) {
        return MB_ERR_CONTROL_STACK;
    }
    runtime->frames[runtime->frame_sp].kind = kind;
    runtime->frames[runtime->frame_sp].return_offset = return_offset;
    runtime->frames[runtime->frame_sp].var = 0;
    runtime->frames[runtime->frame_sp].limit = 0;
    runtime->frames[runtime->frame_sp].step = 0;
    ++runtime->frame_sp;
    return MB_OK;
}

static int control_push_for(MBRuntime *runtime, mb_u8 var, mb_u16 body_offset, mb_i32 limit, mb_i32 step)
{
    int r;

    r = control_push(runtime, MB_FRAME_FOR, body_offset);
    if (r != MB_OK) return r;
    runtime->frames[(mb_u8)(runtime->frame_sp - 1u)].var = var;
    runtime->frames[(mb_u8)(runtime->frame_sp - 1u)].limit = limit;
    runtime->frames[(mb_u8)(runtime->frame_sp - 1u)].step = step;
    return MB_OK;
}

static int control_pop_gosub(MBRuntime *runtime, mb_u16 *return_offset)
{
    if (runtime->frame_sp == 0) {
        return MB_ERR_RETURN_WITHOUT_GOSUB;
    }
    if (runtime->frames[(mb_u8)(runtime->frame_sp - 1u)].kind != MB_FRAME_GOSUB) {
        return MB_ERR_RETURN_WITHOUT_GOSUB;
    }
    --runtime->frame_sp;
    *return_offset = runtime->frames[runtime->frame_sp].return_offset;
    return MB_OK;
}

static int control_top_for(MBRuntime *runtime, mb_u8 var, MBFrame **frame)
{
    if (runtime->frame_sp == 0) {
        return MB_ERR_CONTROL_STACK;
    }
    if (runtime->frames[(mb_u8)(runtime->frame_sp - 1u)].kind != MB_FRAME_FOR) {
        return MB_ERR_CONTROL_STACK;
    }
    if (var != MB_NEXT_ANY && runtime->frames[(mb_u8)(runtime->frame_sp - 1u)].var != var) {
        return MB_ERR_CONTROL_STACK;
    }
    *frame = &runtime->frames[(mb_u8)(runtime->frame_sp - 1u)];
    return MB_OK;
}

static void control_pop_for(MBRuntime *runtime)
{
    if (runtime->frame_sp != 0) {
        --runtime->frame_sp;
    }
}

static mb_u8 statement_opcode_at(const MBProgram *program, mb_u16 off)
{
    const mb_u8 *payload;
    const mb_u8 *code;
    mb_u16 len;
    mb_u16 code_len;

    payload = rec_payload(program, off);
    len = rec_len(program, off);
    code = payload_stmt_code(payload, len, &code_len);
    if (code_len == 0) {
        return 0;
    }
    return code[0];
}

static int plan_add_jump(MBRunPlan *plan, mb_u16 from, mb_u16 to)
{
    if (plan->jump_count >= MB_RUN_JUMP_MAX) {
        return MB_ERR_FULL;
    }
    plan->jumps[plan->jump_count].from = from;
    plan->jumps[plan->jump_count].to = to;
    ++plan->jump_count;
    return MB_OK;
}

static mb_u16 plan_find_jump(const MBRunPlan *plan, mb_u16 from)
{
    mb_u8 i;

    for (i = 0; i < plan->jump_count; ++i) {
        if (plan->jumps[i].from == from) {
            return plan->jumps[i].to;
        }
    }
    return MB_NO_JUMP;
}

static int prepare_run_plan(const MBProgram *program, MBRunPlan *plan)
{
    MBBlockPrep stack[MB_CONTROL_STACK_MAX];
    mb_u8 sp;
    mb_u16 off;
    mb_u16 next;
    mb_u8 op;
    int r;

    plan->jump_count = 0;
    sp = 0;
    off = program->first;
    while (off != MB_NONE) {
        next = rec_next(program, off);
        op = statement_opcode_at(program, off);

        if (op == MB_ST_IF_BLOCK) {
            if (sp >= MB_CONTROL_STACK_MAX) return MB_ERR_CONTROL_STACK;
            stack[sp].kind = MB_ST_IF_BLOCK;
            stack[sp].start_offset = off;
            stack[sp].else_offset = MB_NONE;
            stack[sp].has_else = 0;
            ++sp;
        } else if (op == MB_ST_ELSE) {
            if (sp == 0 || stack[(mb_u8)(sp - 1u)].kind != MB_ST_IF_BLOCK ||
                stack[(mb_u8)(sp - 1u)].has_else) return MB_ERR_SYNTAX;
            stack[(mb_u8)(sp - 1u)].else_offset = off;
            stack[(mb_u8)(sp - 1u)].has_else = 1;
            r = plan_add_jump(plan, stack[(mb_u8)(sp - 1u)].start_offset, next);
            if (r != MB_OK) return r;
        } else if (op == MB_ST_END_IF) {
            if (sp == 0 || stack[(mb_u8)(sp - 1u)].kind != MB_ST_IF_BLOCK) return MB_ERR_SYNTAX;
            --sp;
            if (stack[sp].has_else) {
                r = plan_add_jump(plan, stack[sp].else_offset, next);
            } else {
                r = plan_add_jump(plan, stack[sp].start_offset, next);
            }
            if (r != MB_OK) return r;
        } else if (op == MB_ST_WHILE) {
            if (sp >= MB_CONTROL_STACK_MAX) return MB_ERR_CONTROL_STACK;
            stack[sp].kind = MB_ST_WHILE;
            stack[sp].start_offset = off;
            stack[sp].else_offset = MB_NONE;
            stack[sp].has_else = 0;
            ++sp;
        } else if (op == MB_ST_WEND) {
            if (sp == 0 || stack[(mb_u8)(sp - 1u)].kind != MB_ST_WHILE) return MB_ERR_SYNTAX;
            --sp;
            r = plan_add_jump(plan, stack[sp].start_offset, next);
            if (r != MB_OK) return r;
            r = plan_add_jump(plan, off, stack[sp].start_offset);
            if (r != MB_OK) return r;
        } else if (op == MB_ST_FOR) {
            if (sp >= MB_CONTROL_STACK_MAX) return MB_ERR_CONTROL_STACK;
            stack[sp].kind = MB_ST_FOR;
            stack[sp].start_offset = off;
            stack[sp].else_offset = MB_NONE;
            stack[sp].has_else = 0;
            ++sp;
        } else if (op == MB_ST_NEXT) {
            if (sp == 0 || stack[(mb_u8)(sp - 1u)].kind != MB_ST_FOR) return MB_ERR_SYNTAX;
            --sp;
            r = plan_add_jump(plan, stack[sp].start_offset, next);
            if (r != MB_OK) return r;
        }

        off = next;
    }

    if (sp != 0) {
        return MB_ERR_SYNTAX;
    }
    return MB_OK;
}

static void io_print_text(const MBIO *io, const char *text, mb_u16 len)
{
    if (io != 0 && io->print_str != 0) {
        io->print_str(text, len, io->ctx);
    }
}

/* Optional spaces, an optional sign and at least one digit; nothing else. */
static int parse_input_int(const char *text, mb_u16 len, mb_i32 *value)
{
    mb_u16 i;
    unsigned long v;
    int negative;

    i = 0;
    while (i < len && text[i] == ' ') {
        ++i;
    }
    negative = 0;
    if (i < len && (text[i] == '-' || text[i] == '+')) {
        negative = text[i] == '-';
        ++i;
    }
    if (i >= len || text[i] < '0' || text[i] > '9') {
        return 0;
    }
    v = 0;
    while (i < len && text[i] >= '0' && text[i] <= '9') {
        v = v * 10ul + (unsigned long)(text[i] - '0');
        ++i;
    }
    while (i < len && text[i] == ' ') {
        ++i;
    }
    if (i != len) {
        return 0;
    }
    *value = negative ? -(mb_i32)v : (mb_i32)v;
    return 1;
}

static int input_string(MBRuntime *runtime, mb_u8 var, const char *text, mb_u16 len)
{
    mb_i32 handle;
    mb_u8 attempt;
    int r;

    r = MB_OK;
    for (attempt = 0; attempt < 2; ++attempt) {
        runtime->str_top = runtime->str_used;
        r = mb_str_make(runtime, text, len, &handle);
        if (r == MB_OK) {
            r = str_assign(runtime, var, handle);
        }
        if (r != MB_ERR_STRING_TOO_LONG || runtime->str_garbage == 0) break;
        str_gc(runtime);
    }
    return r;
}

static int execute_input(MBRuntime *runtime, const mb_u8 *code, mb_u16 code_len, const MBIO *io)
{
    char line[MB_INPUT_LINE_MAX];
    mb_i32 value;
    mb_u8 var;
    mb_u8 prompt_len;
    int n;

    if (code_len < 3u || code[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
    var = code[1];
    prompt_len = code[2];
    if ((mb_u16)(code_len - 3u) < prompt_len) return MB_ERR_SYNTAX;
    if (io == 0 || io->read_line == 0) return MB_ERR_NO_INPUT;

    for (;;) {
        if (prompt_len != 0) {
            io_print_text(io, (const char *)(code + 3), prompt_len);
        } else {
            io_print_text(io, "? ", 2);
        }
        n = io->read_line(line, sizeof(line), io->ctx);
        if (n < 0) return MB_ERR_NO_INPUT;
        if (code[0] == MB_ST_INPUT_STR) {
            return input_string(runtime, var, line, (mb_u16)n);
        }
        if (parse_input_int(line, (mb_u16)n, &value)) {
            runtime->vars[var] = value;
            return MB_OK;
        }
        io_print_text(io, "?REDO", 5);
        if (io->newline != 0) {
            io->newline(io->ctx);
        }
    }
}

static int execute_code(const MBProgram *program,
                        const mb_u8 *code,
                        mb_u16 code_len,
                        mb_u16 default_next,
                        MBRuntime *runtime,
                        const MBIO *io,
                        MBExecResult *result)
{
    mb_u16 pc;
    mb_u16 used;
    mb_u16 target_line;
    mb_u16 then_len;
    mb_u16 else_len;
    mb_u8 attempt;
    mb_u8 item_type;
    mb_u16 elem_off;
    mb_i32 value;
    mb_i32 index;
    mb_i32 handle;
    int r;

    result->jumped = 0;
    result->next = default_next;

    if (code_len == 0) {
        return MB_OK;
    }

    pc = 1;
    if (code[0] == MB_ST_REM) {
        return MB_OK;
    }

    if (code[0] == MB_ST_END || code[0] == MB_ST_STOP) {
        result->jumped = 1;
        result->next = MB_NONE;
        return MB_OK;
    }

    if (code[0] == MB_ST_LET) {
        if (pc >= code_len || code[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        ++pc;
        r = eval_expr_for_program(program, code + pc, (mb_u16)(code_len - pc), runtime, &value);
        if (r != MB_OK) return r;
        runtime->vars[code[1]] = value;
        return MB_OK;
    }

    if (code[0] == MB_ST_INPUT || code[0] == MB_ST_INPUT_STR) {
        return execute_input(runtime, code, code_len, io);
    }

    if (code[0] == MB_ST_DIM || code[0] == MB_ST_REDIM) {
        if (code_len < 4u || code[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = eval_expr_for_program(program, code + 3, (mb_u16)(code_len - 3u), runtime, &value);
        if (r != MB_OK) return r;
        return arr_dim(runtime, code[1], code[2], value, code[0] == MB_ST_REDIM);
    }

    if (code[0] == MB_ST_ERASE) {
        if (code_len != 2u || code[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        return arr_erase(runtime, code[1]);
    }

    if (code[0] == MB_ST_LET_ELEM) {
        if (code_len < 3u || code[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        pc = 2;
        r = expr_len(code + pc, (mb_u16)(code_len - pc), &used);
        if (r != MB_OK) return r;
        r = eval_expr_for_program(program, code + pc, used, runtime, &index);
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        r = eval_expr_for_program(program, code + pc, (mb_u16)(code_len - pc), runtime, &value);
        if (r != MB_OK) return r;
        r = arr_locate(runtime, code[1], index, &elem_off);
        if (r != MB_OK) return r;
        write_i32(runtime->heap + elem_off, value);
        return MB_OK;
    }

    if (code[0] == MB_ST_LET_ELEM_STR) {
        if (code_len < 3u || code[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        r = MB_OK;
        for (attempt = 0; attempt < 2; ++attempt) {
            pc = 2;
            r = expr_len(code + pc, (mb_u16)(code_len - pc), &used);
            if (r != MB_OK) return r;
            r = eval_expr_for_program(program, code + pc, used, runtime, &index);
            if (r != MB_OK) return r;
            pc = (mb_u16)(pc + used);
            r = eval_expr_for_program(program, code + pc, (mb_u16)(code_len - pc), runtime, &value);
            if (r != MB_OK) return r;
            r = arr_locate(runtime, code[1], index, &elem_off);
            if (r != MB_OK) return r;
            r = str_persist(runtime, value, &handle);
            if (r == MB_OK) {
                runtime->str_garbage = (mb_u16)(runtime->str_garbage + str_handle_len(read_i32(runtime->heap + elem_off)));
                write_i32(runtime->heap + elem_off, handle);
            }
            if (r != MB_ERR_STRING_TOO_LONG || runtime->str_garbage == 0) break;
            str_gc(runtime);
        }
        return r;
    }

    if (code[0] == MB_ST_LET_STR) {
        if (pc >= code_len || code[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        ++pc;
        r = MB_OK;
        for (attempt = 0; attempt < 2; ++attempt) {
            r = eval_expr_for_program(program, code + pc, (mb_u16)(code_len - pc), runtime, &value);
            if (r != MB_OK) return r;
            r = str_assign(runtime, code[1], value);
            if (r != MB_ERR_STRING_TOO_LONG || runtime->str_garbage == 0) break;
            str_gc(runtime);
        }
        return r;
    }

    if (code[0] == MB_ST_PRINT) {
        if (code_len < 2u) return MB_ERR_SYNTAX;
        pc = 2;
        while (pc < code_len) {
            item_type = code[pc];
            ++pc;
            r = expr_len(code + pc, (mb_u16)(code_len - pc), &used);
            if (r != MB_OK) return r;
            r = eval_expr_for_program(program, code + pc, used, runtime, &value);
            if (r != MB_OK) return r;
            pc = (mb_u16)(pc + used);
            if (item_type == MB_T_STR) {
                io_print_text(io, (const char *)(runtime->heap + str_handle_off(value)), str_handle_len(value));
            } else if (io != 0 && io->print_int != 0) {
                io->print_int(value, io->ctx);
            }
        }
        if ((code[1] & 1u) == 0 && io != 0 && io->newline != 0) {
            io->newline(io->ctx);
        }
        return MB_OK;
    }

    if (code[0] == MB_ST_GOTO) {
        if ((mb_u16)(code_len - pc) < 2u) return MB_ERR_SYNTAX;
        target_line = read_u16(code + pc);
        result->next = find_line_offset(program, target_line);
        if (result->next == MB_NONE) return MB_ERR_NO_SUCH_LINE;
        result->jumped = 1;
        return MB_OK;
    }

    if (code[0] == MB_ST_GOSUB) {
        if ((mb_u16)(code_len - pc) < 2u) return MB_ERR_SYNTAX;
        target_line = read_u16(code + pc);
        result->next = find_line_offset(program, target_line);
        if (result->next == MB_NONE) return MB_ERR_NO_SUCH_LINE;
        r = control_push(runtime, MB_FRAME_GOSUB, default_next);
        if (r != MB_OK) return r;
        result->jumped = 1;
        return MB_OK;
    }

    if (code[0] == MB_ST_RETURN) {
        r = control_pop_gosub(runtime, &result->next);
        if (r != MB_OK) return r;
        result->jumped = 1;
        return MB_OK;
    }

    if (code[0] == MB_ST_IF) {
        r = expr_len(code + pc, (mb_u16)(code_len - pc), &used);
        if (r != MB_OK) return r;
        r = eval_expr_for_program(program, code + pc, used, runtime, &value);
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        if ((mb_u16)(code_len - pc) < 2u) return MB_ERR_SYNTAX;
        then_len = read_u16(code + pc);
        pc = (mb_u16)(pc + 2u);
        if ((mb_u16)(code_len - pc) < then_len) return MB_ERR_SYNTAX;
        if (value != 0) {
            return execute_code(program, code + pc, then_len, default_next, runtime, io, result);
        }
        pc = (mb_u16)(pc + then_len);
        if ((mb_u16)(code_len - pc) < 2u) return MB_ERR_SYNTAX;
        else_len = read_u16(code + pc);
        pc = (mb_u16)(pc + 2u);
        if ((mb_u16)(code_len - pc) < else_len) return MB_ERR_SYNTAX;
        if (else_len != 0) {
            return execute_code(program, code + pc, else_len, default_next, runtime, io, result);
        }
        return MB_OK;
    }

    return MB_ERR_SYNTAX;
}

static int execute_statement(const MBProgram *program,
                             const MBRunPlan *plan,
                             mb_u16 current,
                             MBRuntime *runtime,
                             const MBIO *io,
                             mb_u16 *next)
{
    const mb_u8 *payload;
    const mb_u8 *code;
    mb_u16 len;
    mb_u16 code_len;
    MBExecResult result;
    mb_i32 value;
    mb_i32 start_value;
    mb_i32 limit_value;
    mb_i32 step_value;
    MBFrame *frame;
    mb_u16 used;
    mb_u16 pc;
    int r;

    payload = rec_payload(program, current);
    len = rec_len(program, current);
    code = payload_stmt_code(payload, len, &code_len);
    if (code_len == 0) {
        *next = rec_next(program, current);
        return MB_OK;
    }

    if (code[0] == MB_ST_IF_BLOCK) {
        r = eval_expr_for_program(program, code + 1u, (mb_u16)(code_len - 1u), runtime, &value);
        if (r != MB_OK) return r;
        if (value != 0) {
            *next = rec_next(program, current);
        } else {
            *next = plan_find_jump(plan, current);
            if (*next == MB_NO_JUMP) return MB_ERR_SYNTAX;
        }
        return MB_OK;
    }

    if (code[0] == MB_ST_ELSE) {
        *next = plan_find_jump(plan, current);
        if (*next == MB_NO_JUMP) return MB_ERR_SYNTAX;
        return MB_OK;
    }

    if (code[0] == MB_ST_END_IF) {
        *next = rec_next(program, current);
        return MB_OK;
    }

    if (code[0] == MB_ST_WHILE) {
        r = eval_expr_for_program(program, code + 1u, (mb_u16)(code_len - 1u), runtime, &value);
        if (r != MB_OK) return r;
        if (value != 0) {
            *next = rec_next(program, current);
        } else {
            *next = plan_find_jump(plan, current);
            if (*next == MB_NO_JUMP) return MB_ERR_SYNTAX;
        }
        return MB_OK;
    }

    if (code[0] == MB_ST_WEND) {
        *next = plan_find_jump(plan, current);
        if (*next == MB_NO_JUMP) return MB_ERR_SYNTAX;
        return MB_OK;
    }

    if (code[0] == MB_ST_FOR) {
        if (code_len < 2u || code[1] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
        pc = 2u;
        r = expr_len(code + pc, (mb_u16)(code_len - pc), &used);
        if (r != MB_OK) return r;
        r = eval_expr_for_program(program, code + pc, used, runtime, &start_value);
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        r = expr_len(code + pc, (mb_u16)(code_len - pc), &used);
        if (r != MB_OK) return r;
        r = eval_expr_for_program(program, code + pc, used, runtime, &limit_value);
        if (r != MB_OK) return r;
        pc = (mb_u16)(pc + used);
        r = eval_expr_for_program(program, code + pc, (mb_u16)(code_len - pc), runtime, &step_value);
        if (r != MB_OK) return r;
        if (step_value == 0) return MB_ERR_SYNTAX;

        runtime->vars[code[1]] = start_value;
        if ((step_value > 0 && start_value > limit_value) ||
            (step_value < 0 && start_value < limit_value)) {
            *next = plan_find_jump(plan, current);
            if (*next == MB_NO_JUMP) return MB_ERR_SYNTAX;
            return MB_OK;
        }

        r = control_push_for(runtime, code[1], rec_next(program, current), limit_value, step_value);
        if (r != MB_OK) return r;
        *next = rec_next(program, current);
        return MB_OK;
    }

    if (code[0] == MB_ST_NEXT) {
        if (code_len != 2u) return MB_ERR_SYNTAX;
        r = control_top_for(runtime, code[1], &frame);
        if (r != MB_OK) return r;
        runtime->vars[frame->var] = (mb_i32)(runtime->vars[frame->var] + frame->step);
        if ((frame->step > 0 && runtime->vars[frame->var] <= frame->limit) ||
            (frame->step < 0 && runtime->vars[frame->var] >= frame->limit)) {
            *next = frame->return_offset;
        } else {
            control_pop_for(runtime);
            *next = rec_next(program, current);
        }
        return MB_OK;
    }

    r = execute_code(program, code, code_len, rec_next(program, current), runtime, io, &result);
    if (r != MB_OK) return r;
    *next = result.next;
    return MB_OK;
}

static void list_source_line(mb_u16 line, const char *source, mb_u16 len, void *ctx)
{
    const MBConsoleIO *io;

    io = (const MBConsoleIO *)ctx;
    console_put_u16(io, line);
    console_put_char(io, ' ');
    console_put_text_n(io, source, len);
    console_put_char(io, '\n');
}

static int run_immediate_statement(MBProgram *program, MBRuntime *runtime, const char *text, const MBIO *run_io, mb_u16 max_steps)
{
    mb_u8 memory[MB_IMMEDIATE_MEM];
    MBProgram immediate;
    int r;

    mb_program_init(&immediate, memory, sizeof(memory));
    symbols_copy(&immediate, program);
    r = mb_program_store_payload(&immediate, 1, (const mb_u8 *)"", 0);
    if (r != MB_OK) {
        return r;
    }
    r = mb_program_store_statement(&immediate, 1, text);
    if (r != MB_OK) {
        return r;
    }
    r = mb_program_run(&immediate, runtime, run_io, max_steps);
    symbols_copy(program, &immediate);
    return r;
}

int mb_program_run(const MBProgram *program, MBRuntime *runtime, const MBIO *io, mb_u16 max_steps)
{
    MBRunPlan plan;
    mb_u16 current;
    mb_u16 next;
    mb_u16 steps;
    int r;

    if (program == 0 || runtime == 0) {
        return MB_ERR_BAD_ARG;
    }

    r = prepare_run_plan(program, &plan);
    if (r != MB_OK) {
        return r;
    }

    current = program->first;
    steps = 0;
    runtime->frame_sp = 0;
    while (current != MB_NONE) {
        if (max_steps != 0 && steps >= max_steps) {
            return MB_ERR_TOO_MANY_STEPS;
        }
        r = execute_statement(program, &plan, current, runtime, io, &next);
        if (r != MB_OK) {
            return r;
        }
        current = next;
        ++steps;
    }

    return MB_OK;
}

int mb_console_process_line(MBProgram *program,
                            MBRuntime *runtime,
                            const char *line,
                            const MBIO *run_io,
                            const MBConsoleIO *console_io,
                            mb_u16 max_steps)
{
    const char *s;
    mb_u16 number;
    int r;

    if (program == 0 || runtime == 0 || line == 0) {
        return MB_ERR_BAD_ARG;
    }

    s = line;
    if (parse_leading_line_number(&s, &number)) {
        if (number == 0) {
            return MB_ERR_BAD_LINE;
        }
        if (cstr_is_empty_after_spaces(s)) {
            return mb_program_delete_line(program, number);
        }
        skip_cstr_spaces(&s);
        return mb_program_store_statement(program, number, s);
    }

    s = line;
    if (take_word(&s, "NEW")) {
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        mb_program_clear(program);
        mb_runtime_init(runtime);
        return MB_OK;
    }

    s = line;
    if (take_word(&s, "LIST")) {
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        mb_program_each_source(program, list_source_line, (void *)console_io);
        return MB_OK;
    }

    s = line;
    if (take_word(&s, "RUN")) {
        if (!cstr_is_empty_after_spaces(s)) return MB_ERR_SYNTAX;
        return mb_program_run(program, runtime, run_io, max_steps);
    }

    if (cstr_is_empty_after_spaces(line)) {
        return MB_OK;
    }

    r = run_immediate_statement(program, runtime, line, run_io, max_steps);
    return r;
}

int mb_repl(MBProgram *program,
            MBRuntime *runtime,
            const MBReplIO *io,
            char *line_buffer,
            mb_u16 line_capacity,
            mb_u16 max_steps)
{
    MBIO run_io;
    MBConsoleIO console_io;
    mb_u16 len;
    int ch;
    int r;

    if (program == 0 || runtime == 0 || io == 0 ||
        io->get_char == 0 || io->put_char == 0 ||
        line_buffer == 0 || line_capacity == 0) {
        return MB_ERR_BAD_ARG;
    }

    run_io.print_int = repl_print_int;
    run_io.print_str = repl_print_str;
    run_io.read_line = repl_read_line;
    run_io.newline = repl_print_newline;
    run_io.ctx = (void *)io;

    console_io.put_char = repl_console_put_char;
    console_io.ctx = (void *)io;

    repl_put_text(io, "READY");
    repl_newline(io);

    for (;;) {
        repl_put_text(io, "> ");
        len = 0;
        line_buffer[0] = 0;

        for (;;) {
            ch = io->get_char(io->ctx);
            if (ch < 0) {
                return MB_OK;
            }

            if (ch == '\r' || ch == '\n') {
                repl_newline(io);
                line_buffer[len] = 0;
                r = mb_console_process_line(program,
                                            runtime,
                                            line_buffer,
                                            &run_io,
                                            &console_io,
                                            max_steps);
                print_error(io, r);
                break;
            }

            if (ch == 8 || ch == 127) {
                if (len != 0) {
                    --len;
                    line_buffer[len] = 0;
                    repl_put_char(io, 8);
                    repl_put_char(io, ' ');
                    repl_put_char(io, 8);
                }
                continue;
            }

            if (ch >= 32 && ch < 127) {
                if (len + 1u >= line_capacity) {
                    print_error(io, MB_ERR_FULL);
                    len = 0;
                    line_buffer[0] = 0;
                    break;
                }
                line_buffer[len] = (char)ch;
                ++len;
                line_buffer[len] = 0;
                repl_put_char(io, (char)ch);
            }
        }
    }
}

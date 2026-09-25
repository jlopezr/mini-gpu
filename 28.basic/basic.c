#include "basic.h"
#include "basic_builtins.h"

#define MB_NONE 0u
#define MB_FIRST_OFFSET 1u
#define MB_HEADER_SIZE 6u
#define MB_PAYLOAD_SOURCE_STMT 0x7eu
#define MB_KW_THEN 250u
#define MB_KW_ELSE 251u
#define MB_KW_TO 252u
#define MB_KW_STEP 253u
#define MB_RUN_JUMP_MAX 64u
#define MB_NEXT_ANY 255u

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

static const MBOperatorInfo mb_operators[] = {
    { "<>", MB_BC_NE, 1 },
    { "<=", MB_BC_LE, 1 },
    { ">=", MB_BC_GE, 1 },
    { "=", MB_BC_EQ, 1 },
    { "<", MB_BC_LT, 1 },
    { ">", MB_BC_GT, 1 },
    { "+", MB_BC_ADD, 2 },
    { "-", MB_BC_SUB, 2 },
    { "*", MB_BC_MUL, 3 },
    { "/", MB_BC_DIV, 3 },
    { 0, 0, 0 }
};

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

static int parse_ident_text(const char **s, char *name, mb_u16 cap)
{
    mb_u16 len;

    skip_cstr_spaces(s);
    if (!is_alpha(**s)) {
        return MB_ERR_SYNTAX;
    }

    len = 0;
    while (is_ident_tail(**s)) {
        if (len + 1u >= cap) {
            return MB_ERR_FULL;
        }
        name[len] = upper_char(**s);
        ++len;
        ++*s;
    }
    name[len] = 0;
    return MB_OK;
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

static int builtin_find(const MBProgram *program, const char *name, mb_u8 *id)
{
    mb_u8 i;

    if (program == 0 || program->builtins == 0) {
        return 0;
    }
    for (i = 0; i < program->builtin_count; ++i) {
        if (str_eq(program->builtins[i].name, name)) {
            *id = i;
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

static const MBOperatorInfo *operator_by_text(const char *s, mb_u8 min_prec, mb_u8 max_prec)
{
    mb_u16 i;
    mb_u16 n;

    for (i = 0; mb_operators[i].text != 0; ++i) {
        if (mb_operators[i].prec < min_prec || mb_operators[i].prec > max_prec) {
            continue;
        }
        n = cstr_len(mb_operators[i].text);
        if (str_ieq_n(s, mb_operators[i].text, n)) {
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

    r = parse_ident_text(s, name, sizeof(name));
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
    mb_u8 code[128];
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
    char line[160];
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
    }
    runtime->frame_sp = 0;
}

typedef struct ExprParser ExprParser;

struct ExprParser {
    MBProgram *program;
    const char *s;
    mb_u8 *out;
    mb_u16 cap;
    mb_u16 len;
};

static void skip_spaces(ExprParser *parser)
{
    while (is_space(*parser->s)) {
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

static int parse_builtin_call(ExprParser *parser, const char *name)
{
    mb_u8 builtin_id;
    mb_u8 argc;
    int r;

    if (parser->program == 0 || !builtin_find(parser->program, name, &builtin_id)) {
        return MB_ERR_BAD_BUILTIN;
    }

    ++parser->s;
    argc = 0;
    skip_spaces(parser);
    if (*parser->s != ')') {
        for (;;) {
            if (argc >= MB_BUILTIN_ARG_MAX) {
                return MB_ERR_BAD_BUILTIN;
            }
            r = parse_compare(parser);
            if (r != MB_OK) return r;
            ++argc;
            skip_spaces(parser);
            if (*parser->s == ',') {
                ++parser->s;
                continue;
            }
            break;
        }
    }

    skip_spaces(parser);
    if (*parser->s != ')') {
        return MB_ERR_SYNTAX;
    }
    ++parser->s;

    if (argc < parser->program->builtins[builtin_id].min_args ||
        argc > parser->program->builtins[builtin_id].max_args) {
        return MB_ERR_BAD_BUILTIN;
    }

    r = emit_op(parser, MB_BC_CALL_BUILTIN);
    if (r != MB_OK) return r;
    r = emit_u8(parser, builtin_id);
    if (r != MB_OK) return r;
    return emit_u8(parser, argc);
}

static int parse_primary(ExprParser *parser)
{
    mb_i32 value;
    int r;
    mb_u8 var;
    char name[MB_SYMBOL_NAME_MAX];

    skip_spaces(parser);

    if (*parser->s == '(') {
        ++parser->s;
        r = parse_compare(parser);
        if (r != MB_OK) return r;
        skip_spaces(parser);
        if (*parser->s != ')') {
            return MB_ERR_SYNTAX;
        }
        ++parser->s;
        return MB_OK;
    }

    if (is_digit(*parser->s)) {
        value = 0;
        while (is_digit(*parser->s)) {
            value = (mb_i32)(value * 10 + (*parser->s - '0'));
            ++parser->s;
        }
        r = emit_op(parser, MB_BC_PUSH_I32);
        if (r != MB_OK) return r;
        return emit_i32(parser, value);
    }

    if (is_alpha(*parser->s)) {
        r = parse_ident_text(&parser->s, name, sizeof(name));
        if (r != MB_OK) return r;
        skip_spaces(parser);
        if (*parser->s == '(') {
            return parse_builtin_call(parser, name);
        }
        if (parser->program == 0) {
            if (name[0] == 0 || name[1] != 0) return MB_ERR_SYNTAX;
            var = (mb_u8)(name[0] - 'A');
        } else {
            r = symbol_get_or_create(parser->program, name, &var);
            if (r != MB_OK) return r;
        }
        r = emit_op(parser, MB_BC_PUSH_VAR);
        if (r != MB_OK) return r;
        return emit_u8(parser, var);
    }

    return MB_ERR_SYNTAX;
}

static int parse_unary(ExprParser *parser)
{
    int r;

    skip_spaces(parser);
    if (*parser->s == '-') {
        ++parser->s;
        r = parse_unary(parser);
        if (r != MB_OK) return r;
        return emit_op(parser, MB_BC_NEG);
    }
    return parse_primary(parser);
}

static int parse_mul(ExprParser *parser)
{
    int r;
    const MBOperatorInfo *op;

    r = parse_unary(parser);
    if (r != MB_OK) return r;

    for (;;) {
        skip_spaces(parser);
        op = operator_by_text(parser->s, 3, 3);
        if (op == 0) {
            return MB_OK;
        }
        parser->s += cstr_len(op->text);
        r = parse_unary(parser);
        if (r != MB_OK) return r;
        r = emit_op(parser, op->opcode);
        if (r != MB_OK) return r;
    }
}

static int parse_add(ExprParser *parser)
{
    int r;
    const MBOperatorInfo *op;

    r = parse_mul(parser);
    if (r != MB_OK) return r;

    for (;;) {
        skip_spaces(parser);
        op = operator_by_text(parser->s, 2, 2);
        if (op == 0) {
            return MB_OK;
        }
        parser->s += cstr_len(op->text);
        r = parse_mul(parser);
        if (r != MB_OK) return r;
        r = emit_op(parser, op->opcode);
        if (r != MB_OK) return r;
    }
}

static int parse_compare(ExprParser *parser)
{
    int r;
    const MBOperatorInfo *op;

    r = parse_add(parser);
    if (r != MB_OK) return r;

    skip_spaces(parser);
    op = operator_by_text(parser->s, 1, 1);
    if (op == 0) {
        return MB_OK;
    }
    parser->s += cstr_len(op->text);

    r = parse_add(parser);
    if (r != MB_OK) return r;
    return emit_op(parser, op->opcode);
}

static int compile_expr_for_program(MBProgram *program, const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    ExprParser parser;
    int r;

    if (text == 0 || out == 0 || out_len == 0) {
        return MB_ERR_BAD_ARG;
    }

    parser.program = program;
    parser.s = text;
    parser.out = out;
    parser.cap = cap;
    parser.len = 0;

    r = parse_compare(&parser);
    if (r != MB_OK) return r;
    skip_spaces(&parser);
    if (*parser.s != 0) {
        return MB_ERR_SYNTAX;
    }
    r = emit_op(&parser, MB_BC_END);
    if (r != MB_OK) return r;

    *out_len = parser.len;
    return MB_OK;
}

int mb_compile_expr(const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    return compile_expr_for_program(0, text, out, cap, out_len);
}

static int compile_expr_until(MBProgram *program, const char *start, const char *end, mb_u8 *out, mb_u16 cap, mb_u16 *out_len)
{
    char tmp[96];
    mb_u16 n;

    if (end < start) {
        return MB_ERR_SYNTAX;
    }
    n = (mb_u16)(end - start);
    if (n >= sizeof(tmp)) {
        return MB_ERR_FULL;
    }
    copy_bytes((mb_u8 *)tmp, (const mb_u8 *)start, n);
    tmp[n] = 0;
    return compile_expr_for_program(program, tmp, out, cap, out_len);
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
    char tmp[128];
    mb_u8 stmt[128];
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
        r = emit_stmt_u8(out, cap, &len, MB_ST_PRINT);
        if (r != MB_OK) return r;
        r = compile_expr_for_program(program, s, out + len, (mb_u16)(cap - len), &expr_len);
        if (r != MB_OK) return r;
        len = (mb_u16)(len + expr_len);
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
    if (!take_char(&s, '=')) return MB_ERR_SYNTAX;
    r = emit_stmt_u8(out, cap, &len, MB_ST_LET);
    if (r != MB_OK) return r;
    r = emit_stmt_u8(out, cap, &len, var);
    if (r != MB_OK) return r;
    r = compile_expr_for_program(program, s, out + len, (mb_u16)(cap - len), &expr_len);
    if (r != MB_OK) return r;
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

static int eval_expr_for_program(const MBProgram *program, const mb_u8 *code, mb_u16 len, MBRuntime *runtime, mb_i32 *result)
{
    mb_i32 stack[MB_EXPR_STACK_MAX];
    mb_i32 args[MB_BUILTIN_ARG_MAX];
    mb_u16 sp;
    mb_u16 pc;
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
            r = program->builtins[id].fn(args, argc, &a);
            if (r != MB_OK) return r;
            r = stack_push(stack, &sp, a);
            if (r != MB_OK) return r;
            break;
        case MB_BC_NEG:
            r = stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            r = stack_push(stack, &sp, -a);
            if (r != MB_OK) return r;
            break;
        case MB_BC_ADD:
        case MB_BC_SUB:
        case MB_BC_MUL:
        case MB_BC_DIV:
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
            else if (op == MB_BC_DIV) {
                if (b == 0) return MB_ERR_DIV_ZERO;
                r = stack_push(stack, &sp, (mb_i32)(a / b));
            } else if (op == MB_BC_EQ) r = stack_push(stack, &sp, a == b);
            else if (op == MB_BC_NE) r = stack_push(stack, &sp, a != b);
            else if (op == MB_BC_LT) r = stack_push(stack, &sp, a < b);
            else if (op == MB_BC_LE) r = stack_push(stack, &sp, a <= b);
            else if (op == MB_BC_GT) r = stack_push(stack, &sp, a > b);
            else r = stack_push(stack, &sp, a >= b);
            if (r != MB_OK) return r;
            break;
        default:
            return MB_ERR_SYNTAX;
        }
    }

    return MB_ERR_SYNTAX;
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
        } else if (op == MB_BC_PUSH_VAR) {
            if (pc >= len) return MB_ERR_SYNTAX;
            ++pc;
        } else if (op == MB_BC_CALL_BUILTIN) {
            if ((mb_u16)(len - pc) < 2u) return MB_ERR_SYNTAX;
            pc = (mb_u16)(pc + 2u);
        } else if ((op >= MB_BC_ADD && op <= MB_BC_NEG) || (op >= MB_BC_EQ && op <= MB_BC_GE)) {
        } else {
            return MB_ERR_SYNTAX;
        }
    }
    return MB_ERR_SYNTAX;
}

static mb_u16 read_u16(const mb_u8 *p);

typedef struct DecompExpr DecompExpr;

struct DecompExpr {
    char text[64];
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

static mb_u8 decomp_prec(mb_u8 op)
{
    const MBOperatorInfo *info;

    info = operator_by_opcode(op);
    if (info != 0) return info->prec;
    if (op == MB_BC_NEG) {
        return 4;
    }
    return 5;
}

static const char *decomp_op_text(mb_u8 op)
{
    const MBOperatorInfo *info;

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
            r = expr_stack_push(stack, &sp, out, 5);
            if (r != MB_OK) return r;
        } else if (op == MB_BC_PUSH_VAR) {
            if (pc >= len || code[pc] >= MB_VAR_COUNT) return MB_ERR_SYNTAX;
            r = expr_stack_push(stack, &sp, symbol_name(program, code[pc]), 5);
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
            r = expr_stack_push(stack, &sp, out, 5);
            if (r != MB_OK) return r;
        } else if (op == MB_BC_NEG) {
            r = expr_stack_pop(stack, &sp, &a);
            if (r != MB_OK) return r;
            prec = decomp_prec(op);
            text_len = 0;
            out[0] = 0;
            r = append_char_buf(out, cap, &text_len, '-');
            if (r != MB_OK) return r;
            r = append_operand(out, cap, &text_len, &a, prec, 0);
            if (r != MB_OK) return r;
            r = expr_stack_push(stack, &sp, out, prec);
            if (r != MB_OK) return r;
        } else if ((op >= MB_BC_ADD && op <= MB_BC_DIV) || (op >= MB_BC_EQ && op <= MB_BC_GE)) {
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
    char expr[96];
    char expr2[96];
    char expr3[96];
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

    if (stmt[0] == MB_ST_LET) {
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
        if (keyword == 0) return MB_ERR_SYNTAX;
        r = append_text_buf(out, cap, &out_len, keyword->text);
        if (r != MB_OK) return r;
        r = append_char_buf(out, cap, &out_len, ' ');
        if (r != MB_OK) return r;
        r = decompile_expr(program, stmt + pc, (mb_u16)(stmt_len - pc), &used, expr, sizeof(expr));
        if (r != MB_OK) return r;
        return append_text_buf(out, cap, &out_len, expr);
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
    return MB_NONE;
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
    mb_i32 value;
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

    if (code[0] == MB_ST_PRINT) {
        r = eval_expr_for_program(program, code + pc, (mb_u16)(code_len - pc), runtime, &value);
        if (r != MB_OK) return r;
        if (io != 0 && io->print_int != 0) {
            io->print_int(value, io->ctx);
        }
        if (io != 0 && io->newline != 0) {
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
            if (*next == MB_NONE) return MB_ERR_SYNTAX;
        }
        return MB_OK;
    }

    if (code[0] == MB_ST_ELSE) {
        *next = plan_find_jump(plan, current);
        if (*next == MB_NONE) return MB_ERR_SYNTAX;
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
            if (*next == MB_NONE) return MB_ERR_SYNTAX;
        }
        return MB_OK;
    }

    if (code[0] == MB_ST_WEND) {
        *next = plan_find_jump(plan, current);
        if (*next == MB_NONE) return MB_ERR_SYNTAX;
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
            if (*next == MB_NONE) return MB_ERR_SYNTAX;
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
    mb_u8 memory[192];
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

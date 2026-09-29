#include "basic_builtins.h"

static int builtin_abs(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)runtime;
    (void)argc;
    *result = args[0] < 0 ? -args[0] : args[0];
    return MB_OK;
}

static int builtin_min(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)runtime;
    (void)argc;
    *result = args[0] < args[1] ? args[0] : args[1];
    return MB_OK;
}

static int builtin_max(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)runtime;
    (void)argc;
    *result = args[0] > args[1] ? args[0] : args[1];
    return MB_OK;
}

static int builtin_len(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    mb_u16 len;

    (void)argc;
    mb_str_data(runtime, args[0], &len);
    *result = (mb_i32)len;
    return MB_OK;
}

static int builtin_asc(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    const char *text;
    mb_u16 len;

    (void)argc;
    text = mb_str_data(runtime, args[0], &len);
    if (len == 0) {
        return MB_ERR_BAD_ARG;
    }
    *result = (mb_i32)(unsigned char)text[0];
    return MB_OK;
}

/* Leading spaces, an optional sign, then digits; stops at the first other
   character and yields 0 when there are no digits. */
static int builtin_val(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    const char *text;
    mb_u16 len;
    mb_u16 i;
    unsigned long value;
    int negative;

    (void)argc;
    text = mb_str_data(runtime, args[0], &len);
    i = 0;
    while (i < len && text[i] == ' ') {
        ++i;
    }
    negative = 0;
    if (i < len && (text[i] == '-' || text[i] == '+')) {
        negative = text[i] == '-';
        ++i;
    }
    value = 0;
    while (i < len && text[i] >= '0' && text[i] <= '9') {
        value = value * 10ul + (unsigned long)(text[i] - '0');
        ++i;
    }
    *result = negative ? -(mb_i32)value : (mb_i32)value;
    return MB_OK;
}

static int builtin_chr(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    char c;

    (void)argc;
    if (args[0] < 0 || args[0] > 255) {
        return MB_ERR_BAD_ARG;
    }
    c = (char)args[0];
    return mb_str_make(runtime, &c, 1, result);
}

static int builtin_str(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    char buf[16];
    mb_u16 n;
    unsigned long v;
    int negative;

    (void)argc;
    negative = args[0] < 0;
    v = negative ? (unsigned long)(-args[0]) : (unsigned long)args[0];
    n = sizeof(buf);
    do {
        --n;
        buf[n] = (char)('0' + (v % 10ul));
        v = v / 10ul;
    } while (v != 0 && n > 1u);
    if (negative) {
        --n;
        buf[n] = '-';
    }
    return mb_str_make(runtime, buf + n, (mb_u16)(sizeof(buf) - n), result);
}

static int builtin_left(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    mb_u16 len;
    mb_u16 n;

    (void)argc;
    if (args[1] < 0) {
        return MB_ERR_BAD_ARG;
    }
    mb_str_data(runtime, args[0], &len);
    n = args[1] > (mb_i32)len ? len : (mb_u16)args[1];
    *result = mb_str_slice(args[0], 0, n);
    return MB_OK;
}

static int builtin_right(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    mb_u16 len;
    mb_u16 n;

    (void)argc;
    if (args[1] < 0) {
        return MB_ERR_BAD_ARG;
    }
    mb_str_data(runtime, args[0], &len);
    n = args[1] > (mb_i32)len ? len : (mb_u16)args[1];
    *result = mb_str_slice(args[0], (mb_u16)(len - n), n);
    return MB_OK;
}

/* MID$(s$, start [, n]): start counts from 1; without n it runs to the end. */
static int builtin_mid(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    mb_u16 len;
    mb_u16 start;
    mb_u16 n;

    if (args[1] < 1 || (argc > 2u && args[2] < 0)) {
        return MB_ERR_BAD_ARG;
    }
    mb_str_data(runtime, args[0], &len);
    if (args[1] > (mb_i32)len) {
        *result = 0;
        return MB_OK;
    }
    start = (mb_u16)(args[1] - 1);
    n = (mb_u16)(len - start);
    if (argc > 2u && args[2] < (mb_i32)n) {
        n = (mb_u16)args[2];
    }
    *result = mb_str_slice(args[0], start, n);
    return MB_OK;
}

/* INSTR(a$, b$) or INSTR(start, a$, b$): 1-based position of b$ in a$, or 0.
   An empty b$ is found at start. */
static int builtin_instr(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    const char *hay;
    const char *needle;
    mb_u16 hay_len;
    mb_u16 needle_len;
    mb_u16 i;
    mb_u16 j;
    mb_i32 start;

    start = 1;
    if (argc > 2u) {
        start = args[0];
        ++args;
    }
    if (start < 1) {
        return MB_ERR_BAD_ARG;
    }
    hay = mb_str_data(runtime, args[0], &hay_len);
    needle = mb_str_data(runtime, args[1], &needle_len);
    *result = 0;
    if (start > (mb_i32)hay_len + 1) {
        return MB_OK;
    }
    for (i = (mb_u16)(start - 1); (mb_u16)(i + needle_len) <= hay_len; ++i) {
        for (j = 0; j < needle_len && hay[i + j] == needle[j]; ++j) {
        }
        if (j == needle_len) {
            *result = (mb_i32)i + 1;
            return MB_OK;
        }
    }
    return MB_OK;
}

static int change_case(MBRuntime *runtime, mb_i32 handle, mb_i32 *result, int upper)
{
    const char *src;
    char *dst;
    mb_u16 len;
    mb_u16 i;
    int r;

    src = mb_str_data(runtime, handle, &len);
    r = mb_str_alloc(runtime, len, result);
    if (r != MB_OK || len == 0) return r;
    /* The heap belongs to the runtime; the const only protects arguments. */
    dst = (char *)mb_str_data(runtime, *result, &len);
    for (i = 0; i < len; ++i) {
        dst[i] = src[i];
        if (upper && dst[i] >= 'a' && dst[i] <= 'z') {
            dst[i] = (char)(dst[i] - 'a' + 'A');
        } else if (!upper && dst[i] >= 'A' && dst[i] <= 'Z') {
            dst[i] = (char)(dst[i] - 'A' + 'a');
        }
    }
    return MB_OK;
}

static int builtin_ucase(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)argc;
    return change_case(runtime, args[0], result, 1);
}

static int builtin_lcase(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)argc;
    return change_case(runtime, args[0], result, 0);
}

static int builtin_space(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    char *dst;
    mb_u16 len;
    mb_u16 i;
    int r;

    (void)argc;
    if (args[0] < 0) {
        return MB_ERR_BAD_ARG;
    }
    if (args[0] > MB_HEAP_SIZE) {
        return MB_ERR_STRING_TOO_LONG;
    }
    r = mb_str_alloc(runtime, (mb_u16)args[0], result);
    if (r != MB_OK || args[0] == 0) return r;
    dst = (char *)mb_str_data(runtime, *result, &len);
    for (i = 0; i < len; ++i) {
        dst[i] = ' ';
    }
    return MB_OK;
}

/* FRE() or FRE(x), x ignored: bytes still free for strings and arrays. Dead
   strings count as free because the next collection gives them back. */
static int builtin_fre(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)args;
    (void)argc;
    *result = (mb_i32)(runtime->arr_base - runtime->str_top) + (mb_i32)runtime->str_garbage;
    return MB_OK;
}

const MBBuiltin mb_default_builtins[] = {
    { "ABS", 1, 1, builtin_abs, 0, 0 },
    { "MIN", 2, 2, builtin_min, 0, 0 },
    { "MAX", 2, 2, builtin_max, 0, 0 },
    { "LEN", 1, 1, builtin_len, 1, 0 },
    { "ASC", 1, 1, builtin_asc, 1, 0 },
    { "VAL", 1, 1, builtin_val, 1, 0 },
    { "CHR$", 1, 1, builtin_chr, 0, 1 },
    { "STR$", 1, 1, builtin_str, 0, 1 },
    { "LEFT$", 2, 2, builtin_left, 1, 1 },
    { "RIGHT$", 2, 2, builtin_right, 1, 1 },
    { "MID$", 2, 3, builtin_mid, 1, 1 },
    { "INSTR", 2, 2, builtin_instr, 3, 0 },
    { "INSTR", 3, 3, builtin_instr, 6, 0 },
    { "UCASE$", 1, 1, builtin_ucase, 1, 1 },
    { "LCASE$", 1, 1, builtin_lcase, 1, 1 },
    { "SPACE$", 1, 1, builtin_space, 0, 1 },
    { "FRE", 0, 1, builtin_fre, 0, 0 }
};

const mb_u8 mb_default_builtin_count = 17;

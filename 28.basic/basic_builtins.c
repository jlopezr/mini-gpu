#include "basic_builtins.h"

static int builtin_abs(const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)argc;
    *result = args[0] < 0 ? -args[0] : args[0];
    return MB_OK;
}

static int builtin_min(const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)argc;
    *result = args[0] < args[1] ? args[0] : args[1];
    return MB_OK;
}

static int builtin_max(const mb_i32 *args, mb_u8 argc, mb_i32 *result)
{
    (void)argc;
    *result = args[0] > args[1] ? args[0] : args[1];
    return MB_OK;
}

const MBBuiltin mb_default_builtins[] = {
    { "ABS", 1, 1, builtin_abs },
    { "MIN", 2, 2, builtin_min },
    { "MAX", 2, 2, builtin_max }
};

const mb_u8 mb_default_builtin_count = 3;

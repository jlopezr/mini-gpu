#include "basic.h"

#include <stdio.h>

static int check_expr(const char *text, MBRuntime *runtime, mb_i32 want)
{
    mb_u8 code[128];
    mb_u16 len;
    mb_i32 got;
    int r;

    r = mb_compile_expr(text, code, sizeof(code), &len);
    if (r != MB_OK) {
        printf("compile failed for '%s': %d\n", text, r);
        return 1;
    }

    r = mb_eval_expr(code, len, runtime, &got);
    if (r != MB_OK) {
        printf("eval failed for '%s': %d\n", text, r);
        return 1;
    }

    if (got != want) {
        printf("bad result for '%s': got %ld want %ld\n", text, got, want);
        return 1;
    }

    return 0;
}

int main(void)
{
    MBRuntime runtime;
    mb_u8 code[128];
    mb_u16 len;
    mb_i32 got;
    int r;

    mb_runtime_init(&runtime);
    runtime.vars[0] = 3;
    runtime.vars[1] = 4;

    if (check_expr("1 + 2 * 3", &runtime, 7)) return 1;
    if (check_expr("(1 + 2) * 3", &runtime, 9)) return 1;
    if (check_expr("A + B * 2", &runtime, 11)) return 1;
    if (check_expr("-A + 10", &runtime, 7)) return 1;
    if (check_expr("A < B", &runtime, 1)) return 1;
    if (check_expr("A >= B", &runtime, 0)) return 1;
    if (check_expr("A <> B", &runtime, 1)) return 1;

    r = mb_compile_expr("1 / 0", code, sizeof(code), &len);
    if (r != MB_OK) return 1;
    got = 99;
    r = mb_eval_expr(code, len, &runtime, &got);
    if (r != MB_ERR_DIV_ZERO) {
        printf("expected div-zero, got %d\n", r);
        return 1;
    }

    r = mb_compile_expr("A +", code, sizeof(code), &len);
    if (r != MB_ERR_SYNTAX) {
        printf("expected syntax error, got %d\n", r);
        return 1;
    }

    printf("ok: expression compile/eval\n");
    return 0;
}

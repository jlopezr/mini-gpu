#ifndef MINI_BASIC_BASIC_H
#define MINI_BASIC_BASIC_H

typedef unsigned char mb_u8;
typedef unsigned short mb_u16;
typedef long mb_i32;

enum {
    MB_OK = 0,
    MB_ERR_FULL = -1,
    MB_ERR_BAD_LINE = -2,
    MB_ERR_BAD_ARG = -3,
    MB_ERR_SYNTAX = -4,
    MB_ERR_STACK = -5,
    MB_ERR_DIV_ZERO = -6,
    MB_ERR_NO_SUCH_LINE = -7,
    MB_ERR_TOO_MANY_STEPS = -8,
    MB_ERR_CONTROL_STACK = -9,
    MB_ERR_RETURN_WITHOUT_GOSUB = -10,
    MB_ERR_BAD_BUILTIN = -11
};

enum {
    MB_VAR_COUNT = 64,
    MB_SYMBOL_NAME_MAX = 16,
    MB_BUILTIN_NAME_MAX = 12,
    MB_BUILTIN_ARG_MAX = 4,
    MB_CONTROL_STACK_MAX = 16,
    MB_EXPR_STACK_MAX = 16
};

enum {
    MB_BC_END = 0,
    MB_BC_PUSH_I32 = 1,
    MB_BC_PUSH_VAR = 2,
    MB_BC_CALL_BUILTIN = 3,
    MB_BC_ADD = 16,
    MB_BC_SUB = 17,
    MB_BC_MUL = 18,
    MB_BC_DIV = 19,
    MB_BC_NEG = 20,
    MB_BC_EQ = 32,
    MB_BC_NE = 33,
    MB_BC_LT = 34,
    MB_BC_LE = 35,
    MB_BC_GT = 36,
    MB_BC_GE = 37
};

enum {
    MB_ST_LET = 64,
    MB_ST_PRINT = 65,
    MB_ST_GOTO = 66,
    MB_ST_IF = 67,
    MB_ST_END = 68,
    MB_ST_STOP = 69,
    MB_ST_REM = 70,
    MB_ST_GOSUB = 71,
    MB_ST_RETURN = 72,
    MB_ST_IF_BLOCK = 73,
    MB_ST_ELSE = 74,
    MB_ST_END_IF = 75,
    MB_ST_WHILE = 76,
    MB_ST_WEND = 77,
    MB_ST_FOR = 78,
    MB_ST_NEXT = 79
};

enum {
    MB_FRAME_GOSUB = 1,
    MB_FRAME_FOR = 2
};

typedef struct MBProgram MBProgram;
typedef struct MBRuntime MBRuntime;
typedef struct MBIO MBIO;
typedef struct MBConsoleIO MBConsoleIO;
typedef struct MBReplIO MBReplIO;
typedef struct MBSymbol MBSymbol;
typedef struct MBFrame MBFrame;
typedef struct MBBuiltin MBBuiltin;

typedef int (*MBBuiltinFn)(const mb_i32 *args, mb_u8 argc, mb_i32 *result);

struct MBSymbol {
    char name[MB_SYMBOL_NAME_MAX];
};

struct MBFrame {
    mb_u8 kind;
    mb_u16 return_offset;
    mb_u8 var;
    mb_i32 limit;
    mb_i32 step;
};

struct MBBuiltin {
    const char *name;
    mb_u8 min_args;
    mb_u8 max_args;
    MBBuiltinFn fn;
};

struct MBProgram {
    mb_u8 *mem;
    mb_u16 capacity;
    mb_u16 used;
    mb_u16 first;
    MBSymbol symbols[MB_VAR_COUNT];
    mb_u8 symbol_count;
    const MBBuiltin *builtins;
    mb_u8 builtin_count;
};

struct MBRuntime {
    mb_i32 vars[MB_VAR_COUNT];
    MBFrame frames[MB_CONTROL_STACK_MAX];
    mb_u8 frame_sp;
};

struct MBIO {
    void (*print_int)(mb_i32 value, void *ctx);
    void (*newline)(void *ctx);
    void *ctx;
};

struct MBConsoleIO {
    void (*put_char)(char c, void *ctx);
    void *ctx;
};

struct MBReplIO {
    int (*get_char)(void *ctx);
    void (*put_char)(char c, void *ctx);
    void *ctx;
};

typedef void (*MBListFn)(mb_u16 line, const mb_u8 *payload, mb_u16 len, void *ctx);
typedef void (*MBSourceListFn)(mb_u16 line, const char *source, mb_u16 len, void *ctx);

void mb_program_init(MBProgram *program, mb_u8 *memory, mb_u16 capacity);
void mb_program_set_builtins(MBProgram *program, const MBBuiltin *builtins, mb_u8 count);
void mb_program_clear(MBProgram *program);
int mb_program_store_line(MBProgram *program, mb_u16 line, const char *text);
int mb_program_store_payload(MBProgram *program, mb_u16 line, const mb_u8 *payload, mb_u16 len);
int mb_program_delete_line(MBProgram *program, mb_u16 line);
void mb_program_each(const MBProgram *program, MBListFn fn, void *ctx);
void mb_program_each_source(const MBProgram *program, MBSourceListFn fn, void *ctx);
mb_u16 mb_program_bytes_used(const MBProgram *program);

void mb_runtime_init(MBRuntime *runtime);
int mb_compile_expr(const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len);
int mb_eval_expr(const mb_u8 *code, mb_u16 len, MBRuntime *runtime, mb_i32 *result);
int mb_compile_statement(const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len);
int mb_decompile_statement(const mb_u8 *code, mb_u16 len, char *out, mb_u16 cap);
int mb_program_store_statement(MBProgram *program, mb_u16 line, const char *text);
int mb_program_run(const MBProgram *program, MBRuntime *runtime, const MBIO *io, mb_u16 max_steps);
int mb_console_process_line(MBProgram *program,
                            MBRuntime *runtime,
                            const char *line,
                            const MBIO *run_io,
                            const MBConsoleIO *console_io,
                            mb_u16 max_steps);
int mb_repl(MBProgram *program,
            MBRuntime *runtime,
            const MBReplIO *io,
            char *line_buffer,
            mb_u16 line_capacity,
            mb_u16 max_steps);

#endif

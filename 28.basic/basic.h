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
    MB_ERR_BAD_BUILTIN = -11,
    MB_ERR_STRING_TOO_LONG = -12,
    MB_ERR_TYPE_MISMATCH = -13,
    MB_ERR_NO_INPUT = -14,
    MB_ERR_SUBSCRIPT = -15,
    MB_ERR_NO_ARRAY = -16,
    MB_ERR_ARRAY_EXISTS = -17
};

/* Non-error results of mb_run_step (positive, so any negative is an error). */
enum {
    MB_RUNNING = 1,       /* more statements to run */
    MB_WAITING_INPUT = 2  /* an INPUT has no line yet; call mb_run_step again later */
};

/* MBIO.read_line may return this instead of a length: "no line yet". Only
   mb_run_step understands it (as MB_WAITING_INPUT); mb_program_run turns it
   into MB_ERR_NO_INPUT. Any other negative value still means no more input. */
#define MB_READ_WAIT (-2)

/* Sizes and limits. Everything tunable lives here.

   The text limits form a chain: what the compiler accepts has to be something
   LIST can decompile again, so the decompiler-side buffers are never smaller
   than the compiler-side ones (checked at compile time in basic.c). */
enum {
    /* Runtime state */
    MB_VAR_COUNT = 64,           /* variables, integer and string together */
    MB_SYMBOL_NAME_MAX = 16,     /* variable name, including '$' and the NUL */
    MB_CONTROL_STACK_MAX = 16,   /* nested GOSUB / FOR / block IF / WHILE */
    MB_EXPR_STACK_MAX = 16,      /* operands of one expression */
    MB_HEAP_SIZE = 2048,         /* bytes shared by strings and arrays, at most 65535 */
    MB_RUN_JUMP_MAX = 64,        /* IF/ELSE/WHILE/FOR jumps prepared by RUN */
    MB_LOAD_LINE_MAX = 256,      /* one source line given to mb_program_load_text */

    /* Builtins */
    MB_BUILTIN_NAME_MAX = 12,
    MB_BUILTIN_ARG_MAX = 4,

    /* Compiler: source text */
    MB_EXPR_TEXT_MAX = 96,       /* one expression, one PRINT item, one decompiled expression (with the NUL) */
    MB_STMT_TEXT_MAX = 128,      /* the THEN or ELSE branch of a one-line IF (with the NUL) */
    MB_STRING_LITERAL_MAX = 255, /* bytes in a "literal" or INPUT prompt; its length is one byte, do not raise */

    /* Compiler: bytecode */
    MB_STMT_CODE_MAX = 128,      /* compiled bytes of one statement */

    /* Decompiler and console */
    MB_LINE_TEXT_MAX = 192,      /* one decompiled statement, as LIST prints it (with the NUL) */
    MB_INPUT_LINE_MAX = 128      /* one INPUT reply (with the NUL) */
};

enum {
    MB_BC_END = 0,
    MB_BC_PUSH_I32 = 1,
    MB_BC_PUSH_VAR = 2,
    MB_BC_CALL_BUILTIN = 3,
    MB_BC_PUSH_STR = 4,
    MB_BC_PUSH_ELEM = 5,
    MB_BC_ADD = 16,
    MB_BC_SUB = 17,
    MB_BC_MUL = 18,
    MB_BC_DIV = 19,
    MB_BC_NEG = 20,
    MB_BC_MOD = 21,
    MB_BC_IDIV = 22,
    MB_BC_POW = 23,
    MB_BC_AND = 24,
    MB_BC_OR = 25,
    MB_BC_XOR = 26,
    MB_BC_NOT = 27,
    MB_BC_SHL = 28,
    MB_BC_SHR = 29,
    MB_BC_EQ = 32,
    MB_BC_NE = 33,
    MB_BC_LT = 34,
    MB_BC_LE = 35,
    MB_BC_GT = 36,
    MB_BC_GE = 37,
    MB_BC_CONCAT = 48,
    MB_BC_SEQ = 49,
    MB_BC_SNE = 50,
    MB_BC_SLT = 51,
    MB_BC_SLE = 52,
    MB_BC_SGT = 53,
    MB_BC_SGE = 54
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
    MB_ST_NEXT = 79,
    MB_ST_LET_STR = 80,
    MB_ST_INPUT = 82,
    MB_ST_INPUT_STR = 83,
    MB_ST_DIM = 84,
    MB_ST_REDIM = 85,
    MB_ST_ERASE = 86,
    MB_ST_LET_ELEM = 87,
    MB_ST_LET_ELEM_STR = 88
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
typedef struct MBJumpEntry MBJumpEntry;
typedef struct MBRunPlan MBRunPlan;
typedef struct MBRun MBRun;
typedef struct MBBuiltin MBBuiltin;
typedef struct MBArray MBArray;

typedef int (*MBBuiltinFn)(MBRuntime *runtime, const mb_i32 *args, mb_u8 argc, mb_i32 *result);

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

/* A one-dimensional array: count elements of 4 bytes each, stored in the heap. */
struct MBArray {
    mb_u16 off;
    mb_u16 count; /* 0: not dimensioned */
    mb_u8 is_str;
};

struct MBBuiltin {
    const char *name;
    mb_u8 min_args;
    mb_u8 max_args;
    MBBuiltinFn fn;
    mb_u8 string_args;   /* bit i set: argument i is a string */
    mb_u8 string_result; /* non-zero: the result is a string */
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

struct MBJumpEntry {
    mb_u16 from;
    mb_u16 to;
};

/* Jumps paired by the preparation pass that starts a run. */
struct MBRunPlan {
    MBJumpEntry jumps[MB_RUN_JUMP_MAX];
    mb_u8 jump_count;
};

/* A run in progress: where it is and the plan it follows. The caller owns it
   and must not touch the program while it is live. */
struct MBRun {
    MBRunPlan plan;
    mb_u16 current; /* offset of the next statement; 0 when finished */
};

struct MBRuntime {
    mb_i32 vars[MB_VAR_COUNT];
    MBFrame frames[MB_CONTROL_STACK_MAX];
    mb_u8 frame_sp;
    mb_u8 input_prompted; /* an INPUT printed its prompt and is waiting for the line */
    /* One heap for strings and arrays:
         [0, str_used)        persistent strings (a string holds a handle,
                              offset << 16 | length)
         [str_used, str_top)  temporaries of the expression being evaluated,
                              discarded when the next one starts
         [str_top, arr_base)  free
         [arr_base, end)      array blocks, allocated downwards
       str_garbage counts the bytes of persistent strings nobody refers to any
       more; a string collection gets them back. */
    mb_u8 heap[MB_HEAP_SIZE];
    mb_u16 str_used;
    mb_u16 str_top;
    mb_u16 str_garbage;
    mb_u16 arr_base;
    mb_u8 str_var[MB_VAR_COUNT];
    MBArray arrays[MB_VAR_COUNT];
};

struct MBIO {
    void (*print_int)(mb_i32 value, void *ctx);
    void (*print_str)(const char *text, mb_u16 len, void *ctx);
    void (*newline)(void *ctx);
    /* Reads one line for INPUT into buf (at most cap - 1 characters, without
       the line terminator) and returns its length, or a negative value when
       there is no more input. */
    int (*read_line)(char *buf, mb_u16 cap, void *ctx);
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

/* String helpers for builtins. A string argument or result is a handle. */
const char *mb_str_data(const MBRuntime *runtime, mb_i32 handle, mb_u16 *len);
mb_i32 mb_str_slice(mb_i32 handle, mb_u16 start, mb_u16 len);
int mb_str_alloc(MBRuntime *runtime, mb_u16 len, mb_i32 *handle);
int mb_str_make(MBRuntime *runtime, const char *text, mb_u16 len, mb_i32 *handle);
int mb_compile_expr(const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len);
int mb_eval_expr(const mb_u8 *code, mb_u16 len, MBRuntime *runtime, mb_i32 *result);
int mb_compile_statement(const char *text, mb_u8 *out, mb_u16 cap, mb_u16 *out_len);
int mb_decompile_statement(const mb_u8 *code, mb_u16 len, char *out, mb_u16 cap);
int mb_program_store_statement(MBProgram *program, mb_u16 line, const char *text);
int mb_program_run(const MBProgram *program, MBRuntime *runtime, const MBIO *io, mb_u16 max_steps);

/* Run in slices, so the caller can do other things in between (redraw a screen,
   look for a break key). mb_run_begin prepares the run; each mb_run_step then
   executes up to max_statements statements (at least one) and returns
   MB_RUNNING (call again), MB_OK (the program ended), MB_WAITING_INPUT (an
   INPUT is waiting: call again once io->read_line can deliver a line) or a
   negative error. To abandon a run, just stop calling mb_run_step. */
int mb_run_begin(const MBProgram *program, MBRuntime *runtime, MBRun *run);
int mb_run_step(const MBProgram *program, MBRuntime *runtime, MBRun *run, const MBIO *io, mb_u16 max_statements);

/* Line number of the statement a run is at: after mb_run_step returned an error,
   the one that failed. 0 when the run has finished. */
mb_u16 mb_run_line(const MBProgram *program, const MBRun *run);

/* Name of an error, as the REPL prints it after the '?' ("DIV ZERO"). */
const char *mb_error_text(int err);

/* Stores a whole program given as text: one numbered line per text line ('\n'
   or "\r\n"); blank lines are skipped. It does not clear the program first. On
   an error returns it and sets *error_line (when not null) to the 1-based
   position of the offending text line. */
int mb_program_load_text(MBProgram *program, const char *text, mb_u16 len, mb_u16 *error_line);
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

#include "basic.h"
#include "basic_platform.h"

/* Program and REPL line buffers. Static: on MiniCPU everything (code, data and
   the stack that starts at 0x10000) shares 64 KiB. */
static mb_u8 program_memory[4096];
static char line_buffer[160];
static MBProgram program;
static MBRuntime runtime;

int main(void)
{
    MBReplIO io;

    mb_program_init(&program, program_memory, sizeof(program_memory));
    mb_runtime_init(&runtime);

    io.get_char = platform_get_char;
    io.put_char = platform_put_char;
    io.ctx = 0;

    return mb_repl(&program, &runtime, &io, line_buffer, sizeof(line_buffer), 0xFFFF);
}

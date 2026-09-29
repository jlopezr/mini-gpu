/* Same as basic_mini.c but for a live terminal: no BASIC_UART_EOF, so an empty
   input queue means "no key yet" and get_char waits instead of ending the
   session. Used by run_minicpu.py --interactive. */

#include "basic.c"
#include "basic_builtins.c"
#include "basic_platform_mini.c"
#include "basic_main.c"

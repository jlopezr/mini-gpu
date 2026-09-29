/* Single translation unit for mini-lcc, which takes one .c: the BASIC, the
   MiniCPU platform and main. The host build compiles the files separately
   (see the Makefile). */

/* Simulator build: an empty input queue ends the session and main returns,
   which reaches the HALT after the call to main. Remove for a board. */
#define BASIC_UART_EOF 1

#include "basic.c"
#include "basic_builtins.c"
#include "basic_platform_mini.c"
#include "basic_main.c"

/* Same as basic_mini_tty.c, but the output also goes to the text console of
   prototype 30 (see basic_platform_console.c). Input is still the serial port,
   so run it with `run-board --prototype 30 --interactive` or monitor.py
   console. No BASIC_UART_EOF: an empty queue means "no key yet". */

#include "basic.c"
#include "basic_builtins.c"
#include "basic_platform_console.c"

/* basic_main.c owns main(); take it over to initialise the screen first. */
#define main basic_main
#include "basic_main.c"
#undef main

int main(void)
{
    console_init();
    return basic_main();
}

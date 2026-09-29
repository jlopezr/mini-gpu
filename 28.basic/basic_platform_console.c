#include "basic_platform.h"

/* MiniCPU with the 80x30 text console of prototype 30. Input comes from the
   serial port, like basic_platform_mini.c; output goes to the serial port AND
   to the screen, so a terminal on the PC keeps working as before.

   The console has no hardware cursor, no scroll and no control characters: it
   is a 2400-cell RAM, one 32-bit word per cell, `BG[15:12] FG[11:8] CHAR[7:0]`.
   Everything else (cursor, newline, backspace, scroll by copying) lives here. */

#define UART_DATA   (*(volatile unsigned int *)0x80100000)
#define UART_STATUS (*(volatile unsigned int *)0x80100004)

#define VIDEO_COMMIT    (*(volatile unsigned int *)0x8020000c)
#define VIDEO_CONFIG    (*(volatile unsigned int *)0x80200040)
#define VIDEO_PALETTE1  (*(volatile unsigned int *)0x80201004)
#define TEXT_RAM        ((volatile unsigned int *)0x80206000)

#define COLS   80
#define ROWS   30
#define CELLS  (COLS * ROWS)

#define ATTR_FG1  0x0100          /* palette entry 1 on entry 0 */
#define BLANK     (ATTR_FG1 | 0x20)
#define CURSOR    (ATTR_FG1 | 0x5F)   /* underscore */

static int cur_col;
static int cur_row;
static unsigned int under;        /* what the cursor is sitting on */

static void cursor_hide(void)
{
    TEXT_RAM[cur_row * COLS + cur_col] = under;
}

static void cursor_show(void)
{
    under = TEXT_RAM[cur_row * COLS + cur_col] & 0xFFFF;
    TEXT_RAM[cur_row * COLS + cur_col] = CURSOR;
}

static void scroll_up(void)
{
    int i;
    for (i = 0; i < CELLS - COLS; i++)
        TEXT_RAM[i] = TEXT_RAM[i + COLS];
    for (; i < CELLS; i++)
        TEXT_RAM[i] = BLANK;
}

static void new_line(void)
{
    cur_col = 0;
    if (cur_row == ROWS - 1)
        scroll_up();
    else
        cur_row++;
}

/* Clears the screen, sets the colour and turns the text layer on. Must run
   once before the first platform_put_char. Nothing here relies on statics
   being zero at start: the program is loaded over whatever was in RAM. */
void console_init(void)
{
    int i;

    VIDEO_PALETTE1 = 0x00f0c040;              /* amber, like the CPC demo */
    for (i = 0; i < CELLS; i++)
        TEXT_RAM[i] = BLANK;

    VIDEO_CONFIG = 4;                         /* TEXT_ENABLE, in the shadow */
    VIDEO_COMMIT = 2;                         /* applied on the next VBlank */
    while (VIDEO_COMMIT != 0) {
    }

    cur_col = 0;
    cur_row = 0;
    under = BLANK;
    cursor_show();
}

static void screen_put(char c)
{
    unsigned char ch = (unsigned char)c;

    cursor_hide();
    if (ch == '\r') {
        cur_col = 0;
    } else if (ch == '\n') {
        new_line();
    } else if (ch == 8 || ch == 127) {
        if (cur_col > 0)
            cur_col--;
    } else if (ch >= 32) {
        TEXT_RAM[cur_row * COLS + cur_col] = ATTR_FG1 | ch;
        cur_col++;
        if (cur_col == COLS)
            new_line();
    }
    cursor_show();
}

int platform_get_char(void *ctx)
{
    (void)ctx;
    while ((UART_STATUS & 0xFF) == 0) {
    }
    return (int)(UART_DATA & 0xFF);
}

void platform_put_char(char c, void *ctx)
{
    (void)ctx;
    screen_put(c);
    while (((UART_STATUS >> 8) & 0xFF) == 0) {
    }
    UART_DATA = (unsigned int)(unsigned char)c;
}

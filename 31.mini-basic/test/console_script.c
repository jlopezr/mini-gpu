/*
 * A console backend with the keys written down, for running mini-basic without a
 * terminal: it feeds the keys of a scenario (MB_SCENARIO=1..3), and when they run
 * out it prints the screen and exits. The scenarios depend on the sample program in
 * mb_main.c.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "console.h"

#define W 80
#define H 30

static int chars[H][W];
static const int *keys;
static int key_count;
static int key_pos;

#define E TUI_KEY_ENTER

/* F5, then three guesses, then an immediate statement that reads a variable. */
static const int scenario1[] = {
    TUI_KEY_F5,
    '1', '0', E, '5', '0', E, '3', '7', E,
    TUI_KEY_F6,
    'P', 'R', 'I', 'N', 'T', ' ', 'N', '*', '2', E
};

/* F5, then Esc while the program waits for its INPUT. */
static const int scenario2[] = {
    TUI_KEY_F5, TUI_KEY_ESCAPE
};

/* A faulty program typed at the top of the editor: the error names its line. */
static const int scenario3[] = {
    '5', ' ', 'P', 'R', 'I', 'N', 'T', ' ', '1', '/', '0', E, TUI_KEY_F5
};

/* F1 opens the About window. */
static const int scenario4[] = {
    TUI_KEY_F1
};

int tui_console_init(void)
{
    const char *s;
    int n;

    s = getenv("MB_SCENARIO");
    n = s != 0 ? atoi(s) : 1;
    if (n == 4) {
        keys = scenario4;
        key_count = (int)(sizeof(scenario4) / sizeof(scenario4[0]));
    } else if (n == 2) {
        keys = scenario2;
        key_count = (int)(sizeof(scenario2) / sizeof(scenario2[0]));
    } else if (n == 3) {
        keys = scenario3;
        key_count = (int)(sizeof(scenario3) / sizeof(scenario3[0]));
    } else {
        keys = scenario1;
        key_count = (int)(sizeof(scenario1) / sizeof(scenario1[0]));
    }
    return 1;
}

void tui_console_shutdown(void) {}
int tui_console_width(void) { return W; }
int tui_console_height(void) { return H; }
int tui_console_has_mouse(void) { return 0; }
int tui_console_printable(int key) { return TUI_ASCII_PRINTABLE(key); }
void tui_console_mouse(int *x, int *y, int *a, int *b) { *x = *y = *a = *b = 0; }
void tui_console_cursor(int x, int y, int visible) { (void)x; (void)y; (void)visible; }
void tui_console_present(void) {}

void tui_console_cell(int x, int y, int ch, int attr)
{
    (void)attr;
    if (x >= 0 && x < W && y >= 0 && y < H)
        chars[y][x] = ch;
}

int tui_console_poll(void)
{
    if (key_pos < key_count)
        return keys[key_pos++];
    return TUI_KEY_NONE;
}

/* Blocking read with nothing left to type: the scenario is over, show the screen. */
int tui_console_key(void)
{
    int x;
    int y;
    int last;
    int c;

    if (key_pos < key_count)
        return keys[key_pos++];

    for (y = 0; y < H; ++y) {
        last = -1;
        for (x = 0; x < W; ++x) {
            if (chars[y][x] != ' ' && chars[y][x] != 0)
                last = x;
        }
        for (x = 0; x <= last; ++x) {
            c = chars[y][x];
            putchar(c >= 32 && c < 127 ? c : (c == 0 ? ' ' : '#'));
        }
        putchar('\n');
    }
    exit(0);
    return TUI_KEY_NONE;
}

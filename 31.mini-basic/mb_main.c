/*
 * mini-basic: a QBasic-like environment. The program is edited in the upper
 * window; the lower one is the immediate window: the output of the run and, under
 * it, a line to type statements (or the answer to an INPUT).
 *
 * The interpreter (28.basic) runs in slices of a few statements between two looks
 * at the keyboard, so the screen stays alive and Esc stops a program.
 */
#include "../z.tui/tui.h"
#include "../28.basic/basic.h"

#define SRC_CAP        8192   /* program text */
#define OUT_CAP        4096   /* output kept; the oldest lines go first */
#define PROGRAM_MEMORY 8192   /* compiled program */
#define EDIT_CAP       128    /* the immediate line, and an INPUT reply */
#define SLICE          200    /* statements between two looks at the keyboard */
#define IMMEDIATE_MAX  20000  /* statements an immediate line may run */
#define STATUS_CAP     48

#define CMD_NEW        101
#define CMD_RUN        102
#define CMD_STOP       103
#define CMD_QUIT       104
#define CMD_FOCUS      105
#define CMD_ABOUT      106
#define CMD_ABOUT_OK   107

enum { MODE_IDLE, MODE_RUNNING, MODE_INPUT };

typedef struct App {
    int running;
    int mode;

    TuiDesktop desktop;
    TuiMenuBar menu_bar;
    TuiStatusBar status_bar;
    TuiPanel screen;

    TuiWindow editor_window;
    TuiWindow immediate_window;

    TuiWindow about_window;
    TuiLabel about_title;
    TuiLabel about_line1;
    TuiLabel about_line2;
    TuiLabel about_line3;
    TuiButton about_ok;
    int about_open;

    char src_buffer[SRC_CAP];
    TuiEditor editor;

    char out_buffer[OUT_CAP];
    TuiLinearTextModel out_model;
    TuiEditor out;
    int out_dirty;

    char line_buffer[EDIT_CAP];
    TuiEdit line;

    char status[STATUS_CAP];

    mb_u8 program_memory[PROGRAM_MEMORY];
    MBProgram program;
    MBRuntime runtime;
    MBRun run;
    MBIO io;
    MBConsoleIO console_io;

    char reply[EDIT_CAP];   /* the INPUT reply waiting for read_line */
    int reply_ready;
} App;

static const char sample_program[] =
    "10 REM Guess the number\n"
    "20 SECRET = 37\n"
    "30 INPUT \"Your guess: \"; G\n"
    "40 N = N + 1\n"
    "50 IF G < SECRET THEN PRINT \"Too low\"\n"
    "60 IF G > SECRET THEN PRINT \"Too high\"\n"
    "70 IF G <> SECRET THEN GOTO 30\n"
    "80 PRINT \"Got it in \"; N; \" tries\"\n"
    "90 END\n";

/*
 * ------------------------------------------------------------
 * Small text helpers (no libc: this has to build for the MiniCPU too)
 * ------------------------------------------------------------
 */

static int text_length(const char *s)
{
    int n;

    for (n = 0; s[n] != '\0'; ++n)
        ;
    return n;
}

static int upper(int c)
{
    return (c >= 'a' && c <= 'z') ? c - 'a' + 'A' : c;
}

/* True if text is the word (case-insensitive) followed only by blanks. */
static int is_word(const char *text, const char *word)
{
    while (*text == ' ')
        ++text;
    while (*word != '\0') {
        if (upper(*text) != *word)
            return 0;
        ++text;
        ++word;
    }
    while (*text == ' ')
        ++text;
    return *text == '\0';
}

/* Writes the decimal text of v at dst (room for 12) and returns its length. */
static int format_long(char *dst, long v)
{
    char tmp[12];
    unsigned long u;
    int n;
    int i;

    n = 0;
    if (v < 0) {
        dst[n++] = '-';
        u = 0UL - (unsigned long)v;
    } else {
        u = (unsigned long)v;
    }
    i = 0;
    do {
        tmp[i++] = (char)('0' + (int)(u % 10UL));
        u /= 10UL;
    } while (u != 0UL);
    while (i > 0)
        dst[n++] = tmp[--i];
    dst[n] = '\0';
    return n;
}

/*
 * ------------------------------------------------------------
 * Output window
 * ------------------------------------------------------------
 */

static void out_put(App *app, const char *text, int n)
{
    int length;
    int drop;
    int need;

    if (n <= 0)
        return;
    if (n > OUT_CAP - 1)
        n = OUT_CAP - 1;

    length = tui_text_model_length(&app->out_model.model);
    need = length + n - (OUT_CAP - 1);
    if (need > 0) {
        /* Drop whole lines from the top: from the start up to the first newline
           at or after the bytes that have to go. */
        drop = need;
        while (drop < length && app->out_buffer[drop - 1] != '\n')
            ++drop;
        if (drop > length)
            drop = length;
        tui_text_model_delete(&app->out_model.model, 0, drop);
        length -= drop;
    }
    tui_text_model_insert(&app->out_model.model, length, text, n);
    app->out_dirty = 1;
}

static void out_text(App *app, const char *text)
{
    out_put(app, text, text_length(text));
}

static void out_clear(App *app)
{
    tui_linear_text_model_set_text(&app->out_model, "");
    app->out_dirty = 1;
}

/* Puts the cursor at the end and scrolls there; once per frame, not per PRINT. */
static void out_flush(App *app)
{
    if (!app->out_dirty)
        return;
    app->out_dirty = 0;
    app->out.cursor_pos = tui_text_model_length(&app->out_model.model);
    tui_editor_reset(&app->out);
}

/* The error as the REPL prints it, with the program line when there is one. */
static void out_error(App *app, int error, int line)
{
    char num[12];

    out_text(app, "?");
    out_text(app, mb_error_text(error));
    if (line > 0) {
        out_text(app, " IN ");
        format_long(num, line);
        out_text(app, num);
    }
    out_text(app, "\n");
}

/* MBIO / MBConsoleIO callbacks. The context is the App. */
static void io_print_int(mb_i32 value, void *ctx)
{
    char num[12];

    format_long(num, (long)value);
    out_text((App *)ctx, num);
}

static void io_print_str(const char *text, mb_u16 len, void *ctx)
{
    out_put((App *)ctx, text, (int)len);
}

static void io_newline(void *ctx)
{
    out_put((App *)ctx, "\n", 1);
}

static void io_put_char(char c, void *ctx)
{
    out_put((App *)ctx, &c, 1);
}

/* INPUT asks for a line: it is there once the user has pressed Enter. */
static int io_read_line(char *buf, mb_u16 cap, void *ctx)
{
    App *app;
    int n;
    int i;

    app = (App *)ctx;
    if (!app->reply_ready)
        return MB_READ_WAIT;

    app->reply_ready = 0;
    n = text_length(app->reply);
    if (n >= (int)cap)
        n = (int)cap - 1;
    for (i = 0; i < n; ++i)
        buf[i] = app->reply[i];
    buf[n] = '\0';
    return n;
}

/*
 * ------------------------------------------------------------
 * Status bar
 * ------------------------------------------------------------
 */

static void status_set(App *app, const char *text)
{
    int i;

    for (i = 0; text[i] != '\0' && i < STATUS_CAP - 1; ++i) {
        if (app->status[i] != text[i])
            break;
    }
    if (text[i] == '\0' && app->status[i] == '\0')
        return;   /* unchanged: do not invalidate the bar */

    for (i = 0; text[i] != '\0' && i < STATUS_CAP - 1; ++i)
        app->status[i] = text[i];
    app->status[i] = '\0';
    tui_statusbar_set_text(&app->status_bar, app->status);
}

static void status_update(App *app)
{
    char text[STATUS_CAP];
    TuiEditorPosition position;
    int n;

    if (app->mode == MODE_RUNNING) {
        status_set(app, "Running - Esc to stop");
        return;
    }
    if (app->mode == MODE_INPUT) {
        status_set(app, "INPUT - type the reply and press Enter");
        return;
    }

    tui_editor_get_position(&app->editor, &position);
    n = 0;
    text[n++] = 'L';
    text[n++] = 'n';
    text[n++] = ' ';
    n += format_long(text + n, position.line + 1);
    text[n++] = ',';
    text[n++] = ' ';
    text[n++] = 'C';
    text[n++] = 'o';
    text[n++] = 'l';
    text[n++] = ' ';
    n += format_long(text + n, position.column + 1);
    text[n] = '\0';
    status_set(app, text);
}

/*
 * ------------------------------------------------------------
 * Running programs
 * ------------------------------------------------------------
 */

/* Puts the cursor of the editor at an offset of its text, and focuses it. */
static void editor_goto(App *app, int offset)
{
    app->editor.cursor_pos = offset;
    tui_editor_reset(&app->editor);
    tui_desktop_set_focus(&app->desktop, &app->editor.control);
}

/* Offset of the start of the 1-based text line, or the end of the text. */
static int offset_of_text_line(const char *src, int line)
{
    int offset;

    offset = 0;
    while (line > 1 && src[offset] != '\0') {
        if (src[offset] == '\n')
            --line;
        ++offset;
    }
    return offset;
}

/* Offset of the text line that starts with the BASIC line number, or -1. */
static int offset_of_basic_line(const char *src, int number)
{
    int offset;
    long value;
    int i;

    offset = 0;
    for (;;) {
        i = offset;
        while (src[i] == ' ')
            ++i;
        value = 0;
        if (src[i] >= '0' && src[i] <= '9') {
            while (src[i] >= '0' && src[i] <= '9') {
                value = value * 10 + (src[i] - '0');
                ++i;
            }
            if (value == number)
                return offset;
        }
        while (src[offset] != '\0' && src[offset] != '\n')
            ++offset;
        if (src[offset] == '\0')
            return -1;
        ++offset;
    }
}

static void run_finish(App *app)
{
    app->mode = MODE_IDLE;
    app->reply_ready = 0;
    tui_desktop_set_focus(&app->desktop, &app->editor.control);
    status_update(app);
}

/* F5: the text of the editor becomes the program, and starts running. */
static void run_start(App *app)
{
    const char *src;
    mb_u16 error_line;
    int r;

    src = tui_editor_get_text(&app->editor);
    mb_program_clear(&app->program);
    mb_runtime_init(&app->runtime);
    out_clear(app);

    error_line = 0;
    r = mb_program_load_text(&app->program, src, (mb_u16)text_length(src), &error_line);
    if (r != MB_OK) {
        char num[12];

        out_error(app, r, 0);
        out_text(app, "in text line ");
        format_long(num, error_line);
        out_text(app, num);
        out_text(app, "\n");
        editor_goto(app, offset_of_text_line(src, error_line));
        status_update(app);
        return;
    }

    r = mb_run_begin(&app->program, &app->runtime, &app->run);
    if (r != MB_OK) {
        out_error(app, r, 0);
        return;
    }

    app->reply_ready = 0;
    app->mode = MODE_RUNNING;
    status_update(app);
}

/* One slice of the run. */
static void run_slice(App *app)
{
    const char *src;
    int line;
    int offset;
    int r;

    r = mb_run_step(&app->program, &app->runtime, &app->run, &app->io, SLICE);
    if (r == MB_RUNNING)
        return;

    if (r == MB_WAITING_INPUT) {
        if (app->mode != MODE_INPUT) {
            app->mode = MODE_INPUT;
            tui_desktop_set_focus(&app->desktop, &app->line.control);
            status_update(app);
        }
        return;
    }

    if (r == MB_OK) {
        out_text(app, "\n(program ended)\n");
        run_finish(app);
        return;
    }

    line = (int)mb_run_line(&app->program, &app->run);
    out_error(app, r, line);
    run_finish(app);
    if (line > 0) {
        src = tui_editor_get_text(&app->editor);
        offset = offset_of_basic_line(src, line);
        if (offset >= 0)
            editor_goto(app, offset);
    }
    status_update(app);
}

static void run_stop(App *app)
{
    if (app->mode == MODE_IDLE)
        return;
    out_text(app, "\n(stopped)\n");
    run_finish(app);
}

/* Enter in the line: an INPUT reply while a program waits, otherwise a statement. */
static void line_enter(App *app)
{
    const char *text;
    const char *p;
    int i;
    int r;

    text = tui_edit_get_text(&app->line);

    if (app->mode == MODE_INPUT) {
        for (i = 0; text[i] != '\0' && i < EDIT_CAP - 1; ++i)
            app->reply[i] = text[i];
        app->reply[i] = '\0';
        app->reply_ready = 1;
        out_text(app, text);
        out_text(app, "\n");
        tui_edit_set_text(&app->line, "");
        app->mode = MODE_RUNNING;
        status_update(app);
        return;
    }
    if (app->mode != MODE_IDLE)
        return;

    out_text(app, text);
    out_text(app, "\n");

    for (p = text; *p == ' '; ++p)
        ;
    if (*p == '\0') {
        tui_edit_set_text(&app->line, "");
        return;
    }

    if (*p >= '0' && *p <= '9') {
        out_text(app, "Numbered lines go in the program window\n");
    } else if (is_word(p, "RUN")) {
        tui_edit_set_text(&app->line, "");
        run_start(app);
        return;
    } else if (is_word(p, "NEW")) {
        tui_editor_set_text(&app->editor, "");
        mb_program_clear(&app->program);
        mb_runtime_init(&app->runtime);
        out_clear(app);
    } else {
        r = mb_console_process_line(&app->program, &app->runtime, p,
                                    &app->io, &app->console_io, IMMEDIATE_MAX);
        if (r != MB_OK)
            out_error(app, r, 0);
    }
    tui_edit_set_text(&app->line, "");
}

/*
 * ------------------------------------------------------------
 * Commands, menus and screen
 * ------------------------------------------------------------
 */

static void cmd_new(void *context, int command)
{
    App *app;

    (void)command;
    app = (App *)context;
    run_stop(app);
    tui_editor_set_text(&app->editor, "");
    mb_program_clear(&app->program);
    mb_runtime_init(&app->runtime);
    out_clear(app);
    editor_goto(app, 0);
    status_update(app);
}

static void cmd_run(void *context, int command)
{
    App *app;

    (void)command;
    app = (App *)context;
    if (app->mode == MODE_IDLE)
        run_start(app);
}

static void cmd_stop(void *context, int command)
{
    (void)command;
    run_stop((App *)context);
}

static void cmd_quit(void *context, int command)
{
    (void)command;
    ((App *)context)->running = 0;
}

/* F6 moves between the program and the immediate line. */
static void cmd_focus(void *context, int command)
{
    App *app;

    (void)command;
    app = (App *)context;
    if (app->mode != MODE_IDLE)
        return;
    if (tui_desktop_get_focus(&app->desktop) == &app->line.control)
        tui_desktop_set_focus(&app->desktop, &app->editor.control);
    else
        tui_desktop_set_focus(&app->desktop, &app->line.control);
}

/* The About window floats over the desktop until OK (or Esc) takes it away. */
static void about_close(App *app)
{
    if (!app->about_open)
        return;
    app->about_open = 0;
    tui_remove(&app->about_window.control);
    tui_desktop_set_focus(&app->desktop,
                          app->mode == MODE_INPUT ? &app->line.control
                                                  : &app->editor.control);
}

static void cmd_about(void *context, int command)
{
    App *app;

    (void)command;
    app = (App *)context;
    if (app->about_open)
        return;
    app->about_open = 1;
    tui_add(&app->desktop.control, &app->about_window.control);
    tui_desktop_set_focus(&app->desktop, &app->about_ok.control);
}

static void cmd_about_ok(void *context, int command)
{
    (void)command;
    about_close((App *)context);
}

static const TuiCommand command_table[] = {
    { CMD_ABOUT,    0, cmd_about },
    { CMD_ABOUT_OK, 0, cmd_about_ok },
    { CMD_NEW,   0, cmd_new },
    { CMD_RUN,   0, cmd_run },
    { CMD_STOP,  0, cmd_stop },
    { CMD_QUIT,  0, cmd_quit },
    { CMD_FOCUS, 0, cmd_focus },
    TUI_COMMANDS_END
};

static TuiMenuItem file_items[] = {
    { "New",  CMD_NEW,  TUI_KEY_NONE, 0 },
    { 0,      0,        TUI_KEY_NONE, TUI_MENU_SEPARATOR },
    { "Exit", CMD_QUIT, TUI_KEY_F10,  0 }
};

static TuiMenuItem run_items[] = {
    { "Run",              CMD_RUN,   TUI_KEY_F5,   0 },
    { "Stop",             CMD_STOP,  TUI_KEY_NONE, 0 },
    { "Switch window",    CMD_FOCUS, TUI_KEY_F6,   0 }
};

static TuiMenuItem help_items[] = {
    { "About", CMD_ABOUT, TUI_KEY_F1, 0 }
};

static TuiMenu menus[] = {
    { "File", file_items, 3 },
    { "Run",  run_items,  3 },
    { "Help", help_items, 1 }
};

static TuiStatusItem status_items[] = {
    { "Help",   TUI_KEY_F1,  CMD_ABOUT },
    { "Run",    TUI_KEY_F5,  CMD_RUN   },
    { "Window", TUI_KEY_F6,  CMD_FOCUS },
    { "Exit",   TUI_KEY_F10, CMD_QUIT  }
};

static void build_screen(App *app)
{
    tui_panel_init(&app->screen, 0, 0, 1, 1);
    app->screen.control.dock = TUI_DOCK_FILL;

    /* Docked in this order: the bottom window takes its share, the rest is the editor. */
    tui_window_init(&app->immediate_window, 0, 0, 1, 10, "Immediate");
    app->immediate_window.control.dock = TUI_DOCK_BOTTOM;
    app->immediate_window.control.attr = TUI_ATTR(TUI_LIGHTGRAY, TUI_BLACK);

    tui_window_init(&app->editor_window, 0, 0, 1, 1, "Untitled");
    app->editor_window.control.dock = TUI_DOCK_FILL;
    app->editor_window.control.attr = TUI_ATTR(TUI_WHITE, TUI_BLUE);

    app->src_buffer[0] = '\0';
    tui_editor_init_buffer(&app->editor, 0, 0, 1, 1, app->src_buffer, SRC_CAP);
    app->editor.control.dock = TUI_DOCK_FILL;
    tui_editor_set_text(&app->editor, sample_program);

    app->out_buffer[0] = '\0';
    tui_linear_text_model_init(&app->out_model, app->out_buffer, OUT_CAP);
    tui_editor_init(&app->out, 0, 0, 1, 1, &app->out_model.model);
    app->out.control.dock = TUI_DOCK_FILL;
    tui_editor_set_readonly(&app->out, 1);

    app->line_buffer[0] = '\0';
    tui_edit_init(&app->line, 0, 0, 1, app->line_buffer, EDIT_CAP);
    app->line.control.dock = TUI_DOCK_BOTTOM;
    app->line.control.attr = TUI_ATTR(TUI_BLACK, TUI_CYAN);

    /* The line first: it docks to the bottom, the output takes what is left. */
    tui_add(&app->immediate_window.control, &app->line.control);
    tui_add(&app->immediate_window.control, &app->out.control);
    tui_add(&app->editor_window.control, &app->editor.control);

    tui_add(&app->screen.control, &app->immediate_window.control);
    tui_add(&app->screen.control, &app->editor_window.control);

    /* Built here, added to the desktop only while it is open. */
    tui_window_init(&app->about_window, 18, 8, 44, 11, "About");
    tui_window_set_flags(&app->about_window, TUI_WINDOW_FIXED | TUI_WINDOW_ACTIVE_DOUBLE);
    app->about_window.control.attr = TUI_ATTR(TUI_BLACK, TUI_LIGHTGRAY);
    tui_label_init(&app->about_title, 1, 1, "mini-basic");
    tui_label_init(&app->about_line1, 1, 3, "A QBasic-like BASIC for the MiniCPU.");
    tui_label_init(&app->about_line2, 1, 4, "Interpreter: 28.basic    TUI: z.tui");
    tui_label_init(&app->about_line3, 1, 6, "F5 run   Esc stop   F6 switch window");
    tui_button_init(&app->about_ok, 17, 8, 8, "OK", CMD_ABOUT_OK);
    tui_add(&app->about_window.control, &app->about_title.control);
    tui_add(&app->about_window.control, &app->about_line1.control);
    tui_add(&app->about_window.control, &app->about_line2.control);
    tui_add(&app->about_window.control, &app->about_line3.control);
    tui_add(&app->about_window.control, &app->about_ok.control);
}

int main(void)
{
    /* Static: far bigger than the 8 KiB stack of the MiniCPU start-up code. */
    static App app;
    TuiEvent event;
    int got;

    if (!tui_init())
        return 1;

    tui_desktop_init(&app.desktop);
    tui_menubar_init(&app.menu_bar, menus, 3);
    tui_statusbar_init(&app.status_bar, status_items, 4);
    tui_add(&app.desktop.control, &app.menu_bar.control);
    tui_add(&app.desktop.control, &app.status_bar.control);
    tui_desktop_set_commands(&app.desktop, command_table, &app, &app.status_bar);

    build_screen(&app);
    tui_add(&app.desktop.control, &app.screen.control);

    mb_program_init(&app.program, app.program_memory, sizeof(app.program_memory));
    mb_runtime_init(&app.runtime);
    app.io.print_int = io_print_int;
    app.io.print_str = io_print_str;
    app.io.newline = io_newline;
    app.io.read_line = io_read_line;
    app.io.ctx = &app;
    app.console_io.put_char = io_put_char;
    app.console_io.ctx = &app;

    app.mode = MODE_IDLE;
    app.running = 1;
    tui_desktop_set_focus(&app.desktop, &app.editor.control);
    status_update(&app);

    while (app.running) {
        if (app.mode == MODE_RUNNING)
            run_slice(&app);

        out_flush(&app);
        tui_draw_pending(&app.desktop);

        /* Waiting for a key only when there is nothing else to do. */
        if (app.mode == MODE_RUNNING)
            got = tui_poll_event(&event);
        else
            got = tui_read_event(&event);
        if (!got)
            continue;

        if (event.type == TUI_EV_KEY &&
            event.key == TUI_KEY_ESCAPE &&
            app.about_open) {
            about_close(&app);
        } else if (event.type == TUI_EV_KEY &&
            event.key == TUI_KEY_ESCAPE &&
            app.mode != MODE_IDLE) {
            run_stop(&app);
        } else if (event.type == TUI_EV_KEY &&
                   event.key == TUI_KEY_ENTER &&
                   app.desktop.capture == 0 &&
                   tui_desktop_get_focus(&app.desktop) == &app.line.control) {
            line_enter(&app);
        } else {
            tui_dispatch(&app.desktop, &event);
        }

        if (app.mode == MODE_IDLE)
            status_update(&app);
    }

    tui_shutdown();
    return 0;
}

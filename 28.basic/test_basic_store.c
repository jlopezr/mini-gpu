#include "basic.h"

#include <stdio.h>
#include <string.h>

struct Capture {
    char text[512];
    int failed;
};

static void append_char(struct Capture *cap, char c)
{
    size_t n;

    n = strlen(cap->text);
    if (n + 1 >= sizeof(cap->text)) {
        cap->failed = 1;
        return;
    }
    cap->text[n] = c;
    cap->text[n + 1] = 0;
}

static void append_text(struct Capture *cap, const char *s)
{
    while (*s != 0) {
        append_char(cap, *s);
        ++s;
    }
}

static void append_u16(struct Capture *cap, mb_u16 value)
{
    char buf[8];

    sprintf(buf, "%u", (unsigned)value);
    append_text(cap, buf);
}

static void capture_line(mb_u16 line, const mb_u8 *payload, mb_u16 len, void *ctx)
{
    struct Capture *cap;
    mb_u16 i;

    cap = (struct Capture *)ctx;
    append_u16(cap, line);
    append_char(cap, ' ');
    for (i = 0; i < len; ++i) {
        append_char(cap, (char)payload[i]);
    }
    append_char(cap, '\n');
}

static int expect_text(const char *got, const char *want)
{
    if (strcmp(got, want) != 0) {
        printf("got:\n%s\nwant:\n%s\n", got, want);
        return 1;
    }
    return 0;
}

int main(void)
{
    mb_u8 memory[256];
    MBProgram program;
    struct Capture cap;

    mb_program_init(&program, memory, sizeof(memory));

    if (mb_program_store_line(&program, 20, "PRINT A") != MB_OK) return 1;
    if (mb_program_store_line(&program, 10, "LET A = 1") != MB_OK) return 1;
    if (mb_program_store_line(&program, 30, "GOTO 20") != MB_OK) return 1;
    if (mb_program_store_line(&program, 20, "PRINT A + 1") != MB_OK) return 1;
    if (mb_program_delete_line(&program, 30) != MB_OK) return 1;

    cap.text[0] = 0;
    cap.failed = 0;
    mb_program_each(&program, capture_line, &cap);

    if (cap.failed) return 1;
    if (expect_text(cap.text, "10 LET A = 1\n20 PRINT A + 1\n") != 0) return 1;

    printf("ok: store/replace/delete/list\n");
    return 0;
}

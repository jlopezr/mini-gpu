/* stdio.c - formatter pequeño con sinks para UART, consola HDMI y buffers. */
#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <console.h>
#include <mmio.h>

#define SERIAL_TX_FREE_SHIFT 8
#define CONSOLE_CONFIG        (VIDEO_BASE + 0x40u)
#define CONSOLE_TEXT          (VIDEO_BASE + 0x6000u)
#define CONSOLE_COLUMNS       80u
#define CONSOLE_ROWS          30u
#define VIDEO_STATE_COMMIT    2u

typedef int (*Putc)(int c, void *ctx);

typedef struct {
    char *dst;
    size_t size;
    size_t count;
} Buffer;

static unsigned console_x;
static unsigned console_y;
static unsigned console_attr = 0x0f00u;

int serial_putc(int c) {
    while (((REG(MMIO_SERIAL_STATUS_ADDR) >> SERIAL_TX_FREE_SHIFT) & 0xffu) == 0) {}
    REG(MMIO_SERIAL_DATA_ADDR) = (unsigned char)c;
    return (unsigned char)c;
}

static void console_cell(unsigned x, unsigned y, unsigned value) {
    REG(CONSOLE_TEXT + 4u * (y * CONSOLE_COLUMNS + x)) = value;
}

static void console_newline(void) {
    console_x = 0;
    if (++console_y < CONSOLE_ROWS) return;
    for (console_y = 1; console_y < CONSOLE_ROWS; ++console_y)
        for (console_x = 0; console_x < CONSOLE_COLUMNS; ++console_x)
            console_cell(console_x, console_y - 1, REG(CONSOLE_TEXT + 4u *
                         (console_y * CONSOLE_COLUMNS + console_x)));
    for (console_x = 0; console_x < CONSOLE_COLUMNS; ++console_x)
        console_cell(console_x, CONSOLE_ROWS - 1, console_attr | ' ');
    console_x = 0;
    console_y = CONSOLE_ROWS - 1;
}

void console_init(unsigned foreground, unsigned background) {
    console_x = 0;
    console_y = 0;
    console_attr = ((foreground & 15u) << 8) | ((background & 15u) << 12);
}

void console_enable(void) {
    REG(CONSOLE_CONFIG) = 4u;
    REG(VIDEO_SWAP) = VIDEO_STATE_COMMIT;
}

int console_putc(int c) {
    unsigned char ch = (unsigned char)c;
    if (ch == '\r') {
        console_x = 0;
    } else if (ch == '\n') {
        console_newline();
    } else if (ch == '\b') {
        if (console_x) --console_x;
    } else {
        console_cell(console_x, console_y, console_attr | ch);
        if (++console_x == CONSOLE_COLUMNS) console_newline();
    }
    return ch;
}

int serial_console_putc(int c) {
    serial_putc(c);
    return console_putc(c);
}

static int serial_emit(int c, void *ctx) {
    (void)ctx;
    return serial_putc(c);
}

static int console_emit(int c, void *ctx) {
    (void)ctx;
    return console_putc(c);
}

static int tee_emit(int c, void *ctx) {
    (void)ctx;
    return serial_console_putc(c);
}

static int buffer_emit(int c, void *ctx) {
    Buffer *buffer = (Buffer *)ctx;
    if (buffer->size && buffer->count + 1 < buffer->size)
        buffer->dst[buffer->count] = (char)c;
    ++buffer->count;
    return c;
}

static void emit_unsigned(Putc putc_fn, void *ctx, unsigned value, unsigned base,
                          unsigned width, int zero_pad, int upper, int *count) {
    char digits[11];
    unsigned n = 0;
    do {
        unsigned digit = value % base;
        digits[n++] = (char)(digit < 10 ? '0' + digit
            : (upper ? 'A' : 'a') + digit - 10);
        value /= base;
    } while (value);
    while (n < width) {
        putc_fn(zero_pad ? '0' : ' ', ctx);
        ++*count;
        --width;
    }
    while (n) {
        putc_fn(digits[--n], ctx);
        ++*count;
    }
}

static int vformat(Putc putc_fn, void *ctx, const char *fmt, va_list ap) {
    int count = 0;
    while (*fmt) {
        unsigned width = 0;
        int precision = -1;
        int zero_pad = 0;
        int c;
        if (*fmt != '%') {
            putc_fn((unsigned char)*fmt++, ctx);
            ++count;
            continue;
        }
        ++fmt;
        if (*fmt == '0') {
            zero_pad = 1;
            ++fmt;
        }
        while (*fmt >= '0' && *fmt <= '9') width = width * 10u + (unsigned)(*fmt++ - '0');
        if (*fmt == '.') {
            precision = 0;
            ++fmt;
            while (*fmt >= '0' && *fmt <= '9')
                precision = precision * 10 + (*fmt++ - '0');
        }
        if (*fmt == 'l') ++fmt;
        c = (unsigned char)*fmt++;
        if (c == 'd' || c == 'i') {
            int value = va_arg(ap, int);
            if (value < 0) {
                putc_fn('-', ctx);
                ++count;
                if (width) --width;
                emit_unsigned(putc_fn, ctx, (unsigned)-(value + 1) + 1u, 10, width,
                              zero_pad, 0, &count);
            } else emit_unsigned(putc_fn, ctx, (unsigned)value, 10, width, zero_pad, 0, &count);
        } else if (c == 'u') {
            emit_unsigned(putc_fn, ctx, va_arg(ap, unsigned), 10, width, zero_pad, 0, &count);
        } else if (c == 'x' || c == 'X' || c == 'o') {
            emit_unsigned(putc_fn, ctx, va_arg(ap, unsigned), c == 'o' ? 8 : 16,
                          width, zero_pad, c == 'X', &count);
        } else if (c == 'p') {
            emit_unsigned(putc_fn, ctx, (unsigned)va_arg(ap, void *), 16,
                          width, zero_pad, 0, &count);
        } else if (c == 'c') {
            putc_fn(va_arg(ap, int), ctx);
            ++count;
        } else if (c == 's') {
            const char *s = va_arg(ap, const char *);
            unsigned length = 0;
            if (!s) s = "(null)";
            while (s[length] && (precision < 0 || length < (unsigned)precision)) ++length;
            while (length < width) {
                putc_fn(' ', ctx);
                ++count;
                --width;
            }
            while (length--) {
                putc_fn((unsigned char)*s++, ctx);
                ++count;
            }
        } else if (c == '%') {
            putc_fn('%', ctx);
            ++count;
        } else {
            putc_fn('%', ctx);
            putc_fn(c, ctx);
            count += 2;
        }
    }
    return count;
}

int vprintf(const char *fmt, va_list ap) { return vformat(serial_emit, 0, fmt, ap); }
int console_vprintf(const char *fmt, va_list ap) { return vformat(console_emit, 0, fmt, ap); }
int tee_vprintf(const char *fmt, va_list ap) { return vformat(tee_emit, 0, fmt, ap); }

int printf(const char *fmt, ...) {
    int result;
    va_list ap;
    va_start(ap, fmt);
    result = vprintf(fmt, ap);
    va_end(ap);
    return result;
}

int console_printf(const char *fmt, ...) {
    int result;
    va_list ap;
    va_start(ap, fmt);
    result = console_vprintf(fmt, ap);
    va_end(ap);
    return result;
}

int tee_printf(const char *fmt, ...) {
    int result;
    va_list ap;
    va_start(ap, fmt);
    result = tee_vprintf(fmt, ap);
    va_end(ap);
    return result;
}

int putchar(int c) { return serial_putc(c); }

int puts(const char *s) {
    int count = 0;
    while (*s) {
        putchar((unsigned char)*s++);
        ++count;
    }
    putchar('\n');
    return count + 1;
}

int vsnprintf(char *dst, size_t size, const char *fmt, va_list ap) {
    Buffer buffer;
    buffer.dst = dst;
    buffer.size = size;
    buffer.count = 0;
    {
        int result = vformat(buffer_emit, &buffer, fmt, ap);
        if (size) dst[buffer.count < size ? buffer.count : size - 1] = '\0';
        return result;
    }
}

int snprintf(char *dst, size_t size, const char *fmt, ...) {
    int result;
    va_list ap;
    va_start(ap, fmt);
    result = vsnprintf(dst, size, fmt, ap);
    va_end(ap);
    return result;
}

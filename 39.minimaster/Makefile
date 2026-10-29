CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
LDFLAGS ?=

OBJS = example.o display_list.o renderer_cpu.o

.PHONY: all run clean
all: example
example: $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $(OBJS)
%.o: %.c gfx.h
	$(CC) $(CFLAGS) -c -o $@ $<
run: example
	./example
clean:
	rm -f example $(OBJS) demo-320x240.ppm demo-640x480.ppm

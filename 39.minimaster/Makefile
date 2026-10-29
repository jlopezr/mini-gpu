CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
CPPFLAGS += -Iminifont/include
vpath %.c minifont/src
vpath %.h minifont/include
OBJS = example.o display_list.o renderer_cpu.o minifont.o
.PHONY: all run clean
all: example
example: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS)
%.o: %.c gfx.h minifont.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
run: example
	./example park10.mf
clean:
	rm -f example test test.o $(OBJS) demo-320x240.ppm demo-640x480.ppm blit_demo blit_test blit_demo.o blit_test.o blit-*.ppm
test: test.o display_list.o renderer_cpu.o minifont.o
	$(CC) $(CFLAGS) -o test $^
	./test

blit_demo: blit_demo.o display_list.o renderer_cpu.o minifont.o
	$(CC) $(CFLAGS) -o $@ $^
blit_test: blit_test.o display_list.o renderer_cpu.o minifont.o
	$(CC) $(CFLAGS) -o $@ $^
run-blit: blit_demo
	./blit_demo
check-blit: blit_test
	./blit_test

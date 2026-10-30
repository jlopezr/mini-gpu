CC ?= cc
CFLAGS ?= -std=c89 -pedantic -Wall -Wextra -O2
# MGL_GPU_HOST_TEST: el renderer GPU (V2) se ejecuta emulado en el host.
CPPFLAGS += -Isrc -DMGL_GPU_HOST_TEST

# src/: MiniGL + API Processing + plataforma host. examples/: sketches.
# tests/: comparaciones V0/V1/V2. Todo se compila en build/.
HDRS = $(wildcard src/*.h)
LIB = build/minigl.o build/processing.o build/raster.o build/gpu_renderer.o build/gpu_host.o
EXAMPLES = build/shapes build/pattern
TESTS = build/test_cpu build/test_gpu
# Version a ejecutar con make run-<sketch>: 0, 1, 2 o all.
V ?= all

.PHONY: all run test clean
all: $(EXAMPLES) $(TESTS) compile_commands.json

# Para IntelliSense de VS Code (C_Cpp.default.compileCommands en
# .vscode/settings.json): cómo se compila cada fichero, con los mismos flags.
SRCS = $(wildcard src/*.c examples/*.c tests/*.c)
compile_commands.json: Makefile $(SRCS)
	@echo '[' > $@; first=1; for f in $(SRCS); do \
	    [ $$first = 1 ] || echo ',' >> $@; first=0; \
	    printf '  {"directory": "%s", "file": "%s", "command": "%s %s %s -c %s"}' \
	        "$(CURDIR)" "$$f" "$(CC)" "$(CPPFLAGS)" "$(CFLAGS)" "$$f" >> $@; \
	done; printf '\n]\n' >> $@

build:
	mkdir -p build
build/%.o: src/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/%.o: examples/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/%.o: tests/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
$(EXAMPLES): build/%: build/%.o build/platform_host.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^
$(TESTS): build/%: build/%.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^

# make run-shapes, make run-pattern V=2 ...; make run las lanza todas.
run: $(EXAMPLES:build/%=run-%)
run-%: build/%
	./$< -v $(V)

test: $(TESTS)
	./build/test_cpu
	./build/test_gpu

clean:
	rm -rf build
	rm -f *.ppm

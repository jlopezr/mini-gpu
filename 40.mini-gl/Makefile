CC ?= cc
CFLAGS ?= -std=c89 -pedantic -Wall -Wextra -O2
# MGL_GPU_HOST_TEST: el renderer GPU (V2) se ejecuta emulado en el host.
CPPFLAGS += -Isrc -DMGL_GPU_HOST_TEST

# SDL2 solo para la plataforma con ventana (make sdl, make sdl-<sketch>).
SDL_CONFIG ?= sdl2-config
SDL_CFLAGS := $(shell $(SDL_CONFIG) --cflags 2>/dev/null)
SDL_LIBS := $(shell $(SDL_CONFIG) --libs 2>/dev/null)

# src/: MiniGL + API Processing + plataformas (host PPM y SDL). examples/:
# sketches. tests/: comparaciones V0/V1/V2. Todo se compila en build/.
HDRS = $(wildcard src/*.h)
LIB = build/minigl.o build/processing.o build/raster.o build/gpu_renderer.o build/gpu_host.o \
    build/platform.o
SKETCHES = shapes pattern bounce
EXAMPLES = $(SKETCHES:%=build/%)
SDL_EXAMPLES = $(SKETCHES:%=build/%-sdl)
TESTS = build/test_cpu build/test_gpu
# Version a ejecutar con make run-<sketch> (0, 1, 2 o all) y sdl-<sketch> (0, 1 o 2).
V ?= all

.PHONY: all run test sdl clean
all: $(EXAMPLES) $(TESTS) compile_commands.json
sdl: $(SDL_EXAMPLES)

# Para IntelliSense de VS Code (C_Cpp.default.compileCommands en
# .vscode/settings.json): cómo se compila cada fichero, con los mismos flags.
SRCS = $(wildcard src/*.c examples/*.c tests/*.c)
compile_commands.json: Makefile $(SRCS)
	@echo '[' > $@; first=1; for f in $(SRCS); do \
	    [ $$first = 1 ] || echo ',' >> $@; first=0; \
	    extra=; [ $$f = src/platform_sdl.c ] && extra="$(SDL_CFLAGS)"; \
	    printf '  {"directory": "%s", "file": "%s", "command": "%s %s %s %s -c %s"}' \
	        "$(CURDIR)" "$$f" "$(CC)" "$(CPPFLAGS)" "$$extra" "$(CFLAGS)" "$$f" >> $@; \
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
build/platform_sdl.o: CPPFLAGS += $(SDL_CFLAGS)
$(SDL_EXAMPLES): build/%-sdl: build/%.o build/platform_sdl.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^ $(SDL_LIBS)
$(TESTS): build/%: build/%.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^

# make run-shapes, make run-pattern V=2 ...; make run las lanza todas.
run: $(EXAMPLES:build/%=run-%)
run-%: build/%
	./$< -v $(V)

# Ventana SDL: make sdl-bounce, make sdl-shapes V=2 (teclas 0/1/2 cambian de versión).
sdl-%: build/%-sdl
	./$< $(if $(filter all,$(V)),,-v $(V))

test: $(TESTS)
	./build/test_cpu
	./build/test_gpu

clean:
	rm -rf build
	rm -f *.ppm

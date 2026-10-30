CC ?= cc
CFLAGS ?= -std=c89 -pedantic -Wall -Wextra -O2
# MGL_GPU_HOST_TEST: el renderer GPU (V2) se ejecuta emulado en el host.
CPPFLAGS += -Isrc -DMGL_GPU_HOST_TEST

# SDL2 solo para la plataforma con ventana (make sdl, make sdl-<sketch>).
SDL_CONFIG ?= sdl2-config
SDL_CFLAGS := $(shell $(SDL_CONFIG) --cflags 2>/dev/null)
SDL_LIBS := $(shell $(SDL_CONFIG) --libs 2>/dev/null)

# Plataforma MiniGPU (make minigpu, sim-<sketch>, check-minigpu): se compila con build-c (mini-lcc)
# del repo y se ejecuta en su simulador de CPU + GPU.
REPO := $(abspath ..)
PYTHON ?= python3
BUILD_C = $(PYTHON) $(REPO)/tools/build-c
SIM_SYS = $(PYTHON) $(REPO)/32.cpu-gpu-func-sim/cpu_gpu_sim.py
COMPARE_FRAMES = $(PYTHON) $(REPO)/tools/compare-frames.py
MINIGPU_SRCS = src/minigl.c src/processing.c src/raster.c
# Frames que compara check-minigpu, y argumentos extra para sim-<sketch>.
FRAMES ?= 1
SIM_ARGS ?=

# src/: MiniGL + API Processing + plataformas (host PPM, SDL y MiniGPU). examples/:
# sketches. tests/: comparaciones V0/V1/V2. Todo se compila en build/.
HDRS = $(wildcard src/*.h)
LIB = build/minigl.o build/processing.o build/raster.o build/gpu_renderer.o build/gpu_host.o \
    build/platform.o
SKETCHES = shapes pattern bounce
EXAMPLES = $(SKETCHES:%=build/%)
SDL_EXAMPLES = $(SKETCHES:%=build/%-sdl)
MINIGPU_EXAMPLES = $(SKETCHES:%=build/minigpu/%.bin)
TESTS = build/test_cpu build/test_gpu
# Version a ejecutar con make run-<sketch> (0, 1, 2 o all) y sdl-<sketch> (0, 1 o 2).
V ?= all

.PHONY: all run test sdl minigpu check-minigpu clean
all: $(EXAMPLES) $(TESTS) compile_commands.json
sdl: $(SDL_EXAMPLES)
minigpu: $(MINIGPU_EXAMPLES)

# Para IntelliSense de VS Code (C_Cpp.default.compileCommands en
# .vscode/settings.json): cómo se compila cada fichero, con los mismos flags.
SRCS = $(wildcard src/*.c examples/*.c tests/*.c)
compile_commands.json: Makefile $(SRCS)
	@echo '[' > $@; first=1; for f in $(SRCS); do \
	    [ $$first = 1 ] || echo ',' >> $@; first=0; \
	    extra=; [ $$f = src/platform_sdl.c ] && extra="$(SDL_CFLAGS)"; \
	    [ $$f = src/platform_minigpu.c ] && extra="-I$(REPO)/t.tests/inc"; \
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

# MiniGPU: platform_minigpu.c va primero porque lleva main.
build/minigpu/%.bin: examples/%.c src/platform_minigpu.c $(MINIGPU_SRCS) $(HDRS)
	$(BUILD_C) src/platform_minigpu.c $< $(MINIGPU_SRCS) -I src --outdir build/minigpu/$* -o $@

# Ventana del simulador: make sim-bounce. Cada frame son millones de instrucciones (varios segundos).
sim-%: build/minigpu/%.bin
	$(SIM_SYS) $< --window --run-limit 100000000000 $(SIM_ARGS)

# Instrucciones por función C (y del runtime) hasta el frame FRAMES: make profile-minigpu-shapes.
profile-minigpu-%: build/minigpu/%.bin
	$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --run-limit 100000000000 \
	    --profile --symbols build/minigpu/$*/platform_minigpu.asm | sed -n '/^Perfil/,$$p'

# El frame FRAMES de cada sketch en el simulador, píxel a píxel contra V0 en el host.
check-minigpu: $(SKETCHES:%=check-minigpu-%)
check-minigpu-%: build/minigpu/%.bin build/%
	./build/$* -v 0 -f $(FRAMES) -o build/minigpu/$*-host.bin > /dev/null
	$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --frame-output build/minigpu/$*-sim.bin \
	    --run-limit 100000000000 > /dev/null
	$(COMPARE_FRAMES) --rgb565 320x240 build/minigpu/$*-host.bin build/minigpu/$*-sim.bin

test: $(TESTS)
	./build/test_cpu
	./build/test_gpu

clean:
	rm -rf build
	rm -f *.ppm

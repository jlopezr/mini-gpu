CC ?= cc
CFLAGS ?= -std=c89 -pedantic -Wall -Wextra -O2
CPPFLAGS += -Isrc

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
# La biblioteca C mínima que build-c añade a cada programa.
LIBC = $(wildcard $(REPO)/t.tests/runtime/libc/*.c $(REPO)/t.tests/inc/*.h)
MINIGPU_SRCS = src/minigl.c src/processing.c src/raster.c $(if $(filter 2,$(MV)),src/gpu_renderer.c)
# Frames que compara check-minigpu, y argumentos extra para sim-<sketch>.
FRAMES ?= 1
SIM_ARGS ?=

# src/: MiniGL + API Processing + plataformas (host PPM, SDL y MiniGPU). examples/:
# sketches. tests/: comparaciones V0/V1/V2. Todo se compila en build/.
HDRS = $(wildcard src/*.h)
LIB = build/minigl.o build/processing.o build/raster.o build/gpu_renderer.o \
    build/platform.o
SKETCHES = shapes pattern bounce trail paint
EXAMPLES = $(SKETCHES:%=build/%)
SDL_EXAMPLES = $(SKETCHES:%=build/%-sdl)
TESTS = build/test_cpu build/test_gpu
# Version a ejecutar con make run-<sketch> (0, 1, 2 o all) y sdl-<sketch> (0, 1 o 2). En MiniGPU se elige
# al compilar (0, 1 o 2; all es 0) y cada una va a su carpeta: make sim-bounce V=1, check-minigpu V=1...
V ?= all
MV := $(if $(filter all,$(V)),0,$(V))
MG := build/minigpu/v$(MV)
MINIGPU_EXAMPLES = $(SKETCHES:%=$(MG)/%.bin)

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

# Ventana SDL: make sdl-bounce, make sdl-shapes V=2 (F1/F2/F3 cambian de versión).
sdl-%: build/%-sdl
	./$< $(if $(filter all,$(V)),,-v $(V))

# MiniGPU: platform_minigpu.c va primero porque lleva main.
$(MG)/%.bin: examples/%.c src/platform_minigpu.c $(MINIGPU_SRCS) $(HDRS) $(LIBC)
	$(BUILD_C) src/platform_minigpu.c $< $(MINIGPU_SRCS) -I src -D MGL_VERSION=$(MV) --outdir $(MG)/$* -o $@

# Ventana del simulador: make sim-bounce. Cada frame son millones de instrucciones (varios segundos).
sim-%: $(MG)/%.bin
	$(SIM_SYS) $< --window --run-limit 100000000000 $(SIM_ARGS)

# Instrucciones por función C (y del runtime) hasta el frame FRAMES: make profile-minigpu-shapes. Deja
# además el .asm con la cuenta de cada instrucción en $(MG)/<sketch>-anotado.txt.
profile-minigpu-%: $(MG)/%.bin
	$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --run-limit 100000000000 \
	    --profile --symbols $(MG)/$*/platform_minigpu.asm \
	    --profile-annotate $(MG)/$*-anotado.txt | sed -n '/^Perfil/,$$p'

# El frame FRAMES de cada sketch en el simulador, píxel a píxel contra la misma versión en el host.
check-minigpu: $(SKETCHES:%=check-minigpu-%)
check-minigpu-%: $(MG)/%.bin build/%
	./build/$* -v $(MV) -f $(FRAMES) -o $(MG)/$*-host.bin > /dev/null
	$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --frame-output $(MG)/$*-sim.bin \
	    --run-limit 100000000000 > /dev/null
	$(COMPARE_FRAMES) --rgb565 320x240 $(MG)/$*-host.bin $(MG)/$*-sim.bin

test: $(TESTS)
	./build/test_cpu
	./build/test_gpu

clean:
	rm -rf build
	rm -f *.ppm

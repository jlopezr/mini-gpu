CC ?= cc
# -ffp-contract=off: sin fusionar multiplicación y suma en float, para que el 3D dé en el host los mismos bits
# que en MiniGPU (soft-float IEEE, una operación cada vez).
CFLAGS ?= -std=c89 -pedantic -Wall -Wextra -O2 -ffp-contract=off
CPPFLAGS += -Isrc -Irenderer

# SDL2 solo para la plataforma con ventana (make sdl, make sdl-<sketch>).
SDL_CONFIG ?= sdl2-config
SDL_CFLAGS := $(shell $(SDL_CONFIG) --cflags 2>/dev/null)
SDL_LIBS := $(shell $(SDL_CONFIG) --libs 2>/dev/null)

# Plataforma MiniGPU (make minigpu, sim-<sketch>, check-minigpu): se compila con build-c (mini-lcc)
# del repo y se ejecuta en su simulador de CPU + GPU.
REPO := $(abspath ..)
PYTHON ?= python3
BUILD_C = $(PYTHON) $(REPO)/tools/build-c
# El simulador va de 4 a 10 veces más rápido con PyPy (uv python install pypy@3.11): se usa si está, y si no,
# PYTHON. La ventana se abre igualmente con CPython (gui_python, en tools/sim_host.py). SIM_PYTHON=python3 lo evita.
ifndef SIM_PYTHON
SIM_PYTHON := $(or $(shell uv python find pypy 2>/dev/null),$(PYTHON))
endif
SIM_SYS = $(SIM_PYTHON) $(REPO)/32.cpu-gpu-func-sim/cpu_gpu_sim.py
COMPARE_FRAMES = $(PYTHON) $(REPO)/tools/compare-frames.py
# La biblioteca C mínima que build-c añade a cada programa.
LIBC = $(wildcard $(REPO)/t.tests/runtime/libc/*.c $(REPO)/t.tests/inc/*.h)
MINIGPU_SRCS = src/minigl.c src/processing.c src/raster.c $(if $(filter 2,$(MV)),src/gpu_renderer.c)
# Frames que compara check-minigpu, y argumentos extra para sim-<sketch>.
FRAMES ?= 1
SIM_ARGS ?=

# src/: MiniGL + API Processing + plataformas (host PPM, SDL y MiniGPU). renderer/: el renderer 3D de
# referencia. examples/: sketches. tests/: comparaciones V0/V1/V2 y pruebas 3D. Todo se compila en build/.
HDRS = $(wildcard src/*.h renderer/*.h)
LIB = build/minigl.o build/processing.o build/raster.o build/gpu_renderer.o \
    build/platform.o
# 3D: MiniGL 3D, el renderer (sin dependencias de MiniGL) y lo que usan las plataformas 3D.
RENDERER_SRCS = $(filter-out renderer/replay_host.c,$(wildcard renderer/*.c))
RENDERER = $(RENDERER_SRCS:renderer/%.c=build/%.o) build/mgl_math.o build/mgl_memory.o build/raster.o
MGL3D = build/minigl.o build/mgl_3d.o build/mgl_resources.o build/mgl_math.o build/mgl_memory.o
LIB3D = $(MGL3D) $(RENDERER) build/processing.o build/processing3d.o build/platform3d.o \
    build/mgl_capture.o build/ppm.o
SKETCHES3D = rotating_cube boxes colored_cube
EXAMPLES3D = $(SKETCHES3D:%=build/%)
TESTS3D = build/test_commands build/test_matrices build/test_clipping build/test_raster \
    build/test_resources build/test_cube
# Frames de make run-<sketch 3D>: el último va a <sketch>.ppm y uno de cada FRAMES_EVERY a <sketch>-NNNN.ppm.
FRAMES3D ?= 60
FRAMES_EVERY ?= 15
SKETCHES = shapes pattern bounce trail paint
EXAMPLES = $(SKETCHES:%=build/%)
SDL_EXAMPLES = $(SKETCHES:%=build/%-sdl)
SDL_EXAMPLES3D = $(SKETCHES3D:%=build/%-sdl)
TESTS = build/test_cpu build/test_gpu build/test_fuzz_v2
# Version a ejecutar con make run-<sketch> (0, 1, 2 o all) y sdl-<sketch> (0, 1 o 2). En MiniGPU se elige
# al compilar (0, 1 o 2; all es 0) y cada una va a su carpeta: make sim-bounce V=1, check-minigpu V=1...
V ?= all
MV := $(if $(filter all,$(V)),0,$(V))
MG := build/minigpu/v$(MV)
MINIGPU_EXAMPLES = $(SKETCHES:%=$(MG)/%.bin)

.PHONY: all run test test3d sdl minigpu minigpu3d check-minigpu check-minigpu3d clean
all: $(EXAMPLES) $(TESTS) $(EXAMPLES3D) $(TESTS3D) build/mgl-replay compile_commands.json
sdl: $(SDL_EXAMPLES) $(SDL_EXAMPLES3D)
minigpu: $(MINIGPU_EXAMPLES)

# Para IntelliSense de VS Code (C_Cpp.default.compileCommands en
# .vscode/settings.json): cómo se compila cada fichero, con los mismos flags.
SRCS = $(wildcard src/*.c renderer/*.c examples/*.c tests/*.c)
compile_commands.json: Makefile $(SRCS)
	@echo '[' > $@; first=1; for f in $(SRCS); do \
	    [ $$first = 1 ] || echo ',' >> $@; first=0; \
	    extra=; case $$f in src/platform_sdl.c|src/platform3d_sdl.c) extra="$(SDL_CFLAGS)";; esac; \
	    case $$f in src/platform_minigpu.c|src/platform3d_minigpu.c) extra="-I$(REPO)/t.tests/inc";; esac; \
	    printf '  {"directory": "%s", "file": "%s", "command": "%s %s %s %s -c %s"}' \
	        "$(CURDIR)" "$$f" "$(CC)" "$(CPPFLAGS)" "$$extra" "$(CFLAGS)" "$$f" >> $@; \
	done; printf '\n]\n' >> $@

build:
	mkdir -p build
build/%.o: src/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/%.o: renderer/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/%.o: examples/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/%.o: tests/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
$(EXAMPLES): build/%: build/%.o build/platform_host.o build/ppm.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^
$(EXAMPLES3D): build/%: build/%.o build/platform3d_host.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $(sort $^)
$(TESTS3D): build/%: build/%.o build/fixture3d.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $(sort $^) -lm
# Reproduce una captura (-c de un sketch 3D) solo con el renderer: no enlaza MiniGL.
build/mgl-replay: build/replay_host.o $(RENDERER) build/mgl_capture.o build/ppm.o
	$(CC) $(CFLAGS) -o $@ $(sort $^)
build/platform_sdl.o build/platform3d_sdl.o: CPPFLAGS += $(SDL_CFLAGS)
$(SDL_EXAMPLES): build/%-sdl: build/%.o build/platform_sdl.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^ $(SDL_LIBS)
$(SDL_EXAMPLES3D): build/%-sdl: build/%.o build/platform3d_sdl.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $(sort $^) $(SDL_LIBS)
$(TESTS): build/%: build/%.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^

# make run-shapes, make run-pattern V=2 ...; make run las lanza todas.
run: $(EXAMPLES:build/%=run-%) $(EXAMPLES3D:build/%=run-%)
run-%: build/%
	./$< -v $(V)
# Los sketches 3D no tienen versiones: varios frames (make run-rotating_cube FRAMES3D=120).
$(SKETCHES3D:%=run-%): run-%: build/%
	./$< -f $(FRAMES3D) -e $(FRAMES_EVERY)

# Ventana SDL: make sdl-bounce, make sdl-shapes V=2 (F1/F2/F3 cambian de versión).
sdl-%: build/%-sdl
	./$< $(if $(filter all,$(V)),,-v $(V))
# Los 3D no tienen versiones: make sdl-rotating_cube (SCALE=4 para otra escala).
$(SKETCHES3D:%=sdl-%): sdl-%: build/%-sdl
	./$< $(if $(SCALE),-s $(SCALE))

# MiniGPU: platform_minigpu.c va primero porque lleva main.
$(MG)/%.bin: examples/%.c src/platform_minigpu.c $(MINIGPU_SRCS) $(HDRS) $(LIBC)
	$(BUILD_C) src/platform_minigpu.c $< $(MINIGPU_SRCS) -I src -D MGL_VERSION=$(MV) --outdir $(MG)/$* -o $@

# MiniGPU 3D: el renderer de referencia en la CPU de MiniGPU, con las mismas fuentes que en el host.
MG3 := build/minigpu/3d
MINIGPU3D_SRCS = src/platform3d.c src/processing3d.c src/processing.c src/minigl.c src/mgl_3d.c \
    src/mgl_resources.c src/mgl_math.c src/mgl_memory.c src/raster.c $(RENDERER_SRCS)
minigpu3d: $(SKETCHES3D:%=$(MG3)/%.bin)
$(MG3)/%.bin: examples/%.c src/platform3d_minigpu.c $(MINIGPU3D_SRCS) $(HDRS) $(LIBC)
	$(BUILD_C) src/platform3d_minigpu.c $< $(MINIGPU3D_SRCS) -I src -I renderer --outdir $(MG3)/$* -o $@
$(SKETCHES3D:%=sim-%): sim-%: $(MG3)/%.bin
	$(SIM_SYS) $< --window --run-limit 100000000000 $(SIM_ARGS)
$(SKETCHES3D:%=profile-minigpu-%): profile-minigpu-%: $(MG3)/%.bin
	$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --run-limit 100000000000 \
	    --profile --symbols $(MG3)/$*/platform3d_minigpu.asm \
	    --profile-annotate $(MG3)/$*-anotado.txt | sed -n '/^Perfil/,$$p'
# El frame FRAMES de cada sketch 3D en el simulador, píxel a píxel contra el host.
check-minigpu3d: $(SKETCHES3D:%=check-minigpu-%)
$(SKETCHES3D:%=check-minigpu-%): check-minigpu-%: $(MG3)/%.bin build/%
	./build/$* -f $(FRAMES) -o $(MG3)/$*-host.bin -q
	$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --frame-output $(MG3)/$*-sim.bin \
	    --run-limit 100000000000 > /dev/null
	$(COMPARE_FRAMES) --rgb565 320x240 $(MG3)/$*-host.bin $(MG3)/$*-sim.bin

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

test: $(TESTS) test3d
	./build/test_cpu
	./build/test_gpu
	./build/test_fuzz_v2

test3d: $(TESTS3D) build/mgl-replay build/rotating_cube
	@for t in $(TESTS3D); do echo ./$$t; ./$$t || exit 1; done
	./build/rotating_cube -f 40 -o build/replay-host.ppm -c build/replay.mglx -q
	./build/mgl-replay build/replay.mglx build/replay-renderer.ppm
	cmp build/replay-host.ppm build/replay-renderer.ppm && echo "PASS: mgl-replay == sketch, frame 40"

clean:
	rm -rf build
	rm -f *.ppm

# MiniGL: la API de MiniGL + Processing, sus sketches y sus pruebas, en tres
# plataformas: host (PPM), ventana SDL y MiniGPU (simulador CPU+GPU del repo).
# `make help` lista los objetivos. Todo se compila en build/.
#
#   src/                MiniGL, API Processing y plataformas (host, SDL, MiniGPU)
#   src/render/2d, 3d   renderers 2D y 3D de referencia
#   examples/           sketches          tests/   pruebas (V0/V1/V2 y 3D)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

CC ?= cc
# -ffp-contract=off: sin fusionar multiplicación y suma en float, para que el 3D dé en el host los mismos bits
# que en MiniGPU (soft-float IEEE, una operación cada vez).
CFLAGS ?= -std=c89 -pedantic -Wall -Wextra -O2 -ffp-contract=off
INCLUDE_DIRS = src src/processing src/render src/render/2d src/render/3d src/platform
INCLUDES = $(addprefix -I ,$(INCLUDE_DIRS))
CPPFLAGS += $(INCLUDES)

# SDL2 solo para la plataforma con ventana (make sdl, make sdl-<sketch>).
SDL_CONFIG ?= sdl2-config
SDL_CFLAGS := $(shell $(SDL_CONFIG) --cflags 2>/dev/null)
SDL_LIBS := $(shell $(SDL_CONFIG) --libs 2>/dev/null)

# MiniGPU: se compila con mini-cc (mini-lcc) del repo y se ejecuta en su simulador CPU+GPU, `sim-sys`.
# sim-sys usa su motor Codon si está instalado; si no, el de Python, que con PyPy (uv python install
# pypy@3.11) va de 4 a 10 veces más rápido: se usa PyPy si está. La ventana se abre igualmente con
# CPython (gui_python, en tools/sim_host.py). SIM_PYTHON=python3 evita PyPy.
REPO := $(abspath ..)
PYTHON ?= python
ifndef SIM_PYTHON
SIM_PYTHON := $(or $(shell uv python find pypy 2>/dev/null),$(PYTHON))
endif
BUILD_C = $(PYTHON) $(REPO)/tools/mini-cc
SIM_SYS = $(SIM_PYTHON) $(REPO)/tools/sim-sys
COMPARE_FRAMES = $(PYTHON) $(REPO)/tools/compare-frames.py
# Límite de instrucciones del simulador: en la práctica, ninguno.
SIM_LIMIT = 100000000000
# Lo que mini-cc no pone solo: el runtime de la GPU y la biblioteca C mínima (runtime/).
LIBC = $(REPO)/runtime/src/gpu.c $(REPO)/runtime/src/gpu_runtime.inc $(REPO)/runtime/src/bench.inc $(REPO)/runtime/src/string.c
LIBC_DEPS = $(LIBC) $(wildcard $(REPO)/runtime/include/*.h)

# Variables de la línea de órdenes (ver `make help`).
# Versión 2D: 0, 1, 2 o all (run-<sketch>); en sdl-<sketch>, 0, 1 o 2.
V ?= all
# Frame que comparan check-minigpu* y hasta el que perfilan profile-minigpu-*.
FRAMES ?= 1
# Frames de run-<sketch 3D>: el último va a <sketch>.ppm y uno de cada FRAMES_EVERY a <sketch>-NNNN.ppm.
FRAMES3D ?= 60
FRAMES_EVERY ?= 15
# Argumentos extra para sim-<sketch>.
SIM_ARGS ?=
# En MiniGPU la versión 2D se elige al compilar (all es 0) y cada una va a su carpeta.
MV := $(if $(filter all,$(V)),0,$(V))
MG := build/minigpu/v$(MV)
# FIXED=1: geometría (transformar, outcode, recorte, viewport) y profundidad en Q16.16 en vez de float soft
# (MGR_FIXED_GEOMETRY/MGR_FIXED_DEPTH, experimentales); va a su carpeta para comparar con la de float.
FIXED ?= 0
# FP32=1: + - * / de float con las instrucciones FP32 de la 38 (mini-cc --fp32) en vez de softfloat. Solo corre
# en la 38 (en otra CPU, ERROR_INVALID_OPCODE). FP32 es DAZ/FTZ: con subnormales puede diferir del host.
FP32 ?= 0
# EXT=1: MIN/MAX y CLZ con las instrucciones EXT de la 38 (mgl_ext.h, intrínsecos de mini-lcc). Solo la 38.
EXT ?= 0
MG3 := build/minigpu/3d$(if $(filter 1,$(FIXED)),-fixed)$(if $(filter 1,$(FP32)),-fp32)$(if $(filter 1,$(EXT)),-ext)
MG3_DEFS := $(if $(filter 1,$(FIXED)),-D MGR_FIXED_GEOMETRY=1 -D MGR_FIXED_DEPTH=1) $(if $(filter 1,$(FP32)),--fp32) \
    $(if $(filter 1,$(EXT)),-D MGL_EXT=1)

# ---------------------------------------------------------------------------
# Fuentes, objetos y programas
# ---------------------------------------------------------------------------

HDRS = $(foreach dir,$(INCLUDE_DIRS),$(wildcard $(dir)/*.h))

SKETCHES = shapes pattern bounce trail paint
SKETCHES3D = rotating_cube boxes colored_cube tie_fighter x_wing tanks skimmer racer

# 2D: MiniGL + Processing + raster, con los renderers de las tres versiones.
LIB = build/minigl.o build/processing.o build/raster.o build/gpu_renderer.o \
    build/platform.o build/context2d.o
# 3D: el renderer de referencia (independiente de MiniGL), MiniGL 3D encima y el contexto que usan los
# drivers comunes.
RENDERER_SRCS = $(wildcard src/render/3d/*.c)
RENDERER = $(RENDERER_SRCS:src/render/3d/%.c=build/%.o) build/mgl_math.o build/mgl_memory.o build/raster.o
LIB3D = build/minigl.o build/mgl_3d.o build/mgl_resources.o $(RENDERER) \
    build/processing.o build/processing3d.o build/context3d.o build/platform.o build/mgl_capture.o build/ppm.o

EXAMPLES = $(SKETCHES:%=build/%)
EXAMPLES3D = $(SKETCHES3D:%=build/%)
SDL_EXAMPLES = $(SKETCHES:%=build/%-sdl)
SDL_EXAMPLES3D = $(SKETCHES3D:%=build/%-sdl)
TESTS = build/test_cpu build/test_gpu build/test_fuzz_v2 build/test_platform2d
TESTS3D = build/test_commands build/test_matrices build/test_clipping build/test_raster \
    build/test_resources build/test_cube build/test_clear build/test_fragment build/test_platform3d

# Lo que compila mini-cc para MiniGPU, además del sketch y del driver src/platform/minigpu.c.
MINIGPU_SRCS = src/platform/platform.c src/render/context2d.c src/minigl.c src/processing/processing.c \
    src/render/2d/raster.c $(if $(filter 2,$(MV)),src/render/2d/gpu_renderer.c)
MINIGPU3D_SRCS = src/platform/platform.c src/render/context3d.c src/processing/processing3d.c \
    src/processing/processing.c src/minigl.c src/mgl_3d.c src/mgl_resources.c src/mgl_math.c \
    src/mgl_memory.c src/render/2d/raster.c $(RENDERER_SRCS)

.PHONY: all help run racer-scene test test3d sdl minigpu minigpu3d check-minigpu check-minigpu3d clean
all: $(EXAMPLES) $(TESTS) $(EXAMPLES3D) $(TESTS3D) build/mgl-replay compile_commands.json
sdl: $(SDL_EXAMPLES) $(SDL_EXAMPLES3D)
minigpu: $(SKETCHES:%=$(MG)/%.bin)
minigpu3d: $(SKETCHES3D:%=$(MG3)/%.bin)

help:
	@echo 'Host (PPM):'
	@echo '  make / make all          compila sketches, pruebas y mgl-replay'
	@echo '  make run-<sketch>        2D: $(SKETCHES) (V=0|1|2|all)'
	@echo '  make run-<sketch 3D>     3D: $(SKETCHES3D) (FRAMES3D, FRAMES_EVERY)'
	@echo '  make run                 todos'
	@echo '  make racer-scene SCENE=  una escena de racer congelada con G, otra vez (CAPTURE=x.mglx)'
	@echo '  make test                pruebas 2D y 3D'
	@echo 'Ventana SDL:'
	@echo '  make sdl-<sketch>        V=0|1|2 (F1/F2/F3 cambian de versión); 3D con SCALE=n'
	@echo 'MiniGPU (simulador CPU+GPU):'
	@echo '  make sim-<sketch>        ventana del simulador, 2D (V=0|1|2) o 3D; SIM_ARGS extra'
	@echo '  make check-minigpu       frame FRAMES de cada sketch 2D contra el host (V=0|1|2)'
	@echo '  make check-minigpu3d     lo mismo con los sketches 3D'
	@echo '  make profile-minigpu-<sketch>  instrucciones por función hasta el frame FRAMES'
	@echo '  make minigpu / minigpu3d solo compilar los .bin'
	@echo '  FIXED=1 (3D)             geometría y profundidad en coma fija, en build/minigpu/3d-fixed'
	@echo '  FP32=1 (3D)              float con las instrucciones FP32 (solo la 38), en build/minigpu/3d-fp32'
	@echo '  EXT=1 (3D)               MIN/MAX/CLZ con las instrucciones EXT (solo la 38), sufijo -ext'
	@echo 'Placa (tools/run-board):'
	@echo '  make board-<sketch>      compila el .bin, sube el bitstream si la placa no tiene el del prototipo,'
	@echo '                           y carga y arranca el programa; BOARD_PROTO=38, BOARD_UPLOAD=0 (no subir),'
	@echo '                           BOARD_ARGS="--port ..."'
	@echo '                           racer, con FIXED=1 FP32=1 EXT=1 (BOARD_OPTS_racer; la línea de órdenes manda)'
	@echo 'Otros:'
	@echo '  make clean               borra build/ y los .ppm'

# ---------------------------------------------------------------------------
# Compilación en el host
# ---------------------------------------------------------------------------

# Un .o por .c, venga de la carpeta que venga (no hay dos .c con el mismo nombre).
vpath %.c $(INCLUDE_DIRS) apps examples tests

build:
	mkdir -p build
build/%.o: %.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/sdl.o: CPPFLAGS += $(SDL_CFLAGS)
# tests/test_platform.c prueba el contexto 2D o, con TEST_CONTEXT_3D, el 3D.
build/test_platform2d.o: tests/test_platform.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/test_platform3d.o: tests/test_platform.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -DTEST_CONTEXT_3D=1 -c -o $@ $<

# Sketches.
$(EXAMPLES): build/%: build/%.o build/host.o build/ppm.o build/mgl_capture.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^
$(EXAMPLES3D): build/%: build/%.o build/host.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $^
$(SDL_EXAMPLES): build/%-sdl: build/%.o build/sdl.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^ $(SDL_LIBS)
$(SDL_EXAMPLES3D): build/%-sdl: build/%.o build/sdl.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $^ $(SDL_LIBS)

# Modelos OBJ convertidos a PShape (tools/obj2shape.py). El .h generado está en el repo, para compilar
# sin regenerarlo; se rehace si cambian el modelo, la textura o el conversor.
TIE = examples/low-poly-tie-fighter
examples/tie_fighter_shape.h: $(TIE)/source/TIE.obj $(TIE)/textures/TIETexture.png tools/obj2shape.py
	$(PYTHON) tools/obj2shape.py $< --texture $(TIE)/textures/TIETexture.png --name tie_fighter --cull -o $@ \
	    --credit '"Low Poly Tie Fighter Star Wars", de tolotedesign (Sketchfab), CC BY 4.0.'
build/tie_fighter.o $(MG3)/tie_fighter.bin: examples/tie_fighter_shape.h
XWING = examples/low-poly-xwing
examples/x_wing_shape.h: $(XWING)/Xwing_Lowpoly.obj $(XWING)/Xwing_color.png tools/obj2shape.py
	$(PYTHON) tools/obj2shape.py $< --texture $(XWING)/Xwing_color.png --face-color mayoria --name x_wing -o $@ \
	    --credit '"Xwing", de metalmorag (Sketchfab), CC BY 4.0.'
build/x_wing.o $(MG3)/x_wing.bin: examples/x_wing_shape.h

# Pruebas.
$(filter-out build/test_platform2d,$(TESTS)): build/%: build/%.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^
build/test_platform2d: build/test_platform2d.o $(LIB)
	$(CC) $(CFLAGS) -o $@ $^
$(filter-out build/test_platform3d,$(TESTS3D)): build/%: build/%.o build/fixture3d.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $^ -lm
build/test_platform3d: build/test_platform3d.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $^

# Las pruebas de profundidad comparan el raster 3D actual, con profundidad incremental, con la variante
# float anterior: el mismo raster3d.c, draw.c y commands.c compilados otra vez con las funciones
# renombradas (*_reference), para que las dos convivan en un mismo programa.
build/raster3d_reference.o: src/render/3d/raster3d.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -DMGR_INCREMENTAL_DEPTH=0 \
	    -Dmgr_raster_triangle=mgr_raster_triangle_reference \
	    -Dmgr_raster_triangle_area=mgr_raster_triangle_area_reference -c -o $@ $<
build/draw_reference.o: src/render/3d/draw.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -Dmgr_draw_indexed=mgr_draw_indexed_reference \
	    -Dmgr_sort_flush=mgr_sort_flush_reference -Dmgr_sort_discard=mgr_sort_discard_reference \
	    -Dmgr_raster_triangle=mgr_raster_triangle_reference \
	    -Dmgr_raster_triangle_area=mgr_raster_triangle_area_reference -c -o $@ $<
build/commands_reference.o: src/render/3d/commands.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -Dmgr_execute=mgr_execute_reference \
	    -Dmgr_draw_indexed=mgr_draw_indexed_reference -Dmgr_init=mgr_init_reference \
	    -Dmgr_reset_stats=mgr_reset_stats_reference -Dmgr_sort_flush=mgr_sort_flush_reference \
	    -Dmgr_sort_discard=mgr_sort_discard_reference -c -o $@ $<
REFERENCE_OBJS = build/raster3d_reference.o build/draw_reference.o build/commands_reference.o
$(SKETCHES3D:%=build/test_depth_%): build/test_depth_%: build/test_depth_scenes.o build/%.o $(REFERENCE_OBJS) $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $^
build/test_depth_triangles: build/test_depth_triangles.o build/raster3d_reference.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $^

# racer: los niveles están en examples/racer/*.h. Una escena congelada con G (modo debug), otra vez
# en el host: make racer-scene SCENE="<el texto del panel>" [CAPTURE=escena.mglx].
build/racer.o $(MG3)/racer.bin: $(wildcard examples/racer/*.h)
build/racer_scene.o: examples/racer/scene.c examples/racer.c $(wildcard examples/racer/*.h) $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/racer_scene: build/racer_scene.o build/host.o $(LIB3D)
	$(CC) $(CFLAGS) -o $@ $^
racer-scene: build/racer_scene
	./$< -o racer-scene.ppm $(if $(CAPTURE),-c $(CAPTURE))

# Reproduce una captura (-c de un sketch 3D) solo con el renderer: no enlaza MiniGL.
build/mgl-replay: build/replay.o $(RENDERER) build/mgl_capture.o build/ppm.o
	$(CC) $(CFLAGS) -o $@ $^

# Para IntelliSense de VS Code (C_Cpp.default.compileCommands en
# .vscode/settings.json): cómo se compila cada fichero, con los mismos flags.
SRCS = $(foreach dir,$(INCLUDE_DIRS),$(wildcard $(dir)/*.c)) $(wildcard apps/*.c examples/*.c tests/*.c)
compile_commands.json: Makefile $(SRCS)
	@echo '[' > $@; first=1; for f in $(SRCS); do \
	    [ $$first = 1 ] || echo ',' >> $@; first=0; \
	    extra=; case $$f in src/platform/sdl.c) extra="$(SDL_CFLAGS)";; esac; \
	    case $$f in src/platform/minigpu.c) extra="-I$(REPO)/runtime/include";; esac; \
	    printf '  {"directory": "%s", "file": "%s", "command": "%s %s %s %s -c %s"}' \
	        "$(CURDIR)" "$$f" "$(CC)" "$(CPPFLAGS)" "$$extra" "$(CFLAGS)" "$$f" >> $@; \
	done; printf '\n]\n' >> $@

# ---------------------------------------------------------------------------
# Ejecutar en el host y en SDL
# ---------------------------------------------------------------------------

run: $(SKETCHES:%=run-%) $(SKETCHES3D:%=run-%)
run-%: build/%
	./$< -v $(V)
# Los 3D no tienen versiones: varios frames (make run-rotating_cube FRAMES3D=120).
$(SKETCHES3D:%=run-%): run-%: build/%
	./$< -f $(FRAMES3D) -e $(FRAMES_EVERY)

sdl-%: build/%-sdl
	./$< $(if $(filter all,$(V)),,-v $(V))
$(SKETCHES3D:%=sdl-%): sdl-%: build/%-sdl
	./$< $(if $(SCALE),-s $(SCALE))

# ---------------------------------------------------------------------------
# MiniGPU
# ---------------------------------------------------------------------------

# El driver minigpu.c va primero porque lleva main.
$(MG)/%.bin: examples/%.c src/platform/minigpu.c $(MINIGPU_SRCS) $(HDRS) $(LIBC_DEPS)
	$(BUILD_C) src/platform/minigpu.c $< $(MINIGPU_SRCS) $(LIBC) $(INCLUDES) -D MGL_VERSION=$(MV) --outdir $(MG)/$* -o $@
# 3D: el renderer de referencia en la CPU de MiniGPU, con las mismas fuentes que en el host.
$(MG3)/%.bin: examples/%.c src/platform/minigpu.c $(MINIGPU3D_SRCS) $(HDRS) $(LIBC_DEPS)
	$(BUILD_C) src/platform/minigpu.c $< $(MINIGPU3D_SRCS) $(LIBC) $(INCLUDES) $(MG3_DEFS) --outdir $(MG3)/$* -o $@

# Las mismas tres órdenes para 2D ($(MG)) y 3D ($(MG3)); $(1) es la carpeta.
# Ventana del simulador. Cada frame son millones de instrucciones.
SIM_WINDOW = $(SIM_SYS) $< --window --run-limit $(SIM_LIMIT) $(SIM_ARGS)
# Instrucciones por función C (y del runtime) hasta el frame FRAMES; deja además el .asm con la cuenta de
# cada instrucción en <carpeta>/<sketch>-anotado.txt.
define SIM_PROFILE
$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --run-limit $(SIM_LIMIT) \
    --profile --symbols $(1)/$*/minigpu.asm \
    --profile-annotate $(1)/$*-anotado.txt | sed -n '/^Perfil/,$$p'
endef
# El frame FRAMES en el simulador, píxel a píxel contra el host. $(2): opciones del sketch en el host.
define SIM_CHECK
./build/$* -f $(FRAMES) -o $(1)/$*-host.bin $(2)
$(SIM_SYS) $< --halt-after-swaps $(FRAMES) --frame-output $(1)/$*-sim.bin \
    --run-limit $(SIM_LIMIT) > /dev/null
$(COMPARE_FRAMES) --rgb565 320x240 $(1)/$*-host.bin $(1)/$*-sim.bin
endef

sim-%: $(MG)/%.bin
	$(SIM_WINDOW)
profile-minigpu-%: $(MG)/%.bin
	$(call SIM_PROFILE,$(MG))
check-minigpu: $(SKETCHES:%=check-minigpu-%)
check-minigpu-%: $(MG)/%.bin build/%
	$(call SIM_CHECK,$(MG),-v $(MV) > /dev/null)

$(SKETCHES3D:%=sim-%): sim-%: $(MG3)/%.bin
	$(SIM_WINDOW)
$(SKETCHES3D:%=profile-minigpu-%): profile-minigpu-%: $(MG3)/%.bin
	$(call SIM_PROFILE,$(MG3))
check-minigpu3d: $(SKETCHES3D:%=check-minigpu-%)
$(SKETCHES3D:%=check-minigpu-%): check-minigpu-%: $(MG3)/%.bin build/%
	$(call SIM_CHECK,$(MG3),-q)

# ---------------------------------------------------------------------------
# Placa (tools/run-board): compila el .bin, comprueba que la placa tenga el
# bitstream del prototipo (la identidad del monitor, la del RTL) y, si no, lo
# sube sin preguntar (el de _build/default del prototipo); luego carga el
# programa y lo arranca. BOARD_UPLOAD=0: no sube nada, falla si no coincide.
# ---------------------------------------------------------------------------

BOARD_PROTO ?= 38
BOARD_UPLOAD ?= 1
BOARD_ARGS ?=
# Desde la raíz del repo: run-board busca ahí los prototipos.
BOARD_LOAD = cd $(REPO) && tools/run-board -p $(BOARD_PROTO) $(if $(filter 0,$(BOARD_UPLOAD)),--no-upload,-y) \
    $(BOARD_ARGS)
# Opciones con las que se compila cada sketch 3D para la placa (las de la 38). FIXED, FP32 o EXT en la
# línea de órdenes mandan sobre estas.
BOARD_OPTS_racer = FIXED=1 FP32=1 EXT=1
# board_opt(VAR,sketch): VAR=valor, de la línea de órdenes, o si no de BOARD_OPTS_<sketch>, o el de siempre.
board_opt = $(if $(filter command line,$(origin $(1))),$(1)=$($(1)),$(or $(filter $(1)=%,$(BOARD_OPTS_$(2))),$(1)=$($(1))))

board-%: $(MG)/%.bin
	$(BOARD_LOAD) --program $(abspath $<)
$(SKETCHES3D:%=board-%): board-%:
	@$(MAKE) --no-print-directory $(call board_opt,FIXED,$*) $(call board_opt,FP32,$*) \
	    $(call board_opt,EXT,$*) board-load3d-$*
board-load3d-%: $(MG3)/%.bin
	$(BOARD_LOAD) --program $(abspath $<)

# ---------------------------------------------------------------------------
# Pruebas y limpieza
# ---------------------------------------------------------------------------

test: $(TESTS) test3d
	./build/test_cpu
	./build/test_gpu
	./build/test_fuzz_v2
	./build/test_platform2d

test3d: $(TESTS3D) build/test_depth_triangles build/mgl-replay build/rotating_cube
	@for t in $(TESTS3D); do echo ./$$t; ./$$t || exit 1; done
	./build/test_depth_triangles
	./build/rotating_cube -f 40 -o build/replay-host.ppm -c build/replay.mglx -q
	./build/mgl-replay build/replay.mglx build/replay-renderer.ppm
	cmp build/replay-host.ppm build/replay-renderer.ppm && echo "PASS: mgl-replay == sketch, frame 40"

clean:
	rm -rf build
	rm -f *.ppm

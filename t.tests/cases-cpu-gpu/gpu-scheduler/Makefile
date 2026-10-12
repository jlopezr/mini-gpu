# Scheduler de jobs de GPU: biblioteca sin `main`, asi que no usa
# tools/c-program.mk (build-c enlaza crt0 y espera un programa entero).
#
#   make        comprueba C89 con el compilador anfitrion y compila con mini-lcc
#   make host   solo la comprobacion C89 con $(CC)
#   make lcc    solo mini-lcc + mini-opt + mini-asm
#   make test   test-scheduler.c en el anfitrion (C99, ASan y UBSan)
#   make case   test-scheduler.c + scheduler.c para MiniISA, con build-c (lo usa test.json)
#   make sim    ese binario en sim-sys: R1 = 0 si pasa, o la linea del primer fallo
#   make demo-sim  demo.c: el scheduler lanza un job en la GPU de sim-sys (R1 = 0 si va bien)
#   make clean
#
# mini-lcc es C89 y usa las cabeceras de t.tests/inc (stdint.h, stdbool.h).

PYTHON ?= python
CC ?= cc
.DEFAULT_GOAL := all

BASE ?= $(shell git rev-parse --show-toplevel)
MINI_GPU_ROOT := $(BASE)
INC := $(MINI_GPU_ROOT)/t.tests/inc
OUTDIR ?= $(MINI_GPU_ROOT)/_build/c/gpu-scheduler

MINI_LCC := $(PYTHON) "$(MINI_GPU_ROOT)/tools/mini-lcc"
MINI_OPT := $(PYTHON) "$(MINI_GPU_ROOT)/tools/mini-opt"
MINI_ASM := $(PYTHON) "$(MINI_GPU_ROOT)/tools/mini-asm"
BUILD_C := $(PYTHON) "$(MINI_GPU_ROOT)/tools/build-c"
SIM_SYS := $(PYTHON) "$(MINI_GPU_ROOT)/tools/sim-sys"

HOST_CFLAGS := -std=c89 -pedantic -Wno-long-long -Wall -Wextra -Werror -Wdeclaration-after-statement

SOURCE := scheduler.c
DEPS := $(SOURCE) scheduler.h $(INC)/stdint.h $(INC)/stdbool.h
HOST_OBJ := $(OUTDIR)/scheduler.host.o
ASM := $(OUTDIR)/scheduler.s
OPT_ASM := $(OUTDIR)/scheduler.opt.s
BIN := $(OUTDIR)/scheduler.bin
TEST_SOURCE := test-scheduler.c
TEST_HOST_BIN := $(OUTDIR)/test-scheduler-host
CASE_OUTDIR := $(OUTDIR)/case
TEST_IMAGE := $(CASE_OUTDIR)/test-scheduler.bin
DEMO_IMAGE := $(CASE_OUTDIR)/demo.bin
# El test usa printf: va con las cabeceras del sistema, no con las de t.tests/inc.
TEST_CFLAGS := -std=c99 -Wall -Wextra -Werror -g -fsanitize=address,undefined -DTEST_HOST

.PHONY: all host lcc test case sim demo demo-sim clean

all: host lcc

host: $(HOST_OBJ)

lcc: $(BIN)

$(OUTDIR):
	mkdir -p "$@"

# Con las mismas cabeceras que ve mini-lcc: el stdbool.h del sistema usa _Bool, que no es C89.
$(HOST_OBJ): $(DEPS) | $(OUTDIR)
	$(CC) $(HOST_CFLAGS) -I "$(INC)" -c $(SOURCE) -o "$@"

$(ASM): $(DEPS) | $(OUTDIR)
	$(MINI_LCC) $(SOURCE) --no-crt -I "$(INC)" -o "$@"

$(OPT_ASM): $(ASM)
	$(MINI_OPT) "$<" -o "$@" --stats

# Ensamblar solo comprueba que el .s es valido; el .bin no es ejecutable por si solo.
$(BIN): $(OPT_ASM)
	$(MINI_ASM) "$<" -o "$@"

$(TEST_HOST_BIN): $(TEST_SOURCE) $(SOURCE) scheduler.h | $(OUTDIR)
	$(CC) $(TEST_CFLAGS) $(TEST_SOURCE) $(SOURCE) -o "$@"

test: $(TEST_HOST_BIN)
	"$(TEST_HOST_BIN)"

case: $(TEST_IMAGE)

$(TEST_IMAGE): $(TEST_SOURCE) $(DEPS)
	$(BUILD_C) $(TEST_SOURCE) $(SOURCE) --outdir "$(CASE_OUTDIR)" -o "$@"

sim: $(TEST_IMAGE)
	$(SIM_SYS) "$(TEST_IMAGE)"

demo: $(DEMO_IMAGE)

$(DEMO_IMAGE): demo.c $(DEPS)
	$(BUILD_C) demo.c $(SOURCE) --outdir "$(CASE_OUTDIR)" -o "$@"

demo-sim: $(DEMO_IMAGE)
	$(SIM_SYS) "$(DEMO_IMAGE)"

clean:
	rm -rf "$(OUTDIR)"

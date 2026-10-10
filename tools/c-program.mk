# Reglas comunes para los programas CPU+GPU escritos en C.
#
# El Makefile de cada programa define PROGRAM y, opcionalmente, BUILD_ARGS,
# SIM_PROGRAM, SIM_ARGS, DEBUG_ARGS, COMPARE_COMMAND, BOARD_ARGS y PROTOTYPE.
# Las recetas solo invocan Python, por lo que este fichero funciona con GNU
# Make tanto en Windows como en Linux.

PYTHON ?= python
PROTOTYPE ?= 36
.DEFAULT_GOAL := all

BASE ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
MINI_GPU_ROOT := $(BASE)
PROGRAM_DIR := $(CURDIR)
SOURCE ?= $(PROGRAM_DIR)/$(PROGRAM).c
OUTDIR ?= $(MINI_GPU_ROOT)/_build/c
IMAGE := $(OUTDIR)/$(PROGRAM).bin
BOARD_IMAGE := $(OUTDIR)/$(PROGRAM)_board.bin

BUILD_C := $(PYTHON) "$(MINI_GPU_ROOT)/tools/build-c"
SIM_SYS := $(PYTHON) "$(MINI_GPU_ROOT)/tools/sim-sys"
MINI_DBG := $(PYTHON) "$(MINI_GPU_ROOT)/tools/mini-dbg"
RUN_BOARD := $(PYTHON) "$(MINI_GPU_ROOT)/tools/run_board.py"
SIM_PROGRAM ?= $(IMAGE)
SIM_DEPS ?= $(IMAGE)
SIM_COMMAND ?= $(SIM_SYS) "$(SIM_PROGRAM)" $(SIM_ARGS)
DEBUG_PROGRAM ?= $(SIM_PROGRAM)
DEBUG_DEPS ?= $(SIM_DEPS)
DEBUG_ARGS ?=
DEBUG_COMMAND ?= $(MINI_DBG) --gpu "$(DEBUG_PROGRAM)" $(DEBUG_ARGS)
COMPARE_DEPS ?=
RUN_COMMAND ?= $(RUN_BOARD) --prototype $(PROTOTYPE) --program "$(BOARD_IMAGE)"
RUN_DEPS ?= $(BOARD_IMAGE)

.PHONY: all sim debug compare run

all: $(IMAGE)

$(IMAGE): $(SOURCE) $(EXTRA_DEPS)
	$(BUILD_C) "$(SOURCE)" --outdir "$(OUTDIR)" -o "$(IMAGE)" $(BUILD_ARGS)

$(BOARD_IMAGE): $(SOURCE) $(EXTRA_DEPS)
	$(BUILD_C) "$(SOURCE)" --outdir "$(OUTDIR)" -o "$(BOARD_IMAGE)" --board $(BUILD_ARGS) $(BOARD_ARGS)

sim: $(SIM_DEPS)
	$(SIM_COMMAND)

debug: $(DEBUG_DEPS)
	$(DEBUG_COMMAND)

compare: $(COMPARE_DEPS)
	$(COMPARE_COMMAND)

run: $(RUN_DEPS)
	$(RUN_COMMAND)

BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := life
EXTRA_DEPS := life_body.h
SIM_PROGRAM = $(PROGRAM_DIR)/life.asm
SIM_DEPS := life.asm life.inc ../race_host.inc
SIM_ARGS := --window
DEBUG_ARGS := --window
COMPARE_COMMAND = $(PYTHON) "$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/compare/compare_race.py" life
RUN_COMMAND = $(RUN_BOARD) --prototype $(PROTOTYPE) --program "$(PROGRAM_DIR)/life.asm"
RUN_DEPS :=

include $(BASE)/tools/c-program.mk


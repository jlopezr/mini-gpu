BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := rotate
EXTRA_DEPS := rotate_body.h
SIM_PROGRAM = $(PROGRAM_DIR)/rotate.asm
SIM_DEPS := rotate.asm rotate.inc ../race_host.inc
SIM_ARGS := --window
DEBUG_ARGS := --window
COMPARE_COMMAND = $(PYTHON) "$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/compare/compare_race.py" rotate
RUN_COMMAND = $(RUN_BOARD) --prototype $(PROTOTYPE) --program "$(PROGRAM_DIR)/rotate.asm"
RUN_DEPS :=

include $(BASE)/tools/c-program.mk


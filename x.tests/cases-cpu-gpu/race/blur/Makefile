BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := blur
EXTRA_DEPS := blur_body.h
SIM_PROGRAM = $(PROGRAM_DIR)/blur.asm
SIM_DEPS := blur.asm blur.inc ../race_host.inc
SIM_ARGS := --window
DEBUG_ARGS := --window
COMPARE_COMMAND = $(PYTHON) "$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/compare/compare_race.py" blur
RUN_COMMAND = $(RUN_BOARD) --prototype $(PROTOTYPE) --program "$(PROGRAM_DIR)/blur.asm"
RUN_DEPS :=

include $(BASE)/tools/c-program.mk


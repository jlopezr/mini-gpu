BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := cube
SIM_ARGS := --window
DEBUG_ARGS := --window
COMPARE_COMMAND = $(PYTHON) "$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/compare/compare_race.py" cube
include $(BASE)/tools/c-program.mk

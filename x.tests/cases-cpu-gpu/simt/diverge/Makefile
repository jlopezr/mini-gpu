BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := diverge
COMPARE_COMMAND = $(PYTHON) "$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/test_cpu_gpu_sim.py" CDivergenceTest
include $(BASE)/tools/c-program.mk

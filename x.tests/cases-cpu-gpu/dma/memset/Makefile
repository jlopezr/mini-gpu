BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := memset
COMPARE_COMMAND = $(PYTHON) "$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/test_cpu_gpu_sim.py" CKernelTest
include $(BASE)/tools/c-program.mk

BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := plane
TEXTURE := $(BASE)/_build/c/plane_tex.bin
EXTRA_DEPS := plane_body.h logos.png $(TEXTURE)
BUILD_ARGS := --data "plane_tex=$(TEXTURE)"
SIM_ARGS := --window
DEBUG_ARGS := --window
COMPARE_COMMAND = $(PYTHON) -c "import os, runpy, sys; p=r'$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/test_cpu_gpu_sim.py'; os.environ['RUN_SLOW']='1'; sys.argv=[p, 'CPlaneRaceTest']; sys.path.insert(0, os.path.dirname(p)); runpy.run_path(p, run_name='__main__')"

include $(BASE)/tools/c-program.mk

$(TEXTURE): plane_tex.py logos.png
	$(PYTHON) plane_tex.py -o "$(TEXTURE)"

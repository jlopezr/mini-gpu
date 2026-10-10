BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := plane
TEXTURE := $(BASE)/_build/c/plane_tex.bin
TEST_IMAGE := $(BASE)/_build/c/plane_test.bin
TEST_EXPECTED := $(CURDIR)/_build/expected.bin
EXTRA_DEPS := plane_body.h logos.png $(TEXTURE)
BUILD_ARGS := --data "plane_tex=$(TEXTURE)"
SIM_ARGS := --window
DEBUG_ARGS := --window
COMPARE_COMMAND = $(PYTHON) -c "import os, runpy, sys; p=r'$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/test_cpu_gpu_sim.py'; os.environ['RUN_SLOW']='1'; sys.argv=[p, 'CPlaneRaceTest']; sys.path.insert(0, os.path.dirname(p)); runpy.run_path(p, run_name='__main__')"

include $(BASE)/tools/c-program.mk

$(TEXTURE): plane_tex.py logos.png
	$(PYTHON) plane_tex.py -o "$(TEXTURE)"

.PHONY: case
case: $(TEST_IMAGE) $(TEST_EXPECTED)

$(TEST_IMAGE): plane_test.c plane.c plane_body.h $(TEXTURE)
	$(BUILD_C) "$(CURDIR)/plane_test.c" --outdir "$(OUTDIR)" -o "$(TEST_IMAGE)" --data "plane_tex=$(TEXTURE)"

$(TEST_EXPECTED): reference.py $(TEXTURE)
	$(PYTHON) reference.py

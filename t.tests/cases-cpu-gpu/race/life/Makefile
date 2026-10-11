BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := life_app
SOURCE := $(CURDIR)/life_standalone.c
CASE_DATA := $(BASE)/_build/c/life_case.bin
CASE_EXPECTED := $(CURDIR)/_build/expected-0.bin $(CURDIR)/_build/expected-1.bin
EXTRA_DEPS := life.c life_body.h $(CASE_DATA)
BUILD_ARGS := --data "race_case=$(CASE_DATA)"
COMPARE_COMMAND = $(PYTHON) "$(MINI_GPU_ROOT)/32.cpu-gpu-func-sim/compare/compare_race.py" life

include $(BASE)/tools/c-program.mk

.PHONY: case
case: $(IMAGE) $(CASE_EXPECTED)

$(CASE_DATA) $(CASE_EXPECTED): $(BASE)/tools/race_case_data.py
	$(PYTHON) "$(BASE)/tools/race_case_data.py" life "$(CASE_DATA)" --expected-dir "$(CURDIR)/_build"


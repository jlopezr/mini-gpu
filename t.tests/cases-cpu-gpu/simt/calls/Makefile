BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := calls
include $(BASE)/tools/c-program.mk

.PHONY: case
case: $(IMAGE)

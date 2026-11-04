BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := string_test
include $(BASE)/tools/c-program.mk

.PHONY: case
case: $(IMAGE)

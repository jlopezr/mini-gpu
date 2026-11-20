BASE ?= $(shell git rev-parse --show-toplevel)
PROGRAM := string_test
# Es una prueba de libc de CPU: no enlazar la pila ni el lanzador GPU comunes.
GPU_RUNTIME :=
include $(BASE)/tools/c-program.mk

.PHONY: case
case: $(IMAGE)

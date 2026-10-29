CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Werror -pedantic
CPPFLAGS += -Iinclude
PYTHON ?= python3
all: build/demo build/test build/test.mf
build:
	mkdir -p build
build/demo: src/minifont.c examples/demo.c include/minifont.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) src/minifont.c examples/demo.c -o $@
build/test: src/minifont.c tests/test_minifont.c include/minifont.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) src/minifont.c tests/test_minifont.c -o $@
build/test.mf: fonts/test.bdf tools/bdf2mf.py | build
	$(PYTHON) tools/bdf2mf.py fonts/test.bdf $@
test: all
	./build/test build/test.mf
run: test
	./build/demo build/test.mf build/demo.ppm
clean:
	rm -rf build
.PHONY: all test run clean

# Provide the user's copy of NEWS.FLB; original data is not included.
FLB ?= NEWS.FLB
flb-park10: build
	$(PYTHON) tools/flb2mf.py "$(FLB)" --font "park 10" --output build/park10.mf --sheet build/park10.png
	./build/demo build/park10.mf build/park10.ppm
.PHONY: flb-park10

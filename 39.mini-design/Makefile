CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
PYTHON ?= python3
# Originales de NewsMaster (NEWS.FLB/SHP/SDX/SDR/ICN). Las fuentes se extraen
# de NEWS.FLB en el build, no se guardan sueltas.
RES ?= resources
FLB ?= $(RES)/NEWS.FLB
FONT_DIR = build/fonts
FONTS_STAMP = $(FONT_DIR)/.stamp
OBJS = example.o display_list.o renderer_cpu.o minifont.o
.PHONY: all run clean test run-blit check-blit test-minifont run-minifont flb-park10 flb-fonts flb-sheets test-flb
.PHONY: shapes icons test-extractors check
all: example flb-fonts
example: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS)
%.o: %.c gfx.h minifont.h
	$(CC) $(CFLAGS) -c -o $@ $<
run: example $(FONTS_STAMP)
	./example $(FONT_DIR)/park10.mf
clean:
	rm -f example $(OBJS) demo-320x240.ppm demo-640x480.ppm blit_demo blit_demo.o blit-*.ppm
	rm -f demo-*.png blit-*.png
	rm -rf build
LIB_OBJS = display_list.o renderer_cpu.o minifont.o
build/test_gfx: tests/test_gfx.c $(LIB_OBJS) gfx.h minifont.h | build
	$(CC) $(CFLAGS) -I. -o $@ tests/test_gfx.c $(LIB_OBJS)
build/test_blit: tests/test_blit.c $(LIB_OBJS) gfx.h minifont.h | build
	$(CC) $(CFLAGS) -I. -o $@ tests/test_blit.c $(LIB_OBJS)
test: build/test_gfx $(FONTS_STAMP)
	./build/test_gfx $(FONT_DIR)/park10.mf

blit_demo: blit_demo.o display_list.o renderer_cpu.o minifont.o
	$(CC) $(CFLAGS) -o $@ $^
run-blit: blit_demo
	./blit_demo
check-blit: build/test_blit
	./build/test_blit

# MiniFont: lector .mf, conversores y tests. Salida en build/.
build:
	mkdir -p build
build/minifont_demo: minifont.c minifont_demo.c minifont.h | build
	$(CC) $(CFLAGS) minifont.c minifont_demo.c -o $@
build/test_minifont: minifont.c tests/test_minifont.c minifont.h | build
	$(CC) $(CFLAGS) -I. minifont.c tests/test_minifont.c -o $@
build/test.mf: fonts/test.bdf tools/bdf2mf.py | build
	$(PYTHON) tools/bdf2mf.py fonts/test.bdf $@
test-minifont: build/test_minifont build/test.mf
	./build/test_minifont build/test.mf
run-minifont: test-minifont build/minifont_demo
	./build/minifont_demo build/test.mf build/minifont_demo.ppm

# Las 30 fuentes normales de NEWS.FLB -> build/fonts/<nombre>.mf (o FLB=/ruta/a/NEWS.FLB).
$(FONTS_STAMP): $(FLB) tools/flb2mf.py
	$(PYTHON) tools/flb2mf.py "$(FLB)" --all $(FONT_DIR)
	@touch $@
flb-fonts: $(FONTS_STAMP)
flb-park10: build/minifont_demo $(FONTS_STAMP)
	./build/minifont_demo $(FONT_DIR)/park10.mf build/park10.ppm
# Además hojas de muestra build/fonts/<nombre>.png; requiere Pillow.
flb-sheets:
	$(PYTHON) tools/flb2mf.py "$(FLB)" --all $(FONT_DIR) --sheets
	@touch $(FONTS_STAMP)
test-flb:
	$(PYTHON) tests/test_flb.py "$(FLB)"

# Clipart e iconos de NewsMaster (NEWS.SHP/SDX/SDR/ICN en $(RES)); requiere Pillow.
shapes:
	$(PYTHON) tools/shp2png.py $(RES)/NEWS.SHP $(RES)/NEWS.SDX $(RES)/NEWS.SDR --output build/shapes
icons:
	$(PYTHON) tools/icn2png.py $(RES)/NEWS.ICN --output build/icons --correct-aspect
test-extractors:
	$(PYTHON) tests/test_extractors.py --resources $(RES)

check: test check-blit test-minifont test-flb test-extractors

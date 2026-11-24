ROOT := ..
CC ?= gcc
CFLAGS := -std=c89 -pedantic-errors -Wall -Wextra
SDL_CFLAGS := $(shell pkg-config --cflags sdl)
SDL_LIBS := $(shell pkg-config --libs sdl)
BUILD := _build
MOD := axel.mod
MODBIN := $(BUILD)/axel.bin
MINICPU_RATE ?= 48000

.PHONY: host minicpu tone digest-host digest-minicpu clean

host: $(BUILD)/minexample

$(BUILD)/minexample: minexample.c modplay.c modplay.h | $(BUILD)
	$(CC) $(CFLAGS) $(SDL_CFLAGS) minexample.c modplay.c -o $@ $(SDL_LIBS)

minicpu: $(BUILD)/modplay.bin

tone: $(BUILD)/tone_player.bin

$(BUILD)/tone_player.bin: tone_player.c | $(BUILD)
	mini-cc tone_player.c $(ROOT)/runtime/src/string.c -I . --output-dir $(BUILD)/tone
	cp $(BUILD)/tone/tone_player.bin $@

$(MODBIN): $(MOD) | $(BUILD)
	cp $< $@

$(BUILD)/modplay.bin: miniplayer.c modplay.c modplay.h $(MODBIN) | $(BUILD)
	mini-cc miniplayer.c modplay.c $(ROOT)/runtime/src/string.c -I . -D MOD_SAMPLE_RATE=$(MINICPU_RATE) --data mod=$(MODBIN) --output-dir $(BUILD)/minicpu
	cp $(BUILD)/minicpu/miniplayer.bin $@

digest-host: $(BUILD)/render_digest_host

$(BUILD)/render_digest_host: render_digest.c modplay.c modplay.h | $(BUILD)
	$(CC) $(CFLAGS) -DHOST render_digest.c modplay.c -o $@

digest-minicpu: $(BUILD)/render_digest.bin

$(BUILD)/render_digest.bin: render_digest.c modplay.c modplay.h $(MODBIN) | $(BUILD)
	mini-cc render_digest.c modplay.c $(ROOT)/runtime/src/string.c -I . --data mod=$(MODBIN) --output-dir $(BUILD)/digest
	cp $(BUILD)/digest/render_digest.bin $@

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)

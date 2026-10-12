# Compilacion separada y enlace con vlink: tres objetos (dos de C, uno de
# ensamblador), dos de ellos en una biblioteca de la que vlink solo saca lo que
# se usa. Explicado en README.md.
#
#   make          main.o + libejemplo.a -> programa.bin (mates.o se queda fuera)
#   make todo     los tres .o sueltos   -> programa-todo.bin (entra todo)
#   make sim      programa.bin en sim-sys: R1 = 42
#   make clean
#
# Necesita vlink compilado: git submodule update --init w.vlink && build-vlink

PYTHON ?= python3
AR ?= ar
.DEFAULT_GOAL := all

ROOT := $(abspath ../..)
OUTDIR ?= $(ROOT)/_build/ejemplo-enlazado
VLINK ?= $(ROOT)/w.vlink/vlink

MINI_LCC := $(PYTHON) "$(ROOT)/tools/mini-lcc"
MINI_ASM := $(PYTHON) "$(ROOT)/tools/mini-asm"
SIM_SYS := $(PYTHON) "$(ROOT)/tools/sim-sys"

# Funciones que main.c llama sin definir. lcc solo declara `.extern` para datos,
# no para funciones (en build-c todo se ensambla junto), asi que se anaden aqui.
MAIN_EXTERNS := doble

ARRANQUE := $(OUTDIR)/arranque.o
MAIN := $(OUTDIR)/main.o
MATES := $(OUTDIR)/mates.o
RUTINAS := $(OUTDIR)/rutinas.o
LIB := $(OUTDIR)/libejemplo.a
BIN := $(OUTDIR)/programa.bin
BIN_TODO := $(OUTDIR)/programa-todo.bin

.PHONY: all todo sim clean

all: $(BIN)

todo: $(BIN_TODO)

$(OUTDIR):
	mkdir -p "$@"

# --- 1. Compilar: C -> .s -------------------------------------------------
$(OUTDIR)/%.s: %.c | $(OUTDIR)
	$(MINI_LCC) $< --no-crt -o "$@"

# --- 2. Ensamblar: .s/.asm -> .o (VOBJ). Solo --vobj, sin -o: un objeto con
#        simbolos sin resolver no puede ser todavia un .bin. ------------------
$(OUTDIR)/main.ext.s: $(OUTDIR)/main.s
	printf '    .extern %s\n' $(MAIN_EXTERNS) > "$@"
	printf '    .include "main.s"\n' >> "$@"

$(MAIN): $(OUTDIR)/main.ext.s
	$(MINI_ASM) "$<" --vobj "$@"

$(MATES): $(OUTDIR)/mates.s
	$(MINI_ASM) "$<" --vobj "$@"

$(RUTINAS): rutinas.asm | $(OUTDIR)
	$(MINI_ASM) $< --vobj "$@"

$(ARRANQUE): arranque.asm $(ROOT)/1.isa/runtime/crt0.s | $(OUTDIR)
	$(MINI_ASM) $< -I "$(ROOT)/1.isa/runtime" --vobj "$@"

# --- 3. Biblioteca: los objetos que se enlazan solo si alguien los pide ------
$(LIB): $(MATES) $(RUTINAS)
	rm -f "$@"
	$(AR) rc "$@" $^

# --- 4. Enlazar. El orden importa: vlink recorre la biblioteca cuando ya sabe
#        que simbolos faltan, asi que va despues de quien los usa. arranque.o
#        primero: _start tiene que quedar en la direccion 0. -M deja el mapa. --
$(BIN): $(ARRANQUE) $(MAIN) $(LIB)
	"$(VLINK)" -brawbin1 -M -o "$@" $^ > "$(@:.bin=.map)"
	@grep "needed due to" "$(@:.bin=.map)" || true
	@echo "mapa: $(@:.bin=.map)"

$(BIN_TODO): $(ARRANQUE) $(MAIN) $(MATES) $(RUTINAS)
	"$(VLINK)" -brawbin1 -M -o "$@" $^ > "$(@:.bin=.map)"
	@echo "mapa: $(@:.bin=.map)"

sim: $(BIN)
	$(SIM_SYS) "$(BIN)"

clean:
	rm -rf "$(OUTDIR)"

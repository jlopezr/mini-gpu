TOP       := top
DEVICE    ?= 85k
PACKAGE   := CABGA381
FREQ      := 25
SOURCES   := top.v sdram_controller.v memory_test.v

.PHONY: all clean prog flash lint
all: $(TOP).bit

$(TOP).json: $(SOURCES) build.ys
	yosys build.ys

$(TOP).config: $(TOP).json ulx3s.lpf
	nextpnr-ecp5 --$(DEVICE) --package $(PACKAGE) --freq $(FREQ) --json $< --lpf ulx3s.lpf --textcfg $@

$(TOP).bit: $(TOP).config
	ecppack --compress $< $@

lint:
	yosys -q -p "read_verilog -sv $(SOURCES); hierarchy -check -top $(TOP); proc; check"

prog: $(TOP).bit
	ujprog $<

flash: $(TOP).bit
	ujprog -j flash $<

clean:
	rm -f $(TOP).json $(TOP).config $(TOP).bit

# ULX3S async FIFO self-test + UART (v2)

This project exercises a corrected asynchronous FIFO with two independent clock sources:

- write domain: ULX3S 25 MHz oscillator
- read domain: ECP5 internal `OSCG` (`DIV=16`)
- FIFO: 16 x 8 by default
- self-checking producer/consumer
- LEDs for PASS/ERROR/FULL/EMPTY/activity
- FTDI UART monitor at approximately 115200 baud, 8N1

## Files

- `async_fifo.v` - corrected Gray-pointer asynchronous FIFO
- `reset_sync.v` - async assert / synchronous release reset synchronizer
- `divide_by_n.v` - baud tick divider
- `uart.v` - reusable UART TX/RX/wrapper using the existing block interface
- `fifo_test_top.v` - self-test and UART status monitor
- `fifo_test.lpf` - minimal ULX3S v2.0/v2.1 constraints
- `Makefile` - Yosys + nextpnr-ecp5 + ecppack flow

## Reset

FIRE1 is `btn[1]`. Pressing FIRE1 resets both clock domains; release is synchronized independently in each domain.

## LEDs

- D0 / `led[0]`: ERROR latched. Must stay OFF.
- D1 / `led[1]`: FULL has been seen.
- D2 / `led[2]`: EMPTY has been seen after traffic.
- D3 / `led[3]`: write heartbeat.
- D4 / `led[4]`: read heartbeat.
- D5 / `led[5]`: current FULL state.
- D6 / `led[6]`: current EMPTY state.
- D7 / `led[7]`: PASS = FULL seen + EMPTY seen + no error.

Expected healthy result after a short time: D0 OFF, D1/D2/D7 ON, D3/D4 blinking. D5/D6 may appear dim or partially lit because FULL/EMPTY change faster than the eye can follow.

## UART

The monitor uses the on-board FTDI connection:

- `ftdi_rxd`: FPGA -> FTDI -> PC
- `ftdi_txd`: PC -> FTDI -> FPGA

Settings: **115200 baud, 8 data bits, no parity, 1 stop bit**.

The design prints one line per second, for example:

```
WR=0012AC84 FULL=0 EMPTY=1 FSEEN=1 ESEEN=1 ERR=0 PASS=1
```

Sending `s` or `S` from the terminal requests an immediate status line.

Example Linux terminal:

```bash
picocom -b 115200 /dev/ttyUSB0
```

Depending on how the ULX3S/FTDI enumerates on your machine, the serial interface may be another `/dev/ttyUSB*` device.

## Build

For an 85F board:

```bash
make DEVICE=85k
```

For a 45F board:

```bash
make DEVICE=45k
```

Then program SRAM:

```bash
make prog
```

Equivalent manual flow for 85F:

```bash
yosys -p "synth_ecp5 -top fifo_test_top -json fifo_test.json" \
  async_fifo.v reset_sync.v divide_by_n.v uart.v fifo_test_top.v

nextpnr-ecp5 --85k --package CABGA381 \
  --json fifo_test.json \
  --lpf fifo_test.lpf \
  --textcfg fifo_test.config \
  --freq 25

ecppack fifo_test.config fifo_test.bit
fujprog fifo_test.bit
```

## Notes

The UART status monitor only consumes values local to the 25 MHz domain or single-bit status signals synchronized into that domain. It intentionally does not sample the 32-bit read counter directly across the clock-domain boundary.

The FIFO memory itself is not reset. Resetting the pointers and EMPTY/FULL state is sufficient; stale RAM contents are never considered valid after reset.

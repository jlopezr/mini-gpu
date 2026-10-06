# Último informe de síntesis por prototipo

_La tabla la genera `generate-docs` a partir de `x.tests/backends/` y `reports/`; el texto exterior al bloque puede editarse a mano._

<!-- gendoc:begin synthesis-table
generator: synthesis-table
-->

| Prototype | Label | Clock | Achieved / Target (MHz) | Status |
|---|---|---|---|---|
| [`3.fpga`](../3.fpga) | build | $glbnet$clk_25mhz$TRELLIS_IO_IN | 295.42 / 25.00 | PASS |
| [`4.fpga-uart`](../4.fpga-uart) | build | $glbnet$clk | 166.94 / 120.00 | PASS |
| [`5.fpga-monitor`](../5.fpga-monitor) | build | $glbnet$clk | 139.76 / 120.00 | PASS |
| [`6.fpga-cpu`](../6.fpga-cpu) | auto-upload | $glbnet$clk | 112.46 / 100.00 | PASS |
| [`7.ulx3s_w9825g6kh_test`](../7.ulx3s_w9825g6kh_test) | build | $glbnet$sdram_clk$TRELLIS_IO_OUT | 136.05 / 25.00 | PASS |
| [`8.fpga-ram`](../8.fpga-ram) | build | $glbnet$sdram_clk$TRELLIS_IO_OUT | 118.99 / 25.00 | PASS |
| [`9.fpga-ram-param`](../9.fpga-ram-param) | seed4 | $glbnet$sdram_clk$TRELLIS_IO_OUT | 122.58 / 120.00 | PASS |
| [`10.fpga-cpu-ram`](../10.fpga-cpu-ram) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 105.73 / 100.00 | PASS |
| [`12.fpga-gpu`](../12.fpga-gpu) | auto-upload | $glbnet$clk_25mhz$TRELLIS_IO_IN | 35.06 / 25.00 | PASS |
| [`13.hdmi`](../13.hdmi) | build | $glbnet$clk_pix | 110.95 / 74.00 | PASS |
| [`13.hdmi`](../13.hdmi) | build | $glbnet$clk_pix_5x | 425.89 / 370.10 | PASS |
| [`14.fpga-gpu-ram`](../14.fpga-gpu-ram) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 31.56 / 25.00 | PASS |
| [`16.fpga-cpu-hdmi`](../16.fpga-cpu-hdmi) | auto-upload | $glbnet$clk_pix | 103.09 / 25.00 | PASS |
| [`16.fpga-cpu-hdmi`](../16.fpga-cpu-hdmi) | auto-upload | $glbnet$clk_pix_5x | 315.56 / 125.00 | PASS |
| [`16.fpga-cpu-hdmi`](../16.fpga-cpu-hdmi) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 105.24 / 100.00 | PASS |
| [`17.fpga-gpu-ram-v2`](../17.fpga-gpu-ram-v2) | build | $glbnet$sdram_clk$TRELLIS_IO_OUT | 46.46 / 25.00 | PASS |
| [`18.fpga-cpu-hdmi-bl8`](../18.fpga-cpu-hdmi-bl8) | auto-upload | $glbnet$clk_pix | 105.81 / 25.00 | PASS |
| [`18.fpga-cpu-hdmi-bl8`](../18.fpga-cpu-hdmi-bl8) | auto-upload | $glbnet$clk_pix_5x | 294.38 / 125.00 | PASS |
| [`18.fpga-cpu-hdmi-bl8`](../18.fpga-cpu-hdmi-bl8) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 87.50 / 80.00 | PASS |
| [`19.fpga-cpu-hdmi-ls`](../19.fpga-cpu-hdmi-ls) | auto-upload | $glbnet$clk_pix | 103.31 / 25.00 | PASS |
| [`19.fpga-cpu-hdmi-ls`](../19.fpga-cpu-hdmi-ls) | auto-upload | $glbnet$clk_pix_5x | 414.94 / 125.00 | PASS |
| [`19.fpga-cpu-hdmi-ls`](../19.fpga-cpu-hdmi-ls) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 86.57 / 80.00 | PASS |
| [`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu) | auto-upload | $glbnet$clk_pix | 101.61 / 25.00 | PASS |
| [`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu) | auto-upload | $glbnet$clk_pix_5x | 362.06 / 125.00 | PASS |
| [`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 88.08 / 80.00 | PASS |
| [`22.fpga-gpu-bl8`](../22.fpga-gpu-bl8) | auto-upload | $glbnet$clk_pix | 74.03 / 25.00 | PASS |
| [`22.fpga-gpu-bl8`](../22.fpga-gpu-bl8) | auto-upload | $glbnet$clk_pix_5x | 222.27 / 125.00 | PASS |
| [`22.fpga-gpu-bl8`](../22.fpga-gpu-bl8) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 38.41 / 25.00 | PASS |
| [`26.async-fifo`](../26.async-fifo) | build | $glbnet$clk_25mhz$TRELLIS_IO_IN | 159.67 / 25.00 | PASS |
| [`26.async-fifo`](../26.async-fifo) | build | $glbnet$clk_rd | 158.03 / 19.38 | PASS |
| [`27.async-fifo-uart`](../27.async-fifo-uart) | build | $glbnet$clk_25mhz$TRELLIS_IO_IN | 144.20 / 25.00 | PASS |
| [`27.async-fifo-uart`](../27.async-fifo-uart) | build | $glbnet$clk_rd | 153.85 / 19.38 | PASS |
| [`29.fpga-gpu-sm-pipeline`](../29.fpga-gpu-sm-pipeline) | getid-subword | $glbnet$clk_pix | 75.43 / 25.00 | PASS |
| [`29.fpga-gpu-sm-pipeline`](../29.fpga-gpu-sm-pipeline) | getid-subword | $glbnet$clk_pix_5x | 200.12 / 125.00 | PASS |
| [`29.fpga-gpu-sm-pipeline`](../29.fpga-gpu-sm-pipeline) | getid-subword | $glbnet$sdram_clk$TRELLIS_IO_OUT | 38.37 / 25.00 | PASS |
| [`30.fpga-cpu-console`](../30.fpga-cpu-console) | auto-upload | $glbnet$clk_pix | 56.27 / 25.00 | PASS |
| [`30.fpga-cpu-console`](../30.fpga-cpu-console) | auto-upload | $glbnet$clk_pix_5x | 284.01 / 125.00 | PASS |
| [`30.fpga-cpu-console`](../30.fpga-cpu-console) | auto-upload | $glbnet$sdram_clk$TRELLIS_IO_OUT | 85.76 / 80.00 | PASS |

<!-- gendoc:end synthesis-table -->

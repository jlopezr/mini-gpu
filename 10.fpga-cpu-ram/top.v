`default_nettype none

module top (
    input wire clk_25mhz, input wire btn_pwr_n,
    output wire [7:0] led, output wire wifi_gpio0,
    input wire ftdi_txd, output wire ftdi_rxd,
    output wire sdram_clk, output wire sdram_cke, output wire sdram_csn,
    output wire sdram_rasn, output wire sdram_casn, output wire sdram_wen,
    output wire [12:0] sdram_a, output wire [1:0] sdram_ba,
    output wire [1:0] sdram_dqm, inout wire [15:0] sdram_d
);
  // 100 MHz desde que el monitor lleva WRITE_WORD: a 120 no cumplia ninguna
  // de ocho semillas (104,40 a 113,01 MHz, mediana 106,49). Ver pll_100.v.
  // `CLK_FREQ_HZ` es lo que usa el controlador de SDRAM para recalcular sus
  // tiempos, asi que tiene que bajar con el reloj y no despues.
  localparam integer CLK_FREQ_HZ = 100_000_000;
  // 100 MHz / 100 = 1 Mbaud exacto, el mismo que 16, 18, 19 y 21. A 100 no hay
  // divisor que de los 3 Mbaud de antes (33,33), `uart.v` exige multiplo de 4
  // --sobremuestrea a x4-- y 2,5 Mbaud no lo sabe hacer el FTDI, que solo da
  // 3 MHz / n con n entero o n,5 a partir de 2. `monitor.py` lleva el mismo
  // numero.
  localparam integer UART_CLOCKS_PER_BIT = 100;
  localparam integer UART_MAX_BAUD = 1_000_000;
  localparam integer UART_DIVISOR = UART_CLOCKS_PER_BIT;

  wire clk, pll_locked;
  pll_100 pll_i(.clkin(clk_25mhz), .clkout0(clk), .locked(pll_locked));

  // Shifted reset avoids a counter terminal-count path on the high-fanout
  // reset net. Sixteen clean clocks are sufficient; the SDRAM controller then
  // performs its own JEDEC power-up delay before asserting init_done.
  reg [15:0] reset_shift = 16'hffff;
  wire reset = reset_shift[15];
  always @(posedge clk) begin
    if (!pll_locked || !btn_pwr_n) begin
      reset_shift <= 16'hffff;
    end else begin
      reset_shift <= {reset_shift[14:0], 1'b0};
    end
  end
  assign wifi_gpio0 = 1'b1;

  wire [7:0] uart_rx_data, uart_tx_data;
  wire uart_rx_strobe, uart_tx_strobe, uart_tx_ready;
  uart #(.DIVISOR(UART_DIVISOR)) uart_i(
      .clk(clk), .reset(reset), .serial_rxd(ftdi_txd), .serial_txd(ftdi_rxd),
      .rxd(uart_rx_data), .rxd_strobe(uart_rx_strobe),
      .txd(uart_tx_data), .txd_strobe(uart_tx_strobe), .txd_ready(uart_tx_ready));

  // Keep UART receive routing and the monitor's large command FSM on separate
  // timing stages. The strobe is delayed with its byte, preserving semantics.
  (* keep = "true" *) reg [7:0] monitor_rx_data;
  (* keep = "true" *) reg monitor_rx_strobe;
  always @(posedge clk) begin
    if (reset) begin
      monitor_rx_data <= 8'h00;
      monitor_rx_strobe <= 1'b0;
    end else begin
      monitor_rx_data <= uart_rx_data;
      monitor_rx_strobe <= uart_rx_strobe;
    end
  end

  wire [31:0] mem_address;
  wire [7:0] mem_write_data, mem_read_data, last_command;
  wire [31:0] mem_write_word;  // la palabra entera, para WRITE_WORD
  wire mem_write_word_enable;
  wire [31:0] mem_read_word;   // la misma lectura sin trocear
  wire mem_write_enable, mem_read_enable, mem_ready, mem_error, monitor_busy;
  wire cpu_run_request, cpu_halt_request, cpu_step_request, cpu_reset_request;
  wire cpu_halted, cpu_error, cpu_instruction_retired;
  wire [7:0] cpu_error_code;
  wire [4:0] cpu_debug_register_address;
  wire [31:0] cpu_debug_register_data, cpu_pc;

  // MAYOR = juego de comandos (1 = base), MENOR = numero de carpeta.
  // Ver docs/unificacion-mmio.md fase 5.
  //
  // BACKPORT DE R0 CABLEADO A CERO: `R0` vale siempre cero y descarta las
  // escrituras. Es INCOMPATIBLE --un programa que lo use como registro general
  // da otro resultado en silencio-- asi que sube la version aunque el protocolo
  // no cambie ni un byte. Ver 1.isa/isa.md seccion 1.
  //
  // La unica ventana es la de identificacion: esta carpeta tiene `sysid` pero
  // ningun otro MMIO. Gemela de MONITOR_REGIONS en monitor.py.
  monitor #(.VERSION_MAJOR(8'd3),.VERSION_MINOR(8'd10),
      .RAM_END(33'h0_0200_0000),
      .WINDOW0_BASE(33'h0_8000_0f00),.WINDOW0_END(33'h0_8000_0f10))
    monitor_i (
      .clk(clk), .reset(reset), .rx_data(monitor_rx_data),
      .rx_strobe(monitor_rx_strobe),
      .tx_data(uart_tx_data), .tx_strobe(uart_tx_strobe), .tx_ready(uart_tx_ready),
      .mem_address(mem_address), .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable),
      .mem_write_word(mem_write_word),
      .mem_write_word_enable(mem_write_word_enable),
      .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data), .mem_read_word(mem_read_word), .mem_ready(mem_ready), .mem_error(mem_error),
      .cpu_run_request(cpu_run_request), .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request), .cpu_reset_request(cpu_reset_request),
      .cpu_halted(cpu_halted), .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code), .cpu_pc(cpu_pc),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(cpu_debug_register_data),
      // Sin puerto serie: HAS_SERIAL = 0 y las entradas a cero. Las
      // salidas se quedan al aire y la sintesis se las lleva.
      .serial_rx_free(8'd0), .serial_tx_data(8'd0),
      .serial_tx_count(8'd0),
      .last_command(last_command), .busy(monitor_busy));

  // Register both directions of the monitor memory port. Besides making the
  // interface timing-independent, this prevents the monitor FSM, arbitration
  // and response handling from becoming one long combinational path.
  reg [31:0] adapter_monitor_address;
  reg [7:0] adapter_monitor_write_data;
  reg [31:0] adapter_monitor_write_word;
  reg adapter_monitor_write_enable, adapter_monitor_write_word_enable;
  reg adapter_monitor_read_enable;
  wire [7:0] adapter_monitor_read_data;
  // La misma lectura sin trocear, para READ_WORD. El adaptador ya la producia;
  // este top la declaraba, se la pasaba al monitor y no la conducia NADIE, asi
  // que READ_WORD latia una X. No saltaba porque monitor_tb conduce esa senal
  // el mismo, siendo un reg del propio banco.
  wire [31:0] adapter_monitor_read_word;
  wire adapter_monitor_ready, adapter_monitor_error;
  // ---------------------------------------------------------------------
  // Identificacion del prototipo
  // ---------------------------------------------------------------------
  //
  // Esta carpeta NO tiene MMIO, y no lo gana aqui. `sysid` cuelga del camino
  // del MONITOR y nada mas: la CPU no lo ve, no hay pagina de dispositivos y
  // un programa no puede leerlo. La leccion de esta carpeta --mapa plano sobre
  // SDRAM, sin perifericos-- se queda como estaba.
  //
  // Existe porque la version de monitor dejo de servir para identificar la
  // placa. Al renumerarla por JUEGO DE COMANDOS, la 6 y la 10 contestan lo
  // mismo, asi que sin esto `--version sdram` daria por buena una 6 flasheada
  // y se mediria el hardware equivocado, que es exactamente el fallo que
  // SYS_ID existe para cerrar. Ver docs/mapa-de-memoria.md §6.5.
  wire sysid_selected = adapter_monitor_address[31:4] == 28'h800_00f0;
  wire [31:0] sysid_word;
  sysid #(
      .FOLDER(8'd10),
      .CONTRACT(32'd1),
      // A esta CPU le faltan MUL y DIV, y eso no se detecta de ninguna otra
      // forma en ejecucion: es justo el caso que ISA_PROFILE existe para
      // declarar.
      .ISA_PROFILE(32'h0000_0000)
  ) sysid_i (
      .word(adapter_monitor_address[3:2]),
      .read_data(sysid_word)
  );

  reg [7:0] registered_mem_read_data;
  reg [31:0] registered_mem_read_word;
  reg registered_mem_ready, registered_mem_error;
  always @(posedge clk) begin
    if (reset) begin
      adapter_monitor_address <= 32'h0000_0000;
      adapter_monitor_write_data <= 8'h00;
      adapter_monitor_write_word <= 32'h0000_0000;
      adapter_monitor_write_enable <= 1'b0;
      adapter_monitor_write_word_enable <= 1'b0;
      adapter_monitor_read_enable <= 1'b0;
      registered_mem_read_data <= 8'h00;
      registered_mem_read_word <= 32'h0000_0000;
      registered_mem_ready <= 1'b0;
      registered_mem_error <= 1'b0;
    end else begin
      adapter_monitor_address <= mem_address;
      adapter_monitor_write_data <= mem_write_data;
      adapter_monitor_write_word <= mem_write_word;
      adapter_monitor_write_enable <= mem_write_enable;
      adapter_monitor_write_word_enable <= mem_write_word_enable;
      adapter_monitor_read_enable <= mem_read_enable;
      // El bloque de identificacion contesta en lugar de la memoria. Se elige
      // con la direccion YA REGISTRADA, que es la que el adaptador esta
      // atendiendo, para que la respuesta llegue en el mismo ciclo que
      // llegaria la suya.
      registered_mem_read_data <= sysid_selected
          ? sysid_word[8*adapter_monitor_address[1:0] +: 8]
          : adapter_monitor_read_data;
      registered_mem_read_word <= sysid_selected ? sysid_word
                                                 : adapter_monitor_read_word;
      registered_mem_ready <= sysid_selected
          ? (adapter_monitor_read_enable || adapter_monitor_write_enable)
          : adapter_monitor_ready;
      registered_mem_error <= sysid_selected ? adapter_monitor_write_enable : adapter_monitor_error;
    end
  end
  assign mem_read_data = registered_mem_read_data;
  assign mem_read_word = registered_mem_read_word;
  assign mem_ready = registered_mem_ready;
  assign mem_error = registered_mem_error;

  wire cpu_imem_valid, cpu_imem_ready;
  wire [31:0] cpu_imem_address, cpu_imem_read_data;
  wire cpu_dmem_valid, cpu_dmem_ready, cpu_dmem_error;
  wire [31:0] cpu_dmem_address, cpu_dmem_write_data, cpu_dmem_read_data;
  wire [3:0] cpu_dmem_write_enable;
  cpu cpu_i(
      .clk(clk), .reset(reset || cpu_reset_request),
      .run_request(cpu_run_request), .halt_request(cpu_halt_request),
      .step_request(cpu_step_request), .halted(cpu_halted), .error(cpu_error),
      .error_code(cpu_error_code), .instruction_retired(cpu_instruction_retired),
      .imem_valid(cpu_imem_valid), .imem_address(cpu_imem_address),
      .imem_read_data(cpu_imem_read_data), .imem_ready(cpu_imem_ready),
      .dmem_valid(cpu_dmem_valid), .dmem_address(cpu_dmem_address),
      .dmem_write_data(cpu_dmem_write_data),
      .dmem_write_enable(cpu_dmem_write_enable),
      .dmem_read_data(cpu_dmem_read_data), .dmem_ready(cpu_dmem_ready),
      .dmem_error(cpu_dmem_error),
      .debug_register_address(cpu_debug_register_address),
      .debug_register_data(cpu_debug_register_data), .debug_pc(cpu_pc));

  wire req_valid, req_write, req_ready, sdram_done, init_done, sdram_busy;
  wire [23:0] req_addr;
  wire [15:0] req_wdata, sdram_rdata;
  wire [1:0] req_wmask;
  sdram_system_adapter adapter_i(
      .clk(clk), .reset(reset), .init_done(init_done),
      .monitor_address(adapter_monitor_address),
      .monitor_write_data(adapter_monitor_write_data),
      // El acceso al bloque de identificacion no llega a la SDRAM: alli
      // 0x80000f00 esta fuera del mapa y levantaria `error`.
      .monitor_write_enable(adapter_monitor_write_enable && !sysid_selected),
      .monitor_write_word(adapter_monitor_write_word),
      .monitor_write_word_enable(adapter_monitor_write_word_enable && !sysid_selected),
      .monitor_read_enable(adapter_monitor_read_enable && !sysid_selected),
      .monitor_read_data(adapter_monitor_read_data),
      .monitor_read_word(adapter_monitor_read_word),
      .monitor_ready(adapter_monitor_ready),
      .monitor_error(adapter_monitor_error), .cpu_halted(cpu_halted),
      .cpu_imem_valid(cpu_imem_valid), .cpu_imem_address(cpu_imem_address),
      .cpu_imem_read_data(cpu_imem_read_data), .cpu_imem_ready(cpu_imem_ready),
      .cpu_dmem_valid(cpu_dmem_valid), .cpu_dmem_address(cpu_dmem_address),
      .cpu_dmem_write_data(cpu_dmem_write_data),
      .cpu_dmem_write_enable(cpu_dmem_write_enable),
      .cpu_dmem_read_data(cpu_dmem_read_data), .cpu_dmem_ready(cpu_dmem_ready),
      .cpu_dmem_error(cpu_dmem_error), .req_valid(req_valid),
      .req_write(req_write), .req_addr(req_addr), .req_wdata(req_wdata),
      .req_wmask(req_wmask), .req_ready(req_ready), .done(sdram_done),
      .rdata(sdram_rdata));

  sdram_controller #(.CLK_FREQ_HZ(CLK_FREQ_HZ)) controller_i(
      .clk(clk), .reset(reset), .req_valid(req_valid), .req_write(req_write),
      .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
      .req_ready(req_ready), .done(sdram_done), .rdata(sdram_rdata),
      .init_done(init_done), .busy(sdram_busy), .sdram_clk(sdram_clk),
      .sdram_cke(sdram_cke), .sdram_csn(sdram_csn), .sdram_rasn(sdram_rasn),
      .sdram_casn(sdram_casn), .sdram_wen(sdram_wen), .sdram_a(sdram_a),
      .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm), .sdram_d(sdram_d));

  assign led = {cpu_error, cpu_halted, init_done, sdram_busy,
                monitor_busy, last_command[2:0]};
endmodule

`default_nettype wire

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
  localparam integer CLK_FREQ_HZ = 120_000_000;
  localparam integer UART_CLOCKS_PER_BIT = 40;
  localparam integer UART_MAX_BAUD = 3_000_000;
  localparam integer UART_DIVISOR = UART_CLOCKS_PER_BIT;

  wire clk, pll_locked;
  pll_120 pll_i(.clkin(clk_25mhz), .clkout0(clk), .locked(pll_locked));

  reg [7:0] reset_count = 8'hff;
  reg reset = 1'b1;
  always @(posedge clk) begin
    if (!pll_locked || !btn_pwr_n) begin
      reset_count <= 8'hff;
      reset <= 1'b1;
    end else if (reset_count != 0) begin
      reset_count <= reset_count - 1'b1;
      reset <= 1'b1;
    end else reset <= 1'b0;
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
  wire mem_write_enable, mem_read_enable, mem_ready, mem_error, monitor_busy;
  wire cpu_run_request, cpu_halt_request, cpu_step_request, cpu_reset_request;
  wire cpu_halted, cpu_error, cpu_instruction_retired;
  wire [7:0] cpu_error_code;
  wire [4:0] cpu_debug_register_address;
  wire [31:0] cpu_debug_register_data, cpu_pc;

  monitor monitor_i(
      .clk(clk), .reset(reset), .rx_data(monitor_rx_data),
      .rx_strobe(monitor_rx_strobe),
      .tx_data(uart_tx_data), .tx_strobe(uart_tx_strobe), .tx_ready(uart_tx_ready),
      .mem_address(mem_address), .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable), .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data), .mem_ready(mem_ready), .mem_error(mem_error),
      .cpu_run_request(cpu_run_request), .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request), .cpu_reset_request(cpu_reset_request),
      .cpu_halted(cpu_halted), .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code), .cpu_pc(cpu_pc),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(cpu_debug_register_data),
      .last_command(last_command), .busy(monitor_busy));

  // Register both directions of the monitor memory port. Besides making the
  // interface timing-independent, this prevents the monitor FSM, arbitration
  // and response handling from becoming one long combinational path.
  reg [31:0] adapter_monitor_address;
  reg [7:0] adapter_monitor_write_data;
  reg adapter_monitor_write_enable, adapter_monitor_read_enable;
  wire [7:0] adapter_monitor_read_data;
  wire adapter_monitor_ready, adapter_monitor_error;
  reg [7:0] registered_mem_read_data;
  reg registered_mem_ready, registered_mem_error;
  always @(posedge clk) begin
    if (reset) begin
      adapter_monitor_address <= 32'h0000_0000;
      adapter_monitor_write_data <= 8'h00;
      adapter_monitor_write_enable <= 1'b0;
      adapter_monitor_read_enable <= 1'b0;
      registered_mem_read_data <= 8'h00;
      registered_mem_ready <= 1'b0;
      registered_mem_error <= 1'b0;
    end else begin
      adapter_monitor_address <= mem_address;
      adapter_monitor_write_data <= mem_write_data;
      adapter_monitor_write_enable <= mem_write_enable;
      adapter_monitor_read_enable <= mem_read_enable;
      registered_mem_read_data <= adapter_monitor_read_data;
      registered_mem_ready <= adapter_monitor_ready;
      registered_mem_error <= adapter_monitor_error;
    end
  end
  assign mem_read_data = registered_mem_read_data;
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
      .monitor_write_enable(adapter_monitor_write_enable),
      .monitor_read_enable(adapter_monitor_read_enable),
      .monitor_read_data(adapter_monitor_read_data),
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

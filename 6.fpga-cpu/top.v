`default_nettype none

module top (
    input clk_25mhz,
    output [7:0] led,
    output wifi_gpio0,
    input ftdi_txd,
    output ftdi_rxd
);

  localparam UART_DIVISOR = 40;

  assign wifi_gpio0 = 1'b1;

  // Clock and reset
  wire clk;
  wire locked;
  wire reset;

  assign reset = ~locked;

  pll_120 pll_120_i (
      .clkin  (clk_25mhz),
      .clkout0(clk),
      .locked (locked)
  );

  // UART interface: 120 MHz / 40 = 3 Mbaud
  wire [7:0] uart_rx_data;
  wire uart_rx_strobe;
  wire [7:0] uart_tx_data;
  wire uart_tx_strobe;
  wire uart_tx_ready;

  uart #(
      .DIVISOR(UART_DIVISOR)
  ) uart_i (
      .clk(clk),
      .reset(reset),
      .serial_txd(ftdi_rxd),
      .serial_rxd(ftdi_txd),
      .rxd(uart_rx_data),
      .rxd_strobe(uart_rx_strobe),
      .txd(uart_tx_data),
      .txd_strobe(uart_tx_strobe),
      .txd_ready(uart_tx_ready)
  );

  // Command monitor
  wire [7:0] last_command;
  wire monitor_busy;
  wire [31:0] mem_address;
  wire [7:0] mem_write_data;
  wire mem_write_enable;
  wire mem_read_enable;
  wire [7:0] mem_read_data;
  wire mem_ready;
  wire mem_error;

  wire cpu_run_request;
  wire cpu_halt_request;
  wire cpu_step_request;
  wire cpu_halted;
  wire cpu_error;
  wire [7:0] cpu_error_code;
  wire cpu_instruction_retired;
  wire [4:0] cpu_debug_register_address;
  wire [31:0] cpu_debug_register_data;
  wire [31:0] cpu_pc;

  wire cpu_imem_valid;
  wire [31:0] cpu_imem_address;
  wire [31:0] cpu_imem_read_data;
  wire cpu_imem_ready;

  wire cpu_dmem_valid;
  wire [31:0] cpu_dmem_address;
  wire [31:0] cpu_dmem_write_data;
  wire [3:0] cpu_dmem_write_enable;
  wire [31:0] cpu_dmem_read_data;
  wire cpu_dmem_ready;
  wire cpu_dmem_error;

  monitor monitor_i (
      .clk(clk),
      .reset(reset),
      .rx_data(uart_rx_data),
      .rx_strobe(uart_rx_strobe),
      .tx_data(uart_tx_data),
      .tx_strobe(uart_tx_strobe),
      .tx_ready(uart_tx_ready),
      .mem_address(mem_address),
      .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable),
      .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data),
      .mem_ready(mem_ready),
      .mem_error(mem_error),
      .cpu_run_request(cpu_run_request),
      .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request),
      .cpu_halted(cpu_halted),
      .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code),
      .cpu_pc(cpu_pc),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(cpu_debug_register_data),
      .last_command(last_command),
      .busy(monitor_busy)
  );

  cpu cpu_i (
      .clk(clk),
      .reset(reset),
      .run_request(cpu_run_request),
      .halt_request(cpu_halt_request),
      .step_request(cpu_step_request),
      .halted(cpu_halted),
      .error(cpu_error),
      .error_code(cpu_error_code),
      .instruction_retired(cpu_instruction_retired),
      .imem_valid(cpu_imem_valid),
      .imem_address(cpu_imem_address),
      .imem_read_data(cpu_imem_read_data),
      .imem_ready(cpu_imem_ready),
      .dmem_valid(cpu_dmem_valid),
      .dmem_address(cpu_dmem_address),
      .dmem_write_data(cpu_dmem_write_data),
      .dmem_write_enable(cpu_dmem_write_enable),
      .dmem_read_data(cpu_dmem_read_data),
      .dmem_ready(cpu_dmem_ready),
      .dmem_error(cpu_dmem_error),
      .debug_register_address(cpu_debug_register_address),
      .debug_register_data(cpu_debug_register_data),
      .debug_pc(cpu_pc)
  );

  // Shared Harvard map: monitor when halted, CPU while running.
  memory_map memory_map_i (
      .clk(clk),
      .reset(reset),
      .address(mem_address),
      .write_data(mem_write_data),
      .write_enable(mem_write_enable),
      .read_enable(mem_read_enable),
      .read_data(mem_read_data),
      .ready(mem_ready),
      .error(mem_error),
      .cpu_halted(cpu_halted),
      .cpu_imem_valid(cpu_imem_valid),
      .cpu_imem_address(cpu_imem_address),
      .cpu_imem_read_data(cpu_imem_read_data),
      .cpu_imem_ready(cpu_imem_ready),
      .cpu_dmem_valid(cpu_dmem_valid),
      .cpu_dmem_address(cpu_dmem_address),
      .cpu_dmem_write_data(cpu_dmem_write_data),
      .cpu_dmem_write_enable(cpu_dmem_write_enable),
      .cpu_dmem_read_data(cpu_dmem_read_data),
      .cpu_dmem_ready(cpu_dmem_ready),
      .cpu_dmem_error(cpu_dmem_error)
  );

  // Display the last command. LED 7 lights while a response is pending.
  assign led = {monitor_busy, cpu_error, cpu_halted, last_command[4:0]};
endmodule

`default_nettype wire

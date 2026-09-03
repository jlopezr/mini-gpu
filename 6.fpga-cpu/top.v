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
      .last_command(last_command),
      .busy(monitor_busy)
  );

  // Temporary Harvard map: separate 16 KiB program and data memories.
  memory_map memory_map_i (
      .clk(clk),
      .reset(reset),
      .address(mem_address),
      .write_data(mem_write_data),
      .write_enable(mem_write_enable),
      .read_enable(mem_read_enable),
      .read_data(mem_read_data),
      .ready(mem_ready),
      .error(mem_error)
  );

  // Display the last command. LED 7 lights while a response is pending.
  assign led = {monitor_busy, last_command[6:0]};
endmodule

`default_nettype wire

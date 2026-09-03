/*
 * Hello world on the ulx3s FTDI serial port at 3000000 baud.
 */
`default_nettype none

module top (
    input clk_25mhz,
    output [7:0] led,
    output wifi_gpio0,
    input ftdi_txd,  // from the ftdi chip
    output ftdi_rxd  // to the ftdi chip
);

  localparam UART_DIVISOR = 40;

  // GPIO0 must be high to prevent the ESP32 from rebooting the board.
  assign wifi_gpio0 = 1'b1;

  reg [7:0] led_reg;
  assign led = led_reg;

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
  wire uart_txd_ready;
  wire uart_rxd_strobe;
  wire [7:0] uart_rxd;

  reg [7:0] uart_txd;
  reg uart_txd_strobe;
  reg [7:0] rx_pending_data;
  reg rx_pending;

  uart #(
      .DIVISOR(UART_DIVISOR)
  ) uart_i (
      .clk(clk),
      .reset(reset),
      // Physical interface
      .serial_txd(ftdi_rxd),  // fpga --> ftdi
      .serial_rxd(ftdi_txd),  // fpga <-- ftdi
      // Logical interface
      .txd(uart_txd),
      .txd_ready(uart_txd_ready),
      .txd_strobe(uart_txd_strobe),
      .rxd(uart_rxd),
      .rxd_strobe(uart_rxd_strobe)
  );

  // Demo logic
  reg [31:0] counter;

  function [7:0] ascii_hex;
    input [3:0] value;
    begin
      ascii_hex = value < 10 ? "0" + value : "a" + value - 10;
    end
  endfunction

  always @(posedge clk) begin
    uart_txd_strobe <= 0;
    counter <= counter + 1;

    if (reset) begin
      counter         <= 0;
      led_reg         <= 0;
      uart_txd        <= 0;
      uart_txd_strobe <= 0;
      rx_pending_data <= 0;
      rx_pending      <= 0;
    end else begin
      if (uart_rxd_strobe) begin
        led_reg <= uart_rxd;
      end

      if (rx_pending && uart_txd_ready) begin
        // Send the queued byte. If another byte arrives now, queue the new one.
        uart_txd <= rx_pending_data;
        uart_txd_strobe <= 1;
        rx_pending <= uart_rxd_strobe;
        if (uart_rxd_strobe) begin
          rx_pending_data <= uart_rxd;
        end
      end else if (uart_rxd_strobe && uart_txd_ready) begin
        // Echo a received byte immediately when the transmitter is idle.
        uart_txd <= uart_rxd;
        uart_txd_strobe <= 1;
      end else if (uart_rxd_strobe) begin
        // Keep one byte pending while the transmitter is busy.
        rx_pending_data <= uart_rxd;
        rx_pending <= 1;
      end else if (counter[26:0] == 0 && uart_txd_ready) begin
        // Periodically print an increasing hexadecimal digit.
        led_reg <= counter[31:24];
        uart_txd <= ascii_hex(counter[30:27]);
        uart_txd_strobe <= 1;
      end
    end
  end
endmodule

`default_nettype wire

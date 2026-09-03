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
  // 25 MHz / 40 = 625 kbaud. Keeping all logic in one clock domain makes
  // this bring-up design deliberately simple.
  localparam UART_DIVISOR = 40;
  reg [7:0] reset_count = 8'hff;
  always @(posedge clk_25mhz) begin
    if (!btn_pwr_n) reset_count <= 8'hff;
    else if (reset_count != 0) reset_count <= reset_count - 1'b1;
  end
  wire reset = reset_count != 0;
  assign wifi_gpio0 = 1'b1;

  wire [7:0] uart_rx_data, uart_tx_data;
  wire uart_rx_strobe, uart_tx_strobe, uart_tx_ready;
  uart #(.DIVISOR(UART_DIVISOR)) uart_i (
      .clk(clk_25mhz), .reset(reset), .serial_rxd(ftdi_txd), .serial_txd(ftdi_rxd),
      .rxd(uart_rx_data), .rxd_strobe(uart_rx_strobe),
      .txd(uart_tx_data), .txd_strobe(uart_tx_strobe), .txd_ready(uart_tx_ready)
  );

  wire [31:0] mem_address;
  wire [7:0] mem_write_data, mem_read_data, last_command;
  wire mem_write_enable, mem_read_enable, mem_ready, mem_error, monitor_busy;
  monitor monitor_i (
      .clk(clk_25mhz), .reset(reset), .rx_data(uart_rx_data), .rx_strobe(uart_rx_strobe),
      .tx_data(uart_tx_data), .tx_strobe(uart_tx_strobe), .tx_ready(uart_tx_ready),
      .mem_address(mem_address), .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable), .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data), .mem_ready(mem_ready), .mem_error(mem_error),
      .last_command(last_command), .busy(monitor_busy)
  );

  wire req_valid, req_write, req_ready, sdram_done, init_done, sdram_busy;
  wire [23:0] req_addr;
  wire [15:0] req_wdata, sdram_rdata;
  wire [1:0] req_wmask;
  sdram_byte_adapter adapter_i (
      .clk(clk_25mhz), .reset(reset), .init_done(init_done),
      .address(mem_address), .write_data(mem_write_data),
      .write_enable(mem_write_enable), .read_enable(mem_read_enable),
      .read_data(mem_read_data), .ready(mem_ready), .error(mem_error),
      .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
      .req_wdata(req_wdata), .req_wmask(req_wmask), .req_ready(req_ready),
      .done(sdram_done), .rdata(sdram_rdata)
  );
  sdram_controller controller_i (
      .clk(clk_25mhz), .reset(reset), .req_valid(req_valid), .req_write(req_write),
      .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
      .req_ready(req_ready), .done(sdram_done), .rdata(sdram_rdata),
      .init_done(init_done), .busy(sdram_busy), .sdram_clk(sdram_clk),
      .sdram_cke(sdram_cke), .sdram_csn(sdram_csn), .sdram_rasn(sdram_rasn),
      .sdram_casn(sdram_casn), .sdram_wen(sdram_wen), .sdram_a(sdram_a),
      .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm), .sdram_d(sdram_d)
  );

  assign led = {last_command[3:0], mem_error, sdram_busy, monitor_busy, init_done};
endmodule

`default_nettype wire

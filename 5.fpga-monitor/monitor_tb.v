`timescale 1ns / 1ps
`default_nettype none

module monitor_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg [7:0] rx_data = 8'h00;
  reg rx_strobe = 1'b0;
  reg tx_ready = 1'b1;

  wire [7:0] tx_data;
  wire tx_strobe;
  wire [7:0] last_command;
  wire busy;

  reg [7:0] received[0:7];
  integer received_count = 0;
  integer busy_cycles = 0;

  always #5 clk = ~clk;

  monitor dut (
      .clk(clk),
      .reset(reset),
      .rx_data(rx_data),
      .rx_strobe(rx_strobe),
      .tx_data(tx_data),
      .tx_strobe(tx_strobe),
      .tx_ready(tx_ready),
      .last_command(last_command),
      .busy(busy)
  );

  // Minimal model of the uart_tx ready/strobe handshake.
  always @(posedge clk) begin
    if (reset) begin
      tx_ready <= 1'b1;
      busy_cycles <= 0;
    end else if (tx_strobe && tx_ready) begin
      received[received_count] <= tx_data;
      received_count <= received_count + 1;
      tx_ready <= 1'b0;
      busy_cycles <= 2;
    end else if (busy_cycles > 0) begin
      busy_cycles <= busy_cycles - 1;
      if (busy_cycles == 1) begin
        tx_ready <= 1'b1;
      end
    end
  end

  task send_command;
    input [7:0] command;
    begin
      @(negedge clk);
      rx_data = command;
      rx_strobe = 1'b1;
      @(negedge clk);
      rx_strobe = 1'b0;
    end
  endtask

  initial begin
    repeat (2) @(negedge clk);
    reset = 1'b0;

    send_command(8'h01);
    wait (received_count == 1);
    if (received[0] !== 8'h81) $fatal(1, "PING response mismatch");

    wait (!busy && tx_ready);
    send_command(8'h02);
    wait (received_count == 4);
    if (received[1] !== 8'h82) $fatal(1, "VERSION response mismatch");
    if (received[2] !== 8'h01) $fatal(1, "VERSION major mismatch");
    if (received[3] !== 8'h00) $fatal(1, "VERSION minor mismatch");

    wait (!busy && tx_ready);
    send_command(8'h55);
    wait (received_count == 5);
    if (received[4] !== 8'hff) $fatal(1, "ERROR response mismatch");

    $display("PASS: monitor protocol responses are correct");
    $finish;
  end
endmodule

`default_nettype wire

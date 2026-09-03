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
  wire [31:0] mem_address;
  wire [7:0] mem_write_data;
  wire mem_write_enable;
  wire mem_read_enable;
  wire [7:0] mem_read_data;
  wire mem_ready;
  wire mem_error;

  reg [7:0] received[0:31];
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
      .mem_address(mem_address),
      .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable),
      .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data),
      .mem_ready(mem_ready),
      .mem_error(mem_error),
      .last_command(last_command),
      .busy(busy)
  );

  memory memory_i (
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
      repeat (4) @(negedge clk);
    end
  endtask

  initial begin
    $dumpvars(0, monitor_tb);

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

    wait (!busy && tx_ready);
    send_command(8'h10);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h25);
    send_command(8'hab);
    wait (received_count == 6);
    if (received[5] !== 8'h90) $fatal(1, "WRITE_BYTE response mismatch");

    wait (!busy && tx_ready);
    send_command(8'h11);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h25);
    wait (received_count == 8);
    if (received[6] !== 8'h91) $fatal(1, "READ_BYTE response mismatch");
    if (received[7] !== 8'hab) $fatal(1, "READ_BYTE data mismatch");

    wait (!busy && tx_ready);
    send_command(8'h20);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h01);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h04);
    send_command(8'hde);
    send_command(8'had);
    send_command(8'hbe);
    send_command(8'hef);
    wait (received_count == 9);
    if (received[8] !== 8'ha0) $fatal(1, "WRITE_BLOCK response mismatch");

    wait (!busy && tx_ready);
    send_command(8'h21);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h01);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h04);
    wait (received_count == 14);
    if (received[9] !== 8'ha1) $fatal(1, "READ_BLOCK response mismatch");
    if (received[10] !== 8'hde) $fatal(1, "READ_BLOCK byte 0 mismatch");
    if (received[11] !== 8'had) $fatal(1, "READ_BLOCK byte 1 mismatch");
    if (received[12] !== 8'hbe) $fatal(1, "READ_BLOCK byte 2 mismatch");
    if (received[13] !== 8'hef) $fatal(1, "READ_BLOCK byte 3 mismatch");

    // The protocol transports the full 32-bit address. The temporary memory
    // currently rejects the future framebuffer region at 0x00100000.
    wait (!busy && tx_ready);
    send_command(8'h11);
    send_command(8'h00);
    send_command(8'h10);
    send_command(8'h00);
    send_command(8'h00);
    wait (received_count == 15);
    if (received[14] !== 8'hff) $fatal(1, "32-bit invalid address mismatch");

    $display("PASS: monitor protocol responses are correct");
    $finish;
  end
endmodule

`default_nettype wire

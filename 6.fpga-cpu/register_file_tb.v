`timescale 1ns / 1ps
`default_nettype none

module register_file_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg [4:0] read_address_a = 5'd0;
  reg [4:0] read_address_b = 5'd0;
  reg write_enable = 1'b0;
  reg [4:0] write_address = 5'd0;
  reg [31:0] write_data = 32'h0000_0000;
  reg [4:0] debug_address = 5'd0;

  wire [31:0] read_data_a;
  wire [31:0] read_data_b;
  wire [31:0] debug_data;

  integer index;

  always #5 clk = ~clk;

  register_file dut (
      .clk(clk),
      .reset(reset),
      .read_address_a(read_address_a),
      .read_data_a(read_data_a),
      .read_address_b(read_address_b),
      .read_data_b(read_data_b),
      .write_enable(write_enable),
      .write_address(write_address),
      .write_data(write_data),
      .debug_address(debug_address),
      .debug_data(debug_data)
  );

  task write_register;
    input [4:0] address;
    input [31:0] data;
    begin
      @(negedge clk);
      write_address = address;
      write_data = data;
      write_enable = 1'b1;
      @(negedge clk);
      write_enable = 1'b0;
    end
  endtask

  task expect_debug_register;
    input [4:0] address;
    input [31:0] expected;
    begin
      @(negedge clk);
      debug_address = address;
      repeat (2) @(posedge clk);
      #1;

      if (debug_data !== expected) begin
        $fatal(1, "Debug R%0d mismatch", address);
      end
    end
  endtask

  initial begin
    $dumpvars(0, register_file_tb);

    repeat (2) @(negedge clk);
    reset = 1'b0;

    // Reset must clear every register, including R0.
    for (index = 0; index < 32; index = index + 1) begin
      expect_debug_register(index, 32'h0000_0000);
    end

    // The two CPU read ports operate independently and simultaneously.
    write_register(5'd1, 32'h1234_5678);
    write_register(5'd2, 32'hdead_beef);
    read_address_a = 5'd1;
    read_address_b = 5'd2;
    #1;
    if (read_data_a !== 32'h1234_5678) $fatal(1, "Read port A mismatch");
    if (read_data_b !== 32'hdead_beef) $fatal(1, "Read port B mismatch");

    // R0 is writable in MiniISA v0.1.
    write_register(5'd0, 32'hffff_ffff);
    read_address_a = 5'd0;
    #1;
    if (read_data_a !== 32'hffff_ffff) $fatal(1, "R0 is not writable");

    // The debug port can inspect a register independently of the CPU ports.
    expect_debug_register(5'd2, 32'hdead_beef);

    // Data and address changes must have no effect while writes are disabled.
    @(negedge clk);
    write_enable = 1'b0;
    write_address = 5'd1;
    write_data = 32'haaaa_5555;
    @(negedge clk);
    expect_debug_register(5'd1, 32'h1234_5678);

    $display("PASS: register file behavior is correct");
    $finish;
  end
endmodule

`default_nettype wire

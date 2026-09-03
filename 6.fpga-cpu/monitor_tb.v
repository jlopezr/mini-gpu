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
  wire cpu_run_request;
  wire cpu_halt_request;
  wire cpu_step_request;
  reg cpu_halted = 1'b1;
  reg cpu_error = 1'b0;
  reg [7:0] cpu_error_code = 8'h00;
  reg [31:0] cpu_pc = 32'h1234_5678;
  wire [4:0] cpu_debug_register_address;
  reg [31:0] cpu_debug_register_data = 32'hdead_beef;

  reg [7:0] received[0:63];
  integer received_count = 0;
  integer busy_cycles = 0;
  reg run_request_seen = 1'b0;
  reg halt_request_seen = 1'b0;
  reg step_request_seen = 1'b0;

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
      .busy(busy)
  );

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
      .cpu_imem_valid(1'b0),
      .cpu_imem_address(32'h0000_0000),
      .cpu_imem_read_data(),
      .cpu_imem_ready(),
      .cpu_dmem_valid(1'b0),
      .cpu_dmem_address(32'h0000_0000),
      .cpu_dmem_write_data(32'h0000_0000),
      .cpu_dmem_write_enable(4'b0000),
      .cpu_dmem_read_data(),
      .cpu_dmem_ready(),
      .cpu_dmem_error()
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

    if (cpu_run_request) run_request_seen <= 1'b1;
    if (cpu_halt_request) halt_request_seen <= 1'b1;
    if (cpu_step_request) step_request_seen <= 1'b1;
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
    if (received[3] !== 8'h01) $fatal(1, "VERSION minor mismatch");

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

    // Write and read the physically separate data memory at 0x00100000.
    wait (!busy && tx_ready);
    send_command(8'h10);
    send_command(8'h00);
    send_command(8'h10);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h5a);
    wait (received_count == 15);
    if (received[14] !== 8'h90) $fatal(1, "Data-memory WRITE_BYTE mismatch");

    wait (!busy && tx_ready);
    send_command(8'h11);
    send_command(8'h00);
    send_command(8'h10);
    send_command(8'h00);
    send_command(8'h00);
    wait (received_count == 17);
    if (received[15] !== 8'h91) $fatal(1, "Data-memory READ_BYTE mismatch");
    if (received[16] !== 8'h5a) $fatal(1, "Data-memory value mismatch");

    // An address in the unmapped gap must still fail.
    wait (!busy && tx_ready);
    send_command(8'h11);
    send_command(8'h00);
    send_command(8'h01);
    send_command(8'h00);
    send_command(8'h00);
    wait (received_count == 18);
    if (received[17] !== 8'hff) $fatal(1, "Unmapped address mismatch");

    wait (!busy && tx_ready);
    send_command(8'h33);
    wait (received_count == 25);
    if (received[18] !== 8'hb3) $fatal(1, "STATUS response mismatch");
    if (received[19] !== 8'h01) $fatal(1, "STATUS flags mismatch");
    if (received[20] !== 8'h00) $fatal(1, "STATUS error code mismatch");
    if ({received[21], received[22], received[23], received[24]} !== 32'h1234_5678)
      $fatal(1, "STATUS PC mismatch");

    wait (!busy && tx_ready);
    send_command(8'h34);
    send_command(8'h07);
    wait (received_count == 30);
    if (cpu_debug_register_address !== 5'd7) $fatal(1, "READ_REG address mismatch");
    if (received[25] !== 8'hb4) $fatal(1, "READ_REG response mismatch");
    if ({received[26], received[27], received[28], received[29]} !== 32'hdead_beef)
      $fatal(1, "READ_REG data mismatch");

    wait (!busy && tx_ready);
    send_command(8'h30);
    wait (received_count == 31);
    if (received[30] !== 8'hb0 || !run_request_seen) $fatal(1, "RUN mismatch");

    wait (!busy && tx_ready);
    send_command(8'h32);
    wait (received_count == 32);
    if (received[31] !== 8'hb2 || !step_request_seen) $fatal(1, "STEP mismatch");

    wait (!busy && tx_ready);
    send_command(8'h31);
    wait (received_count == 33);
    if (received[32] !== 8'hb1 || !halt_request_seen) $fatal(1, "HALT mismatch");

    // Memory commands are rejected while the CPU owns the memories.
    cpu_halted = 1'b0;
    wait (!busy && tx_ready);
    send_command(8'h11);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h00);
    send_command(8'h00);
    wait (received_count == 34);
    if (received[33] !== 8'hff) $fatal(1, "Running CPU memory access mismatch");

    $display("PASS: monitor protocol responses are correct");
    $finish;
  end
endmodule

`default_nettype wire

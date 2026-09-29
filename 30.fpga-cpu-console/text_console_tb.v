`timescale 1ns/1ps
`default_nettype none

module text_console_tb;
  reg clk_sys = 0, clk_pix = 0;
  always #5 clk_sys = ~clk_sys;
  always #20 clk_pix = ~clk_pix;

  reg reset_sys = 1, reset_pix = 1;
  reg select = 0, write = 0;
  reg [3:0] write_mask = 4'hf;
  reg [15:0] address = 0;
  reg [31:0] write_data = 0;
  wire [31:0] read_data;
  wire error;
  reg enable = 0;
  reg [11:0] sx = 0, sy = 0;
  wire [7:0] r, g, b;
  wire de, hs, vs;
  integer failures = 0;

  text_console dut(
      .clk_sys(clk_sys), .reset_sys(reset_sys), .select(select),
      .write(write), .write_mask(write_mask), .address(address),
      .write_data(write_data), .read_data(read_data), .error(error),
      .clk_pix(clk_pix), .reset_pix(reset_pix), .enable(enable),
      .sx(sx), .sy(sy), .r_in(8'h12), .g_in(8'h34), .b_in(8'h56),
      .de_in(1'b1), .hsync_in(1'b0), .vsync_in(1'b0),
      .r_out(r), .g_out(g), .b_out(b), .de_out(de),
      .hsync_out(hs), .vsync_out(vs));

  task mmio_write(input [15:0] addr, input [31:0] data);
    begin
      @(negedge clk_sys);
      address = addr; write_data = data; select = 1; write = 1;
      @(posedge clk_sys);
      #1;
      if (error) begin
        $display("FAIL: error inesperado en %04x=%08x", addr, data);
        failures = failures + 1;
      end
      @(negedge clk_sys);
      select = 0; write = 0;
    end
  endtask

  task settle_pixel;
    integer n;
    begin
      for (n = 0; n < 8; n = n + 1) @(posedge clk_pix);
      #1;
    end
  endtask

  initial begin
    repeat (3) @(posedge clk_sys);
    reset_sys = 0;
    repeat (2) @(posedge clk_pix);
    reset_pix = 0;

    // Paleta: 1 rojo, 2 azul. Glifo 65: solo el pixel izquierdo de fila 0.
    mmio_write(16'h1004, 32'h00ff0000);
    mmio_write(16'h1008, 32'h000000ff);
    mmio_write(16'h0084, 32'd65);
    mmio_write(16'h0080, 32'd1);
    mmio_write(16'h0088, 32'h00000080);
    mmio_write(16'h008c, 0);
    mmio_write(16'h0090, 0);
    mmio_write(16'h0094, 0);
    mmio_write(16'h6000, 32'h00002141); // BG=2, FG=1, 'A'

    enable = 1;
    sx = 0; sy = 0;
    settle_pixel();
    if ({r,g,b} !== 24'hff0000) begin
      $display("FAIL: foreground %02x%02x%02x", r, g, b);
      failures = failures + 1;
    end

    sx = 1;
    settle_pixel();
    if ({r,g,b} !== 24'h0000ff) begin
      $display("FAIL: background %02x%02x%02x", r, g, b);
      failures = failures + 1;
    end

    // Transparencia: BG=0 conserva exactamente el pixel inferior.
    mmio_write(16'h6000, 32'h00000141);
    sx = 1;
    settle_pixel();
    if ({r,g,b} !== 24'h123456) begin
      $display("FAIL: transparencia %02x%02x%02x", r, g, b);
      failures = failures + 1;
    end

    // Bits de celda reservados: error y ninguna escritura.
    @(negedge clk_sys);
    address = 16'h6000; write_data = 32'h00010000;
    select = 1; write = 1;
    @(posedge clk_sys); #1;
    if (!error) begin
      $display("FAIL: celda con bits reservados no dio error");
      failures = failures + 1;
    end
    select = 0; write = 0;

    if (failures == 0) $display("PASS: text_console");
    else $fatal(1, "FAIL: %0d errores", failures);
    $finish;
  end
endmodule

`default_nettype wire

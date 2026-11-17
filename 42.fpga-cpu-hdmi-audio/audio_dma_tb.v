`timescale 1ns/1ps
`default_nettype none

module audio_dma_tb;
  reg clk = 0, reset = 1, enabled = 0, wb_dirty = 0, req_ready = 1;
  reg [31:0] ring_base = 32'h1000, write_cursor = 0;
  reg [4:0] ring_log2_frames = 5'd4;
  wire req_valid, req_write, rsp_ready, fifo_wr_en;
  wire [31:0] req_addr, read_cursor, fifo_wdata;
  wire [127:0] req_wdata;
  wire [15:0] req_wmask;
  reg rsp_valid = 0, rsp_error = 0, fifo_full = 0;
  reg [127:0] rsp_rdata = 0;
  wire [31:0] errors;
  always #5 clk = ~clk;
  audio_dma dut(.clk(clk), .reset(reset), .enabled(enabled), .wb_dirty(wb_dirty),
    .ring_base(ring_base), .ring_log2_frames(ring_log2_frames), .write_cursor(write_cursor), .read_cursor(read_cursor),
    .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write), .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
    .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
    .fifo_wr_en(fifo_wr_en), .fifo_wdata(fifo_wdata), .fifo_full(fifo_full), .errors(errors));
  integer writes;
  always @(posedge clk) if (fifo_wr_en) begin
    if (fifo_wdata !== (32'h11110000 + writes)) $fatal(1, "frame order");
    writes = writes + 1;
  end
  initial begin
    writes = 0;
    repeat (3) @(posedge clk); reset = 0; enabled = 1;
    // Menos de cuatro frames: el lector no adelanta ni lanza SDRAM.
    write_cursor = 3; repeat (3) @(posedge clk);
    if (req_valid || read_cursor != 0) $fatal(1, "read premature");
    // Cuatro frames completos: una lectura alineada y cuatro writes FIFO.
    write_cursor = 4;
    wait(req_valid); if (req_addr != 32'h1000 || req_write) $fatal(1, "bad request");
    @(posedge clk); rsp_rdata = {32'h11110003,32'h11110002,32'h11110001,32'h11110000}; rsp_valid = 1;
    @(posedge clk); rsp_valid = 0;
    wait(writes == 4); if (read_cursor != 4) $fatal(1, "cursor");
    // wb_dirty impide iniciar una lectura nueva.
    write_cursor = 8; wb_dirty = 1; repeat (3) @(posedge clk);
    if (req_valid) $fatal(1, "wb_dirty");
    $display("PASS audio_dma"); $finish;
  end
endmodule
`default_nettype wire

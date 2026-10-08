`default_nettype none
`timescale 1ns/1ps
// Cuatro warps con barrera, divergencia y un STORE de offset negativo.
//
// Complementa a gpu_system_tb (hito 1), cuyo kernel no usa BAR, SSY ni offsets
// negativos. Comprueba lo que cambia al reescribir el planificador y la barrera
// de gpu_sm: round-robin entre warps, `same_group`, `generation` de un bit, y
// el sumador de direcciones por lane. Lleva su propia copia de ram_port (accede a `mem` por nombre jerarquico).
module gpu_barrier_tb;
    reg clk = 0, gclk = 0;
    always #6.25 clk = ~clk;
    always #20 gclk = ~gclk;
    reg reset = 1, greset = 1;

    reg         start = 0, wr = 0;
    reg  [31:0] addr = 0, wdata = 0;
    wire        done, err;
    wire [31:0] rdata;
    wire        h_valid, h_write, h_done, h_error;
    wire [31:0] h_addr, h_wdata, h_rdata;

    gpu_mmio_bridge bridge (
        .clk(clk), .reset(reset), .start(start), .write(wr), .address(addr),
        .write_data(wdata), .done(done), .read_data(rdata), .error(err),
        .gclk(gclk), .greset(greset), .h_valid(h_valid), .h_write(h_write),
        .h_addr(h_addr), .h_wdata(h_wdata), .h_done(h_done),
        .h_rdata(h_rdata), .h_error(h_error));

    wire         p0_req_valid, p0_req_ready, p0_req_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
    wire [31:0]  p0_req_addr;
    wire [127:0] p0_req_wdata, p0_rsp_rdata;
    wire [15:0]  p0_req_wmask;
    wire         p1_req_valid, p1_req_ready, p1_req_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
    wire [31:0]  p1_req_addr;
    wire [127:0] p1_req_wdata, p1_rsp_rdata;
    wire [15:0]  p1_req_wmask;
    wire         gpu_halted, gpu_error;

    gpu_system dut (
        .clk(gclk), .reset(greset), .init_done(1'b1),
        .h_valid(h_valid), .h_write(h_write), .h_addr(h_addr), .h_wdata(h_wdata),
        .h_done(h_done), .h_rdata(h_rdata), .h_error(h_error),
        .p0_req_valid(p0_req_valid), .p0_req_ready(p0_req_ready), .p0_req_write(p0_req_write),
        .p0_req_addr(p0_req_addr), .p0_req_wdata(p0_req_wdata), .p0_req_wmask(p0_req_wmask),
        .p0_rsp_valid(p0_rsp_valid), .p0_rsp_ready(p0_rsp_ready),
        .p0_rsp_rdata(p0_rsp_rdata), .p0_rsp_error(p0_rsp_error),
        .p1_req_valid(p1_req_valid), .p1_req_ready(p1_req_ready), .p1_req_write(p1_req_write),
        .p1_req_addr(p1_req_addr), .p1_req_wdata(p1_req_wdata), .p1_req_wmask(p1_req_wmask),
        .p1_rsp_valid(p1_rsp_valid), .p1_rsp_ready(p1_rsp_ready),
        .p1_rsp_rdata(p1_rsp_rdata), .p1_rsp_error(p1_rsp_error),
        .gpu_halted(gpu_halted), .gpu_error(gpu_error));

    localparam LINES = 1024;              // 16 KiB
    reg [127:0] mem [0:LINES-1];

    ram_port_bar #(.LAT(5)) ram0 (.clk(gclk), .reset(greset),
        .req_valid(p0_req_valid), .req_ready(p0_req_ready), .req_write(p0_req_write),
        .req_addr(p0_req_addr), .req_wdata(p0_req_wdata), .req_wmask(p0_req_wmask),
        .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
        .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));
    ram_port_bar #(.LAT(7)) ram1 (.clk(gclk), .reset(greset),
        .req_valid(p1_req_valid), .req_ready(p1_req_ready), .req_write(p1_req_write),
        .req_addr(p1_req_addr), .req_wdata(p1_req_wdata), .req_wmask(p1_req_wmask),
        .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
        .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error));

    reg         done_seen;
    reg  [31:0] got_data;
    reg         got_err;
    always @(posedge clk) if (done) done_seen <= 1'b1;

    task mmio;
        input         is_write;
        input  [31:0] a;
        input  [31:0] d;
        integer n;
        begin
            @(negedge clk);
            wr = is_write; addr = a; wdata = d; done_seen = 1'b0;
            @(negedge clk); start = 1'b1;
            @(negedge clk); start = 1'b0;
            n = 0;
            while (!done_seen && n < 400) begin @(negedge clk); n = n + 1; end
            if (!done_seen) begin
                $display("FALLO: MMIO %s %h sin respuesta", is_write ? "W" : "R", a);
                $fatal(1);
            end
            got_data = rdata; got_err = err;
        end
    endtask

    localparam [31:0] CORE = 32'h8200_0000, WARPS = 32'h8201_0000;
    localparam [31:0] ST_IDLE = 4, ST_ERROR = 8;

    function [31:0] word;
        input [31:0] byte_addr;
        begin word = mem[byte_addr / 16][((byte_addr / 4) % 4) * 32 +: 32]; end
    endfunction

    integer i, polls, bad;
    reg [31:0] status, want;
    reg [31:0] kernel_words [0:21];

    initial begin
        for (i = 0; i < LINES; i = i + 1) mem[i] = 128'd0;
        $readmemh("sim/kernel_bar.hex", kernel_words);
        for (i = 0; i < 22; i = i + 1)
            mem[i / 4][(i % 4) * 32 +: 32] = kernel_words[i];

        repeat (6) @(negedge gclk);
        reset = 0; greset = 0;
        repeat (400) @(negedge gclk);

        for (i = 0; i < 4; i = i + 1) begin
            mmio(1, WARPS + i * 16 + 32'h00, 32'h0);          // PC
            mmio(1, WARPS + i * 16 + 32'h04, 32'h0000_00ff);  // ACTIVE
        end
        mmio(1, CORE + 32'h18, 32'h1);                        // RUN

        polls = 0; status = 0;
        while (!(status & ST_IDLE) && polls < 4000) begin
            mmio(0, CORE + 32'h14, 0);
            status = got_data;
            polls = polls + 1;
        end
        $display("GPU paro tras %0d sondeos; STATUS=%h", polls, status);
        if (!(status & ST_IDLE) || (status & ST_ERROR)) begin
            $display("FALLO: la GPU no termino bien (STATUS=%h)", status);
            $fatal(1);
        end

        bad = 0;
        for (i = 0; i < 32; i = i + 1) begin
            if (word(32'h800 + 4 * i) !== i + 100) begin
                $display("FALLO: A[%0d] = %0d, esperaba %0d", i, word(32'h800 + 4 * i), i + 100); bad = bad + 1;
            end
            if (word(32'h900 + 4 * i) !== i) begin
                $display("FALLO: B[%0d] = %0d, esperaba %0d", i, word(32'h900 + 4 * i), i); bad = bad + 1;
            end
            want = (i < 24) ? i + 8 + 100 : 32'd0;
            if (word(32'hA00 + 4 * i) !== want) begin
                $display("FALLO: C[%0d] = %0d, esperaba %0d (barrera)", i, word(32'hA00 + 4 * i), want); bad = bad + 1;
            end
            want = (i < 16) ? i + 1 : i + 2;
            if (word(32'hB00 + 4 * i) !== want) begin
                $display("FALLO: D[%0d] = %0d, esperaba %0d (divergencia)", i, word(32'hB00 + 4 * i), want); bad = bad + 1;
            end
        end
        if (bad != 0) begin
            $display("GPU_BARRIER: %0d errores", bad);
            $fatal(1);
        end
        $display("GPU_BARRIER: OK");
        $finish;
    end
endmodule

// Memoria de 128 bits con latencia fija, como la de gpu_system_tb.v.
module ram_port_bar #(parameter LAT = 5) (
    input  wire         clk, reset,
    input  wire         req_valid,
    output wire         req_ready,
    input  wire         req_write,
    input  wire [31:0]  req_addr,
    input  wire [127:0] req_wdata,
    input  wire [15:0]  req_wmask,
    output wire         rsp_valid,
    input  wire         rsp_ready,
    output wire [127:0] rsp_rdata,
    output wire         rsp_error
);
    localparam DEPTH = 8;
    reg [127:0] q_data  [0:DEPTH-1];
    reg         q_err   [0:DEPTH-1];
    reg [15:0]  q_due   [0:DEPTH-1];
    reg [3:0]   head, count;
    reg [15:0]  now;
    reg [127:0] line;
    integer b;
    wire [3:0] tail = (head + count) % DEPTH;

    assign req_ready = (count < DEPTH - 1);
    assign rsp_valid = (count != 0) && (now >= q_due[head]);
    assign rsp_rdata = q_data[head];
    assign rsp_error = q_err[head];

    wire accept = req_valid && req_ready;
    wire pop = rsp_valid && rsp_ready;
    wire in_range = (req_addr[31:4] < gpu_barrier_tb.LINES);

    always @(posedge clk) begin
        if (reset) begin
            head <= 0; count <= 0; now <= 0;
        end else begin
            now <= now + 1;
            if (accept) begin
                if (in_range) begin
                    line = gpu_barrier_tb.mem[req_addr[31:4]];
                    q_data[tail] <= line;
                    q_err[tail] <= 1'b0;
                    if (req_write) begin
                        for (b = 0; b < 16; b = b + 1)
                            if (req_wmask[b]) line[b*8 +: 8] = req_wdata[b*8 +: 8];
                        gpu_barrier_tb.mem[req_addr[31:4]] = line;
                    end
                end else begin
                    q_data[tail] <= 128'd0;
                    q_err[tail] <= 1'b1;
                end
                q_due[tail] <= now + LAT;
            end
            if (pop) head <= (head + 1) % DEPTH;
            count <= count + (accept ? 1 : 0) - (pop ? 1 : 0);
        end
    end
endmodule
`default_nettype wire

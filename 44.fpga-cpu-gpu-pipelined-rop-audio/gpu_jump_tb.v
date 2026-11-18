`default_nettype none
`timescale 1ns/1ps
// Llamadas y saltos indirectos de la GPU: JAL, JALR y JR.
//
// Fase 1: cuatro warps ejecutan sim/kernel_jump.hex, donde todos los hilos van
// al mismo destino. Se comprueba la llamada y el retorno, JALR con
// desplazamiento, JALR con Rd = Ra (el enlace se escribe despues de leer el
// destino) y JR con los dos bits bajos del destino sucios.
//
// Fase 2: tras un RESET de la GPU, un warp ejecuta sim/kernel_jump_div.hex, donde
// cada lane calcula un destino distinto para un JR. El SM tiene que parar con
// ERROR_SIMT (0x06) y no elegir uno.
//
// Lleva su propia ram_port_jmp: accede a `mem` por nombre jerarquico.
module gpu_jump_tb;
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

    ram_port_jmp #(.LAT(5)) ram0 (.clk(gclk), .reset(greset),
        .req_valid(p0_req_valid), .req_ready(p0_req_ready), .req_write(p0_req_write),
        .req_addr(p0_req_addr), .req_wdata(p0_req_wdata), .req_wmask(p0_req_wmask),
        .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
        .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));
    ram_port_jmp #(.LAT(7)) ram1 (.clk(gclk), .reset(greset),
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

    localparam [31:0] CORE = 32'h8200_0000, WARPS = 32'h8201_0000, SIMT = 32'h8202_0000;
    localparam [31:0] ST_IDLE = 4, ST_ERROR = 8;
    localparam [31:0] DIV_BASE = 32'h400;
    localparam [7:0]  ERROR_SIMT = 8'h06;

    function [31:0] word;
        input [31:0] byte_addr;
        begin word = mem[byte_addr / 16][((byte_addr / 4) % 4) * 32 +: 32]; end
    endfunction

    reg [31:0] kernel_words [0:63];
    reg [31:0] div_words [0:31];
    integer i, polls, bad;
    reg [31:0] status, want;

    task run_and_wait;
        begin
            mmio(1, CORE + 32'h18, 32'h1);                        // RUN
            polls = 0; status = 0;
            while (!(status & (ST_IDLE | ST_ERROR)) && polls < 20000) begin
                mmio(0, CORE + 32'h14, 0);
                status = got_data;
                polls = polls + 1;
            end
        end
    endtask

    initial begin
        for (i = 0; i < LINES; i = i + 1) mem[i] = 128'd0;
        for (i = 0; i < 64; i = i + 1) kernel_words[i] = 32'd0;
        for (i = 0; i < 32; i = i + 1) div_words[i] = 32'd0;
        $readmemh("sim/kernel_jump.hex", kernel_words);
        $readmemh("sim/kernel_jump_div.hex", div_words);
        // `mem` es de 128 bits: cuatro palabras por linea.
        for (i = 0; i < 64; i = i + 1)
            mem[i / 4][(i % 4) * 32 +: 32] = kernel_words[i];
        for (i = 0; i < 32; i = i + 1)
            mem[(DIV_BASE / 4 + i) / 4][((DIV_BASE / 4 + i) % 4) * 32 +: 32] = div_words[i];

        repeat (6) @(negedge gclk);
        reset = 0; greset = 0;
        repeat (400) @(negedge gclk);

        // ---- Fase 1: todos de acuerdo ----
        for (i = 0; i < 4; i = i + 1) begin
            mmio(1, WARPS + i * 16 + 32'h00, 32'h0);          // PC
            mmio(1, WARPS + i * 16 + 32'h04, 32'h0000_00ff);  // ACTIVE
        end
        run_and_wait;
        $display("fase 1: la GPU paro tras %0d sondeos; STATUS=%h", polls, status);
        if (!(status & ST_IDLE) || (status & ST_ERROR)) begin
            $display("FALLO: la GPU no termino bien (STATUS=%h)", status);
            $fatal(1);
        end
        bad = 0;
        for (i = 0; i < 32; i = i + 1) begin
            if (word(32'hA00 + 4 * i) !== 32'd10) begin
                $display("FALLO: doble(5) del hilo %0d = %0d, esperaba 10", i, word(32'hA00 + 4 * i)); bad = bad + 1;
            end
            if (word(32'hB00 + 4 * i) !== 3 * i) begin
                $display("FALLO: triple(%0d) por JALR = %0d, esperaba %0d", i, word(32'hB00 + 4 * i), 3 * i); bad = bad + 1;
            end
            if (word(32'hC00 + 4 * i) !== 32'h30) begin
                $display("FALLO: enlace de JALR Rd=Ra del hilo %0d = %h, esperaba 30", i, word(32'hC00 + 4 * i)); bad = bad + 1;
            end
            if (word(32'hD00 + 4 * i) !== 32'd4) begin
                $display("FALLO: JR con destino sucio del hilo %0d dejo %0d, esperaba 4", i, word(32'hD00 + 4 * i)); bad = bad + 1;
            end
        end
        if (bad != 0) begin
            $display("GPU_JUMP: %0d errores", bad);
            $fatal(1);
        end

        // ---- Fase 2: destinos distintos por lane ----
        mmio(1, CORE + 32'h18, 32'h10);                       // RESET
        repeat (50) @(negedge gclk);
        mmio(1, WARPS + 32'h00, DIV_BASE);                    // warp 0: PC
        mmio(1, WARPS + 32'h04, 32'h0000_00ff);               //         ACTIVE
        run_and_wait;
        $display("fase 2: la GPU paro tras %0d sondeos; STATUS=%h", polls, status);
        if (!(status & ST_ERROR)) begin
            $display("FALLO: un JR con destinos distintos no dio error (STATUS=%h)", status);
            $fatal(1);
        end
        mmio(0, SIMT + 32'h08, 0);
        if (got_data[15:8] !== ERROR_SIMT) begin
            $display("FALLO: codigo de error %h, esperaba %h (ERROR_SIMT)", got_data[15:8], ERROR_SIMT);
            $fatal(1);
        end
        $display("GPU_JUMP: OK");
        $finish;
    end

    initial begin
        #20_000_000;
        $display("FALLO: timeout");
        $fatal(1);
    end
endmodule

// Memoria de 128 bits con latencia fija, como la de gpu_system_tb.v.
module ram_port_jmp #(parameter LAT = 5) (
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
    wire in_range = (req_addr[31:4] < gpu_jump_tb.LINES);

    always @(posedge clk) begin
        if (reset) begin
            head <= 0; count <= 0; now <= 0;
        end else begin
            now <= now + 1;
            if (accept) begin
                if (in_range) begin
                    line = gpu_jump_tb.mem[req_addr[31:4]];
                    q_data[tail] <= line;
                    q_err[tail] <= 1'b0;
                    if (req_write) begin
                        for (b = 0; b < 16; b = b + 1)
                            if (req_wmask[b]) line[b*8 +: 8] = req_wdata[b*8 +: 8];
                        gpu_jump_tb.mem[req_addr[31:4]] = line;
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

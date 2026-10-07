`default_nettype none
`timescale 1ns/1ps
// Hito 1 de la 36: la GPU como cliente de memoria y esclava del MMIO de la CPU.
//
// Dos relojes, como en la placa: `clk` (80 MHz, la CPU) y `gclk` (25 MHz, la
// GPU). El banco hace de CPU: manda accesos MMIO de palabra por el puente
// (`gpu_mmio_bridge`), que los cruza al dominio de la GPU. La RAM es de 128 bits
// y la comparten los dos puertos de memoria (LSU e instrucciones), con latencia
// y respuestas en orden, como el fabric.
//
// Se comprueba:
//   * identidad y estado de GPU CORE tras el reset;
//   * escribir descriptores, lanzar con RUN y esperar a que la GPU termine;
//   * que el kernel `out[tid] = tid*tid + 1` deja 16 palabras en RAM;
//   * WARP_LIVE, WARP_DONE (pegajoso y W1C);
//   * los errores de contrato: WARP_START (hito 2), comandos a la vez, bits
//     reservados, RESUME sin HALT, registros inexistentes, escribir un
//     descriptor con la GPU en marcha.
module gpu_system_tb;
    reg clk = 0, gclk = 0;
    always #6.25 clk = ~clk;
    always #20 gclk = ~gclk;
    reg reset = 1, greset = 1;

    // ---- CPU -> puente ----
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

    // ---- memoria ----
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

    ram_port #(.LAT(5)) ram0 (.clk(gclk), .reset(greset),
        .req_valid(p0_req_valid), .req_ready(p0_req_ready), .req_write(p0_req_write),
        .req_addr(p0_req_addr), .req_wdata(p0_req_wdata), .req_wmask(p0_req_wmask),
        .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
        .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));
    ram_port #(.LAT(7)) ram1 (.clk(gclk), .reset(greset),
        .req_valid(p1_req_valid), .req_ready(p1_req_ready), .req_write(p1_req_write),
        .req_addr(p1_req_addr), .req_wdata(p1_req_wdata), .req_wmask(p1_req_wmask),
        .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
        .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error));

    // ---- CPU: un acceso MMIO ----
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

    task expect_read;
        input [31:0] a;
        input [31:0] want;
        begin
            mmio(0, a, 0);
            if (got_err || got_data !== want) begin
                $display("FALLO: leer %h = %h (error=%b), esperaba %h", a, got_data, got_err, want);
                $fatal(1);
            end
        end
    endtask

    task expect_write_ok;
        input [31:0] a;
        input [31:0] d;
        begin
            mmio(1, a, d);
            if (got_err) begin
                $display("FALLO: escribir %h <- %h dio error", a, d);
                $fatal(1);
            end
        end
    endtask

    task expect_write_error;
        input [31:0] a;
        input [31:0] d;
        begin
            mmio(1, a, d);
            if (!got_err) begin
                $display("FALLO: escribir %h <- %h deberia dar error", a, d);
                $fatal(1);
            end
        end
    endtask

    task expect_read_error;
        input [31:0] a;
        begin
            mmio(0, a, 0);
            if (!got_err) begin
                $display("FALLO: leer %h deberia dar error (dio %h)", a, got_data);
                $fatal(1);
            end
        end
    endtask

    localparam [31:0] CORE = 32'h8200_0000, WARPS = 32'h8201_0000, SIMT = 32'h8202_0000;
    localparam [31:0] ST_RUNNING = 1, ST_HALTED = 2, ST_IDLE = 4, ST_ERROR = 8;

    integer i, polls;
    reg [31:0] status;
    reg [31:0] kernel_words [0:8];

    initial begin
        for (i = 0; i < LINES; i = i + 1) mem[i] = 128'd0;
        $readmemh("sim/kernel_square.hex", kernel_words);
        for (i = 0; i < 9; i = i + 1)
            mem[i / 4][(i % 4) * 32 +: 32] = kernel_words[i];

        repeat (6) @(negedge gclk);
        reset = 0; greset = 0;
        repeat (400) @(negedge gclk);      // el banco de registros de gpu_sm se inicializa

        // ---- GPU CORE tras el reset ----
        expect_read(CORE + 32'h00, 32'd11);          // GPU_ID
        expect_read(CORE + 32'h04, 32'd1);           // GPU_VERSION
        expect_read(CORE + 32'h08, 32'h0f);          // GPU_ISA
        expect_read(CORE + 32'h0c, 32'd0);           // GPU_FEATURES
        expect_read(CORE + 32'h10, 32'h0000_0808);   // GPU_CAPS: 8 warps, 8 lanes
        expect_read(CORE + 32'h14, ST_IDLE);         // sin warps vivos, parada
        expect_read(CORE + 32'h18, 32'd0);           // GPU_CONTROL lee cero
        expect_read(CORE + 32'h20, 32'd0);           // WARP_LIVE
        expect_read(CORE + 32'h24, 32'd0);           // WARP_DONE

        // ---- Errores de acceso ----
        expect_read_error (CORE + 32'h1c);           // WARP_START es solo escritura
        expect_write_error(CORE + 32'h00, 32'd1);    // GPU_ID es de solo lectura
        expect_write_error(CORE + 32'h14, 32'd1);    // GPU_STATUS tambien
        expect_read_error (CORE + 32'h28);           // fuera del bloque
        expect_read_error (32'h8204_0000);           // bloque que no es de la GPU
        expect_write_error(CORE + 32'h1c, 32'h1);    // WARP_START: hito 2
        expect_write_error(CORE + 32'h18, 32'h3);    // dos comandos a la vez
        expect_write_error(CORE + 32'h18, 32'h20);   // bit reservado
        expect_write_error(CORE + 32'h18, 32'h4);    // RESUME sin HALT
        expect_write_error(CORE + 32'h18, 32'h8);    // STEP sin HALT
        expect_write_error(WARPS + 32'h0c, 32'd1);   // SIMT_STATE es de solo lectura
        expect_read_error (WARPS + 32'h80);          // hueco entre descriptores y arrays
        expect_read_error (WARPS + 32'h220);         // warp 8 no existe

        // ---- Descriptores: warps 0 y 1 con el kernel; el resto, apagados ----
        expect_write_ok(WARPS + 32'h00, 32'h0000_0000);   // warp 0: PC
        expect_write_ok(WARPS + 32'h04, 32'h0000_00ff);   //         ACTIVE
        expect_write_ok(WARPS + 32'h10, 32'h0000_0000);   // warp 1: PC
        expect_write_ok(WARPS + 32'h14, 32'h0000_00ff);   //         ACTIVE
        expect_read(WARPS + 32'h04, 32'h0000_00ff);
        expect_read(WARPS + 32'h14, 32'h0000_00ff);
        expect_read(WARPS + 32'h24, 32'h0000_0000);       // warp 2 sigue apagado
        expect_read(CORE + 32'h20, 32'h0000_0003);        // WARP_LIVE (hito 1: ya con los descriptores)

        // ---- RUN ----
        expect_write_ok(CORE + 32'h18, 32'h1);
        polls = 0;
        status = 0;
        while (!(status & ST_IDLE) && polls < 2000) begin
            mmio(0, CORE + 32'h14, 0);
            status = got_data;
            polls = polls + 1;
        end
        if (!(status & ST_IDLE)) begin
            $display("FALLO: la GPU no termino; STATUS=%h", status);
            $fatal(1);
        end
        $display("GPU termino tras %0d sondeos; STATUS=%h", polls, status);
        if (status & ST_ERROR) begin
            $display("FALLO: la GPU acabo con error");
            $fatal(1);
        end
        expect_read(CORE + 32'h20, 32'd0);                // ya no hay warps vivos
        expect_read(CORE + 32'h24, 32'h0000_0003);        // WARP_DONE pegajoso: warps 0 y 1
        expect_read(CORE + 32'h24, 32'h0000_0003);        // y sigue ahi tras leerlo
        expect_write_ok(CORE + 32'h24, 32'h0000_0001);    // W1C del warp 0
        expect_read(CORE + 32'h24, 32'h0000_0002);
        expect_write_ok(CORE + 32'h24, 32'h0000_0002);
        expect_read(CORE + 32'h24, 32'h0000_0000);

        // ---- Resultado en RAM: out[tid] = tid*tid + 1, en 0x400 ----
        for (i = 0; i < 16; i = i + 1) begin
            if (mem[64 + i / 4][(i % 4) * 32 +: 32] !== i * i + 1) begin
                $display("FALLO: out[%0d] = %0d, esperaba %0d", i,
                         mem[64 + i / 4][(i % 4) * 32 +: 32], i * i + 1);
                $fatal(1);
            end
        end
        if (mem[68][31:0] !== 32'd0) begin
            $display("FALLO: la GPU escribio mas alla de out[15]: %h", mem[68][31:0]);
            $fatal(1);
        end

        // ---- HALT / RESUME sobre una GPU parada ----
        expect_write_ok(CORE + 32'h18, 32'h2);            // HALT
        expect_read(CORE + 32'h14, ST_IDLE | ST_HALTED);
        expect_write_ok(CORE + 32'h18, 32'h4);            // RESUME
        expect_read(CORE + 32'h14, ST_IDLE);

        // ---- RESET ----
        expect_write_ok(CORE + 32'h18, 32'h10);
        repeat (50) @(negedge gclk);
        expect_read(CORE + 32'h14, ST_IDLE);

        $display("GPU_SYSTEM: OK (hito 1)");
        $finish;
    end

    initial begin
        #5_000_000;
        $display("FALLO: timeout; STATUS de la GPU sin terminar");
        $fatal(1);
    end
endmodule

// Memoria de 128 bits con latencia fija y respuestas en orden, para un puerto
// del fabric. Comparte el array `mem` del banco. Cada peticion aceptada da UNA
// respuesta, tambien las escrituras. Una direccion fuera de la RAM da error.
module ram_port #(parameter LAT = 5) (
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
    wire in_range = (req_addr[31:4] < gpu_system_tb.LINES);

    always @(posedge clk) begin
        if (reset) begin
            head <= 0; count <= 0; now <= 0;
        end else begin
            now <= now + 1;
            if (accept) begin
                if (in_range) begin
                    line = gpu_system_tb.mem[req_addr[31:4]];
                    q_data[tail] <= line;
                    q_err[tail] <= 1'b0;
                    if (req_write) begin
                        for (b = 0; b < 16; b = b + 1)
                            if (req_wmask[b]) line[b*8 +: 8] = req_wdata[b*8 +: 8];
                        gpu_system_tb.mem[req_addr[31:4]] = line;
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

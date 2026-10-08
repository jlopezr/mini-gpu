`default_nettype none
`timescale 1ns/1ps
// Hito 2 de GPU CORE: las reglas de lanzamiento de mmio.md §14.1.
//
// Comprueba, sobre gpu_system con su puente y una RAM simulada:
//   * el descriptor sigue siendo el descriptor tras ejecutar (no lo consume);
//   * RESET conserva descriptores y relanzar con RUN repite el resultado;
//   * WARP_START arranca solo los warps pedidos, aunque haya otros configurados;
//   * WARP_START es todo o nada, y da error sobre un warp inexistente;
//   * con un warp vivo se pueden escribir los descriptores de OTROS warps y
//     arrancarlos, pero no tocar el del vivo ni arrancarlo otra vez;
//   * WARP_START con la GPU parada deja el warp vivo y en pausa hasta RESUME;
//   * RUN sin ningun descriptor con ACTIVE != 0 da error.
//
// Kernels: sim/kernel_square.hex (out[tid] = tid*tid + 1, en 0x400) en la
// direccion 0, y sim/kernel_spin.hex (gira hasta que [0x900] != 0) en 0x200.
// Lleva su propia ram_port_core: accede a `mem` por nombre jerarquico.
module gpu_core_tb;
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

    ram_port_core #(.LAT(5)) ram0 (.clk(gclk), .reset(greset),
        .req_valid(p0_req_valid), .req_ready(p0_req_ready), .req_write(p0_req_write),
        .req_addr(p0_req_addr), .req_wdata(p0_req_wdata), .req_wmask(p0_req_wmask),
        .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
        .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));
    ram_port_core #(.LAT(7)) ram1 (.clk(gclk), .reset(greset),
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

    task expect_read;
        input [255:0] what;
        input [31:0] a;
        input [31:0] want;
        begin
            mmio(0, a, 0);
            if (got_err || got_data !== want) begin
                $display("FALLO: %0s: leer %h = %h (error=%b), esperaba %h", what, a, got_data, got_err, want);
                $fatal(1);
            end
        end
    endtask

    task expect_write_ok;
        input [255:0] what;
        input [31:0] a;
        input [31:0] d;
        begin
            mmio(1, a, d);
            if (got_err) begin
                $display("FALLO: %0s: escribir %h <- %h dio error", what, a, d);
                $fatal(1);
            end
        end
    endtask

    task expect_write_error;
        input [255:0] what;
        input [31:0] a;
        input [31:0] d;
        begin
            mmio(1, a, d);
            if (!got_err) begin
                $display("FALLO: %0s: escribir %h <- %h deberia dar error", what, a, d);
                $fatal(1);
            end
        end
    endtask

    localparam [31:0] CORE = 32'h8200_0000, WARPS = 32'h8201_0000;
    localparam [31:0] STATUS = CORE + 32'h14, CONTROL = CORE + 32'h18,
                      WSTART = CORE + 32'h1c, LIVE = CORE + 32'h20, WDONE = CORE + 32'h24;
    localparam [31:0] ST_RUNNING = 1, ST_HALTED = 2, ST_IDLE = 4, ST_ERROR = 8;
    localparam [31:0] C_RUN = 1, C_HALT = 2, C_RESUME = 4, C_RESET = 16;

    function [31:0] word;
        input [31:0] byte_addr;
        begin word = mem[byte_addr / 16][((byte_addr / 4) % 4) * 32 +: 32]; end
    endfunction

    integer i, polls;
    reg [31:0] status;
    reg [31:0] square_words [0:8];
    reg [31:0] spin_words [0:3];

    // Estado inicial de la RAM de salida: out[0..31] a cero.
    task clear_out;
        integer k;
        begin for (k = 0; k < 8; k = k + 1) mem[64 + k] = 128'd0; end
    endtask

    // out[tid] = tid*tid + 1 para los warps de `mask` y cero para el resto.
    task check_out;
        input [255:0] what;
        input [7:0] mask;
        integer t, w;
        reg [31:0] want;
        begin
            for (t = 0; t < 32; t = t + 1) begin
                w = t / 8;
                want = mask[w] ? t * t + 1 : 32'd0;
                if (word(32'h400 + 4 * t) !== want) begin
                    $display("FALLO: %0s: out[%0d] = %0d, esperaba %0d", what, t, word(32'h400 + 4 * t), want);
                    $fatal(1);
                end
            end
        end
    endtask

    task wait_status;
        input [31:0] bit_mask;      // espera a que el STATUS tenga alguno de estos bits
        input [255:0] what;
        begin
            polls = 0; status = 0;
            while (!(status & bit_mask) && polls < 4000) begin
                mmio(0, STATUS, 0);
                status = got_data;
                polls = polls + 1;
            end
            if (!(status & bit_mask)) begin
                $display("FALLO: %0s: STATUS=%h tras %0d sondeos", what, status, polls);
                $fatal(1);
            end
        end
    endtask

    task wait_done_bit;
        input integer which;
        input [255:0] what;
        begin
            polls = 0; got_data = 0;
            while (!got_data[which] && polls < 4000) begin
                mmio(0, WDONE, 0);
                polls = polls + 1;
            end
            if (!got_data[which]) begin
                $display("FALLO: %0s: WARP_DONE=%h tras %0d sondeos", what, got_data, polls);
                $fatal(1);
            end
        end
    endtask

    // Descriptor de un warp: PC y ACTIVE.
    task desc;
        input integer w;
        input [31:0] pc_value;
        input [31:0] active_value;
        begin
            expect_write_ok("descriptor PC", WARPS + 16 * w, pc_value);
            expect_write_ok("descriptor ACTIVE", WARPS + 16 * w + 4, active_value);
        end
    endtask

    task disable_all;
        integer w;
        begin for (w = 0; w < 8; w = w + 1) expect_write_ok("apagar", WARPS + 16 * w + 4, 32'd0); end
    endtask

    task do_reset;
        begin
            expect_write_ok("RESET", CONTROL, C_RESET);
            repeat (50) @(negedge gclk);
        end
    endtask

    initial begin
        for (i = 0; i < LINES; i = i + 1) mem[i] = 128'd0;
        $readmemh("sim/kernel_square.hex", square_words);
        $readmemh("sim/kernel_spin.hex", spin_words);
        for (i = 0; i < 9; i = i + 1)
            mem[i / 4][(i % 4) * 32 +: 32] = square_words[i];
        for (i = 0; i < 4; i = i + 1)
            mem[(32'h200 / 4 + i) / 4][((32'h200 / 4 + i) % 4) * 32 +: 32] = spin_words[i];

        repeat (6) @(negedge gclk);
        reset = 0; greset = 0;
        repeat (400) @(negedge gclk);

        // ---- 1. RUN no consume el descriptor ----
        desc(0, 0, 32'hff);
        desc(1, 0, 32'hff);
        expect_write_ok("RUN", CONTROL, C_RUN);
        wait_status(ST_IDLE, "fin de RUN");
        check_out("RUN", 8'b0000_0011);
        expect_read("PC del warp 0 tras ejecutar", WARPS + 32'h00, 32'h0);
        expect_read("ACTIVE del warp 0 tras ejecutar", WARPS + 32'h04, 32'hff);
        expect_read("ACTIVE del warp 1 tras ejecutar", WARPS + 32'h14, 32'hff);
        expect_read("WARP_DONE", WDONE, 32'h3);

        // ---- 2. RESET conserva descriptores; relanzar repite el resultado ----
        do_reset;
        expect_read("WARP_LIVE tras RESET", LIVE, 32'h0);
        expect_read("WARP_DONE tras RESET", WDONE, 32'h0);
        expect_read("STATUS tras RESET", STATUS, ST_IDLE);
        expect_read("ACTIVE del warp 0 tras RESET", WARPS + 32'h04, 32'hff);
        expect_read("ACTIVE del warp 1 tras RESET", WARPS + 32'h14, 32'hff);
        clear_out;
        expect_write_ok("RUN tras RESET", CONTROL, C_RUN);
        wait_status(ST_IDLE, "fin del RUN tras RESET");
        check_out("RUN tras RESET", 8'b0000_0011);

        // ---- 3. WARP_START en reposo arranca solo los warps pedidos ----
        do_reset;
        desc(2, 0, 32'hff);                        // warps 0 y 1 siguen configurados
        clear_out;
        expect_write_ok("WARP_START del warp 2", WSTART, 32'h4);
        wait_status(ST_IDLE, "fin de WARP_START");
        check_out("WARP_START", 8'b0000_0100);     // los warps 0 y 1 NO han corrido
        expect_read("WARP_DONE tras WARP_START", WDONE, 32'h4);

        // ---- 4. WARP_START es todo o nada ----
        do_reset;
        clear_out;
        expect_write_ok("apagar warp 3", WARPS + 16 * 3 + 4, 32'd0);
        expect_write_error("WARP_START con un ACTIVE = 0", WSTART, 32'hc);   // warps 2 y 3
        expect_read("WARP_LIVE tras el error", LIVE, 32'h0);
        expect_read("STATUS tras el error", STATUS, ST_IDLE);
        expect_write_error("WARP_START de un warp inexistente", WSTART, 32'h100);
        expect_write_error("WARP_START con warp valido e inexistente", WSTART, 32'h104);
        expect_read("WARP_LIVE tras el segundo error", LIVE, 32'h0);
        repeat (200) @(negedge gclk);
        check_out("todo o nada", 8'b0000_0000);

        // ---- 5. Un warp vivo no impide configurar y arrancar otros ----
        do_reset;
        disable_all;
        clear_out;
        mem[144] = 128'd0;                         // [0x900] = 0: el warp 0 gira
        desc(0, 32'h200, 32'hff);
        expect_write_ok("RUN del warp que gira", CONTROL, C_RUN);
        expect_read("WARP_LIVE con el warp 0 girando", LIVE, 32'h1);
        desc(1, 0, 32'hff);                        // otro warp: valido
        expect_write_ok("WARP_START con otro vivo", WSTART, 32'h2);
        wait_done_bit(1, "el warp 1 termina mientras el 0 gira");
        expect_read("WARP_LIVE", LIVE, 32'h1);
        mmio(0, STATUS, 0);
        if (!(got_data & ST_RUNNING)) begin
            $display("FALLO: la GPU no sigue RUNNING con el warp 0 vivo (STATUS=%h)", got_data);
            $fatal(1);
        end
        expect_write_error("descriptor de un warp vivo", WARPS + 32'h00, 32'h0);
        expect_write_error("ACTIVE de un warp vivo", WARPS + 32'h04, 32'h0f);
        expect_write_error("WARP_START de un warp vivo", WSTART, 32'h1);
        expect_write_error("RUN con un warp vivo", CONTROL, C_RUN);
        expect_read("el descriptor del warp vivo no cambia", WARPS + 32'h04, 32'hff);
        mem[144] = 128'd1;                         // [0x900] = 1: el warp 0 sale
        wait_status(ST_IDLE, "el warp 0 sale");
        expect_read("WARP_DONE de los dos", WDONE, 32'h3);
        check_out("concurrente", 8'b0000_0010);

        // ---- 6. WARP_START con la GPU parada: vivo y en pausa ----
        do_reset;
        disable_all;
        clear_out;
        desc(3, 0, 32'hff);
        expect_write_ok("HALT en reposo", CONTROL, C_HALT);
        expect_read("STATUS parada", STATUS, ST_IDLE | ST_HALTED);
        expect_write_ok("WARP_START con la GPU parada", WSTART, 32'h8);
        expect_read("WARP_LIVE", LIVE, 32'h8);
        repeat (400) @(negedge gclk);
        mmio(0, STATUS, 0);
        if (!(got_data & ST_HALTED) || (got_data & ST_RUNNING)) begin
            $display("FALLO: la GPU parada deberia seguir HALTED y sin RUNNING (STATUS=%h)", got_data);
            $fatal(1);
        end
        check_out("antes de RESUME", 8'b0000_0000);
        expect_write_ok("RESUME", CONTROL, C_RESUME);
        wait_status(ST_IDLE, "fin tras RESUME");
        check_out("tras RESUME", 8'b0000_1000);
        expect_read("WARP_DONE del warp 3", WDONE, 32'h8);

        // ---- 7. RUN sin ningun descriptor activo ----
        do_reset;
        disable_all;
        expect_write_error("RUN sin descriptores", CONTROL, C_RUN);
        expect_read("STATUS", STATUS, ST_IDLE);

        $display("GPU_CORE: OK (hito 2)");
        $finish;
    end

    initial begin
        #200_000_000;
        $display("FALLO: timeout");
        $fatal(1);
    end
endmodule

// Memoria de 128 bits con latencia fija, como la de gpu_system_tb.v.
module ram_port_core #(parameter LAT = 5) (
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
    wire in_range = (req_addr[31:4] < gpu_core_tb.LINES);

    always @(posedge clk) begin
        if (reset) begin
            head <= 0; count <= 0; now <= 0;
        end else begin
            now <= now + 1;
            if (accept) begin
                if (in_range) begin
                    line = gpu_core_tb.mem[req_addr[31:4]];
                    q_data[tail] <= line;
                    q_err[tail] <= 1'b0;
                    if (req_write) begin
                        for (b = 0; b < 16; b = b + 1)
                            if (req_wmask[b]) line[b*8 +: 8] = req_wdata[b*8 +: 8];
                        gpu_core_tb.mem[req_addr[31:4]] = line;
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

`default_nettype none
`timescale 1ns/1ps
// La respuesta de un LOAD no debe esperar a que acabe una ALU larga de otro
// warp. W0 carga 0xdeadbeef y lo almacena; W1 ejecuta un DIV iterativo. El
// banco exige que mem_q se llene mientras X sigue ocupado y que el dato llegue
// al STORE posterior.
module gpu_mem_x_overlap_tb;
    reg clk = 0, gclk = 0;
    always #6.25 clk = ~clk;
    always #20 gclk = ~gclk;
    reg reset = 1, greset = 1;

    reg start = 0, wr = 0;
    reg [31:0] addr = 0, wdata = 0;
    wire done, err, h_valid, h_write, h_done, h_error;
    wire [31:0] rdata, h_addr, h_wdata, h_rdata;
    gpu_mmio_bridge bridge (
        .clk(clk), .reset(reset), .start(start), .write(wr), .address(addr),
        .write_data(wdata), .done(done), .read_data(rdata), .error(err),
        .gclk(gclk), .greset(greset), .h_valid(h_valid), .h_write(h_write),
        .h_addr(h_addr), .h_wdata(h_wdata), .h_done(h_done),
        .h_rdata(h_rdata), .h_error(h_error));

    wire p0_req_valid, p0_req_ready, p0_req_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
    wire [31:0] p0_req_addr;
    wire [127:0] p0_req_wdata, p0_rsp_rdata;
    wire [15:0] p0_req_wmask;
    wire p1_req_valid, p1_req_ready, p1_req_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
    wire [31:0] p1_req_addr;
    wire [127:0] p1_req_wdata, p1_rsp_rdata;
    wire [15:0] p1_req_wmask;
    wire gpu_halted, gpu_error;

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

    // P0 tarda bastante para que la respuesta caiga durante el DIV de W1.
    // Los dos MOVI de W1 consumen la primera parte de la latencia. 64 ciclos
    // deja caer la respuesta en los 32 pasos iterativos del DIV, no antes.
    overlap_ram_port #(.FETCH(0), .LAT(64)) ram0 (
        .clk(gclk), .reset(greset), .req_valid(p0_req_valid), .req_ready(p0_req_ready),
        .req_write(p0_req_write), .req_addr(p0_req_addr), .req_wdata(p0_req_wdata),
        .req_wmask(p0_req_wmask), .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
        .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));
    overlap_ram_port #(.FETCH(1), .LAT(3)) ram1 (
        .clk(gclk), .reset(greset), .req_valid(p1_req_valid), .req_ready(p1_req_ready),
        .req_write(p1_req_write), .req_addr(p1_req_addr), .req_wdata(p1_req_wdata),
        .req_wmask(p1_req_wmask), .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
        .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error));

    reg done_seen, overlap_seen, same_warp_seen, raw_early_seen, store_seen;
    reg [31:0] got_data;
    integer polls, gpu_cycles;
    reg measuring;
    always @(posedge clk) if (done) done_seen <= 1'b1;
    always @(posedge gclk) begin
        if (measuring) gpu_cycles <= gpu_cycles + 1;
        if (dut.sm.mem_q_valid && dut.sm.x_valid) overlap_seen <= 1'b1;
        if (dut.sm.mem_valid[0] && dut.sm.x_valid && dut.sm.x_warp == 0 &&
            dut.sm.x_instruction == 32'h40a0_0055) same_warp_seen <= 1'b1;
        if (dut.sm.mem_valid[0] && dut.sm.x_valid && dut.sm.x_warp == 0 &&
            dut.sm.x_instruction == 32'h5820_0804) raw_early_seen <= 1'b1;
        if (p0_req_valid && p0_req_ready && p0_req_write &&
            (p0_req_wdata[31:0] == 32'hdead_beef ||
             p0_req_wdata[63:32] == 32'hdead_beef ||
             p0_req_wdata[95:64] == 32'hdead_beef ||
             p0_req_wdata[127:96] == 32'hdead_beef)) store_seen <= 1'b1;
    end

    task mmio_write;
        input [31:0] a, d;
        integer n;
        begin
            @(negedge clk); wr = 1'b1; addr = a; wdata = d; done_seen = 0;
            @(negedge clk); start = 1'b1;
            @(negedge clk); start = 1'b0;
            n = 0;
            while (!done_seen && n < 400) begin @(negedge clk); n = n + 1; end
            if (!done_seen || err) begin
                $display("FALLO: MMIO W %h (done=%b error=%b)", a, done_seen, err);
                $fatal(1);
            end
        end
    endtask

    task mmio_read;
        input [31:0] a;
        integer n;
        begin
            @(negedge clk); wr = 1'b0; addr = a; wdata = 0; done_seen = 0;
            @(negedge clk); start = 1'b1;
            @(negedge clk); start = 1'b0;
            n = 0;
            while (!done_seen && n < 400) begin @(negedge clk); n = n + 1; end
            if (!done_seen || err) begin
                $display("FALLO: MMIO R %h (done=%b error=%b)", a, done_seen, err);
                $fatal(1);
            end
            got_data = rdata;
        end
    endtask

    localparam [31:0] CORE = 32'h8200_0000, WARPS = 32'h8201_0000;
    localparam [31:0] ST_IDLE = 32'h4, ST_ERROR = 32'h8;
    task run_scale;
        input integer nwarps;
        input [31:0] entry;
        input raw_case;
        integer w, n;
        begin
            // Cada fila empieza con contadores, descriptors y LSU limpios.
            greset = 1;
            repeat (6) @(negedge gclk);
            greset = 0;
            repeat (400) @(negedge gclk);
            for (w = 0; w < nwarps; w = w + 1) begin
                mmio_write(WARPS + w * 16, entry);
                mmio_write(WARPS + w * 16 + 4, 32'h0000_00ff);
            end
            mmio_write(CORE + 32'h18, 32'h1);
            @(negedge gclk); gpu_cycles = 0; measuring = 1;
            n = 0; got_data = 0;
            while (!(got_data & ST_IDLE) && n < 8000) begin
                mmio_read(CORE + 32'h14);
                n = n + 1;
            end
            measuring = 0;
            if (!(got_data & ST_IDLE) || (got_data & ST_ERROR)) begin
                $display("FALLO: microbench %0d warps STATUS=%h", nwarps, got_data);
                $fatal(1);
            end
            if (raw_case)
                $display("GPU_MEM_BENCH RAW: warps=%0d ciclos=%0d retiradas=%0d CPI=%0f",
                         nwarps, dut.perf.cycles, dut.perf.retired_count,
                         dut.perf.cycles * 1.0 / dut.perf.retired_count);
            else
                $display("GPU_MEM_BENCH independiente: warps=%0d ciclos=%0d retiradas=%0d CPI=%0f",
                         nwarps, dut.perf.cycles, dut.perf.retired_count,
                         dut.perf.cycles * 1.0 / dut.perf.retired_count);
        end
    endtask
    initial begin
        overlap_seen = 0; same_warp_seen = 0; raw_early_seen = 0; store_seen = 0;
        measuring = 0; gpu_cycles = 0;
        repeat (6) @(negedge gclk);
        reset = 0; greset = 0;
        repeat (400) @(negedge gclk);

        // W0: LOAD; MOVI independiente; STORE del valor cargado; HALT.
        mmio_write(WARPS + 32'h00, 32'h0000_0000);
        mmio_write(WARPS + 32'h04, 32'h0000_00ff);
        // W1: MOVI r1,100; MOVI r2,3; DIV r3,r1,r2; HALT.
        mmio_write(WARPS + 32'h10, 32'h0000_0100);
        mmio_write(WARPS + 32'h14, 32'h0000_00ff);
        mmio_write(CORE + 32'h18, 32'h1);
        @(negedge gclk); gpu_cycles = 0; measuring = 1;

        polls = 0; got_data = 0;
        while (!(got_data & ST_IDLE) && polls < 4000) begin
            mmio_read(CORE + 32'h14);
            polls = polls + 1;
        end
        if (!(got_data & ST_IDLE) || (got_data & ST_ERROR)) begin
            $display("FALLO: GPU no termino STATUS=%h", got_data);
            $fatal(1);
        end
        measuring = 0;
        if (!overlap_seen) begin
            $display("FALLO: mem_q nunca estuvo valido mientras X ejecutaba");
            $fatal(1);
        end
        if (!same_warp_seen) begin
            $display("FALLO: la ALU independiente de W0 no adelanto al LOAD");
            $fatal(1);
        end
        if (raw_early_seen) begin
            $display("FALLO: el STORE dependiente entro en X antes del LOAD");
            $fatal(1);
        end
        if (!store_seen) begin
            $display("FALLO: el STORE no recibio el dato cargado");
            $fatal(1);
        end
        $display("GPU_MEM_BENCH independiente+RAW: warps=2 ciclos=%0d retiradas=%0d CPI=%0f",
                 gpu_cycles, dut.sm.retired_count,
                 gpu_cycles * 1.0 / dut.sm.retired_count);
        $display("GPU_MEM_X_OVERLAP: OK (%0d sondeos)", polls);
        run_scale(1, 32'h0000_0300, 0); run_scale(2, 32'h0000_0300, 0);
        run_scale(4, 32'h0000_0300, 0); run_scale(8, 32'h0000_0300, 0);
        run_scale(1, 32'h0000_0200, 1); run_scale(2, 32'h0000_0200, 1);
        run_scale(4, 32'h0000_0200, 1); run_scale(8, 32'h0000_0200, 1);
        $finish;
    end
endmodule

// RAM de latencia fija. FETCH=1 sirve los dos microkernels; FETCH=0 devuelve
// el dato de LOAD y acepta el STORE de comprobacion.
module overlap_ram_port #(parameter integer FETCH = 0, parameter integer LAT = 4) (
    input clk, reset, input req_valid, output req_ready, input req_write,
    input [31:0] req_addr, input [127:0] req_wdata, input [15:0] req_wmask,
    output reg rsp_valid, input rsp_ready, output reg [127:0] rsp_rdata,
    output reg rsp_error);
    reg pending;
    integer count;
    reg [127:0] pending_data;
    assign req_ready = !pending && !rsp_valid;
    always @(posedge clk) begin
        if (reset) begin
            pending <= 0; count <= 0; rsp_valid <= 0; rsp_rdata <= 0; rsp_error <= 0;
        end else begin
            if (rsp_valid && rsp_ready) rsp_valid <= 0;
            if (req_valid && req_ready) begin
                pending <= 1; count <= LAT; rsp_error <= 0;
                if (FETCH) begin
                    case (req_addr & 32'hffff_fff0)
                        32'h0000_0000: pending_data <= {32'hfc00_0000, 32'h5820_0804,
                                                         32'h40a0_0055, 32'h5420_0800};
                        32'h0000_0100: pending_data <= {32'hfc00_0000, 32'h3061_1000,
                                                         32'h4040_0003, 32'h4020_0064};
                        // LOAD r1,[r0+0x900]; ADD r3,r1,r0; HALT.
                        32'h0000_0200: pending_data <= {32'hfc00_0000, 32'h0000_0000,
                                                         32'h0461_0000, 32'h5420_0900};
                        // LOAD r1,[r0+0x800]; MOVI r5,55; HALT.
                        32'h0000_0300: pending_data <= {32'hfc00_0000, 32'h0000_0000,
                                                         32'h40a0_0055, 32'h5420_0800};
                        default: pending_data <= 128'd0;
                    endcase
                end else begin
                    // LOAD en 0x800 toma la primera palabra de la linea.
                    pending_data <= {96'd0, 32'hdead_beef};
                end
            end else if (pending) begin
                if (count == 0) begin
                    pending <= 0; rsp_valid <= 1; rsp_rdata <= pending_data;
                end else count <= count - 1;
            end
        end
    end
endmodule
`default_nettype wire

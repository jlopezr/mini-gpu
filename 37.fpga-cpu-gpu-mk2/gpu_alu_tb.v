`default_nettype none
`timescale 1ns/1ps
// Las instrucciones de ALU que la GPU toma de la CPU (SLT, SLTU, ...).
//
// Cuatro warps de ocho lanes ejecutan sim/kernel_alu.hex: cada hilo lee su par
// (a, b) de dos tablas en RAM y deja el resultado de cada instruccion en una
// tabla propia. El banco calcula lo esperado con operadores de Verilog, que es
// una descripcion independiente de la que hay en gpu_lane.v.
//
// Los 32 pares recorren los bordes (0, 1, -1, minimo y maximo con signo,
// valores a ambos lados de 2^15 y 2^16) y repiten operandos iguales. `b` nunca
// es cero, para que DIVU, REM y REMU no paren la GPU.
//
// Lleva su propia ram_port_alu: accede a `mem` por nombre jerarquico.
module gpu_alu_tb;
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

    ram_port_alu #(.LAT(5)) ram0 (.clk(gclk), .reset(greset),
        .req_valid(p0_req_valid), .req_ready(p0_req_ready), .req_write(p0_req_write),
        .req_addr(p0_req_addr), .req_wdata(p0_req_wdata), .req_wmask(p0_req_wmask),
        .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
        .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));
    ram_port_alu #(.LAT(7)) ram1 (.clk(gclk), .reset(greset),
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
    localparam [31:0] A_TABLE = 32'h800, B_TABLE = 32'h900;
    localparam [31:0] SLT_OUT = 32'hA00, SLTU_OUT = 32'hB00, MULHI_OUT = 32'hC00,
                      DIV_OUT = 32'hD00, DIVU_OUT = 32'hE00, REM_OUT = 32'hF00,
                      REMU_OUT = 32'h1000;

    function [31:0] word;
        input [31:0] byte_addr;
        begin word = mem[byte_addr / 16][((byte_addr / 4) % 4) * 32 +: 32]; end
    endfunction

    reg [31:0] vals [0:15];
    reg [31:0] op_a [0:31];
    reg [31:0] op_b [0:31];
    reg [31:0] kernel_words [0:63];

    integer i, polls, bad;
    reg [31:0] status, want, got;

    // Comprueba una tabla de 32 resultados contra `want`, que cada llamada
    // calcula a partir de (a, b) segun `which`.
    localparam W_SLT = 0, W_SLTU = 1, W_MULHI = 2, W_DIV = 3, W_DIVU = 4,
               W_REM = 5, W_REMU = 6;
    reg signed [63:0] product;
    reg signed [31:0] sa, sb, sq;
    function [31:0] expected;
        input integer which;
        input [31:0] a, b;
        begin
            case (which)
                W_SLT:  expected = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
                W_SLTU: expected = (a < b) ? 32'd1 : 32'd0;
                W_MULHI: begin
                    product = $signed({{32{a[31]}}, a}) * $signed({{32{b[31]}}, b});
                    expected = product[63:32];
                end
                // -2^31 / -1 no cabe: el cociente da la vuelta y el resto es 0.
                W_DIV: begin
                    sa = a; sb = b;
                    if (a == 32'h8000_0000 && b == 32'hffff_ffff) expected = 32'h8000_0000;
                    else begin sq = sa / sb; expected = sq; end
                end
                W_DIVU: expected = a / b;
                W_REM: begin
                    sa = a; sb = b;
                    if (a == 32'h8000_0000 && b == 32'hffff_ffff) expected = 32'd0;
                    else begin sq = sa % sb; expected = sq; end
                end
                W_REMU: expected = a % b;
                default: expected = 32'hxxxx_xxxx;
            endcase
        end
    endfunction

    task check_table;
        input [255:0] name;
        input [31:0]  base;
        input integer which;
        integer k;
        begin
            for (k = 0; k < 32; k = k + 1) begin
                want = expected(which, op_a[k], op_b[k]);
                got  = word(base + 4 * k);
                if (got !== want) begin
                    $display("FALLO: %0s a=%h b=%h -> %h, esperaba %h",
                             name, op_a[k], op_b[k], got, want);
                    bad = bad + 1;
                end
            end
        end
    endtask

    initial begin
        vals[0]  = 32'h0000_0000;  vals[1]  = 32'h0000_0001;
        vals[2]  = 32'hffff_ffff;  vals[3]  = 32'h0000_0002;
        vals[4]  = 32'h7fff_ffff;  vals[5]  = 32'h8000_0000;
        vals[6]  = 32'h8000_0001;  vals[7]  = 32'h1234_5678;
        vals[8]  = 32'hdead_beef;  vals[9]  = 32'h0000_0064;
        vals[10] = 32'hffff_ff9c;  vals[11] = 32'h0000_ffff;
        vals[12] = 32'h0001_0000;  vals[13] = 32'h0000_7fff;
        vals[14] = 32'h0000_8000;  vals[15] = 32'h0000_0003;
        for (i = 0; i < 32; i = i + 1) begin
            op_a[i] = vals[i % 16];
            op_b[i] = vals[(i < 16 ? i * 3 + 1 : i * 7 + 5) % 16];
            if (op_b[i] == 0) op_b[i] = 32'd7;
        end
        op_b[5]  = op_a[5];          // operandos iguales
        op_b[21] = op_a[21];
        // Casos que rompen implementaciones ingenuas.
        op_a[9]  = 32'h8000_0000;  op_b[9]  = 32'hffff_ffff;   // -2^31 / -1
        op_a[11] = 32'hffff_ffff;  op_b[11] = 32'h8000_0001;   // divisor > 2^31
        op_a[13] = 32'hffff_fffe;  op_b[13] = 32'hc000_0000;
        op_a[26] = 32'h8000_0000;  op_b[26] = 32'h8000_0000;   // minimo por minimo

        for (i = 0; i < LINES; i = i + 1) mem[i] = 128'd0;
        for (i = 0; i < 64; i = i + 1) kernel_words[i] = 32'd0;
        $readmemh("sim/kernel_alu.hex", kernel_words);
        for (i = 0; i < 64; i = i + 1)
            mem[i / 4][(i % 4) * 32 +: 32] = kernel_words[i];
        for (i = 0; i < 32; i = i + 1) begin
            mem[(A_TABLE + 4 * i) / 16][(((A_TABLE + 4 * i) / 4) % 4) * 32 +: 32] = op_a[i];
            mem[(B_TABLE + 4 * i) / 16][(((B_TABLE + 4 * i) / 4) % 4) * 32 +: 32] = op_b[i];
        end

        repeat (6) @(negedge gclk);
        reset = 0; greset = 0;
        repeat (400) @(negedge gclk);

        for (i = 0; i < 4; i = i + 1) begin
            mmio(1, WARPS + i * 16 + 32'h00, 32'h0);          // PC
            mmio(1, WARPS + i * 16 + 32'h04, 32'h0000_00ff);  // ACTIVE
        end
        mmio(1, CORE + 32'h18, 32'h1);                        // RUN

        polls = 0; status = 0;
        while (!(status & ST_IDLE) && polls < 20000) begin
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
        check_table("SLT",  SLT_OUT,  W_SLT);
        check_table("SLTU", SLTU_OUT, W_SLTU);
        check_table("MULHI", MULHI_OUT, W_MULHI);
        check_table("DIV",  DIV_OUT,  W_DIV);
        check_table("DIVU", DIVU_OUT, W_DIVU);
        check_table("REM",  REM_OUT,  W_REM);
        check_table("REMU", REMU_OUT, W_REMU);
        if (bad != 0) begin
            $display("GPU_ALU: %0d errores", bad);
            $fatal(1);
        end
        $display("GPU_ALU: OK");
        $finish;
    end

    initial begin
        #20_000_000;
        $display("FALLO: timeout");
        $fatal(1);
    end
endmodule

// Memoria de 128 bits con latencia fija, como la de gpu_system_tb.v.
module ram_port_alu #(parameter LAT = 5) (
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
    wire in_range = (req_addr[31:4] < gpu_alu_tb.LINES);

    always @(posedge clk) begin
        if (reset) begin
            head <= 0; count <= 0; now <= 0;
        end else begin
            now <= now + 1;
            if (accept) begin
                if (in_range) begin
                    line = gpu_alu_tb.mem[req_addr[31:4]];
                    q_data[tail] <= line;
                    q_err[tail] <= 1'b0;
                    if (req_write) begin
                        for (b = 0; b < 16; b = b + 1)
                            if (req_wmask[b]) line[b*8 +: 8] = req_wdata[b*8 +: 8];
                        gpu_alu_tb.mem[req_addr[31:4]] = line;
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
